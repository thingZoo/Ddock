from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from korean_asr_editorial_review import (
    _parse_response,
    apply_korean_asr_editorial_review,
    load_canonical_registry,
)
from runtime_generation_metrics import (
    capture_runtime_generation_metrics,
    generation_stage,
)
from v0316_extension import _install_generation_instrumentation


ROOT = Path(__file__).resolve().parent


def _source(texts: list[str], *, language: str = "ko") -> dict:
    items = []
    for index, text in enumerate(texts):
        items.append(
            {
                "segment_id": f"TR-{index + 1:05d}",
                "text": text,
                "start_seconds": float(index * 10),
                "end_seconds": float(index * 10 + 5),
                "duration_seconds": 5.0,
            }
        )
    return {
        "metadata": {
            "video_id": "editorial-fixture",
            "title": "Figma 튜터의 AI 코딩과 디자인 시스템",
            "description_raw": (
                "Figma, Dev Mode, React, Cursor, Claude Code와 MCP를 설명합니다."
            ),
            "duration_seconds": max(60, len(texts) * 10),
        },
        "creator_chapters": [
            {
                "start_seconds": 0.0,
                "end_seconds": max(60, len(texts) * 10),
                "label": "Figma와 AI 코딩",
            }
        ],
        "transcript": {
            "language": language,
            "language_code": language,
            "is_generated": True,
            "items": items,
        },
    }


def _result(texts: list[str], *, language: str = "ko") -> dict:
    rows = []
    raw = []
    for index, text in enumerate(texts):
        row_id = f"UT-{index + 1:05d}"
        segment_id = f"TR-{index + 1:05d}"
        rows.append(
            {
                "utterance_id": row_id,
                "chapter_id": "CH-01",
                "chapter_label": "Figma와 AI 코딩",
                "start_seconds": float(index * 10),
                "end_seconds": float(index * 10 + 5),
                "raw_joined_text": text,
                "normalized_text": text,
                "auto_normalized_text": text,
                "source_segment_ids": [segment_id],
                "source_spans": [
                    {
                        "segment_id": segment_id,
                        "raw_segment_text": text,
                        "start_seconds": float(index * 10),
                        "end_seconds": float(index * 10 + 5),
                    }
                ],
                "validation_warnings": [],
                "normalization_item_ids": [],
                "review_status": "needs_review",
            }
        )
        raw.append({"segment_id": segment_id, "text": text})
    return {
        "source_language": language,
        "translation_required": language != "ko",
        "translation_status": "not_required" if language == "ko" else "pending",
        "processed_chapter": {"chapter_id": "FULL"},
        "normalized_utterances": rows,
        "normalization_items": [],
        "unresolved_terms": [],
        "raw_segments": raw,
        "processing_report": {},
    }


def _core(*, load_error: Exception | None = None) -> SimpleNamespace:
    def loader(_name):
        if load_error:
            raise load_error
        return object()

    return SimpleNamespace(
        _DEFAULT_LOCAL_LLM_MODEL_V034=(
            "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"
        ),
        _LOCAL_LLM_CACHE_V032={},
        _load_local_llm_v032=loader,
        _extract_json_object_v032=lambda text: json.loads(text),
    )


def _generator(decisions: dict[str, dict]) -> tuple[callable, list[list[str]]]:
    calls: list[list[str]] = []

    def generate(_model, _system, user, _max_tokens):
        payload = json.loads(user)
        calls.append([item["utterance_id"] for item in payload["rows"]])
        reviews = []
        for item in payload["rows"]:
            configured = copy.deepcopy(decisions.get(item["utterance_id"]))
            if configured is None:
                configured = {
                    "decision": "keep",
                    "corrected_text": item["current"],
                    "confidence": "high",
                    "changes": [],
                    "evidence": ["no sufficiently supported repair"],
                }
            configured["utterance_id"] = item["utterance_id"]
            reviews.append(configured)
        return json.dumps({"reviews": reviews}, ensure_ascii=False)

    return generate, calls


class KoreanAsrEditorialReviewTests(unittest.TestCase):
    def test_registry_extends_v02_and_separates_tiers(self) -> None:
        registry = load_canonical_registry(ROOT)
        self.assertEqual(registry["schema_version"], "canonical_entity_registry_v0.3")
        names = {entity.canonical_name: entity for entity in registry["entities"]}
        self.assertEqual(names["React"].category, "framework")
        self.assertEqual(names["MCP"].tier, "B")
        self.assertEqual(names["Dev Mode"].category, "UI_feature")
        self.assertIn("컴포넌트", registry["protected_korean_concepts"])

    def test_clean_repeated_korean_does_not_load_or_call_model(self) -> None:
        texts = ["오늘은 디자인 시스템의 기본 원리를 차근차근 설명합니다."] * 10
        source = _source(texts)
        result = _result(texts)
        generate, calls = _generator({})
        output = apply_korean_asr_editorial_review(
            result, source, core=_core(), generator=generate
        )
        self.assertEqual(output["korean_editorial_review"]["suspicious_count"], 0)
        self.assertEqual(output["korean_editorial_review"]["model_calls"], 0)
        self.assertEqual(calls, [])

    def test_verified_official_terms_are_deterministically_canonicalized(self) -> None:
        texts = [
            "Figma 데브 모드 MCP에서 리액트 코드를 구현합니다.",
            "AI 코딩 도구 커서와 클로드 코드를 함께 사용합니다.",
        ]
        output = apply_korean_asr_editorial_review(
            _result(texts), _source(texts), core=_core(), allow_model_review=False
        )
        combined = " ".join(row["normalized_text"] for row in output["normalized_utterances"])
        for expected in ("Dev Mode", "React", "Cursor", "Claude Code"):
            self.assertIn(expected, combined)
        self.assertIn("MCP", combined)

    def test_plan_mode_and_shadcn_need_context_then_accept_high_confidence(self) -> None:
        texts = [
            "agent가 바로 구현하지 않게 플랫 모드를 활용해서 먼저 계획을 검토합니다.",
            "오픈 소스 UI 디자인 시스템인 샤드시엔 키트를 사용합니다.",
        ] + ["반복되는 정상 설명 문장입니다."] * 8
        decisions = {
            "UT-00001": {
                "decision": "repair",
                "corrected_text": "agent가 바로 구현하지 않게 Plan Mode를 활용해서 먼저 계획을 검토합니다.",
                "confidence": "high",
                "changes": [{"from": "플랫 모드", "to": "Plan Mode", "reason": "planning workflow context"}],
                "evidence": ["agent", "계획", "검토"],
            },
            "UT-00002": {
                "decision": "repair",
                "corrected_text": "오픈 소스 UI 디자인 시스템인 shadcn/ui를 사용합니다.",
                "confidence": "high",
                "changes": [{"from": "샤드시엔 키트", "to": "shadcn/ui", "reason": "UI kit context"}],
                "evidence": ["오픈 소스", "UI", "디자인 시스템"],
            },
        }
        generate, _ = _generator(decisions)
        output = apply_korean_asr_editorial_review(
            _result(texts), _source(texts), core=_core(), generator=generate
        )
        self.assertIn("Plan Mode", output["normalized_utterances"][0]["normalized_text"])
        self.assertIn("shadcn/ui", output["normalized_utterances"][1]["normalized_text"])

    def test_context_can_repair_severe_asr_without_row_leakage(self) -> None:
        texts = [
            "Figma 튜터의 설명을 시작합니다.",
            "알모신 분들은 마튜터만 잘 따라가시면 됩니다.",
            "다음에는 디자인 시스템 파일을 엽니다.",
        ] + ["반복되는 정상 설명 문장입니다."] * 7
        decisions = {
            "UT-00002": {
                "decision": "repair",
                "corrected_text": "디알못인 분들은 피그마 튜터님에만 잘 따라가시면 됩니다.",
                "confidence": "high",
                "changes": [
                    {"from": "알모신", "to": "디알못인", "reason": "speaker context"},
                    {"from": "마튜터만", "to": "피그마 튜터님에만", "reason": "verified tutor context"},
                ],
                "evidence": ["video title", "previous utterance", "creator chapter"],
            }
        }
        generate, _ = _generator(decisions)
        output = apply_korean_asr_editorial_review(
            _result(texts), _source(texts), core=_core(), generator=generate
        )
        repaired = output["normalized_utterances"][1]["normalized_text"]
        self.assertEqual(
            repaired,
            "디알못인 분들은 피그마 튜터님에만 잘 따라가시면 됩니다.",
        )
        self.assertNotIn("디자인 시스템 파일을 엽니다", repaired)

    def test_ambiguous_acronym_hallucination_is_rejected(self) -> None:
        texts = ["그분의 ICP가 PM분과 자주 회의를 하신대요."] + [
            "반복되는 정상 설명 문장입니다."
        ] * 9
        decisions = {
            "UT-00001": {
                "decision": "repair",
                "corrected_text": "그분의 업무가 PM분과 자주 회의를 하신대요.",
                "confidence": "high",
                "changes": [{"from": "ICP", "to": "업무", "reason": "guess"}],
                "evidence": ["context guess"],
            }
        }
        generate, _ = _generator(decisions)
        output = apply_korean_asr_editorial_review(
            _result(texts), _source(texts), core=_core(), generator=generate
        )
        self.assertIn("ICP", output["normalized_utterances"][0]["normalized_text"])
        self.assertEqual(output["normalized_utterances"][0]["korean_editorial_state"], "unresolved")
        self.assertTrue(output["unresolved_terms"])

    def test_generic_korean_design_terms_cannot_be_forced_to_english(self) -> None:
        texts = ["컴포넌트와 프로퍼티, 레이어와 디자인 시스템을 설명합니다."] + [
            "반복되는 정상 설명 문장입니다."
        ] * 9
        decisions = {
            "UT-00001": {
                "decision": "repair",
                "corrected_text": "Component와 Property, Layer와 Design System을 설명합니다.",
                "confidence": "high",
                "changes": [
                    {"from": "컴포넌트", "to": "Component", "reason": "translate"},
                    {"from": "프로퍼티", "to": "Property", "reason": "translate"},
                    {"from": "레이어", "to": "Layer", "reason": "translate"},
                    {"from": "디자인 시스템", "to": "Design System", "reason": "translate"},
                ],
                "evidence": [],
            }
        }
        generate, _ = _generator(decisions)
        output = apply_korean_asr_editorial_review(
            _result(texts), _source(texts), core=_core(), generator=generate
        )
        self.assertIn("컴포넌트", output["normalized_utterances"][0]["normalized_text"])

    def test_raw_provenance_is_byte_for_byte_unchanged(self) -> None:
        texts = ["Figma 데브 모드 MCP를 설명합니다."]
        source = _source(texts)
        result = _result(texts)
        raw_before = json.dumps(
            {"raw_segments": result["raw_segments"], "source_spans": result["normalized_utterances"][0]["source_spans"]},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        output = apply_korean_asr_editorial_review(
            result, source, core=_core(), allow_model_review=False
        )
        raw_after = json.dumps(
            {"raw_segments": output["raw_segments"], "source_spans": output["normalized_utterances"][0]["source_spans"]},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        self.assertEqual(raw_before, raw_after)

    def test_foreign_source_bypasses_editorial_review(self) -> None:
        texts = ["React code is generated here."]
        result = _result(texts, language="en")
        generate, calls = _generator({})
        output = apply_korean_asr_editorial_review(
            result, _source(texts, language="en"), core=_core(), generator=generate
        )
        self.assertIs(output, result)
        self.assertNotIn("korean_editorial_review", output)
        self.assertEqual(calls, [])

    def test_model_load_failure_preserves_deterministic_output(self) -> None:
        texts = ["Figma 대부모드 MCP를 설명합니다."] + [
            "반복되는 정상 설명 문장입니다."
        ] * 9
        output = apply_korean_asr_editorial_review(
            _result(texts),
            _source(texts),
            core=_core(load_error=RuntimeError("fixture load failure")),
        )
        self.assertIn("Dev Mode", output["normalized_utterances"][0]["normalized_text"])
        self.assertIn("fixture load failure", output["korean_editorial_review"]["model_error"])
        self.assertTrue(output["unresolved_terms"])

    def test_invalid_model_json_is_nonfatal(self) -> None:
        texts = ["Figma 대부모드 MCP를 설명합니다."] + [
            "반복되는 정상 설명 문장입니다."
        ] * 9

        def invalid(*_args):
            return "not-json"

        output = apply_korean_asr_editorial_review(
            _result(texts), _source(texts), core=_core(), generator=invalid
        )
        self.assertIn("Dev Mode", output["normalized_utterances"][0]["normalized_text"])
        self.assertEqual(output["korean_editorial_review"]["model_calls"], 1)
        self.assertTrue(output["unresolved_terms"])

    def test_partial_json_recovers_only_complete_review_objects(self) -> None:
        text = (
            '{"reviews":['
            '{"utterance_id":"UT-00001","decision":"keep",'
            '"corrected_text":"정상","confidence":"high","changes":[],"evidence":[]},'
            '{"utterance_id":"UT-00002","decision":"repair","corrected_text":"미완성"'
        )
        parsed = _parse_response(_core(), text)
        self.assertTrue(parsed["_partial_json_recovery"])
        self.assertEqual(
            [item["utterance_id"] for item in parsed["reviews"]],
            ["UT-00001"],
        )

    def test_production_editorial_files_have_no_fixture_video_hardcoding(self) -> None:
        production_paths = [
            ROOT / "korean_asr_editorial_review.py",
            ROOT / "korean_audio_reasr.py",
            ROOT / "v0316_extension.py",
            ROOT / "profiles" / "canonical_entity_registry_v0_3.json",
        ]
        forbidden = (
            "G0d9CHLpnnc",
            "알모신 분들은 마튜터만",
            "보드렸던",
            "플랫 모드",
            "샤드시엔 키트",
        )
        for path in production_paths:
            content = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(value, content, path.name)

    def test_runtime_metrics_separate_korean_review_from_translation(self) -> None:
        core = SimpleNamespace(
            _LOCAL_LLM_CACHE_V032={},
            _DEFAULT_LOCAL_LLM_MODEL_V032="fixture-model",
            _load_local_llm_v032=lambda name: {"model": name},
            _generate_local_llm_text_v033=lambda *_args, **_kwargs: "{}",
        )
        _install_generation_instrumentation(core)
        with capture_runtime_generation_metrics() as metrics:
            core._load_local_llm_v032("fixture-model")
            with generation_stage("korean_asr_editorial_review"):
                core._generate_local_llm_text_v033(
                    "fixture-model", "system", "user", 100
                )
        self.assertEqual(metrics["total_generation_calls"], 1)
        self.assertEqual(metrics["translation_generation_calls"], 0)
        self.assertEqual(
            metrics["korean_asr_editorial_review_generation_calls"], 1
        )
        self.assertEqual(metrics["model_load_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
