from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from korean_asr_editorial_review import apply_korean_asr_editorial_review
from korean_audio_reasr import (
    AudioWindow,
    _independently_guard_span_patches,
    build_span_safe_patch,
    select_windows_adaptive_high_severity,
)


ROOT = Path(__file__).resolve().parent


def _source(texts: list[str], *, channel_title: str = "", language: str = "ko") -> dict:
    return {
        "metadata": {
            "video_id": "general-recovery-fixture",
            "title": "디자인 AI 개발 인터뷰",
            "description_raw": "디자인 시스템과 AI 개발 흐름을 설명합니다.",
            "channel_title": channel_title,
            "duration_seconds": max(60, len(texts) * 10),
        },
        "creator_chapters": [{"start_seconds": 0, "end_seconds": 60, "label": "디자인 시스템"}],
        "transcript": {
            "language": language,
            "language_code": language,
            "items": [
                {
                    "segment_id": f"TR-{index + 1:05d}",
                    "text": text,
                    "start_seconds": index * 10,
                    "end_seconds": index * 10 + 6,
                }
                for index, text in enumerate(texts)
            ],
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
                "chapter_id": "FULL",
                "chapter_label": "디자인 시스템",
                "start_seconds": index * 10,
                "end_seconds": index * 10 + 6,
                "raw_joined_text": text,
                "normalized_text": text,
                "auto_normalized_text": text,
                "source_segment_ids": [segment_id],
                "source_spans": [{"segment_id": segment_id, "raw_segment_text": text}],
                "validation_warnings": [],
                "normalization_item_ids": [],
            }
        )
        raw.append({"segment_id": segment_id, "text": text})
    return {
        "source_language": language,
        "translation_required": language != "ko",
        "normalized_utterances": rows,
        "normalization_items": [],
        "unresolved_terms": [],
        "raw_segments": raw,
        "processing_report": {},
    }


def _review(texts: list[str], *, channel_title: str = "", language: str = "ko") -> dict:
    return apply_korean_asr_editorial_review(
        _result(texts, language=language),
        _source(texts, channel_title=channel_title, language=language),
        core=SimpleNamespace(_DEFAULT_LOCAL_LLM_MODEL_V034="fixture"),
        allow_model_review=False,
    )


class KoreanCaptionRecoveryCoverageTests(unittest.TestCase):
    def test_gold_fixture_is_test_only_and_covers_required_categories(self) -> None:
        path = ROOT / "tests" / "fixtures" / "korean_human_verified_g0_regressions.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(fixture["runtime_usage"], "test_fixture_only")
        categories = {item["category"] for item in fixture["cases"]}
        self.assertTrue(
            {
                "person_identity", "official_entity_continuity",
                "acronym_discourse_continuity", "technical_compound_phrase",
                "severe_korean_asr", "team_name", "generic_term",
                "multi_span_row", "attached_token_boundary", "ambiguous_keep",
            }.issubset(categories)
        )

    def test_video_local_person_identity_requires_explicit_metadata(self) -> None:
        rows = ["조시님 말씀처럼 진행합니다.", "조씨 님이 운영하십니다."]
        output = _review(rows, channel_title="빌더 조쉬 Builder Josh")
        combined = " ".join(row["normalized_text"] for row in output["normalized_utterances"])
        self.assertIn("조쉬님 말씀처럼", combined)
        self.assertIn("조쉬님이 운영", combined)
        without_metadata = _review(["조시님 말씀처럼 진행합니다."])
        self.assertIn("조시님", without_metadata["normalized_utterances"][0]["normalized_text"])

    def test_official_entity_continuity_uses_nearby_dialogue(self) -> None:
        output = _review([
            "Figma에서 Dev Mode를 연결합니다.",
            "Cursor와 Dev Mode를 확인합니다.",
            "부모드는 유료 사용자만 켤 수 있나요?",
        ])
        self.assertIn("Dev Mode는 유료", output["normalized_utterances"][2]["normalized_text"])

    def test_discourse_entity_continuity_does_not_rewrite_common_words(self) -> None:
        output = _review([
            "Figma 화면을 지금 확인합니다.",
            "Claude Code에서 코드를 작성합니다.",
            "지금은 개발자와 함께 코드를 검토합니다.",
        ])
        self.assertEqual(
            output["normalized_utterances"][2]["normalized_text"],
            "지금은 개발자와 함께 코드를 검토합니다.",
        )

    def test_acronym_continuity_requires_shared_nearby_concept(self) -> None:
        output = _review(["이번에는 LLM 토큰을 봅니다.", "LM 토큰이죠."])
        self.assertIn("LLM 토큰", output["normalized_utterances"][1]["normalized_text"])
        unrelated = _review(["LLM 모델을 설명합니다.", "LM 결과입니다."])
        self.assertIn("LM 결과", unrelated["normalized_utterances"][1]["normalized_text"])

    def test_domain_phrase_patch_is_bounded_and_audio_supported(self) -> None:
        before = "이제 타이퍼 컬러랑 스페이스 토큰을 구현했습니다"
        after = "이제 타이포그래피 컬러랑 스페이싱 토큰을 구현했습니다"
        plan = build_span_safe_patch(
            before,
            before,
            after,
            protected_terms=("타이포그래피", "컬러", "스페이싱", "토큰"),
            audio_confidence=0.95,
            suspicion_signals=("technical_domain_phrase_near_match",),
        )
        self.assertTrue(plan["passed"])
        self.assertEqual(plan["patched_text"], after)

    def test_multi_span_guard_keeps_safe_spans_when_one_fails(self) -> None:
        before = "제품 개발을을 하고 구퇴화를 한 뒤 1단계를 확인합니다"
        plan = build_span_safe_patch(
            before,
            before,
            "제품 개발을 하고 구체화를 한 뒤 2단계를 확인합니다",
            audio_confidence=0.95,
            suspicion_signals=("within_row_lexical_inconsistency",),
        )
        patched, accepted, rejected = _independently_guard_span_patches(
            before,
            plan["span_patches"],
            adjacent=[],
            protected_terms=(),
            known_latin=set(),
        )
        self.assertIn("개발을 하고", patched)
        self.assertIn("구체화를", patched)
        self.assertIn("1단계", patched)
        self.assertGreaterEqual(len(accepted), 2)
        self.assertIn("numbers_dates_or_amounts_changed", {item["reason"] for item in rejected})

    def test_row_signal_cannot_approve_unrelated_or_degraded_span(self) -> None:
        plan = build_span_safe_patch(
            "이런 컴퍼넌트들에는 베리언트뿐만 아니라 아이콘이 있습니다",
            "이런 컴퍼넌트들에는 베리언트뿐만 아니라 아이콘이 있습니다",
            "이런 컴포넌트들에는 에리언트 뿐만 아니라 아이콘이 있습니다",
            protected_terms=("컴포넌트", "버라이언트"),
            audio_confidence=0.95,
            suspicion_signals=("technical_domain_phrase_near_match",),
        )
        self.assertIn("컴포넌트", plan["patched_text"])
        self.assertIn("베리언트", plan["patched_text"])

        dropped = build_span_safe_patch(
            "그리고 근데이 전체 과정을 설명합니다",
            "그리고 근데이 전체 과정을 설명합니다",
            "그리고 이 전체 과정을 설명합니다",
            audio_confidence=0.95,
            suspicion_signals=("attached_token_boundary_candidate",),
        )
        self.assertFalse(dropped["passed"])

        broad = build_span_safe_patch(
            "이제 디자인시스템. com이라는 사이트입니다",
            "이제 디자인시스템. com이라는 사이트입니다",
            "디자인시스템.com 이라는 사이트입니다",
            audio_confidence=0.95,
            suspicion_signals=("malformed_script_boundary",),
        )
        self.assertFalse(broad["passed"])

        homophone = build_span_safe_patch(
            "제품을 구퇴화를 하고 진행합니다",
            "제품을 구퇴화를 하고 진행합니다",
            "제품을 구태화를 하고 진행합니다",
            audio_confidence=0.95,
            suspicion_signals=("within_row_lexical_inconsistency",),
            strict_runtime_evidence=True,
        )
        self.assertFalse(homophone["passed"])

    def test_attached_boundary_repairs_adverb_but_keeps_real_subject_particle(self) -> None:
        output = _review([
            "완벽하게이 스크린 플로우를 만듭니다.",
            "근데이 전환 이유를 설명합니다.",
            "사실이 중요합니다.",
        ])
        self.assertIn("완벽하게 스크린", output["normalized_utterances"][0]["normalized_text"])
        self.assertIn("근데 이 전환", output["normalized_utterances"][1]["normalized_text"])
        self.assertEqual(output["normalized_utterances"][2]["normalized_text"], "사실이 중요합니다.")

    def test_ambiguous_team_name_is_not_invented(self) -> None:
        output = _review(["레이지브라고 하는 팀을 만났습니다."])
        self.assertIn("레이지브", output["normalized_utterances"][0]["normalized_text"])

    def test_adaptive_budget_prioritizes_high_severity_with_bounded_cap(self) -> None:
        windows = [
            AudioWindow("low", 0, 120, ("UT-L",), 210),
            AudioWindow("high-a", 130, 230, ("UT-H1",), 420),
            AudioWindow("high-b", 240, 340, ("UT-H2",), 380),
            AudioWindow("overflow", 350, 650, ("UT-H3",), 370),
        ]
        selected, deferred, policy = select_windows_adaptive_high_severity(windows, 180)
        self.assertEqual({item.window_id for item in selected}, {"high-a", "high-b"})
        self.assertIn("overflow", {item.window_id for item in deferred})
        self.assertLessEqual(sum(item.duration_seconds for item in selected), 480)
        self.assertEqual(policy["mode"], "adaptive_high_severity_first")

    def test_foreign_input_bypasses_korean_pipeline(self) -> None:
        result = _result(["Broken foreign caption"], language="en")
        output = apply_korean_asr_editorial_review(
            result,
            _source(["Broken foreign caption"], language="en"),
            core=SimpleNamespace(),
            allow_model_review=False,
        )
        self.assertIs(output, result)
        self.assertNotIn("korean_editorial_review", output)


if __name__ == "__main__":
    unittest.main()
