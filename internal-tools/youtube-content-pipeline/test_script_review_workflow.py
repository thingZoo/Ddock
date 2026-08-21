from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from app_v0316_launcher import versioned_app_source
from review_store import autosave_path, load_autosave
from screenshot_output import final_image_path, final_json_path
from script_review_ui import (
    apply_manual_review_edits,
    build_timestamp_url,
    collect_review_items,
    initialize_review_session,
    pending_session_edits,
    persist_manual_review_edits,
    result_without_reexport_when_unchanged,
    review_result_fingerprint,
    review_session_key,
    review_workflow_applicable,
)


def _result(*, language: str = "ko", scope: str = "FULL") -> dict:
    rows = [
        {
            "utterance_id": "UT-00001",
            "start_seconds": 625.8,
            "end_seconds": 631.0,
            "display_timestamp": "10:25",
            "raw_joined_text": "타이퍼 컬러랑 스페이스 토큰",
            "normalized_text": "타이퍼 컬러랑 스페이스 토큰",
            "auto_normalized_text": "타이퍼 컬러랑 스페이스 토큰",
            "review_status": "needs_review",
            "korean_editorial_state": "audio_reviewed_unresolved",
            "source_segment_ids": ["TR-00001"],
            "source_spans": [{"segment_id": "TR-00001", "raw_segment_text": "타이퍼 컬러랑 스페이스 토큰"}],
            "validation_warnings": ["korean_audio_reasr:anchor_not_preserved"],
        },
        {
            "utterance_id": "UT-00002",
            "start_seconds": 900.0,
            "end_seconds": 906.0,
            "display_timestamp": "15:00",
            "raw_joined_text": "불확실한 용어",
            "normalized_text": "불확실한 용어",
            "auto_normalized_text": "불확실한 용어",
            "review_status": "needs_review",
            "korean_editorial_state": "review_pending",
            "source_segment_ids": ["TR-00002"],
            "source_spans": [{"segment_id": "TR-00002", "raw_segment_text": "불확실한 용어"}],
            "validation_warnings": [],
        },
        {
            "utterance_id": "UT-00003",
            "start_seconds": 920.0,
            "end_seconds": 925.0,
            "display_timestamp": "15:20",
            "raw_joined_text": "정상 문장",
            "normalized_text": "정상 문장",
            "auto_normalized_text": "정상 문장",
            "review_status": "approved",
            "korean_editorial_state": "clean",
            "source_segment_ids": ["TR-00003"],
            "source_spans": [{"segment_id": "TR-00003", "raw_segment_text": "정상 문장"}],
            "validation_warnings": [],
        },
    ]
    return {
        "schema_version": "script_preprocessing_v0.3.16",
        "created_at": "2026-08-21T00:00:00+00:00",
        "updated_at": "2026-08-21T00:00:00+00:00",
        "video_id": "review-fixture-video",
        "source_url": "https://www.youtube.com/watch?v=review-fixture-video",
        "source_title": "검토 fixture",
        "source_language": language,
        "translation_required": language != "ko",
        "processed_chapter": {"chapter_id": scope, "label": "전체 영상"},
        "raw_segments": [
            {"segment_id": "TR-00001", "text": "타이퍼 컬러랑 스페이스 토큰", "start_seconds": 625.8, "end_seconds": 631.0},
            {"segment_id": "TR-00002", "text": "불확실한 용어", "start_seconds": 900.0, "end_seconds": 906.0},
            {"segment_id": "TR-00003", "text": "정상 문장", "start_seconds": 920.0, "end_seconds": 925.0},
        ],
        "normalized_utterances": rows,
        "unresolved_terms": [
            {"utterance_id": "UT-00001", "reason": "anchor_not_preserved", "stage": "korean_audio_reasr"},
            {"utterance_id": "UT-00002", "reason": "audio_review_duration_budget_deferred", "stage": "korean_audio_reasr"},
        ],
        "korean_editorial_review": {
            "changed_items": [
                {"utterance_id": "UT-00001", "before": "커서", "after": "Cursor", "reason": "official_name"}
            ]
        },
        "korean_audio_review": {
            "classified_items": [
                {
                    "utterance_id": "UT-00001",
                    "classification": "audio_evidence_needed",
                    "audio_priority": "high",
                    "priority_score": 490.0,
                    "signals": ["technical_domain_phrase_near_match"],
                },
                {
                    "utterance_id": "UT-00002",
                    "classification": "audio_evidence_needed",
                    "audio_priority": "medium",
                    "priority_score": 220.0,
                    "signals": ["within_row_lexical_inconsistency"],
                },
            ],
            "candidates": [
                {"utterance_id": "UT-00001", "candidate_text": "타이포그래피 컬러랑 스페이싱 토큰"}
            ],
        },
        "content_chapters": [
            {
                "content_chapter_id": "CCH-01",
                "source_utterance_ids": ["UT-00001", "UT-00002"],
                "start_utterance_id": "UT-00001",
                "end_utterance_id": "UT-00002",
                "start_seconds": 625.8,
                "end_seconds": 906.0,
                "title": "디자인 토큰",
                "summary": "디자인 토큰 설명",
            }
        ],
        "content_chapter_assets": {
            "items": [
                {
                    "content_chapter_id": "CCH-01",
                    "chapter_fingerprint": "stable-fingerprint",
                    "selected_screenshot": {
                        "candidate_index": 1,
                        "relative_path": "CCH-01.jpg",
                        "storage_kind": "final_output",
                    },
                }
            ]
        },
        "processing_report": {},
        "correction_memory": {"applied": [], "global_updates": []},
    }


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class ScriptReviewWorkflowTests(unittest.TestCase):
    def test_needs_review_filter_excludes_clean_row(self) -> None:
        self.assertEqual(
            [item["utterance_id"] for item in collect_review_items(_result())],
            ["UT-00001", "UT-00002"],
        )

    def test_severity_order_is_high_then_medium(self) -> None:
        items = collect_review_items(_result())
        self.assertEqual([item["severity"] for item in items], ["high", "medium"])

    def test_manual_edit_changes_normalized_text_only(self) -> None:
        original = _result()
        saved = apply_manual_review_edits(original, {"UT-00001": "타이포그래피 컬러와 스페이싱 토큰"}, reviewed_at="2026-08-21T01:00:00+00:00")
        self.assertEqual(saved["normalized_utterances"][0]["normalized_text"], "타이포그래피 컬러와 스페이싱 토큰")
        self.assertEqual(saved["normalized_utterances"][0]["auto_normalized_text"], original["normalized_utterances"][0]["auto_normalized_text"])

    def test_raw_provenance_is_unchanged(self) -> None:
        original = _result()
        before = _hash({"raw": original["raw_segments"], "spans": [row["source_spans"] for row in original["normalized_utterances"]]})
        saved = apply_manual_review_edits(original, {"UT-00001": "수정 문장"})
        after = _hash({"raw": saved["raw_segments"], "spans": [row["source_spans"] for row in saved["normalized_utterances"]]})
        self.assertEqual(before, after)

    def test_multiple_edits_apply_in_one_operation(self) -> None:
        saved = apply_manual_review_edits(_result(), {"UT-00001": "수정 A", "UT-00002": "수정 B"})
        self.assertEqual([row["normalized_text"] for row in saved["normalized_utterances"][:2]], ["수정 A", "수정 B"])
        self.assertEqual(saved["manual_review"]["last_saved_edit_count"], 2)
        self.assertEqual(saved["processing_report"]["manual_review_remaining_utterances"], 0)

    def test_unsaved_session_edit_does_not_mutate_result(self) -> None:
        result = _result()
        before = copy.deepcopy(result)
        state: dict = {}
        items = initialize_review_session(state, result)
        state[review_session_key(result, "UT-00001")] = "아직 저장하지 않은 수정"
        self.assertEqual(pending_session_edits(state, result, items), {"UT-00001": "아직 저장하지 않은 수정"})
        self.assertEqual(result, before)

    def test_session_rerun_keeps_edit(self) -> None:
        result = _result()
        state: dict = {}
        initialize_review_session(state, result)
        key = review_session_key(result, "UT-00001")
        state[key] = "rerun 유지"
        initialize_review_session(state, result)
        self.assertEqual(state[key], "rerun 유지")

    def test_different_video_uses_isolated_session_key(self) -> None:
        first = _result()
        second = _result()
        second["video_id"] = "different-video"
        self.assertNotEqual(review_session_key(first, "UT-00001"), review_session_key(second, "UT-00001"))

    def test_save_failure_restores_original_files(self) -> None:
        result = _result()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            autosaves, outputs = root / "autosave", root / "output"
            auto_target = autosave_path(autosaves, result)
            json_target = final_json_path(outputs, result)
            auto_target.parent.mkdir(parents=True)
            json_target.parent.mkdir(parents=True)
            auto_target.write_text("original autosave", encoding="utf-8")
            json_target.write_text("original final", encoding="utf-8")

            def fail(path: Path, _value: dict) -> None:
                path.write_text("partial", encoding="utf-8")
                raise OSError("fixture failure")

            with self.assertRaises(OSError):
                persist_manual_review_edits(result, {"UT-00001": "수정"}, autosaves, outputs, final_writer=fail)
            self.assertEqual(auto_target.read_text(), "original autosave")
            self.assertEqual(json_target.read_text(), "original final")

    def test_manual_review_metadata_records_before_after(self) -> None:
        saved = apply_manual_review_edits(_result(), {"UT-00001": "수정"}, reviewed_at="2026-08-21T01:00:00+00:00")
        review = saved["normalized_utterances"][0]["human_review"]
        self.assertEqual(review["status"], "corrected")
        self.assertEqual(review["before"], "타이퍼 컬러랑 스페이스 토큰")
        self.assertEqual(review["after"], "수정")
        self.assertTrue(review["human_confirmed"])

    def test_legacy_json_without_manual_review_opens(self) -> None:
        result = _result()
        result.pop("manual_review", None)
        self.assertEqual(len(collect_review_items(result)), 2)

    def test_content_chapter_count_is_unchanged(self) -> None:
        result = _result()
        saved = apply_manual_review_edits(result, {"UT-00001": "수정"})
        self.assertEqual(saved["content_chapters"], result["content_chapters"])

    def test_source_ids_and_timing_are_unchanged(self) -> None:
        result = _result()
        before = [{key: row[key] for key in ("utterance_id", "start_seconds", "end_seconds", "source_segment_ids")} for row in result["normalized_utterances"]]
        saved = apply_manual_review_edits(result, {"UT-00001": "수정"})
        after = [{key: row[key] for key in ("utterance_id", "start_seconds", "end_seconds", "source_segment_ids")} for row in saved["normalized_utterances"]]
        self.assertEqual(before, after)

    def test_selected_screenshot_metadata_is_unchanged(self) -> None:
        result = _result()
        saved = apply_manual_review_edits(result, {"UT-00001": "수정"})
        self.assertEqual(saved["content_chapter_assets"], result["content_chapter_assets"])

    def test_screenshot_file_is_unchanged_by_global_save(self) -> None:
        result = _result()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            image = final_image_path(root / "output", result, "CCH-01")
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg fixture bytes")
            before = hashlib.sha256(image.read_bytes()).hexdigest()
            persist_manual_review_edits(result, {"UT-00001": "수정"}, root / "autosave", root / "output")
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), before)

    def test_korean_full_is_supported(self) -> None:
        self.assertTrue(review_workflow_applicable(_result(scope="FULL")))

    def test_korean_creator_chapter_is_supported(self) -> None:
        self.assertTrue(review_workflow_applicable(_result(scope="CH-02")))

    def test_korean_chapterless_full_is_supported(self) -> None:
        result = _result(scope="FULL")
        result["creator_chapters"] = []
        self.assertTrue(review_workflow_applicable(result))

    def test_foreign_result_keeps_legacy_workflow(self) -> None:
        self.assertFalse(review_workflow_applicable(_result(language="en")))

    def test_autosave_and_final_output_share_saved_result(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            package = persist_manual_review_edits(_result(), {"UT-00001": "수정"}, root / "autosave", root / "output", reviewed_at="2026-08-21T01:00:00+00:00")
            autosaved = load_autosave(package["autosave_path"])
            final = json.loads(package["json_path"].read_text(encoding="utf-8"))
            self.assertEqual(autosaved, final)
            self.assertEqual(final["normalized_utterances"][0]["normalized_text"], "수정")

    def test_timestamp_url_starts_before_utterance(self) -> None:
        self.assertTrue(build_timestamp_url(_result(), 625.8).endswith("t=624s"))

    def test_unchanged_editor_does_not_reexport_provenance(self) -> None:
        result = _result()
        frame = pd.DataFrame([
            {"utterance_id": row["utterance_id"], "normalized_text": row["normalized_text"], "review_status": row["review_status"]}
            for row in result["normalized_utterances"]
        ])
        exporter = Mock(side_effect=AssertionError("should not export"))
        current = result_without_reexport_when_unchanged(result, frame, exporter)
        self.assertEqual(current, result)
        exporter.assert_not_called()

    def test_changed_legacy_editor_still_uses_exporter(self) -> None:
        result = _result()
        frame = pd.DataFrame([
            {"utterance_id": row["utterance_id"], "normalized_text": row["normalized_text"], "review_status": row["review_status"]}
            for row in result["normalized_utterances"]
        ])
        frame.loc[0, "normalized_text"] = "legacy edit"
        exporter = Mock(return_value={"exported": True})
        self.assertEqual(result_without_reexport_when_unchanged(result, frame, exporter), {"exported": True})
        exporter.assert_called_once()

    def test_fingerprint_ignores_manual_text_but_isolates_new_run(self) -> None:
        result = _result()
        edited = copy.deepcopy(result)
        edited["normalized_utterances"][0]["normalized_text"] = "manual edit"
        self.assertEqual(review_result_fingerprint(result), review_result_fingerprint(edited))
        edited["created_at"] = "2026-08-22T00:00:00+00:00"
        self.assertNotEqual(review_result_fingerprint(result), review_result_fingerprint(edited))

    def test_correction_memory_is_not_modified(self) -> None:
        result = _result()
        saved = apply_manual_review_edits(result, {"UT-00001": "수정"})
        self.assertEqual(saved["correction_memory"], result["correction_memory"])
        self.assertFalse(saved["manual_review"]["global_correction_memory_updated"])

    def test_v0316_launcher_installs_optional_review_before_screenshots(self) -> None:
        path, source = versioned_app_source()
        compile(source, str(path), "exec")
        self.assertIn("render_optional_script_review", source)
        self.assertIn("result_without_reexport_when_unchanged", source)
        self.assertLess(
            source.index("render_optional_script_review"),
            source.index("render_screenshot_workflow"),
        )


if __name__ == "__main__":
    unittest.main()
