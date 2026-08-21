from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from korean_asr_editorial_review import apply_korean_asr_editorial_review
from korean_audio_reasr import (
    AudioWindow,
    KoreanAudioASRAdapter,
    _resolve_ytdlp_status,
    align_candidate_to_row,
    apply_selective_audio_reasr,
    build_span_safe_patch,
    cluster_audio_windows,
    select_windows_by_duration_budget,
)
from runtime_generation_metrics import capture_runtime_generation_metrics, generation_stage
from v0316_extension import _install_generation_instrumentation


def _source(texts: list[str], *, language: str = "ko") -> dict:
    items = []
    for index, text in enumerate(texts):
        items.append(
            {
                "segment_id": f"TR-{index + 1:05d}",
                "text": text,
                "start_seconds": float(index * 10),
                "end_seconds": float(index * 10 + 6),
            }
        )
    return {
        "metadata": {
            "video_id": "audio-fixture-video",
            "source_url": "https://example.invalid/watch/audio-fixture-video",
            "title": "Figma AI 개발 워크플로우",
            "description_raw": "Figma Dev Mode, React, Cursor와 UI 시스템을 설명합니다.",
            "duration_seconds": max(60.0, float(len(texts) * 10 + 6)),
        },
        "creator_chapters": [
            {
                "start_seconds": 0.0,
                "end_seconds": max(60.0, float(len(texts) * 10 + 6)),
                "label": "AI 디자인 도구",
            }
        ],
        "transcript": {
            "language": language,
            "language_code": language,
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
                "chapter_id": "FULL",
                "chapter_label": "AI 디자인 도구",
                "start_seconds": float(index * 10),
                "end_seconds": float(index * 10 + 6),
                "raw_joined_text": text,
                "normalized_text": text,
                "auto_normalized_text": text,
                "source_segment_ids": [segment_id],
                "source_spans": [
                    {
                        "segment_id": segment_id,
                        "raw_segment_text": text,
                        "start_seconds": float(index * 10),
                        "end_seconds": float(index * 10 + 6),
                    }
                ],
                "validation_warnings": [],
                "normalization_item_ids": [],
                "review_status": "needs_review",
            }
        )
        raw.append(
            {
                "segment_id": segment_id,
                "text": text,
                "start_seconds": float(index * 10),
                "end_seconds": float(index * 10 + 6),
            }
        )
    return {
        "video_id": "audio-fixture-video",
        "source_url": "https://example.invalid/watch/audio-fixture-video",
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


def _core() -> SimpleNamespace:
    return SimpleNamespace(
        _DEFAULT_LOCAL_LLM_MODEL_V034="local-qwen-fixture",
        _extract_json_object_v032=lambda value: json.loads(value),
    )


def _editorial(
    result: dict,
    source: dict,
    *,
    signal: str = "metadata_term_embedded_in_unknown_token",
) -> dict:
    output = apply_korean_asr_editorial_review(
        result,
        source,
        core=_core(),
        allow_model_review=False,
    )
    # Tests exercise general audio contracts without relying on the evolving
    # lexical detector to recognize a particular fixture spelling.
    row = output["normalized_utterances"][0]
    output["korean_editorial_review"]["suspicious_items"] = [
        {
            "utterance_id": row["utterance_id"],
            "chapter_id": row["chapter_id"],
            "start_seconds": row["start_seconds"],
            "signals": [signal],
            "suspicion_score": 9.0,
        }
    ]
    output["korean_editorial_review"]["suspicious_count"] = 1
    return output


class MockAdapter:
    engine_name = "mock-local-asr"
    model_name = "mock-korean-model"

    def __init__(self, outputs=None, *, available=True, failure=None):
        self.outputs = list(outputs or [])
        self.available = available
        self.failure = failure
        self.calls = []
        self.capability_calls = 0
        self.model_load_count = 1 if available else 0
        self.model_load_seconds = 0.01 if available else 0.0
        self.generation_seconds = 0.0

    def capability(self):
        self.capability_calls += 1
        return {
            "available": self.available,
            "engine": self.engine_name,
            "model": self.model_name,
            "reason": None if self.available else "fixture_unavailable",
            "automatic_download": False,
        }

    def transcribe(self, audio_path, start_seconds, end_seconds):
        self.calls.append((Path(audio_path), start_seconds, end_seconds))
        if self.failure:
            raise self.failure
        return copy.deepcopy(self.outputs.pop(0))


class PreparedAudio:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = 0
        self.temp_paths = []

    @contextmanager
    def __call__(self, _url):
        self.calls += 1
        if self.failure:
            raise self.failure
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "source.m4a"
            path.write_bytes(b"fixture-audio")
            self.temp_paths.append(Path(name))
            yield path, {
                "audio_download_count": 1,
                "audio_bytes": path.stat().st_size,
                "audio_source_prepare_seconds": 0.02,
            }


def _words(texts: list[str], start: float, *, probability: float = 0.95):
    words = []
    for index, text in enumerate(texts):
        words.append(
            {
                "word": (" " if index else "") + text,
                "start": start + index * 0.7,
                "end": start + index * 0.7 + 0.6,
                "probability": probability,
            }
        )
    return words


class KoreanAudioReasrTests(unittest.TestCase):
    def test_clean_korean_uses_no_audio_or_model(self):
        texts = ["오늘은 디자인 시스템의 기본 원리를 설명합니다."] * 10
        source = _source(texts)
        result = apply_korean_asr_editorial_review(
            _result(texts), source, core=_core(), allow_model_review=False
        )
        adapter = MockAdapter()
        prepared = PreparedAudio()
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=prepared
        )
        metrics = output["korean_audio_review"]["runtime_metrics"]
        self.assertEqual(metrics["audio_download_count"], 0)
        self.assertEqual(metrics["asr_call_count"], 0)
        self.assertEqual(metrics["qwen_verifier_calls"], 0)
        self.assertEqual(adapter.capability_calls, 0)
        self.assertEqual(prepared.calls, 0)

    def test_official_canonicalization_needs_no_audio(self):
        texts = [
            "Figma 데브모드 MCP에서 리액트 코드를 커서로 구현합니다."
        ] + ["정상적인 후속 설명입니다."] * 9
        source = _source(texts)
        result = apply_korean_asr_editorial_review(
            _result(texts), source, core=_core(), allow_model_review=False
        )
        adapter = MockAdapter()
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        text = output["normalized_utterances"][0]["normalized_text"]
        self.assertIn("Dev Mode", text)
        self.assertIn("React", text)
        self.assertIn("Cursor", text)
        self.assertEqual(output["korean_audio_review"]["runtime_metrics"]["asr_call_count"], 0)

    def test_severe_audio_evidence_is_safely_applied(self):
        texts = ["근데 제가 처음 보드렸던 것만큼의 퀄리티는 나오지 않았지만"] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        adapter = MockAdapter(
            [{"text": "근데 제가 처음 보여드렸던 것만큼의 퀄리티는 나오지 않았지만", "words": _words(["근데", "제가", "처음", "보여드렸던", "것만큼의", "퀄리티는", "나오지", "않았지만"], 0.5)}]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertEqual(
            output["normalized_utterances"][0]["normalized_text"],
            "근데 제가 처음 보여드렸던 것만큼의 퀄리티는 나오지 않았지만",
        )
        self.assertEqual(output["korean_audio_review"]["audio_repaired_count"], 1)
        self.assertEqual(
            output["normalized_utterances"][0]["korean_editorial_state"],
            "audio_span_repaired",
        )

    def test_human_verified_severe_fixture_keeps_row_ownership(self):
        texts = [
            "앞 문장은 인터뷰 소개입니다.",
            "알모신 분들은 마튜터만 잘 따라가시면 됩니다.",
            "뒤 문장은 화면 설명입니다.",
        ] + ["정상 문맥입니다."] * 7
        source = _source(texts)
        result = _editorial(_result(texts), source)
        result["korean_editorial_review"]["suspicious_items"] = [
            {
                "utterance_id": "UT-00002",
                "chapter_id": "FULL",
                "start_seconds": 10.0,
                "signals": ["metadata_term_embedded_in_unknown_token"],
                "suspicion_score": 10.0,
            }
        ]
        adapter = MockAdapter(
            [
                {
                    "text": "앞 문장은 인터뷰 소개입니다. 디알못인 분들은 피그마 튜터님에만 잘 따라가시면 됩니다. 뒤 문장은 화면 설명입니다.",
                    "words": (
                        _words(["앞", "문장은", "인터뷰", "소개입니다."], 7.0)
                        + _words(["디알못인", "분들은", "피그마", "튜터님에만", "잘", "따라가시면", "됩니다."], 10.3)
                        + _words(["뒤", "문장은", "화면", "설명입니다."], 16.2)
                    ),
                }
            ]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        repaired = output["normalized_utterances"][1]["normalized_text"]
        self.assertIn("알모신 분들은 Figma 튜터님에만", repaired)
        self.assertNotIn("앞 문장", repaired)
        self.assertNotIn("뒤 문장", repaired)

    def test_padding_words_are_not_owned_by_current_row(self):
        row = _result(["현재 발화입니다."])["normalized_utterances"][0]
        row["start_seconds"], row["end_seconds"] = 10.0, 16.0
        window = AudioWindow("ARW-0001", 8.25, 17.75, ("UT-00001",), 3)
        output = {
            "words": (
                _words(["이전", "내용"], 8.4)
                + _words(["현재", "발화입니다."], 11.0)
                + _words(["다음", "내용"], 16.5)
            )
        }
        aligned = align_candidate_to_row(output, row, window)
        self.assertEqual(aligned["candidate_text"], "현재 발화입니다.")

    def test_word_timestamp_alignment_uses_midpoint(self):
        row = _result(["현재 발화"])["normalized_utterances"][0]
        row["start_seconds"], row["end_seconds"] = 5.0, 8.0
        window = AudioWindow("ARW-0001", 3.25, 9.75, ("UT-00001",), 3)
        aligned = align_candidate_to_row(
            {
                "words": [
                    {"word": " 밖", "start": 4.0, "end": 4.5, "probability": 0.9},
                    {"word": " 안", "start": 4.8, "end": 5.4, "probability": 0.9},
                    {"word": " 끝", "start": 7.7, "end": 8.2, "probability": 0.9},
                ]
            },
            row,
            window,
        )
        self.assertEqual(aligned["candidate_text"], "안 끝")

    def test_overlapping_rows_receive_exclusive_words(self):
        texts = ["첫 번째 기존 발화입니다.", "두 번째 기존 발화입니다."] + [
            "정상 문맥입니다."
        ] * 8
        source = _source(texts)
        result = _editorial(_result(texts), source)
        first, second = result["normalized_utterances"][:2]
        first["start_seconds"], first["end_seconds"] = 10.0, 16.0
        second["start_seconds"], second["end_seconds"] = 15.0, 20.0
        result["korean_editorial_review"]["suspicious_items"] = [
            {
                "utterance_id": row["utterance_id"],
                "chapter_id": "FULL",
                "start_seconds": row["start_seconds"],
                "signals": ["metadata_term_embedded_in_unknown_token"],
                "suspicion_score": 9.0,
            }
            for row in (first, second)
        ]
        adapter = MockAdapter(
            [
                {
                    "text": "첫 번째 분명한 발화입니다. 두 번째 분명한 발화입니다.",
                    "words": (
                        _words(["첫", "번째", "분명한", "발화입니다."], 10.2)
                        + _words(["두", "번째", "분명한", "발화입니다."], 15.6)
                    ),
                }
            ]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertEqual(
            output["normalized_utterances"][0]["normalized_text"],
            "첫 번째 기존 발화입니다.",
        )
        self.assertEqual(
            output["normalized_utterances"][1]["normalized_text"],
            "두 번째 기존 발화입니다.",
        )
        self.assertEqual(len(adapter.calls), 1)

    def test_no_word_timestamp_never_auto_replaces(self):
        texts = ["깨진 발화 조각입니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        adapter = MockAdapter([{"text": "완전히 다른 후보입니다.", "segments": []}])
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertEqual(output["normalized_utterances"][0]["normalized_text"], texts[0])
        self.assertEqual(output["korean_audio_review"]["audio_unresolved_count"], 1)

    def test_ambiguous_acronym_with_unclear_audio_stays_unresolved(self):
        texts = ["그분의 ICP가 PM과 회의를 진행합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source, signal="singleton_unregistered_acronym")
        adapter = MockAdapter(
            [{"text": "불명확", "words": _words(["불명확"], 0.5, probability=0.3)}]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertIn("ICP", output["normalized_utterances"][0]["normalized_text"])
        self.assertEqual(output["korean_audio_review"]["audio_repaired_count"], 0)

    def test_plan_mode_audio_and_registry_are_canonicalized(self):
        texts = ["agent가 구현 전에 플랜 모드를 사용합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        adapter = MockAdapter(
            [{"text": texts[0], "words": _words(["agent가", "구현", "전에", "플랜", "모드를", "사용합니다."], 0.4)}]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertIn("Plan Mode", output["normalized_utterances"][0]["normalized_text"])

    def test_shadcn_audio_candidate_can_use_verified_registry(self):
        texts = ["오늘은 샤드씨엔 키트를 사용합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source, signal="unverified_official_name_candidate")
        adapter = MockAdapter(
            [{"text": "오늘은 shadcn/ui 키트를 사용합니다.", "words": _words(["오늘은", "shadcn/ui", "키트를", "사용합니다."], 0.4)}]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertIn("shadcn/ui", output["normalized_utterances"][0]["normalized_text"])

    def test_moderate_candidate_requires_noninventive_qwen_verifier(self):
        texts = ["근데 제가 처음 보드렸던 것을 설명합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        candidate = "근데 제가 처음 보여드렸던 것을 설명합니다."
        adapter = MockAdapter(
            [{"text": candidate, "words": _words(candidate.split(), 0.4, probability=0.65)}]
        )
        calls = []

        def verifier(_model, _system, user, _tokens):
            calls.append(json.loads(user))
            return json.dumps(
                {
                    "decision": "accept_reasr",
                    "confidence": "high",
                    "reason": "timestamp aligned audio evidence",
                    "corrected_text": candidate,
                    "evidence": ["audio"],
                },
                ensure_ascii=False,
            )

        output = apply_selective_audio_reasr(
            result,
            source,
            core=_core(),
            adapter=adapter,
            audio_preparer=PreparedAudio(),
            verifier_generator=verifier,
        )
        self.assertEqual(output["normalized_utterances"][0]["normalized_text"], candidate)
        self.assertEqual(len(calls), 1)

    def test_qwen_cannot_invent_third_wording(self):
        texts = ["깨진 표현을 설명합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        adapter = MockAdapter(
            [{"text": "오디오 후보입니다.", "words": _words(["오디오", "후보입니다."], 0.4, probability=0.65)}]
        )

        def verifier(_model, _system, _user, _tokens):
            return json.dumps(
                {
                    "decision": "accept_reasr",
                    "confidence": "high",
                    "reason": "guess",
                    "corrected_text": "모델이 만든 제3의 문장입니다.",
                    "evidence": [],
                },
                ensure_ascii=False,
            )

        output = apply_selective_audio_reasr(
            result,
            source,
            core=_core(),
            adapter=adapter,
            audio_preparer=PreparedAudio(),
            verifier_generator=verifier,
        )
        self.assertEqual(output["normalized_utterances"][0]["normalized_text"], texts[0])

    def test_audio_candidate_cannot_change_actor_or_action(self):
        for before, candidate in (
            ("제가 파일을 저장합니다.", "그가 파일을 저장합니다."),
            ("제가 파일을 저장합니다.", "제가 파일을 삭제합니다."),
        ):
            with self.subTest(candidate=candidate):
                texts = [before] + ["정상 문맥입니다."] * 9
                source = _source(texts)
                result = _editorial(_result(texts), source)
                adapter = MockAdapter(
                    [
                        {
                            "text": candidate,
                            "words": _words(candidate.split(), 0.4),
                        }
                    ]
                )
                output = apply_selective_audio_reasr(
                    result,
                    source,
                    core=_core(),
                    adapter=adapter,
                    audio_preparer=PreparedAudio(),
                )
                self.assertEqual(
                    output["normalized_utterances"][0]["normalized_text"], before
                )

    def test_nearby_rows_share_one_window_and_far_rows_split(self):
        rows = _result(["문장"] * 5)["normalized_utterances"]
        rows[0]["start_seconds"], rows[0]["end_seconds"] = 10.0, 14.0
        rows[1]["start_seconds"], rows[1]["end_seconds"] = 15.0, 19.0
        rows[2]["start_seconds"], rows[2]["end_seconds"] = 50.0, 54.0
        mapping = {row["utterance_id"]: row for row in rows}
        records = [
            {"utterance_id": row["utterance_id"], "priority_score": 3}
            for row in rows[:3]
        ]
        windows = cluster_audio_windows(records, mapping, duration_seconds=100.0)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].row_ids, ("UT-00001", "UT-00002"))
        self.assertEqual(windows[1].row_ids, ("UT-00003",))

    def test_duration_budget_prioritizes_high_severity_windows(self):
        windows = [
            AudioWindow("low", 0.0, 20.0, ("A",), 1),
            AudioWindow("high", 30.0, 50.0, ("B",), 3),
        ]
        selected, deferred = select_windows_by_duration_budget(windows, 20.0)
        self.assertEqual([item.window_id for item in selected], ["high"])
        self.assertEqual([item.window_id for item in deferred], ["low"])
        selected, deferred = select_windows_by_duration_budget(windows, 0.0)
        self.assertEqual(selected, [])
        self.assertEqual(len(deferred), 2)

    def test_asr_model_failure_preserves_deterministic_output(self):
        texts = ["깨진 발화 조각입니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        baseline = result["normalized_utterances"][0]["normalized_text"]
        adapter = MockAdapter(failure=RuntimeError("fixture model failure"))
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertEqual(output["normalized_utterances"][0]["normalized_text"], baseline)
        self.assertEqual(output["korean_audio_review"]["review_failed_count"], 1)

    def test_audio_download_failure_is_nonfatal(self):
        texts = ["깨진 발화 조각입니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        baseline = copy.deepcopy(result)
        output = apply_selective_audio_reasr(
            result,
            source,
            core=_core(),
            adapter=MockAdapter(),
            audio_preparer=PreparedAudio(failure=RuntimeError("download failed")),
        )
        self.assertEqual(
            output["normalized_utterances"][0]["normalized_text"],
            baseline["normalized_utterances"][0]["normalized_text"],
        )
        self.assertGreaterEqual(output["korean_audio_review"]["review_failed_count"], 1)

    def test_unavailable_engine_does_not_download(self):
        texts = ["깨진 발화 조각입니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        prepared = PreparedAudio()
        output = apply_selective_audio_reasr(
            result,
            source,
            core=_core(),
            adapter=MockAdapter(available=False),
            audio_preparer=prepared,
        )
        self.assertEqual(prepared.calls, 0)
        self.assertGreaterEqual(output["korean_audio_review"]["review_pending_count"], 1)

    def test_foreign_source_bypasses_audio_stage(self):
        texts = ["Broken foreign caption"]
        source = _source(texts, language="en")
        result = _result(texts, language="en")
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=MockAdapter(), audio_preparer=PreparedAudio()
        )
        self.assertNotIn("korean_audio_review", output)

    def test_raw_provenance_and_timing_are_unchanged(self):
        texts = ["깨진 발화 조각입니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        raw_before = json.dumps(result["raw_segments"], ensure_ascii=False, sort_keys=True)
        spans_before = copy.deepcopy(
            [row["source_spans"] for row in result["normalized_utterances"]]
        )
        timing_before = [
            (row["utterance_id"], row["start_seconds"], row["end_seconds"])
            for row in result["normalized_utterances"]
        ]
        adapter = MockAdapter(
            [{"text": "분명한 발화입니다.", "words": _words(["분명한", "발화입니다."], 0.5)}]
        )
        prepared = PreparedAudio()
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=prepared
        )
        self.assertEqual(
            json.dumps(output["raw_segments"], ensure_ascii=False, sort_keys=True),
            raw_before,
        )
        self.assertEqual(
            [row["source_spans"] for row in output["normalized_utterances"]],
            spans_before,
        )
        self.assertEqual(
            [
                (row["utterance_id"], row["start_seconds"], row["end_seconds"])
                for row in output["normalized_utterances"]
            ],
            timing_before,
        )
        self.assertTrue(all(not path.exists() for path in prepared.temp_paths))

    def test_span_patch_single_corrupted_span_preserves_both_anchors(self):
        before = "근데 제가 처음 보드렸던 것만큼의 퀄리티는 나오지 않았지만"
        plan = build_span_safe_patch(
            before,
            before,
            "근데 제가 처음 보여드렸던 것만큼의 퀄리티는 나오지 않았지만",
        )
        self.assertTrue(plan["passed"])
        self.assertEqual(plan["span_from"], "보드렸던")
        self.assertEqual(plan["span_to"], "보여드렸던")
        self.assertEqual(
            plan["patched_text"],
            "근데 제가 처음 보여드렸던 것만큼의 퀄리티는 나오지 않았지만",
        )

    def test_missing_prefix_cannot_replace_whole_row(self):
        before = "근데 제가 처음 보드렸던 것만큼의 퀄리티는 나오지 않았지만"
        plan = build_span_safe_patch(
            before,
            before,
            "보여드렸던 것만큼의 퀄리티는 나오지 않았지만",
        )
        self.assertFalse(plan["passed"])
        self.assertTrue(plan["prefix_loss_detected"])
        self.assertEqual(plan["patched_text"], before)

    def test_missing_major_prefix_clause_is_not_auto_applied(self):
        before = "알모신 분들은 마튜터만 잘 따라가시면"
        plan = build_span_safe_patch(
            before,
            before,
            "Figma 튜터님만 잘 따라가시면",
            known_latin={"figma"},
        )
        self.assertFalse(plan["passed"])
        self.assertEqual(plan["patched_text"], before)

    def test_partial_safe_entity_span_keeps_uncertain_prefix(self):
        before = "알모신 분들은 마튜터만 잘 따라가시면"
        plan = build_span_safe_patch(
            before,
            before,
            "기알모이신 분들은 Figma 튜터님만 잘 따라가시면",
            known_latin={"figma"},
        )
        self.assertTrue(plan["passed"])
        self.assertEqual(
            plan["patched_text"],
            "알모신 분들은 Figma 튜터님만 잘 따라가시면",
        )
        self.assertGreater(plan["residual_current_span_count"], 0)
        self.assertTrue(
            {
                "localized_audio_evidence_too_dissimilar",
                "anchor_not_preserved",
            }
            & {item["reason"] for item in plan["rejected_spans"]},
        )

    def test_whisper_spacing_only_difference_is_not_a_repair(self):
        before = "그래서 커뮤니티라는 데가 있잖아요."
        plan = build_span_safe_patch(
            before,
            before,
            "그래서 커뮤니티 라는 데가 있잖아요.",
        )
        self.assertFalse(plan["passed"])
        self.assertIn(
            "formatting_only_audio_difference",
            {item["reason"] for item in plan["rejected_spans"]},
        )

    def test_whisper_punctuation_loss_is_not_a_repair(self):
        before = "그럴 수 있죠. 하지만 설명은 이어집니다."
        plan = build_span_safe_patch(
            before,
            before,
            "그럴 수 있죠 하지만 설명은 이어집니다",
        )
        self.assertFalse(plan["passed"])
        self.assertEqual(plan["patched_text"], before)

    def test_single_token_whisper_expansion_is_not_a_repair(self):
        before = "디자인 시스템들이 많습니다."
        plan = build_span_safe_patch(
            before,
            before,
            "디자인 시스템이 들이 많습니다.",
        )
        self.assertFalse(plan["passed"])
        self.assertIn(
            "single_token_expanded_without_official_entity_evidence",
            {item["reason"] for item in plan["rejected_spans"]},
        )

    def test_next_row_phrase_leakage_is_flagged(self):
        before = "오늘은 피그마를 잘 따라가시면 됩니다."
        plan = build_span_safe_patch(
            before,
            before,
            before + " 네 좋습니다.",
            following="네 좋습니다.",
            speaker_transition=True,
        )
        self.assertTrue(plan["adjacent_leakage_detected"])
        self.assertFalse(plan["passed"])

    def test_previous_row_phrase_leakage_is_flagged(self):
        before = "알모신 분들은 마튜터만 잘 따라가시면"
        plan = build_span_safe_patch(
            before,
            before,
            "그래서 오늘 기알모이신 분들은 마튜터만 잘 따라가시면",
            previous="그래서 오늘 인터뷰를 시작합니다.",
        )
        self.assertTrue(plan["adjacent_leakage_detected"])
        self.assertTrue(plan["prefix_loss_detected"])

    def test_high_audio_confidence_cannot_override_anchor_failure(self):
        texts = ["알모신 분들은 마튜터만 잘 따라가시면"] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        adapter = MockAdapter(
            [{"text": "피그마 튜터님만 잘 따라가시면", "words": _words(["피그마", "튜터님만", "잘", "따라가시면"], 0.4, probability=0.95)}]
        )
        output = apply_selective_audio_reasr(
            result, source, core=_core(), adapter=adapter, audio_preparer=PreparedAudio()
        )
        self.assertEqual(output["normalized_utterances"][0]["normalized_text"], texts[0])
        record = output["korean_audio_review"]["candidates"][0]
        self.assertEqual(record["boundary_integrity"], "failed")
        self.assertEqual(record["final_decision"], "unresolved")

    def test_no_changed_span_keeps_existing(self):
        before = "Figma Dev Mode를 사용합니다."
        plan = build_span_safe_patch(before, before, before)
        self.assertFalse(plan["passed"])
        self.assertEqual(plan["failure_reason"], "empty_or_unchanged_audio_candidate")

    def test_clean_sentence_gets_no_patch(self):
        before = "오늘은 디자인 시스템을 설명합니다."
        plan = build_span_safe_patch(before, before, before)
        self.assertEqual(plan["patched_text"], before)
        self.assertEqual(plan["span_patches"], [])

    def test_number_change_is_never_applied(self):
        texts = ["지금은 50% 결과를 설명합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        candidate = "지금은 15% 결과를 설명합니다."
        output = apply_selective_audio_reasr(
            result,
            source,
            core=_core(),
            adapter=MockAdapter([{"text": candidate, "words": _words(candidate.split(), 0.4)}]),
            audio_preparer=PreparedAudio(),
        )
        self.assertEqual(output["normalized_utterances"][0]["normalized_text"], texts[0])

    def test_official_entity_stable_candidate_is_unchanged(self):
        before = "오늘은 Figma Dev Mode를 사용합니다."
        plan = build_span_safe_patch(before, before, before, known_latin={"figma", "dev", "mode"})
        self.assertFalse(plan["passed"])
        self.assertEqual(plan["patched_text"], before)

    def test_protected_korean_concept_is_not_forced_to_latin(self):
        texts = ["여기서 컴포넌트 구조를 설명합니다."] + ["정상 문맥입니다."] * 9
        source = _source(texts)
        result = _editorial(_result(texts), source)
        candidate = "여기서 Component 구조를 설명합니다."
        output = apply_selective_audio_reasr(
            result,
            source,
            core=_core(),
            adapter=MockAdapter([{"text": candidate, "words": _words(candidate.split(), 0.4)}]),
            audio_preparer=PreparedAudio(),
        )
        self.assertIn("컴포넌트", output["normalized_utterances"][0]["normalized_text"])

    def test_pinned_nightly_is_resolved_once_per_process(self):
        _resolve_ytdlp_status.cache_clear()
        pinned = {
            "available": True,
            "executable_path": "/fixture/pinned-yt-dlp",
            "version": "nightly-fixture",
        }
        with patch("korean_audio_reasr.inspect_pinned_yt_dlp", return_value=pinned) as inspect:
            first = _resolve_ytdlp_status()
            second = _resolve_ytdlp_status()
        self.assertEqual(first["source"], "pinned_nightly_sidecar")
        self.assertEqual(first["executable"], "/fixture/pinned-yt-dlp")
        self.assertIs(first, second)
        self.assertEqual(inspect.call_count, 1)
        self.assertEqual(
            inspect.call_args.kwargs["timeout_seconds"],
            30.0,
        )
        _resolve_ytdlp_status.cache_clear()

    def test_default_adapter_never_claims_auto_download(self):
        capability = KoreanAudioASRAdapter().capability()
        self.assertFalse(capability["automatic_download"])

    def test_qwen_verifier_metrics_are_not_translation(self):
        core = SimpleNamespace(
            _LOCAL_LLM_CACHE_V032={},
            _DEFAULT_LOCAL_LLM_MODEL_V032="fixture-model",
            _load_local_llm_v032=lambda name: {"model": name},
            _generate_local_llm_text_v033=lambda *_args, **_kwargs: "{}",
        )
        _install_generation_instrumentation(core)
        with capture_runtime_generation_metrics() as metrics:
            with generation_stage("korean_audio_reasr_verifier"):
                core._generate_local_llm_text_v033("fixture-model", "s", "u", 50)
        self.assertEqual(metrics["total_generation_calls"], 1)
        self.assertEqual(metrics["translation_generation_calls"], 0)
        self.assertEqual(metrics["korean_audio_reasr_verifier_generation_calls"], 1)


if __name__ == "__main__":
    unittest.main()
