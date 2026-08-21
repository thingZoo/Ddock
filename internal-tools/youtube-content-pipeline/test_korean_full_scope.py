from __future__ import annotations

import copy
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import app_v0316_launcher
import v0316_extension
from content_chapter_segmentation import apply_content_chapter_policy
from korean_full_scope import (
    CHAPTER_SCOPE,
    CHAPTER_SCOPE_LABEL,
    WHOLE_VIDEO_SCOPE,
    WHOLE_VIDEO_SCOPE_LABEL,
    finalize_korean_full_result,
    preprocessing_autosave_target_id,
    render_korean_processing_scope,
    scope_session_key,
    source_for_korean_full,
)
from screenshot_ui import build_screenshot_workflow_view
from review_store import autosave_path
from youtube_acquisition_ui import _clear_downstream_state


def _source(*, language: str = "ko", chapters: bool = True, video_id: str = "video-a"):
    creator_chapters = (
        [
            {
                "timestamp_text": "0:00",
                "label": "처음",
                "start_seconds": 0.0,
                "end_seconds": 20.0,
            },
            {
                "timestamp_text": "0:20",
                "label": "다음",
                "start_seconds": 20.0,
                "end_seconds": 40.0,
            },
        ]
        if chapters
        else []
    )
    return {
        "metadata": {
            "video_id": video_id,
            "title": "fixture",
            "duration_seconds": 40.0,
        },
        "transcript": {
            "language_code": language,
            "items": [
                {"segment_id": "SEG-1", "start_seconds": 1.0, "end_seconds": 2.0, "text": "하나"},
                {"segment_id": "SEG-2", "start_seconds": 21.0, "end_seconds": 22.0, "text": "둘"},
                {"segment_id": "SEG-3", "start_seconds": 31.0, "end_seconds": 32.0, "text": "셋"},
            ],
        },
        "creator_chapters": creator_chapters,
    }


class _FakeStreamlit:
    def __init__(self, selection: str):
        self.selection = selection
        self.radio_calls = []

    def radio(self, label, **kwargs):
        self.radio_calls.append((label, kwargs))
        return self.selection


def _fake_core():
    calls = []

    def translation_required(source):
        return not str(source["transcript"]["language_code"]).startswith("ko")

    def build(data, chapter_index=0, **kwargs):
        calls.append((copy.deepcopy(data), dict(kwargs)))
        chapters = data.get("creator_chapters") or []
        if chapters:
            chapter = chapters[chapter_index]
            start = float(chapter.get("start_seconds", 0) or 0)
            end = float(chapter.get("end_seconds", 40) or 40)
            chapter_id = f"CH-{chapter_index + 1:02d}"
        else:
            start, end, chapter_id = 0.0, 40.0, "FULL"
        items = [
            item
            for item in data["transcript"]["items"]
            if start <= float(item["start_seconds"]) < end
        ]
        return {
            "video_id": data["metadata"]["video_id"],
            "source_language": data["transcript"]["language_code"],
            "input_document_kind": "acquisition",
            "processed_chapter": {
                "chapter_id": chapter_id,
                "start_seconds": start,
                "end_seconds": end,
            },
            "normalized_utterances": [
                {
                    "utterance_id": f"UT-{index:05d}",
                    "normalized_text": item["text"],
                    "start_seconds": item["start_seconds"],
                    "end_seconds": item["end_seconds"],
                }
                for index, item in enumerate(items, start=1)
            ],
            "translation_required": False,
            "translation_status": "not_required",
        }

    def owner_for_time(data, seconds):
        chapters = data.get("creator_chapters") or []
        chosen_index = 0
        for index, chapter in enumerate(chapters):
            if float(chapter.get("start_seconds", 0) or 0) <= float(seconds or 0):
                chosen_index = index
            else:
                break
        chapter = copy.deepcopy(chapters[chosen_index])
        chapter["chapter_id"] = f"CH-{chosen_index + 1:02d}"
        chapter["chapter_index"] = chosen_index
        return chapter

    core = types.SimpleNamespace(
        _V03151_PATCH_APPLIED=True,
        _V03151_PATCH_VERSION="v0.3.15.1",
        build_preprocessing_draft=build,
        prepare_existing_preprocessing=lambda data: data,
        export_editor_result=lambda draft, rows: draft,
        translation_required_for_source=translation_required,
        _creator_chapter_for_time_v033=owner_for_time,
    )
    return core, calls


def _add_mock_content_chapters(result, source_data=None, **kwargs):
    output = copy.deepcopy(result)
    output["content_chapters"] = [
        {
            "content_chapter_id": "CCH-01",
            "title": "fixture chapter",
            "source_utterance_ids": ["UT-00001"],
        }
    ]
    output["content_chapter_generation"] = {
        "semantic_split_applied": False,
        "llm_invoked": False,
    }
    return output


class KoreanFullScopeTests(unittest.TestCase):
    def test_chapter_scope_ui_is_available_for_korean_with_chapters(self):
        st = _FakeStreamlit(CHAPTER_SCOPE_LABEL)
        source = _source()
        scope = render_korean_processing_scope(
            st,
            source,
            source["creator_chapters"],
            needs_translation=False,
        )
        self.assertEqual(scope, CHAPTER_SCOPE)
        self.assertEqual(st.radio_calls[0][0], "처리 범위")
        self.assertEqual(
            st.radio_calls[0][1]["options"],
            [CHAPTER_SCOPE_LABEL, WHOLE_VIDEO_SCOPE_LABEL],
        )

    def test_full_scope_ui_is_available_for_korean_with_chapters(self):
        st = _FakeStreamlit(WHOLE_VIDEO_SCOPE_LABEL)
        source = _source()
        self.assertEqual(
            render_korean_processing_scope(
                st,
                source,
                source["creator_chapters"],
                needs_translation=False,
            ),
            WHOLE_VIDEO_SCOPE,
        )

    def test_chapterless_korean_is_automatically_full_without_radio(self):
        st = _FakeStreamlit(CHAPTER_SCOPE_LABEL)
        source = _source(chapters=False)
        self.assertEqual(
            render_korean_processing_scope(
                st,
                source,
                [],
                needs_translation=False,
            ),
            WHOLE_VIDEO_SCOPE,
        )
        self.assertEqual(st.radio_calls, [])

    def test_foreign_source_keeps_existing_scope_ui(self):
        st = _FakeStreamlit(WHOLE_VIDEO_SCOPE_LABEL)
        source = _source(language="en")
        self.assertEqual(
            render_korean_processing_scope(
                st,
                source,
                source["creator_chapters"],
                needs_translation=True,
            ),
            CHAPTER_SCOPE,
        )
        self.assertEqual(st.radio_calls, [])

    def test_scope_widget_is_isolated_by_video(self):
        self.assertNotEqual(
            scope_session_key(_source(video_id="video-a")),
            scope_session_key(_source(video_id="video-b")),
        )

    def test_video_reset_clears_full_scope_state(self):
        state = {
            scope_session_key(_source()): WHOLE_VIDEO_SCOPE_LABEL,
            "source_chapter_index": 1,
            "unrelated": "keep",
        }
        _clear_downstream_state(state)
        self.assertNotIn(scope_session_key(_source()), state)
        self.assertNotIn("source_chapter_index", state)
        self.assertEqual(state["unrelated"], "keep")

    def test_autosave_targets_are_isolated_by_processing_scope(self):
        chapter_id = preprocessing_autosave_target_id(
            target_id="CH-02",
            needs_translation=False,
            translate_foreign=False,
            processing_scope=CHAPTER_SCOPE,
            translation_scope=CHAPTER_SCOPE,
        )
        full_id = preprocessing_autosave_target_id(
            target_id="FULL",
            needs_translation=False,
            translate_foreign=False,
            processing_scope=WHOLE_VIDEO_SCOPE,
            translation_scope=WHOLE_VIDEO_SCOPE,
        )
        self.assertEqual(chapter_id, "CH-02")
        self.assertEqual(full_id, "FULL")
        self.assertNotEqual(
            autosave_path("/tmp", {"video_id": "video-a", "processed_chapter": {"chapter_id": chapter_id}}),
            autosave_path("/tmp", {"video_id": "video-a", "processed_chapter": {"chapter_id": full_id}}),
        )

    def test_unrequested_foreign_translation_does_not_claim_full_autosave(self):
        self.assertEqual(
            preprocessing_autosave_target_id(
                target_id="CH-02",
                needs_translation=True,
                translate_foreign=False,
                processing_scope=CHAPTER_SCOPE,
                translation_scope=WHOLE_VIDEO_SCOPE,
            ),
            "CH-02",
        )

    def test_full_source_adapter_does_not_mutate_source(self):
        source = _source()
        adapted = source_for_korean_full(source)
        self.assertEqual(adapted["creator_chapters"], [])
        self.assertEqual(len(source["creator_chapters"]), 2)
        self.assertIs(adapted["transcript"], source["transcript"])

    def test_full_result_uses_full_contract_and_preserves_creator_chapters(self):
        source = _source()
        result = finalize_korean_full_result(
            {"processed_chapter": {}, "translation_required": True},
            source,
            core=_fake_core()[0],
        )
        self.assertEqual(result["processed_chapter"]["chapter_id"], "FULL")
        self.assertEqual(result["processed_chapter"]["start_seconds"], 0)
        self.assertEqual(result["processed_chapter"]["end_seconds"], 40.0)
        self.assertTrue(result["processed_chapter"]["creator_chapters_preserved"])
        self.assertEqual(result["creator_chapters"], source["creator_chapters"])
        self.assertFalse(result["translation_required"])
        self.assertEqual(result["translation_status"], "not_required")

    def test_full_result_restores_existing_creator_ownership_fields(self):
        source = _source()
        core, _ = _fake_core()
        result = finalize_korean_full_result(
            {
                "processed_chapter": {},
                "normalized_utterances": [
                    {"utterance_id": "UT-00001", "start_seconds": 1.0, "end_seconds": 2.0},
                    {"utterance_id": "UT-00002", "start_seconds": 21.0, "end_seconds": 22.0},
                ],
            },
            source,
            core=core,
        )
        first, second = result["normalized_utterances"]
        self.assertEqual(
            (first["chapter_id"], first["chapter_index"], first["chapter_label"]),
            ("CH-01", 0, "처음"),
        )
        self.assertEqual(
            (second["chapter_id"], second["chapter_index"], second["chapter_label"]),
            ("CH-02", 1, "다음"),
        )

    def test_chapter_mode_uses_only_selected_creator_chapter(self):
        core, calls = _fake_core()
        with patch.object(v0316_extension, "extend_result_safely", _add_mock_content_chapters):
            v0316_extension.apply(core)
            result = core.build_preprocessing_draft(
                _source(), chapter_index=1, translation_scope=CHAPTER_SCOPE
            )
        self.assertEqual(result["processed_chapter"]["chapter_id"], "CH-02")
        self.assertEqual(len(result["normalized_utterances"]), 2)
        self.assertEqual(len(calls[0][0]["creator_chapters"]), 2)

    def test_full_mode_uses_whole_transcript_without_translation(self):
        core, calls = _fake_core()
        source = _source()
        with patch.object(v0316_extension, "extend_result_safely", _add_mock_content_chapters):
            v0316_extension.apply(core)
            result = core.build_preprocessing_draft(
                source,
                chapter_index=1,
                translation_scope=WHOLE_VIDEO_SCOPE,
                translate_foreign_to_korean=False,
            )
        self.assertEqual(result["processed_chapter"]["chapter_id"], "FULL")
        self.assertEqual(len(result["normalized_utterances"]), 3)
        self.assertEqual(calls[0][0]["creator_chapters"], [])
        self.assertFalse(result["translation_required"])
        self.assertEqual(result["translation_status"], "not_required")
        self.assertIn("runtime_generation_metrics", result)

    def test_korean_full_uses_existing_case_b_without_qwen_or_fallback(self):
        core, _ = _fake_core()
        v0316_extension.apply(core)
        result = core.build_preprocessing_draft(
            _source(),
            chapter_index=1,
            translation_scope=WHOLE_VIDEO_SCOPE,
            translate_foreign_to_korean=False,
        )
        generation = result["content_chapter_generation"]
        self.assertEqual(len(result["content_chapters"]), 2)
        self.assertEqual(
            [item["source_creator_chapter_ids"] for item in result["content_chapters"]],
            [["CH-01"], ["CH-02"]],
        )
        self.assertEqual(
            generation["method"],
            "creator_chapter_ownership_passthrough_v0.1",
        )
        self.assertFalse(generation["fallback_used"])
        self.assertNotIn(
            "creator_chapter_ownership_missing",
            " ".join(generation.get("warnings") or []),
        )
        self.assertEqual(generation["generation_call_count"], 0)
        self.assertFalse(generation["llm_invoked"])
        self.assertEqual(
            result["runtime_generation_metrics"]["content_chapter_generation_calls"],
            0,
        )

    def test_foreign_full_case_b_contract_is_unchanged(self):
        source = _source(language="en")
        result = {
            "processed_chapter": {"chapter_id": "FULL"},
            "normalized_utterances": [
                {"utterance_id": "UT-00001", "chapter_id": "CH-01", "chapter_index": 0, "chapter_label": "처음", "start_seconds": 1.0, "end_seconds": 2.0, "normalized_text": "one"},
                {"utterance_id": "UT-00002", "chapter_id": "CH-02", "chapter_index": 1, "chapter_label": "다음", "start_seconds": 21.0, "end_seconds": 22.0, "normalized_text": "two"},
            ],
        }
        output = apply_content_chapter_policy(
            _fake_core()[0],
            result,
            source,
            allow_semantic_generation=True,
        )
        self.assertEqual(len(output["content_chapters"]), 2)
        self.assertFalse(output["content_chapter_generation"]["fallback_used"])
        self.assertFalse(output["content_chapter_generation"]["llm_invoked"])

    def test_full_to_chapter_switch_does_not_leak_scope(self):
        core, _ = _fake_core()
        with patch.object(v0316_extension, "extend_result_safely", _add_mock_content_chapters):
            v0316_extension.apply(core)
            full = core.build_preprocessing_draft(
                _source(), chapter_index=1, translation_scope=WHOLE_VIDEO_SCOPE
            )
            chapter = core.build_preprocessing_draft(
                _source(), chapter_index=1, translation_scope=CHAPTER_SCOPE
            )
        self.assertEqual(full["processed_chapter"]["chapter_id"], "FULL")
        self.assertEqual(chapter["processed_chapter"]["chapter_id"], "CH-02")
        self.assertEqual(len(chapter["normalized_utterances"]), 2)

    def test_chapterless_runtime_remains_existing_full_path(self):
        core, calls = _fake_core()
        with patch.object(v0316_extension, "extend_result_safely", _add_mock_content_chapters):
            v0316_extension.apply(core)
            result = core.build_preprocessing_draft(
                _source(chapters=False),
                translation_scope=WHOLE_VIDEO_SCOPE,
            )
        self.assertEqual(result["processed_chapter"]["chapter_id"], "FULL")
        self.assertEqual(len(result["normalized_utterances"]), 3)
        self.assertEqual(calls[0][0]["creator_chapters"], [])

    def test_chapterless_korean_still_routes_to_case_c_semantic_path(self):
        source = _source(chapters=False)
        core, _ = _fake_core()
        baseline = core.build_preprocessing_draft(source)
        sentinel = copy.deepcopy(baseline)
        sentinel["content_chapters"] = [{"content_chapter_id": "CCH-01"}]
        sentinel["content_chapter_generation"] = {"method": "semantic-fixture"}
        with patch(
            "content_chapter_segmentation.run_semantic_content_segmentation",
            return_value=sentinel,
        ) as semantic:
            output = apply_content_chapter_policy(
                core,
                baseline,
                source,
                allow_semantic_generation=True,
            )
        semantic.assert_called_once()
        self.assertEqual(
            output["content_chapter_generation"]["method"],
            "semantic-fixture",
        )

    def test_korean_full_is_screenshot_eligible_after_content_chapters(self):
        core, _ = _fake_core()
        with patch.object(v0316_extension, "extend_result_safely", _add_mock_content_chapters):
            v0316_extension.apply(core)
            result = core.build_preprocessing_draft(
                _source(), translation_scope=WHOLE_VIDEO_SCOPE
            )
        with tempfile.TemporaryDirectory() as temporary:
            view = build_screenshot_workflow_view(result, Path(temporary))
        self.assertTrue(view["visible"])
        self.assertEqual(len(view["items"]), 1)

    def test_launcher_installs_labels_and_compiles_transformed_app(self):
        app_path, source = app_v0316_launcher.versioned_app_source()
        self.assertTrue(app_path.name == "app.py")
        self.assertIn(
            "render_korean_processing_scope",
            source,
        )
        self.assertIn('processing_scope = render_korean_processing_scope', source)
        self.assertEqual(CHAPTER_SCOPE_LABEL, "챕터별 전처리")
        self.assertEqual(WHOLE_VIDEO_SCOPE_LABEL, "전체 영상 전처리")
        compile(source, str(app_path), "exec")


if __name__ == "__main__":
    unittest.main()
