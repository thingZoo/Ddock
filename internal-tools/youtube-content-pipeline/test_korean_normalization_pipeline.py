from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import preprocessor
import v0315_1_patch
from korean_evidence_normalization import apply_korean_evidence_normalization
from korean_full_scope import (
    finalize_korean_full_result,
    source_for_korean_full,
)


ROOT = Path(__file__).resolve().parent


def _source(
    texts: list[str],
    *,
    language: str = "ko",
    chapters: bool = True,
) -> dict:
    items = []
    for index, text in enumerate(texts):
        start = float(index * 10)
        items.append(
            {
                "segment_id": f"TR-{index + 1:05d}",
                "text": text,
                "start_seconds": start,
                "duration_seconds": 4.0,
                "end_seconds": start + 4.0,
                "source_type": "test_fixture",
            }
        )
    creator_chapters = []
    if chapters:
        creator_chapters = [
            {
                "timestamp_text": "0:00",
                "start_seconds": 0.0,
                "end_seconds": 20.0,
                "label": "첫 챕터",
            },
            {
                "timestamp_text": "0:20",
                "start_seconds": 20.0,
                "end_seconds": max(40.0, float(len(texts) * 10)),
                "label": "둘째 챕터",
            },
        ]
    return {
        "schema_version": "youtube_acquisition_v0.1",
        "source_url": "https://example.invalid/watch?v=fixture",
        "metadata": {
            "video_id": "fixture-video",
            "title": "일반 한국어 정규화 fixture",
            "description_raw": "Figma와 Claude Code를 사용하는 예시입니다.",
            "default_language": language,
            "duration_seconds": max(40.0, float(len(texts) * 10)),
        },
        "creator_chapters": creator_chapters,
        "transcript": {
            "status": "available",
            "language": language,
            "language_code": language,
            "is_generated": True,
            "items": items,
        },
    }


def _text(result: dict) -> str:
    return " ".join(
        row.get("normalized_text", "")
        for row in result.get("normalized_utterances", [])
    )


class VerifiedKoreanNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        v0315_1_patch.apply()

    def _build(self, source: dict, **kwargs) -> tuple[dict, int]:
        calls = 0

        def forbid_generation(*args, **inner_kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("Korean deterministic normalization must not call Qwen")

        with patch.object(
            preprocessor,
            "_generate_local_llm_text_v033",
            forbid_generation,
        ):
            result = preprocessor.build_preprocessing_draft(source, **kwargs)
        return result, calls

    def test_verified_profile_assets_are_packaged_and_loadable(self) -> None:
        expected = {
            "verified_correction_memory_v0_1.json",
            "verified_correction_memory_v0_2.json",
            "canonical_entity_registry_v0_2.json",
            "canonical_entity_registry_v0_3.json",
        }
        self.assertEqual(
            {path.name for path in (ROOT / "profiles").glob("*.json")},
            expected,
        )
        self.assertEqual(
            preprocessor._MEMORY_V027.get("memory_id"),
            "korean_longform_verified_memory_r1",
        )
        self.assertEqual(
            preprocessor._MEMORY_V028.get("memory_id"),
            "korean_longform_verified_memory_r2",
        )
        self.assertGreater(len(preprocessor._MEMORY_V028.get("rules", [])), 0)
        self.assertGreater(
            len(preprocessor._ENTITY_REGISTRY_V028.get("entities", [])),
            0,
        )

    def test_korean_creator_chapter_uses_verified_memory_without_translation(self) -> None:
        source = _source(
            [
                "그래서이 기능을 설명합니다.",
                "있 있는 항목을 확인합니다.",
                "둘째 챕터의 문장입니다.",
            ]
        )
        snapshot = copy.deepcopy(source)
        result, calls = self._build(source, chapter_index=0)
        normalized = _text(result)
        self.assertIn("그래서 이 기능", normalized)
        self.assertIn("있는 항목", normalized)
        self.assertNotIn("둘째 챕터의 문장", normalized)
        self.assertFalse(result["translation_required"])
        self.assertEqual(result["translation_status"], "not_required")
        self.assertEqual(calls, 0)
        self.assertEqual(source, snapshot)
        self.assertEqual(result["processed_chapter"]["chapter_id"], "CH-01")

    def test_profile_metadata_reports_actual_loaded_and_applied_state(self) -> None:
        result, _ = self._build(
            _source(["그래서이 기능입니다."], chapters=False)
        )
        self.assertEqual(
            result["correction_memory"]["memory_id"],
            "korean_longform_verified_memory_r2",
        )
        self.assertTrue(result["correction_memory"]["loaded"])
        self.assertGreater(
            result["correction_memory"]["applied_change_count"],
            0,
        )
        self.assertTrue(result["processing_report"]["profile_applied"])
        self.assertTrue(result["profile_application"]["profile_applied"])
        self.assertTrue(
            result["normalization_engine_v028"][
                "verified_correction_memory_loaded"
            ]
        )

    def test_korean_full_preserves_creator_ownership_and_raw_provenance(self) -> None:
        source = _source(
            [
                "그래서이 첫 문장입니다.",
                "첫 챕터의 다음 문장입니다.",
                "그래서이 둘째 챕터 문장입니다.",
            ]
        )
        source_snapshot = copy.deepcopy(source)
        adapted = source_for_korean_full(source)
        result, calls = self._build(
            adapted,
            translation_scope="whole_video",
            translate_foreign_to_korean=False,
        )
        result = finalize_korean_full_result(result, source, core=preprocessor)
        self.assertEqual(result["processed_chapter"]["chapter_id"], "FULL")
        self.assertEqual(result["preprocessing_scope"], "whole_video")
        self.assertEqual(result["creator_chapters"], source["creator_chapters"])
        self.assertEqual(calls, 0)
        self.assertEqual(source, source_snapshot)
        self.assertEqual(
            [item["text"] for item in result["raw_segments"]],
            [item["text"] for item in source["transcript"]["items"]],
        )
        self.assertEqual(
            {row["chapter_id"] for row in result["normalized_utterances"]},
            {"CH-01", "CH-02"},
        )

    def test_chapterless_korean_keeps_full_contract_and_normalization(self) -> None:
        source = _source(["그래서이 전체 영상 문장입니다."], chapters=False)
        result, calls = self._build(source)
        self.assertEqual(result["processed_chapter"]["chapter_id"], "FULL")
        self.assertIn("그래서 이 전체 영상", _text(result))
        self.assertFalse(result["translation_required"])
        self.assertEqual(result["translation_status"], "not_required")
        self.assertEqual(calls, 0)

    def test_verified_official_names_use_latin_spelling(self) -> None:
        result, _ = self._build(
            _source(
                ["피그마와 클로드 코드를 쓰고 챗지피티로 확인합니다."],
                chapters=False,
            )
        )
        normalized = _text(result)
        self.assertIn("Figma", normalized)
        self.assertIn("Claude Code", normalized)
        self.assertIn("ChatGPT", normalized)
        self.assertNotIn("피그마", normalized)
        self.assertNotIn("클로드 코드", normalized)

    def test_metadata_and_repeated_context_repair_unique_asr_variants(self) -> None:
        source = _source(
            [
                "기술과 디자인 사이에서 고금 분투했습니다.",
                "유지보스와 컴퍼넌트 구조를 설명합니다.",
                "시그마 디자인과 피그마 MTP 연결을 확인합니다.",
                "MCP와 컴포넌트는 반복 근거입니다.",
                "MCP와 컴포넌트를 다시 확인합니다.",
                "컴포넌트 반복 근거를 추가합니다.",
                "컴포넌트 반복 근거가 충분합니다.",
                "컴포넌트 반복 근거를 검증합니다.",
            ],
            chapters=False,
        )
        source["metadata"]["description_raw"] = (
            "디자인과 기술의 경계에서 고군분투한 이야기입니다. "
            "유지 보수 가능한 컴포넌트와 피그마 MCP를 설명합니다."
        )
        source["metadata"]["title"] = (
            "고군분투하며 유지 보수 가능한 컴포넌트와 피그마 MCP"
        )
        result, calls = self._build(source)
        result = apply_korean_evidence_normalization(
            result,
            source,
            canonicalize=preprocessor._canonicalize_official_foreign_names_v031,
        )
        normalized = _text(result)
        self.assertIn("고군분투", normalized)
        self.assertIn("유지 보수", normalized)
        self.assertNotIn("고금 분투", normalized)
        self.assertNotIn("유지보스", normalized)
        self.assertNotIn("컴퍼넌트", normalized)
        self.assertNotIn("MTP", normalized)
        self.assertNotIn("시그마", normalized)
        self.assertIn("Figma MCP", normalized)
        self.assertEqual(calls, 0)
        audit = result["korean_evidence_normalization"]
        self.assertFalse(audit["model_invoked"])
        self.assertGreaterEqual(audit["applied_change_count"], 5)
        self.assertTrue(
            any(
                item.get("normalization_type")
                == "korean_video_evidence_asr_repair_v0316"
                for item in result["normalization_items"]
            )
        )

    def test_ambiguous_asr_is_not_confidently_rewritten(self) -> None:
        ambiguous = "알모신 분들은 마튜터만 확인해 주세요."
        source = _source(
            [ambiguous, "시작하기 전에 ICP 고객을 확인합니다."],
            chapters=False,
        )
        source["metadata"]["title"] = "시작 계기와 Figma MCP"
        source["metadata"]["description_raw"] = "피그마 MCP 연결을 설명합니다."
        result, _ = self._build(source)
        result = apply_korean_evidence_normalization(
            result,
            source,
            canonicalize=preprocessor._canonicalize_official_foreign_names_v031,
        )
        self.assertIn("알모신 분들은 마튜터만", _text(result))
        self.assertIn("시작하기 전에 ICP 고객", _text(result))
        self.assertTrue(
            all(
                row.get("review_status") == "needs_review"
                for row in result["normalized_utterances"]
            )
        )

    def test_numbers_actions_and_targets_survive_normalization(self) -> None:
        source_text = "2026년에 3단계로 버튼을 선택합니다."
        result, _ = self._build(_source([source_text], chapters=False))
        normalized = _text(result)
        for expected in ("2026", "3단계", "버튼", "선택"):
            self.assertIn(expected, normalized)

    def test_foreign_source_does_not_enter_korean_translation_or_change_text(self) -> None:
        source_text = "The operator selects button 3 in 2026."
        result, calls = self._build(
            _source([source_text], language="en", chapters=False),
            translate_foreign_to_korean=False,
        )
        self.assertTrue(result["translation_required"])
        self.assertNotEqual(result["translation_status"], "not_required")
        self.assertIn(source_text, _text(result))
        self.assertEqual(calls, 0)

    def test_foreign_translation_path_bypasses_korean_verified_memory(self) -> None:
        sentinel = {
            "source_language": "en",
            "translation_required": True,
            "translation_status": "completed_clean",
            "normalized_utterances": [
                {
                    "utterance_id": "UT-00001",
                    "normalized_text": "검증된 기존 번역 결과입니다.",
                }
            ],
        }
        with patch.object(
            preprocessor,
            "_build_foreign_translation_draft_v034",
            return_value=copy.deepcopy(sentinel),
        ) as foreign_builder:
            result = preprocessor.build_preprocessing_draft(
                _source(["Existing foreign source."], language="en", chapters=False),
                translate_foreign_to_korean=True,
            )
        foreign_builder.assert_called_once()
        self.assertEqual(
            result["normalized_utterances"][0]["normalized_text"],
            sentinel["normalized_utterances"][0]["normalized_text"],
        )
        self.assertNotIn("correction_memory", result)

    def test_profile_files_do_not_contain_new_video_specific_rule(self) -> None:
        for path in (ROOT / "profiles").glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("G0d9CHLpnnc", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
