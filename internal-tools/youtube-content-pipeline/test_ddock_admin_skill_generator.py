from __future__ import annotations

import json
import os
import tempfile
import unittest
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

from ddock_admin_skill_generator import (
    AdminSkillInputError,
    AdminSkillResponseError,
    PROMPT_PATH,
    build_pass_2_action_map,
    build_pass_2_payload,
    _exact_prompt,
    _strict_json,
    extract_first_balanced_json_object,
    generate_admin_skill_review,
    materialize_anchor_context,
    materialize_part_contexts,
    materialize_source_span,
    parse_classification_response,
    parse_composition_response,
    parse_step_response,
    prepare_transcript,
    replay_pass_2_candidates,
    resume_admin_skill_review,
    validate_preprocessed_input,
)
from ddock_content_validator import validate_ddock_content_review, validate_review_for_publish


FIXTURE_ROOT = Path(__file__).resolve().parent / "tests" / "fixtures" / "ddock_admin_skill_g0"
RAW_FIXTURE = (
    Path(__file__).resolve().parent
    / "tests"
    / "fixtures"
    / "ddock_admin_skill_raw"
    / "pass_1_classification_fenced_response.txt"
)
TRUNCATED_RAW_FIXTURE = (
    Path(__file__).resolve().parent
    / "tests"
    / "fixtures"
    / "ddock_admin_skill_raw"
    / "pass_1_classification_truncated_response.txt"
)


def preprocessing_fixture() -> dict:
    texts = [
        "설정 메뉴를 열고 MCP 파일을 추가합니다.",
        "MCP는 선택한 레이어의 정보를 읽어 오는 도구입니다.",
        "연결이 끝나면 레이어 이름과 스타일 값이 화면에 표시됩니다.",
        "스타일 가이드 Section을 선택하고 실행 버튼을 누릅니다.",
        "저장하지 않으면 값이 삭제될 수 있으니 저장 버튼을 눌러야 합니다.",
        "오늘 출연해 주셔서 정말 감사합니다.",
    ]
    return {
        "schema_version": "script_preprocessing_v0.3.15.1",
        "video_id": "synthetic-video",
        "source_url": "https://example.invalid/video",
        "source_language": "ko",
        "content_chapter_generation": {"schema_version": "content_chapters_v0.1"},
        "normalized_utterances": [
            {
                "utterance_id": f"ROW-{index:03d}",
                "start_seconds": float(index * 10),
                "end_seconds": float(index * 10 + 8),
                "display_timestamp": f"00:{index * 10:02d}",
                "normalized_text": text,
                "chapter_id": "CH-01" if index <= 3 else "CH-02",
                "chapter_label": "설정" if index <= 3 else "실행",
            }
            for index, text in enumerate(texts, 1)
        ],
    }


def model_responses() -> list[dict]:
    return [
        {
            "mode": "practice",
            "step_ids": ["ROW-001", "ROW-004"],
            "step_preview_ids": [],
        },
        {
            "parts": [
                {
                    "title": "MCP 파일을 연결해요",
                    "action_objective": "MCP 설정을 연결하고 스타일 정보를 확인합니다.",
                    "done_state": "스타일 정보가 화면에 표시됩니다.",
                    "step_anchor_ids": ["ROW-001", "ROW-004"],
                }
            ],
            "excluded_step_anchor_ids": [],
        },
        {
            "steps": [
                {
                    "action_title": "MCP 파일을 추가해요",
                    "anchor_ids": ["ROW-001"],
                    "action_lines": [{"text": "설정 메뉴를 열고 MCP 파일을 추가합니다.", "source_utterance_ids": ["ROW-001"]}],
                    "source_utterance_ids": ["ROW-001"],
                    "prompt": None,
                    "warning": None,
                    "learn_more": [{"question": "MCP는 무엇을 읽나요?", "body": "MCP는 선택한 레이어의 정보를 읽어 오는 도구입니다.", "source_utterance_ids": ["ROW-002"]}],
                    "needs_review": False,
                },
                {
                    "action_title": "Section을 실행해요",
                    "anchor_ids": ["ROW-004"],
                    "action_lines": [{"text": "스타일 가이드 Section을 선택하고 실행 버튼을 누릅니다.", "source_utterance_ids": ["ROW-004"]}],
                    "source_utterance_ids": ["ROW-004"],
                    "prompt": None,
                    "warning": {"title": "저장하지 않으면 값이 삭제될 수 있습니다.", "body": "저장 버튼을 눌러야 합니다.", "source_utterance_ids": ["ROW-005"]},
                    "learn_more": [],
                    "needs_review": False,
                },
            ],
            "checkpoint": {"text": "레이어 이름과 스타일 값이 화면에 표시됩니다.", "source_utterance_ids": ["ROW-003"]},
            "excluded_anchor_ids": [],
        },
    ]


def workflow_response(
    workflows: list[dict],
    *,
    auxiliary_actions: list[dict] | None = None,
    excluded_actions: list[dict] | None = None,
) -> dict:
    return {
        "workflows": workflows,
        "auxiliary_actions": auxiliary_actions or [],
        "excluded_actions": excluded_actions or [],
    }


def workflow_item(
    workflow_id: str,
    anchor_ids: list[str],
    *,
    title: str | None = None,
    done_state: str | None = None,
    surface: str = "Figma",
) -> dict:
    return {
        "workflow_id": workflow_id,
        "title": title or f"{workflow_id} 결과를 만들어요",
        "action_objective": f"{workflow_id} 작업을 끝내요.",
        "done_state": done_state or f"{workflow_id} 결과를 확인할 수 있어요.",
        "primary_tool_or_surface": surface,
        "anchor_ids": anchor_ids,
    }


def boundary_response(
    boundaries: list[dict],
    *,
    auxiliary_actions: list[dict] | None = None,
    excluded_actions: list[dict] | None = None,
) -> dict:
    return {
        "workflow_boundaries": boundaries,
        "auxiliary_actions": auxiliary_actions or [],
        "excluded_actions": excluded_actions or [],
    }


def boundary_item(
    start_anchor_id: str,
    *,
    title: str | None = None,
    done_state: str | None = None,
    surface: str = "Figma",
) -> dict:
    return {
        "start_anchor_id": start_anchor_id,
        "title": title or f"{start_anchor_id} 결과를 만들어요",
        "action_objective": f"{start_anchor_id} 작업을 끝내요.",
        "done_state": done_state or f"{start_anchor_id} 결과를 확인할 수 있어요.",
        "primary_tool_or_surface": surface,
    }


def key_boundary_item(
    start_action_key: str,
    *,
    title: str | None = None,
    done_state: str | None = None,
    surface: str = "Figma",
) -> dict:
    return {
        "start_action_key": start_action_key,
        "title": title or f"{start_action_key} 결과를 만들어요",
        "action_objective": f"{start_action_key} 작업을 끝내요.",
        "done_state": done_state or f"{start_action_key} 결과를 확인할 수 있어요.",
        "primary_tool_or_surface": surface,
    }


def large_action_fixture(count: int = 40) -> dict:
    surfaces = ("설정", "토큰", "코드", "가져오기")
    return {
        "schema_version": "script_preprocessing_v0.3.15.1",
        "video_id": "large-action-video",
        "source_language": "ko",
        "content_chapter_generation": {"schema_version": "content_chapters_v0.1"},
        "normalized_utterances": [
            {
                "utterance_id": f"ACT-{index:03d}",
                "start_seconds": float(index * 40),
                "end_seconds": float(index * 40 + 8),
                "display_timestamp": f"{index * 40 // 60:02d}:{index * 40 % 60:02d}",
                "normalized_text": f"{surfaces[(index - 1) // 10]} 화면에서 {index}번 작업을 실행해요.",
                "chapter_id": "CH-01",
                "chapter_label": "실습",
            }
            for index in range(1, count + 1)
        ],
    }


def relative_gap_fixture() -> dict:
    starts = [0.0, 10.0, 20.0, 30.0, 69.0, 79.0, 89.0]
    return {
        "schema_version": "script_preprocessing_v0.3.15.1",
        "video_id": "relative-gap-video",
        "source_language": "ko",
        "content_chapter_generation": {"schema_version": "content_chapters_v0.1"},
        "normalized_utterances": [
            {
                "utterance_id": f"GAP-{index:03d}",
                "start_seconds": start,
                "end_seconds": start + 5,
                "display_timestamp": f"00:{int(start):02d}",
                "normalized_text": f"{index}번 작업을 실행해요.",
                "chapter_id": "CH-01",
                "chapter_label": "실습",
            }
            for index, start in enumerate(starts, 1)
        ],
    }


class ScriptedGenerator:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.user_payloads: list[dict] = []
        self.max_tokens: list[int] = []

    def __call__(self, _model: str, _system: str, user: str, max_tokens: int) -> str:
        self.calls += 1
        self.user_payloads.append(json.loads(user))
        self.max_tokens.append(max_tokens)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def write_resume_fixture(
    root: Path,
    *,
    initial: dict | None = None,
    repair: dict | None = None,
) -> None:
    raw_root = root / "raw"
    raw_root.mkdir(parents=True)
    records = [
        ("pass_1_action_anchors", model_responses()[0]),
        (
            "pass_2_composition",
            initial or boundary_response([key_boundary_item("A01")]),
        ),
    ]
    if repair is not None:
        records.append(("pass_2_composition_repair", repair))
    for stage, output in records:
        (raw_root / f"{stage}_001.json").write_text(
            json.dumps(
                {
                    "stage": stage,
                    "call_index": 1,
                    "system_prompt": "fixture",
                    "input": {"pass": stage},
                    "raw_output": json.dumps(output, ensure_ascii=False),
                    "parsed_output": output,
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "finished_at": "2026-01-01T00:00:01+00:00",
                    "runtime_seconds": 1.0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


class AdminSkillGeneratorTests(unittest.TestCase):
    def test_prompt_enforces_ddock_user_facing_writing_style(self) -> None:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn("PART titles, STEP titles/action lines, and Learn More", prompt)
        self.assertIn("Korean `해요체`", prompt)
        self.assertIn("`무엇을 → 어디서 → 어떻게`", prompt)
        self.assertIn("Avoid report-style `~합니다`", prompt)
        self.assertIn("Prompt text remains an exact source", prompt)
        self.assertIn("substring. It also never rewrites Script provenance", prompt)
        self.assertIn("never rewrites Script provenance", prompt)

    def test_pass_2_prompt_defines_ordered_action_segmentation(self) -> None:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn("ORDERED ACTION SEQUENCE → WORKFLOW BOUNDARY DETECTION", prompt)
        self.assertIn("workflow_boundaries", prompt)
        self.assertIn("start_action_key", prompt)
        self.assertIn("Never output source utterance IDs", prompt)
        self.assertIn("Context is read-only evidence", prompt)
        self.assertIn("never reorder the sequence", prompt)
        self.assertIn("primary_tool_or_surface", prompt)
        self.assertIn("auxiliary_actions", prompt)
        self.assertIn("CONNECTED DOES NOT MEAN SAME WORKFLOW", prompt)

    def test_actual_invalid_raw_replays_markdown_fence_parser_failure(self) -> None:
        raw = RAW_FIXTURE.read_text(encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw)
        extracted = _strict_json(raw, "replay")
        self.assertEqual(len(extracted["classifications"]), 213)
        self.assertEqual(extracted["classifications"][-1]["utterance_id"], "UT-00213")

    def test_compact_actual_truncated_raw_replays_truncated_json(self) -> None:
        raw = TRUNCATED_RAW_FIXTURE.read_text(encoding="utf-8")
        with self.assertRaisesRegex(AdminSkillResponseError, "truncated_json"):
            _strict_json(raw, "replay")

    def test_strict_json_accepts_one_json_code_fence(self) -> None:
        self.assertEqual(_strict_json('```json\n{"mode":"practice"}\n```', "test"), {"mode": "practice"})

    def test_strict_json_accepts_leading_prose(self) -> None:
        self.assertEqual(_strict_json('result follows: {"mode":"practice"}', "test"), {"mode": "practice"})

    def test_strict_json_accepts_trailing_prose(self) -> None:
        self.assertEqual(_strict_json('{"mode":"practice"}\nfinished', "test"), {"mode": "practice"})

    def test_strict_json_rejects_truncated_object(self) -> None:
        with self.assertRaisesRegex(AdminSkillResponseError, "truncated_json"):
            _strict_json('{"mode":"practice"', "test")

    def test_balanced_json_handles_escaped_quote_and_brace(self) -> None:
        raw = 'before {"text":"escaped \\\" quote and } brace","value":1} after'
        extracted = extract_first_balanced_json_object(raw)
        self.assertEqual(json.loads(extracted)["text"], 'escaped " quote and } brace')

    def test_valid_preprocessing_input(self) -> None:
        value = preprocessing_fixture()
        self.assertIs(validate_preprocessed_input(value), value)

    def test_invalid_schema_rejected(self) -> None:
        value = preprocessing_fixture()
        value["schema_version"] = "unknown"
        with self.assertRaises(AdminSkillInputError):
            validate_preprocessed_input(value)

    def test_review_json_rejected(self) -> None:
        with self.assertRaisesRegex(AdminSkillInputError, "review JSON"):
            validate_preprocessed_input({"schema_version": "ddock_content_review_v0.1"})

    def test_preparation_preserves_script_and_detects_markers(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        self.assertEqual(len(prepared["script"]), 6)
        self.assertGreaterEqual(prepared["action_marker_count"], 2)
        self.assertEqual(prepared["script"][0]["text"], "설정 메뉴를 열고 MCP 파일을 추가합니다.")

    def test_anchor_schema_parser(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        mode, values, warnings = parse_classification_response(model_responses()[0], prepared["script"])
        self.assertEqual(mode, "practice")
        self.assertEqual(values["ROW-001"]["label"], "STEP")
        self.assertEqual(values["ROW-004"]["label"], "STEP")
        self.assertNotIn("ROW-002", values)
        self.assertNotIn("ROW-003", values)
        self.assertNotIn("ROW-006", values)
        self.assertEqual(warnings, ["classification_tail_coverage_warning"])

    def test_omissions_remain_unclassified_context(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        mode, values, warnings = parse_classification_response(
            {
                "mode": "practice",
                "step_ids": ["ROW-001"],
                "step_preview_ids": [],
            },
            prepared["script"],
        )
        self.assertEqual(mode, "practice")
        self.assertEqual(values["ROW-001"]["label"], "STEP")
        self.assertEqual(set(values), {"ROW-001"})
        self.assertEqual(warnings, ["classification_tail_coverage_warning"])

    def test_step_only_anchor_arrays_must_be_present(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        value = model_responses()[0]
        for field in ("step_ids", "step_preview_ids"):
            with self.subTest(field=field):
                invalid = dict(value)
                invalid.pop(field)
                with self.assertRaisesRegex(AdminSkillResponseError, f"{field}_must_be_array"):
                    parse_classification_response(invalid, prepared["script"])

    def test_duplicate_step_ids_are_deduped_in_source_order(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        duplicate = model_responses()[0]
        duplicate["step_ids"] = ["ROW-004", "ROW-001", "ROW-004", "ROW-001"]
        _, values, _ = parse_classification_response(duplicate, prepared["script"])
        self.assertEqual(duplicate["step_ids"], ["ROW-001", "ROW-004"])
        self.assertEqual(list(values), ["ROW-001", "ROW-004"])

    def test_step_wins_when_step_and_preview_overlap(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        response = model_responses()[0]
        response["step_preview_ids"] = ["ROW-001", "ROW-002", "ROW-002"]
        _, values, _ = parse_classification_response(response, prepared["script"])
        self.assertEqual(response["step_preview_ids"], ["ROW-002"])
        self.assertEqual(values["ROW-001"]["label"], "STEP")
        self.assertEqual(values["ROW-002"]["label"], "STEP_PREVIEW")

    def test_removed_secondary_roles_are_not_part_of_pass_1_schema(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        response = model_responses()[0]
        response["checkpoint_ids"] = ["ROW-001"]
        with self.assertRaisesRegex(AdminSkillResponseError, "unexpected_fields:checkpoint_ids"):
            parse_classification_response(response, prepared["script"])

    def test_unknown_classification_id_is_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        with self.assertRaisesRegex(AdminSkillResponseError, "unknown_id"):
            parse_classification_response(
                {
                    "mode": "practice",
                    "step_ids": ["UNKNOWN"],
                    "step_preview_ids": [],
                },
                prepared["script"],
            )

    def test_classification_requires_at_least_one_step(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        with self.assertRaisesRegex(AdminSkillResponseError, "no_step"):
            parse_classification_response(
                {
                    "mode": "information",
                    "step_ids": [],
                    "step_preview_ids": ["ROW-002"],
                },
                prepared["script"],
            )

    def test_invalid_classification_mode_is_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        response = model_responses()[0]
        response["mode"] = "unsupported"
        with self.assertRaisesRegex(AdminSkillResponseError, "invalid_mode"):
            parse_classification_response(response, prepared["script"])

    def test_removed_response_fields_are_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        invalid = model_responses()[0]
        invalid["classified"] = [{"utterance_id": "ROW-001", "verdict": "STEP"}]
        with self.assertRaisesRegex(AdminSkillResponseError, "unexpected_fields:classified"):
            parse_classification_response(invalid, prepared["script"])

    def test_action_signal_and_tail_coverage_emit_warnings_without_relabeling(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, values, warnings = parse_classification_response(
            {
                "mode": "practice",
                "step_ids": ["ROW-006"],
                "step_preview_ids": [],
            },
            prepared["script"],
        )
        self.assertIn("classification_action_signal_dropped_warning", warnings)
        self.assertIn("classification_tail_coverage_warning", warnings)
        self.assertNotIn("ROW-005", values)

    def test_part_composition_crosses_chapters(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, classifications, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, warnings = parse_composition_response(
            model_responses()[1], classifications, {row["utterance_id"]: row for row in prepared["script"]}
        )
        self.assertEqual(warnings, [])
        self.assertEqual(plans[0]["step_anchor_ids"], ["ROW-001", "ROW-004"])
        self.assertEqual(plans[0]["action_start_utterance_id"], "ROW-001")
        self.assertEqual(plans[0]["action_end_utterance_id"], "ROW-004")

    def test_pass_2_payload_uses_compact_anchor_buckets_not_whole_transcript(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, seeds, _ = parse_classification_response(model_responses()[0], prepared["script"])
        payload = build_pass_2_payload("practice", prepared, seeds)
        self.assertNotIn("rows", payload)
        self.assertNotIn("context_rows", payload)
        self.assertEqual(payload["ordered_actions"][0]["action_key"], "A01")
        self.assertTrue(
            any(
                row["candidate_kind"] == "supplemental_candidate"
                for row in payload["ordered_actions"]
            )
        )
        self.assertLess(len(payload["ordered_actions"]), len(prepared["script"]))

    def test_ordered_action_sequence_is_stable_and_source_ordered(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, seeds, _ = parse_classification_response(model_responses()[0], prepared["script"])
        payload = build_pass_2_payload("practice", prepared, seeds)
        sequence = payload["ordered_actions"]
        self.assertEqual(
            [item["action_key"] for item in sequence],
            [f"A{index:02d}" for index in range(1, len(sequence) + 1)],
        )
        times = [item["time"] for item in sequence]
        self.assertEqual(times, sorted(times))

    def test_pass_2_model_payload_exposes_only_action_keys_and_read_only_context(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, seeds, _ = parse_classification_response(model_responses()[0], prepared["script"])
        payload = build_pass_2_payload("practice", prepared, seeds)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("utterance_id", serialized)
        self.assertNotIn("start_anchor_id", serialized)
        self.assertNotIn("ROW-", serialized)
        self.assertTrue(all(item["action_key"].startswith("A") for item in payload["ordered_actions"]))
        self.assertTrue(
            any(item["previous_context"] or item["next_context"] for item in payload["ordered_actions"])
        )

    def test_action_key_map_deterministically_preserves_source_provenance(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, seeds, _ = parse_classification_response(model_responses()[0], prepared["script"])
        first = build_pass_2_action_map(prepared, seeds)
        second = build_pass_2_action_map(prepared, seeds)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["action_key"], "A01")
        self.assertEqual(first[0]["source_utterance_id"], "ROW-001")
        self.assertIn("source_order", first[0])

    def test_resume_replays_both_candidates_and_selects_deterministically(self) -> None:
        repair = boundary_response(
            [
                key_boundary_item(
                    "A01",
                    title="참고 파일 열기",
                    done_state="참고 파일이 열려 있어요",
                )
            ],
            auxiliary_actions=[
                {
                    "action_key": "A99",
                    "reason_category": "reference",
                    "attach_to_previous_or_next": "previous",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as root:
            resume_root = Path(root)
            write_resume_fixture(resume_root, repair=repair)
            before = {
                path.name: path.read_bytes() for path in (resume_root / "raw").glob("*.json")
            }
            replay = replay_pass_2_candidates(preprocessing_fixture(), resume_root)
            after = {
                path.name: path.read_bytes() for path in (resume_root / "raw").glob("*.json")
            }
        reports = {item["candidate"]: item for item in replay["candidate_reports"]}
        self.assertTrue(reports["initial"]["valid"])
        self.assertTrue(reports["repair"]["valid"])
        self.assertEqual(replay["selected_candidate"], "initial")
        self.assertEqual(reports["initial"]["invalid_action_ref_count"], 0)
        self.assertEqual(reports["initial"]["unaccounted_action_count"], 0)
        self.assertTrue(reports["initial"]["chronological"])
        self.assertEqual(before, after)

    def test_resume_materializes_provenance_and_delegates_only_pass_3(self) -> None:
        live = ScriptedGenerator([model_responses()[2]])
        with tempfile.TemporaryDirectory() as root:
            resume_root = Path(root)
            write_resume_fixture(resume_root)
            review = resume_admin_skill_review(
                preprocessing_fixture(), resume_root, generator=live
            )
        resume = review["curation_generation"]["admin_skill"]["resume"]
        self.assertEqual(resume["pass_1_model_calls"], 0)
        self.assertEqual(resume["pass_2_model_calls"], 0)
        self.assertEqual(resume["pass_3_model_calls"], 2)
        self.assertEqual(live.calls, 2)
        self.assertEqual(live.user_payloads[0]["pass"], "PASS_3_PER_PART_STEP_GENERATION")
        self.assertEqual(live.user_payloads[1]["pass"], "PASS_3_TARGETED_REPAIR")
        self.assertEqual(len(review["draft_parts"]), 1)
        materialized = resume["materialized_parts"][0]
        self.assertEqual(materialized["first_action_key"], "A01")
        self.assertTrue(materialized["last_action_key"].startswith("A"))
        self.assertGreaterEqual(materialized["action_count"], 2)
        self.assertLessEqual(
            materialized["source_start_seconds"], materialized["source_end_seconds"]
        )

    def test_resume_partial_pass_3_failure_still_emits_review_draft(self) -> None:
        class PartiallyFailingGenerator:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, _model: str, _system: str, _user: str, _max_tokens: int) -> str:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("synthetic PASS 3 failure")
                return json.dumps(
                    {"steps": [], "checkpoint": None, "excluded_anchor_ids": []}
                )

        live = PartiallyFailingGenerator()
        with tempfile.TemporaryDirectory() as root:
            resume_root = Path(root)
            write_resume_fixture(resume_root)
            review = resume_admin_skill_review(
                preprocessing_fixture(), resume_root, generator=live
            )
        self.assertEqual(len(review["draft_parts"]), 1)
        self.assertEqual(review["draft_parts"][0]["steps"], [])
        self.assertTrue(review["draft_parts"][0]["needs_review"])
        self.assertTrue(
            any(item["severity"] == "blocking" for item in review["review_queue"])
        )

    def test_configured_existing_actual_raw_replays_with_latest_parser(self) -> None:
        actual_value = os.environ.get("DDOCK_ADMIN_SKILL_ACTUAL_REPLAY")
        source_value = os.environ.get("DDOCK_ADMIN_SKILL_ACTUAL_INPUT")
        if not actual_value or not source_value:
            self.skipTest("actual replay paths are not configured")
        replay = replay_pass_2_candidates(
            json.loads(Path(source_value).read_text(encoding="utf-8")),
            Path(actual_value),
        )
        reports = {item["candidate"]: item for item in replay["candidate_reports"]}
        self.assertTrue(reports["initial"]["valid"])
        self.assertTrue(reports["repair"]["valid"])
        self.assertEqual(reports["initial"]["part_count"], 5)
        self.assertEqual(reports["repair"]["part_count"], 5)
        self.assertEqual(reports["initial"]["invalid_action_ref_count"], 0)
        self.assertEqual(reports["initial"]["unaccounted_action_count"], 0)
        self.assertTrue(reports["initial"]["chronological"])

    def test_unspecified_actions_default_to_contiguous_core(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-004"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, warnings = parse_composition_response(
            boundary_response([key_boundary_item("A01")]),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(plans[0]["primary_step_anchor_ids"], ordered)
        self.assertFalse(any("unaccounted_anchor" in warning for warning in warnings))

    def test_auxiliary_and_excluded_conflict_normalizes_with_excluded_winning(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-004"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, warnings = parse_composition_response(
            boundary_response(
                [key_boundary_item("A01"), key_boundary_item("A03")],
                auxiliary_actions=[
                    {
                        "action_key": "A02",
                        "reason_category": "cleanup",
                        "attach_to_previous_or_next": "previous",
                    }
                ],
                excluded_actions=[
                    {
                        "action_key": "A02",
                        "reason_category": "context",
                        "reason": "실행 작업이 아니에요.",
                    }
                ],
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual([plan["primary_step_anchor_ids"] for plan in plans], [["ROW-001"], ["ROW-004"]])
        self.assertTrue(any("conflicting_action_classification:A02" in warning for warning in warnings))

    def test_boundary_classification_conflict_normalizes_with_boundary_winning(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004"]
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, warnings = parse_composition_response(
            boundary_response(
                [key_boundary_item("A01"), key_boundary_item("A02")],
                auxiliary_actions=[
                    {
                        "action_key": "A02",
                        "reason_category": "cleanup",
                        "attach_to_previous_or_next": "previous",
                    }
                ],
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[1]["primary_step_anchor_ids"], ["ROW-004"])
        self.assertTrue(any("boundary_action_classification_conflict:A02" in warning for warning in warnings))

    def test_invalid_and_context_only_action_refs_warn_and_draft_plan_survives(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004"]
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, warnings = parse_composition_response(
            boundary_response(
                [key_boundary_item("A01")],
                auxiliary_actions=[
                    {
                        "action_key": "A99",
                        "reason_category": "cleanup",
                        "attach_to_previous_or_next": "previous",
                    },
                    {
                        "utterance_id": "ROW-006",
                        "reason_category": "context",
                        "attach_to_previous_or_next": "next",
                    },
                ],
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(len(plans), 1)
        self.assertTrue(any("invalid_model_action_key:auxiliary:A99" in warning for warning in warnings))
        self.assertTrue(any("context_only_reference:auxiliary:ROW-006" in warning for warning in warnings))

    def test_legacy_source_id_maps_to_action_key_when_uniquely_addressable(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004"]
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, warnings = parse_composition_response(
            boundary_response([boundary_item("ROW-001"), boundary_item("ROW-004")]),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual([plan["boundary_action_key"] for plan in plans], ["A01", "A02"])
        self.assertTrue(any("legacy_model_utterance_id_normalized" in warning for warning in warnings))

    def test_weak_preparation_workflow_emits_quality_signal(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004"]
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        _, warnings = parse_composition_response(
            boundary_response(
                [key_boundary_item("A01", title="참고 파일을 열어요", done_state="참고 파일이 열려 있어요")]
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertIn("composition:weak_preparation_workflow:0", warnings)

    def test_boundaries_materialize_three_contiguous_non_overlapping_parts(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-003", "ROW-004", "ROW-005"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, _ = parse_composition_response(
            boundary_response(
                [
                    boundary_item("ROW-001", surface="설정"),
                    boundary_item("ROW-003", surface="토큰"),
                    boundary_item("ROW-005", surface="가져오기"),
                ]
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(
            [plan["primary_step_anchor_ids"] for plan in plans],
            [["ROW-001", "ROW-002"], ["ROW-003", "ROW-004"], ["ROW-005"]],
        )
        self.assertEqual(
            len({anchor for plan in plans for anchor in plan["primary_step_anchor_ids"]}),
            len(ordered),
        )

    def test_duplicate_and_out_of_order_boundaries_are_normalized(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-003", "ROW-004"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, warnings = parse_composition_response(
            boundary_response(
                [
                    boundary_item("ROW-003"),
                    boundary_item("ROW-001"),
                    boundary_item("ROW-003"),
                ]
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual([plan["primary_step_anchor_ids"] for plan in plans], [ordered[:2], ordered[2:]])
        self.assertIn("composition:duplicate_boundary_removed:A03", warnings)
        self.assertIn("composition:out_of_order_boundaries_normalized", warnings)

    def test_nonexistent_boundary_is_removed_without_discarding_usable_boundaries(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004"]
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, warnings = parse_composition_response(
            boundary_response(
                [boundary_item("UNKNOWN"), boundary_item("ROW-001"), boundary_item("ROW-004")]
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(len(plans), 2)
        self.assertIn("composition:invalid_model_boundary_key:UNKNOWN", warnings)

    def test_missing_first_boundary_normalizes_to_first_core_action(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004"]
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, warnings = parse_composition_response(
            boundary_response([boundary_item("ROW-004")]),
            anchors,
            rows,
            set(rows),
            allow_unaccounted=True,
            ordered_action_ids=ordered,
        )
        self.assertEqual(plans[0]["primary_step_anchor_ids"], ordered)
        self.assertTrue(
            any(warning.startswith("composition:first_boundary_normalized_to_first_core") for warning in warnings)
        )

    def test_auxiliary_action_attaches_by_direction_without_becoming_a_part(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-004"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, _ = parse_composition_response(
            boundary_response(
                [boundary_item("ROW-001"), boundary_item("ROW-004")],
                auxiliary_actions=[
                    {
                        "utterance_id": "ROW-002",
                        "reason_category": "cleanup",
                        "attach_to_previous_or_next": "previous",
                    }
                ],
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0]["auxiliary_step_anchor_ids"], ["ROW-002"])

    def test_next_auxiliary_cannot_cross_later_core_and_interleave_parts(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-003", "ROW-004"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, warnings = parse_composition_response(
            boundary_response(
                [key_boundary_item("A01"), key_boundary_item("A04")],
                auxiliary_actions=[
                    {
                        "action_key": "A02",
                        "reason_category": "reference",
                        "attach_to_previous_or_next": "next",
                    }
                ],
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(plans[0]["auxiliary_step_anchor_ids"], ["ROW-002"])
        self.assertEqual(plans[0]["action_end_utterance_id"], "ROW-003")
        self.assertEqual(plans[1]["action_start_utterance_id"], "ROW-004")
        self.assertIn("composition:auxiliary_direction_fallback:A02:next", warnings)

    def test_crossed_auxiliary_directions_normalize_to_monotonic_segments(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-002", "ROW-003", "ROW-004"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, warnings = parse_composition_response(
            boundary_response(
                [key_boundary_item("A01"), key_boundary_item("A04")],
                auxiliary_actions=[
                    {
                        "action_key": "A02",
                        "reason_category": "reference",
                        "attach_to_previous_or_next": "next",
                    },
                    {
                        "action_key": "A03",
                        "reason_category": "supporting_action",
                        "attach_to_previous_or_next": "previous",
                    },
                ],
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(plans[0]["action_end_utterance_id"], "ROW-001")
        self.assertEqual(plans[1]["action_start_utterance_id"], "ROW-002")
        self.assertEqual(plans[1]["auxiliary_step_anchor_ids"], ["ROW-002", "ROW-003"])
        self.assertIn("composition:auxiliary_direction_fallback:A03:previous", warnings)

    def test_one_giant_ordered_segment_emits_quality_repair_signal(self) -> None:
        prepared = prepare_transcript(large_action_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = list(rows)
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        _, warnings = parse_composition_response(
            boundary_response([boundary_item(ordered[0])]),
            anchors,
            rows,
            set(rows),
            quality_context={"mode": "practice", "duration_seconds": prepared["duration_seconds"]},
            ordered_action_ids=ordered,
        )
        self.assertTrue(any("one_workflow_quality_floor" in warning for warning in warnings))

    def test_relative_large_gap_tail_cluster_emits_boundary_signal(self) -> None:
        fixture = relative_gap_fixture()
        prepared = prepare_transcript(fixture)
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = list(rows)
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        _, warnings = parse_composition_response(
            boundary_response([key_boundary_item("A01", title="작업을 이어서 해요")]),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertTrue(
            any(
                warning.startswith("composition:possible_missing_workflow_boundary:A05")
                for warning in warnings
            )
        )

    def test_late_gap_quality_signal_gets_one_targeted_boundary_repair(self) -> None:
        fixture = relative_gap_fixture()
        ids = [row["utterance_id"] for row in fixture["normalized_utterances"]]
        classification = {"mode": "practice", "step_ids": ids, "step_preview_ids": []}
        initial = boundary_response([key_boundary_item("A01", title="작업을 이어서 해요")])
        repaired = boundary_response(
            [
                key_boundary_item("A01", title="첫 결과를 만들어요"),
                key_boundary_item("A05", title="후반 결과를 만들어요", surface="새 작업 화면"),
            ]
        )

        def step_response(anchor_ids: list[str], title: str) -> dict:
            source_text = next(
                row["normalized_text"]
                for row in fixture["normalized_utterances"]
                if row["utterance_id"] == anchor_ids[0]
            )
            return {
                "steps": [
                    {
                        "action_title": title,
                        "anchor_ids": anchor_ids,
                        "action_lines": [
                            {"text": source_text, "source_utterance_ids": [anchor_ids[0]]}
                        ],
                        "source_utterance_ids": anchor_ids,
                        "prompt": None,
                        "warning": None,
                        "learn_more": [],
                        "needs_review": False,
                    }
                ],
                "checkpoint": None,
                "excluded_anchor_ids": [],
            }

        generator = ScriptedGenerator(
            [
                classification,
                initial,
                repaired,
                step_response(ids[:4], "첫 작업을 실행해요"),
                step_response(ids[4:], "후반 작업을 실행해요"),
            ]
        )
        review = generate_admin_skill_review(fixture, generator=generator)
        self.assertEqual(len(review["draft_parts"]), 2)
        self.assertEqual(
            review["curation_generation"]["admin_skill"]["pass_2_targeted_repair_count"],
            1,
        )
        repair_payload = generator.user_payloads[2]
        self.assertEqual(repair_payload["candidate_late_split_actions"][0]["action_key"], "A05")
        self.assertNotIn("utterance_id", json.dumps(repair_payload, ensure_ascii=False))

    def test_early_setup_and_late_result_boundaries_remain_independent(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        ordered = ["ROW-001", "ROW-004", "ROW-005"]
        _, anchors, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ordered, "step_preview_ids": []},
            prepared["script"],
        )
        plans, _ = parse_composition_response(
            boundary_response(
                [
                    boundary_item("ROW-001", done_state="연결 상태가 보여요.", surface="설정"),
                    boundary_item("ROW-004", done_state="실행 결과가 보여요.", surface="작업 화면"),
                    boundary_item("ROW-005", done_state="저장 결과가 남아요.", surface="저장 화면"),
                ]
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        self.assertEqual(len(plans), 3)
        self.assertEqual(plans[0]["done_state"], "연결 상태가 보여요.")
        self.assertEqual(plans[-1]["done_state"], "저장 결과가 남아요.")

    def test_pass_3_receives_deterministically_contiguous_boundary_members(self) -> None:
        composition = boundary_response(
            [key_boundary_item("A01"), key_boundary_item("A04")],
            excluded_actions=[
                {
                    "action_key": action_key,
                    "reason_category": "guard",
                    "reason": "이 synthetic fixture에서는 core 실행 작업이 아니에요.",
                }
                for action_key in ("A02", "A03", "A05")
            ],
        )
        first_step = model_responses()[2]
        first_step["steps"] = first_step["steps"][:1]
        second_step = model_responses()[2]
        second_step["steps"] = second_step["steps"][1:]
        generator = ScriptedGenerator(
            [model_responses()[0], composition, first_step, second_step]
        )
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        pass_3_payloads = [
            payload
            for payload in generator.user_payloads
            if payload["pass"] == "PASS_3_PER_PART_STEP_GENERATION"
        ]
        self.assertEqual(
            [payload["part"]["step_anchor_ids"] for payload in pass_3_payloads],
            [["ROW-001"], ["ROW-004"]],
        )
        self.assertEqual(len(review["draft_parts"]), 2)

    def test_unspecified_prefix_defaults_to_core_without_unaccounted_review(self) -> None:
        repaired = boundary_response(
            [boundary_item("ROW-004")],
            excluded_actions=[
                {
                    "utterance_id": utterance_id,
                    "reason_category": "guard",
                    "reason": "이 synthetic fixture에서는 core 실행 작업이 아니에요.",
                }
                for utterance_id in ("ROW-002", "ROW-003", "ROW-005")
            ],
        )
        full_step = model_responses()[2]
        generator = ScriptedGenerator([model_responses()[0], repaired, full_step])
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        self.assertEqual(len(review["draft_parts"]), 1)
        self.assertEqual(review["unassigned_phases"], [])
        self.assertFalse(
            any(item["type"] == "unaccounted_action_anchor" for item in review["review_queue"])
        )

    def test_invalid_boundary_is_ignored_when_valid_boundaries_survive(self) -> None:
        excluded = [
            {
                "utterance_id": utterance_id,
                "reason_category": "context",
                "reason": "이 synthetic fixture에서는 core 실행 작업이 아니에요.",
            }
            for utterance_id in ("ROW-002", "ROW-003", "ROW-005")
        ]
        initial = boundary_response(
            [boundary_item("UNKNOWN"), boundary_item("ROW-001"), boundary_item("ROW-004")],
            excluded_actions=excluded,
        )
        first_step = model_responses()[2]
        first_step["steps"] = first_step["steps"][:1]
        second_step = model_responses()[2]
        second_step["steps"] = second_step["steps"][1:]
        generator = ScriptedGenerator(
            [model_responses()[0], initial, first_step, second_step]
        )
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        self.assertEqual(len(review["draft_parts"]), 2)
        self.assertEqual(
            review["curation_generation"]["admin_skill"]["pass_2_targeted_repair_count"],
            0,
        )
        self.assertTrue(
            any(
                "invalid_model_boundary_key" in warning
                for warning in review["curation_generation"]["warnings"]
            )
        )

    def test_workflow_bucket_splits_independent_done_states(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(
            workflow_response(
                [
                    workflow_item("W1", ["ROW-001"], done_state="MCP 연결을 확인할 수 있어요."),
                    workflow_item("W2", ["ROW-004"], done_state="스타일 실행 결과가 보여요."),
                ]
            ),
            anchors,
            rows,
        )
        self.assertEqual(len(plans), 2)
        self.assertNotEqual(plans[0]["done_state"], plans[1]["done_state"])

    def test_tool_surface_transition_is_preserved_as_workflow_boundary(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(
            workflow_response(
                [
                    workflow_item("W1", ["ROW-001"], surface="Cursor settings"),
                    workflow_item("W2", ["ROW-004"], surface="Figma canvas"),
                ]
            ),
            anchors,
            rows,
        )
        self.assertEqual(
            [plan["primary_tool_or_surface"] for plan in plans],
            ["Cursor settings", "Figma canvas"],
        )

    def test_auxiliary_action_attaches_without_creating_a_part(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(
            workflow_response(
                [workflow_item("W1", ["ROW-001"])],
                auxiliary_actions=[
                    {
                        "utterance_id": "ROW-004",
                        "attach_to_workflow_id": "W1",
                        "reason_category": "cleanup",
                    }
                ],
            ),
            anchors,
            rows,
        )
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["auxiliary_step_anchor_ids"], ["ROW-004"])
        self.assertEqual(plans[0]["step_anchor_ids"], ["ROW-001", "ROW-004"])

    def test_workflow_bucket_requires_every_seed_to_be_accounted(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        with self.assertRaisesRegex(AdminSkillResponseError, "unaccounted_anchor:ROW-004"):
            parse_composition_response(
                workflow_response([workflow_item("W1", ["ROW-001"])]),
                anchors,
                rows,
            )

    def test_interleaved_workflow_buckets_are_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(
            {
                "mode": "practice",
                "step_ids": ["ROW-001", "ROW-002", "ROW-003", "ROW-004"],
                "step_preview_ids": [],
            },
            prepared["script"],
        )
        with self.assertRaisesRegex(AdminSkillResponseError, "interleaved_part_anchor_clusters"):
            parse_composition_response(
                workflow_response(
                    [
                        workflow_item("W1", ["ROW-001", "ROW-004"]),
                        workflow_item("W2", ["ROW-002", "ROW-003"]),
                    ]
                ),
                anchors,
                rows,
            )

    def test_workflow_buckets_are_sorted_chronologically(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(
            workflow_response(
                [
                    workflow_item("W2", ["ROW-004"], title="두 번째 결과를 만들어요"),
                    workflow_item("W1", ["ROW-001"], title="첫 번째 결과를 만들어요"),
                ]
            ),
            anchors,
            rows,
        )
        self.assertEqual([plan["workflow_id"] for plan in plans], ["W1", "W2"])

    def test_many_actions_in_one_workflow_emit_quality_floor_warning(self) -> None:
        prepared = prepare_transcript(large_action_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        response = {
            "mode": "practice",
            "step_ids": list(rows),
            "step_preview_ids": [],
        }
        _, anchors, _ = parse_classification_response(response, prepared["script"])
        _, warnings = parse_composition_response(
            workflow_response([workflow_item("W1", list(rows))]),
            anchors,
            rows,
            quality_context={
                "mode": "practice",
                "duration_seconds": prepared["duration_seconds"],
            },
        )
        self.assertTrue(
            any(warning.startswith("composition:one_workflow_quality_floor") for warning in warnings)
        )

    def test_part_composition_does_not_require_chapter_passthrough(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        _, classifications, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(
            model_responses()[1], classifications, {row["utterance_id"]: row for row in prepared["script"]}
        )
        self.assertNotEqual(set(plans[0]["step_anchor_ids"]), {"ROW-001", "ROW-002", "ROW-003"})

    def test_anchor_context_materialization_is_bounded_and_ordered(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        context = materialize_anchor_context(
            prepared["script"], {"ROW-004"}, radius=1
        )
        self.assertEqual(context, ["ROW-003", "ROW-004", "ROW-005"])
        self.assertLess(len(context), len(prepared["script"]))

    def test_part_plan_materializes_deterministic_action_span_and_context(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(model_responses()[1], anchors, rows, set(rows))
        self.assertEqual(plans[0]["action_span_utterance_ids"], ["ROW-001", "ROW-002", "ROW-003", "ROW-004"])
        self.assertIn("ROW-002", plans[0]["context_utterance_ids"])
        self.assertIn("ROW-005", plans[0]["context_utterance_ids"])

    def test_model_composition_output_has_no_source_range(self) -> None:
        part = model_responses()[1]["parts"][0]
        self.assertNotIn("source_start_utterance_id", part)
        self.assertNotIn("source_end_utterance_id", part)

    def test_real_source_anchor_missing_from_pass_1_becomes_supplemental(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, seeds, _ = parse_classification_response(
            {"mode": "practice", "step_ids": ["ROW-001"], "step_preview_ids": []},
            prepared["script"],
        )
        response = model_responses()[1]
        response["parts"][0]["step_anchor_ids"] = ["ROW-001", "ROW-004"]
        plans, warnings = parse_composition_response(response, seeds, rows, set(rows))
        self.assertEqual(plans[0]["supplemental_step_anchor_ids"], ["ROW-004"])
        self.assertIn("composition:supplemental_action_anchor:ROW-004", warnings)

    def test_nonexistent_pass_2_anchor_remains_hard_error(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, seeds, _ = parse_classification_response(model_responses()[0], prepared["script"])
        response = model_responses()[1]
        response["parts"][0]["step_anchor_ids"] = ["ROW-001", "UT-99999"]
        with self.assertRaisesRegex(AdminSkillResponseError, "unknown_source_utterance_id:UT-99999"):
            parse_composition_response(response, seeds, rows, set(rows))

    def test_supplemental_anchor_duplicate_ownership_is_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, seeds, _ = parse_classification_response(model_responses()[0], prepared["script"])
        first = model_responses()[1]["parts"][0]
        response = {
            "parts": [
                {**first, "title": "첫 작업을 끝내요", "step_anchor_ids": ["ROW-001", "ROW-002"]},
                {**first, "title": "두 번째 작업을 끝내요", "step_anchor_ids": ["ROW-002", "ROW-004"]},
            ],
            "excluded_step_anchor_ids": [],
        }
        with self.assertRaisesRegex(AdminSkillResponseError, "duplicate_anchor_accounting:ROW-002"):
            parse_composition_response(response, seeds, rows, set(rows))

    def test_materialize_source_span_is_inclusive_and_ordered(self) -> None:
        script = prepare_transcript(preprocessing_fixture())["script"]
        self.assertEqual(
            materialize_source_span(script, "ROW-002", "ROW-005"),
            ["ROW-002", "ROW-003", "ROW-004", "ROW-005"],
        )

    def test_composition_requires_done_state(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        response = model_responses()[1]
        response["parts"][0]["done_state"] = ""
        with self.assertRaisesRegex(AdminSkillResponseError, "done_state_required"):
            parse_composition_response(response, anchors, rows, set(rows))

    def test_composition_accounts_for_every_step_anchor(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        response = model_responses()[1]
        response["parts"][0]["step_anchor_ids"] = ["ROW-001"]
        with self.assertRaisesRegex(AdminSkillResponseError, "unaccounted_anchor:ROW-004"):
            parse_composition_response(response, anchors, rows, set(rows))

    def test_composition_rejects_multiple_explicit_done_states(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        response = model_responses()[1]
        response["parts"][0]["done_state"] = "연결이 완료됩니다; 별도 결과물이 생성됩니다."
        with self.assertRaisesRegex(AdminSkillResponseError, "multiple_done_states"):
            parse_composition_response(response, anchors, rows, set(rows))

    def test_composition_sorts_parts_by_first_anchor(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        first = model_responses()[1]["parts"][0]
        response = {
            "parts": [
                {**first, "title": "다음 작업을 끝내요", "step_anchor_ids": ["ROW-004"]},
                {**first, "title": "설정을 먼저 끝내요", "step_anchor_ids": ["ROW-001"]},
            ],
            "excluded_step_anchor_ids": [],
        }
        plans, _ = parse_composition_response(response, anchors, rows, set(rows))
        self.assertEqual(
            [plan["title"] for plan in plans],
            ["설정을 먼저 끝내요", "다음 작업을 끝내요"],
        )

    def test_interleaved_part_anchor_clusters_are_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(
            {
                "mode": "practice",
                "step_ids": ["ROW-001", "ROW-002", "ROW-003", "ROW-004"],
                "step_preview_ids": [],
            },
            prepared["script"],
        )
        first = model_responses()[1]["parts"][0]
        response = {
            "parts": [
                {**first, "title": "첫 결과를 만들어요", "step_anchor_ids": ["ROW-001", "ROW-004"]},
                {**first, "title": "두 번째 결과를 만들어요", "step_anchor_ids": ["ROW-002", "ROW-003"]},
            ],
            "excluded_step_anchor_ids": [],
        }
        with self.assertRaisesRegex(AdminSkillResponseError, "interleaved_part_anchor_clusters"):
            parse_composition_response(response, anchors, rows, set(rows))

    def test_duplicate_anchor_ownership_is_rejected(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        first = model_responses()[1]["parts"][0]
        response = {
            "parts": [
                {**first, "title": "첫 결과를 만들어요", "step_anchor_ids": ["ROW-001", "ROW-004"]},
                {**first, "title": "중복 결과를 만들어요", "step_anchor_ids": ["ROW-004"]},
            ],
            "excluded_step_anchor_ids": [],
        }
        with self.assertRaisesRegex(AdminSkillResponseError, "duplicate_anchor_accounting"):
            parse_composition_response(response, anchors, rows, set(rows))

    def test_excluded_anchor_with_category_and_reason_is_accounted(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        response = model_responses()[1]
        response["parts"][0]["step_anchor_ids"] = ["ROW-001"]
        response["excluded_step_anchor_ids"] = [
            {"utterance_id": "ROW-004", "reason_category": "auxiliary_action", "reason": "기존 workflow를 보조하는 작업이에요."}
        ]
        plans, warnings = parse_composition_response(response, anchors, rows, set(rows))
        self.assertEqual(len(plans), 1)
        self.assertIn("auxiliary_action", warnings[0])

    def test_adjacent_context_materialization_does_not_change_action_span(self) -> None:
        script = prepare_transcript(preprocessing_fixture())["script"]
        rows = {row["utterance_id"]: row for row in script}
        plans = [
            {"step_anchor_ids": ["ROW-002"], "action_start_utterance_id": "ROW-002", "action_end_utterance_id": "ROW-002"},
            {"step_anchor_ids": ["ROW-005"], "action_start_utterance_id": "ROW-005", "action_end_utterance_id": "ROW-005"},
        ]
        materialize_part_contexts(plans, script, rows, radius=1)
        self.assertEqual(plans[0]["context_utterance_ids"], ["ROW-001", "ROW-002", "ROW-003"])
        self.assertEqual(plans[1]["context_utterance_ids"], ["ROW-004", "ROW-005", "ROW-006"])
        self.assertEqual(plans[0]["action_start_utterance_id"], "ROW-002")
        self.assertEqual(plans[1]["action_end_utterance_id"], "ROW-005")

    def test_independent_setup_workflow_survives_composition(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        first = model_responses()[1]["parts"][0]
        response = {
            "parts": [
                {**first, "title": "연결을 끝내요", "done_state": "연결 상태를 확인할 수 있어요.", "step_anchor_ids": ["ROW-001"]},
                {**first, "title": "정보를 실행해요", "done_state": "실행 결과가 화면에 보여요.", "step_anchor_ids": ["ROW-004"]},
            ],
            "excluded_step_anchor_ids": [],
        }
        plans, _ = parse_composition_response(response, anchors, rows, set(rows))
        self.assertEqual(len(plans), 2)

    def test_auxiliary_cleanup_does_not_force_new_part(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        response = model_responses()[1]
        response["parts"][0]["step_anchor_ids"] = ["ROW-001"]
        response["excluded_step_anchor_ids"] = [
            {"utterance_id": "ROW-004", "reason_category": "auxiliary_cleanup", "reason": "완료 결과를 개선하는 선택 작업이에요."}
        ]
        plans, _ = parse_composition_response(response, anchors, rows, set(rows))
        self.assertEqual(len(plans), 1)

    def test_step_generation_and_optional_blocks(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, classifications, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(model_responses()[1], classifications, rows)
        steps, checkpoint, unused, warnings = parse_step_response(model_responses()[2], plans[0], rows)
        self.assertEqual(len(steps), 2)
        self.assertEqual(len(steps[0]["learn_more"]), 1)
        self.assertIsNotNone(steps[1]["warning"])
        self.assertIsNotNone(checkpoint)
        self.assertEqual(unused, [])
        self.assertEqual(warnings, [])

    def test_pass_3_accounts_for_every_part_anchor(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(model_responses()[1], anchors, rows)
        response = model_responses()[2]
        response["steps"][1]["anchor_ids"] = []
        with self.assertRaisesRegex(AdminSkillResponseError, "anchor_ids_required|unaccounted_anchor:ROW-004"):
            parse_step_response(response, plans[0], rows)

    def test_warning_does_not_require_pass_1_warning_anchor(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(model_responses()[1], anchors, rows)
        steps, _, _, warnings = parse_step_response(model_responses()[2], plans[0], rows)
        self.assertIsNotNone(steps[1]["warning"])
        self.assertEqual(warnings, [])

    def test_checkpoint_does_not_require_pass_1_checkpoint_anchor(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(model_responses()[1], anchors, rows)
        _, checkpoint, _, warnings = parse_step_response(model_responses()[2], plans[0], rows)
        self.assertIsNotNone(checkpoint)
        self.assertEqual(warnings, [])

    def test_pass_3_learn_more_uses_unclassified_part_context(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        self.assertNotIn("ROW-002", anchors)
        plans, _ = parse_composition_response(model_responses()[1], anchors, rows, set(rows))
        steps, _, _, warnings = parse_step_response(model_responses()[2], plans[0], rows)
        self.assertEqual(steps[0]["learn_more"][0]["evidence"][0]["utterance_id"], "ROW-002")
        self.assertEqual(warnings, [])

    def test_prompt_requires_verbatim_source_and_cue(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        prompt, warning = _exact_prompt(
            {"text": "새 프롬프트", "source_utterance_ids": ["ROW-001"]}, {"ROW-001"}, rows
        )
        self.assertIsNone(prompt)
        self.assertIn("not_verbatim", warning or "")

    def test_admin_review_schema_and_call_budget(self) -> None:
        generator = ScriptedGenerator(model_responses())
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        self.assertEqual(review["schema_version"], "ddock_content_review_v0.1")
        self.assertEqual(len(review["draft_parts"]), 1)
        self.assertEqual(len(review["draft_parts"][0]["steps"]), 2)
        self.assertEqual(generator.calls, 3)
        self.assertEqual(generator.max_tokens[0], 2000)
        self.assertEqual(validate_ddock_content_review(review)["errors"], [])

    def test_pass_2_deterministic_failure_gets_one_targeted_repair(self) -> None:
        bad_composition = model_responses()[1]
        bad_composition["parts"][0]["done_state"] = ""
        responses = [
            model_responses()[0],
            bad_composition,
            model_responses()[1],
            model_responses()[2],
        ]
        generator = ScriptedGenerator(responses)
        review = generate_admin_skill_review(
            preprocessing_fixture(), generator=generator
        )
        skill = review["curation_generation"]["admin_skill"]
        self.assertEqual(generator.calls, 4)
        self.assertEqual(skill["pass_2_targeted_repair_count"], 1)
        self.assertEqual(
            generator.user_payloads[2]["pass"], "PASS_2_TARGETED_REPAIR"
        )
        repair_payload = generator.user_payloads[2]
        self.assertNotIn("original_input", repair_payload)
        self.assertIn("ordered_actions", repair_payload)
        self.assertNotIn("invalid_output", repair_payload)
        self.assertNotIn(
            "source_start_utterance_id",
            repair_payload["required_output_schema"]["workflow_boundaries"][0],
        )

    def test_pass_3_unaccounted_anchor_survives_after_one_targeted_repair(self) -> None:
        partial = model_responses()[2]
        partial["steps"] = partial["steps"][:1]
        repair = {"steps": [], "checkpoint": None, "excluded_anchor_ids": []}
        generator = ScriptedGenerator(
            [model_responses()[0], model_responses()[1], partial, repair]
        )
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        part = review["draft_parts"][0]
        self.assertEqual(len(part["steps"]), 1)
        self.assertTrue(part["needs_review"])
        self.assertTrue(
            any(
                item["type"] == "unaccounted_action_anchor"
                and item["severity"] == "blocking"
                for item in review["review_queue"]
            )
        )
        self.assertEqual(
            review["curation_generation"]["admin_skill"]["pass_3_targeted_repair_count"],
            1,
        )

    def test_zero_step_part_survives_as_blocking_review_draft(self) -> None:
        empty = {"steps": [], "checkpoint": None, "excluded_anchor_ids": []}
        generator = ScriptedGenerator(
            [model_responses()[0], model_responses()[1], empty, empty]
        )
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        self.assertEqual(review["draft_parts"][0]["steps"], [])
        self.assertTrue(review["draft_parts"][0]["needs_review"])
        self.assertEqual(validate_ddock_content_review(review)["errors"], [])
        self.assertTrue(validate_review_for_publish(review)["errors"])

    def test_pass_2_explicit_exclusion_does_not_become_unaccounted_phase(self) -> None:
        composition = model_responses()[1]
        composition["parts"][0]["step_anchor_ids"] = ["ROW-001"]
        composition["excluded_step_anchor_ids"] = [
            {
                "utterance_id": "ROW-004",
                "reason_category": "auxiliary_action",
                "reason": "검토가 필요한 보조 작업이에요.",
            }
        ]
        step = model_responses()[2]
        step["steps"] = step["steps"][:1]
        generator = ScriptedGenerator([model_responses()[0], composition, step])
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        self.assertEqual(review["unassigned_phases"], [])
        self.assertFalse(any(item["type"] == "unassigned_phase" for item in review["review_queue"]))

    def test_low_pass_2_anchor_coverage_is_a_warning_not_a_failure(self) -> None:
        composition = model_responses()[1]
        composition["parts"][0]["step_anchor_ids"] = ["ROW-001"]
        composition["excluded_step_anchor_ids"] = [
            {
                "utterance_id": "ROW-004",
                "reason_category": "auxiliary_action",
                "reason": "검토가 필요한 보조 작업이에요.",
            }
        ]
        step = model_responses()[2]
        step["steps"] = step["steps"][:1]
        review = generate_admin_skill_review(
            preprocessing_fixture(), generator=ScriptedGenerator([model_responses()[0], composition, step])
        )
        self.assertTrue(
            any(item["type"] == "low_action_anchor_coverage" for item in review["review_queue"])
        )

    def test_anchor_detection_materializes_pass_2_payload(self) -> None:
        generator = ScriptedGenerator(model_responses())
        generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        pass_1_payload = generator.user_payloads[0]
        self.assertEqual(pass_1_payload["pass"], "PASS_1_ACTION_ANCHOR_DETECTION")
        self.assertTrue(pass_1_payload["preparation"]["action_marker_utterance_ids"])
        self.assertTrue(all("chapter_id" not in row for row in pass_1_payload["rows"]))
        payload = generator.user_payloads[1]
        self.assertEqual(payload["pass"], "PASS_2_ORDERED_ACTION_SEGMENTATION")
        self.assertNotIn("rows", payload)
        self.assertEqual(payload["ordered_actions"][0]["action_key"], "A01")
        self.assertEqual(payload["ordered_actions"][0]["anchor_role"], "STEP")
        self.assertTrue(
            all(
                "utterance_id" not in row and "chapter_id" not in row
                for row in payload["ordered_actions"]
            )
        )

        pass_3_payload = generator.user_payloads[2]
        self.assertEqual(pass_3_payload["part"]["done_state"], "스타일 정보가 화면에 표시됩니다.")
        self.assertNotIn("source_start_utterance_id", pass_3_payload["part"])
        self.assertNotIn("source_end_utterance_id", pass_3_payload["part"])
        self.assertEqual(
            [row["utterance_id"] for row in pass_3_payload["rows"]],
            ["ROW-001", "ROW-002", "ROW-003", "ROW-004", "ROW-005", "ROW-006"],
        )

    def test_supplemental_anchor_enters_pass_3_and_projects_warning(self) -> None:
        classification = {"mode": "practice", "step_ids": ["ROW-001"], "step_preview_ids": []}
        composition = model_responses()[1]
        generator = ScriptedGenerator([classification, composition, model_responses()[2]])
        review = generate_admin_skill_review(preprocessing_fixture(), generator=generator)
        self.assertEqual(
            generator.user_payloads[2]["part"]["step_anchor_ids"],
            ["ROW-001", "ROW-004"],
        )
        self.assertTrue(
            any(
                item["type"] == "supplemental_action_anchor"
                and item["severity"] == "warning"
                for item in review["review_queue"]
            )
        )
        skill = review["curation_generation"]["admin_skill"]
        self.assertEqual(skill["seed_action_anchor_count"], 1)
        self.assertEqual(skill["supplemental_action_anchor_count"], 1)
        self.assertEqual(skill["supplemental_action_utterance_ids"], ["ROW-004"])
        self.assertEqual(skill["final_action_anchor_count"], 2)
        baseline = generate_admin_skill_review(
            preprocessing_fixture(), generator=ScriptedGenerator(model_responses())
        )
        self.assertEqual(
            validate_review_for_publish(review)["errors"],
            validate_review_for_publish(baseline)["errors"],
        )

    def test_one_workflow_quality_floor_triggers_one_targeted_repair(self) -> None:
        fixture = large_action_fixture()
        prepared = prepare_transcript(fixture)
        ids = [row["utterance_id"] for row in prepared["script"]]
        classification = {"mode": "practice", "step_ids": ids, "step_preview_ids": []}
        initial = workflow_response([workflow_item("W1", ids)])
        repaired = workflow_response(
            [
                workflow_item("W1", ids[:14], surface="설정"),
                workflow_item("W2", ids[14:27], surface="토큰"),
                workflow_item("W3", ids[27:], surface="코드"),
            ]
        )

        def step_response(anchor_ids: list[str], index: int) -> dict:
            source_id = anchor_ids[0]
            source_text = fixture["normalized_utterances"][ids.index(source_id)]["normalized_text"]
            return {
                "steps": [
                    {
                        "action_title": f"{index}번 작업을 실행해요",
                        "anchor_ids": anchor_ids,
                        "action_lines": [
                            {"text": source_text, "source_utterance_ids": [source_id]}
                        ],
                        "source_utterance_ids": anchor_ids,
                        "prompt": None,
                        "warning": None,
                        "learn_more": [],
                        "needs_review": False,
                    }
                ],
                "checkpoint": None,
                "excluded_anchor_ids": [],
            }

        generator = ScriptedGenerator(
            [
                classification,
                initial,
                repaired,
                step_response(ids[:14], 1),
                step_response(ids[14:27], 2),
                step_response(ids[27:], 3),
            ]
        )
        review = generate_admin_skill_review(fixture, generator=generator)
        self.assertEqual(len(review["draft_parts"]), 3)
        self.assertEqual(
            review["curation_generation"]["admin_skill"]["pass_2_targeted_repair_count"],
            1,
        )
        self.assertEqual(generator.user_payloads[2]["pass"], "PASS_2_TARGETED_REPAIR")

    def test_late_independent_tool_cluster_survives_as_workflow(self) -> None:
        prepared = prepare_transcript(preprocessing_fixture())
        rows = {row["utterance_id"]: row for row in prepared["script"]}
        _, anchors, _ = parse_classification_response(model_responses()[0], prepared["script"])
        plans, _ = parse_composition_response(
            workflow_response(
                [
                    workflow_item("W1", ["ROW-001"], surface="설정 화면"),
                    workflow_item(
                        "W2",
                        ["ROW-004"],
                        surface="별도 가져오기 도구",
                        done_state="가져온 결과가 편집 화면에 보여요.",
                    ),
                ]
            ),
            anchors,
            rows,
        )
        self.assertEqual(plans[-1]["primary_tool_or_surface"], "별도 가져오기 도구")

    def test_noun_style_part_and_step_titles_project_writing_style_warning(self) -> None:
        composition = workflow_response(
            [workflow_item("W1", ["ROW-001", "ROW-004"], title="토큰 구성하기")]
        )
        step = model_responses()[2]
        step["steps"][0]["action_title"] = "MCP 설정"
        review = generate_admin_skill_review(
            preprocessing_fixture(),
            generator=ScriptedGenerator([model_responses()[0], composition, step]),
        )
        self.assertTrue(
            any(item["type"] == "writing_style_review" for item in review["review_queue"])
        )

    def test_possible_duplicate_part_is_warning_only(self) -> None:
        first = model_responses()[1]["parts"][0]
        composition = {
            "parts": [
                {**first, "title": "MCP 연결을 설정해요", "step_anchor_ids": ["ROW-001"]},
                {**first, "title": "MCP 연결 설정을 마쳐요", "step_anchor_ids": ["ROW-004"]},
            ],
            "excluded_step_anchor_ids": [],
        }
        first_step = model_responses()[2]
        first_step["steps"] = first_step["steps"][:1]
        second_step = model_responses()[2]
        second_step["steps"] = second_step["steps"][1:]
        review = generate_admin_skill_review(
            preprocessing_fixture(),
            generator=ScriptedGenerator(
                [model_responses()[0], composition, first_step, second_step]
            ),
        )
        self.assertTrue(
            any(
                item["type"] == "possible_duplicate_part"
                and item["severity"] == "warning"
                for item in review["review_queue"]
            )
        )

    def test_action_phase_is_projected_from_steps(self) -> None:
        review = generate_admin_skill_review(
            preprocessing_fixture(), generator=ScriptedGenerator(model_responses())
        )
        self.assertEqual(len(review["action_phases"]), 2)
        self.assertTrue(all(phase["assigned_part_id"] == "PART-01" for phase in review["action_phases"]))

    def test_checkpoint_is_preserved_in_generation_diagnostics(self) -> None:
        review = generate_admin_skill_review(
            preprocessing_fixture(), generator=ScriptedGenerator(model_responses())
        )
        skill = review["curation_generation"]["admin_skill"]
        self.assertEqual(skill["checkpoint_count"], 1)
        self.assertEqual(skill["checkpoints"][0]["part_id"], "PART-01")

    def test_raw_dump_is_env_gated_and_contains_parsed_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"DDOCK_ADMIN_SKILL_DUMP_RAW": root}):
                generate_admin_skill_review(
                    preprocessing_fixture(), generator=ScriptedGenerator(model_responses())
                )
            paths = sorted(Path(root).glob("*.json"))
            self.assertEqual(len(paths), 3)
            self.assertIsInstance(json.loads(paths[0].read_text())["parsed_output"], dict)

    def test_generation_failure_raises_without_partial_review(self) -> None:
        generator = ScriptedGenerator(
            [{
                "mode": "practice",
                "step_ids": [],
                "step_preview_ids": [],
            }]
        )
        with self.assertRaises(AdminSkillResponseError):
            generate_admin_skill_review(preprocessing_fixture(), generator=generator)

    def test_dev_admin_script_exists(self) -> None:
        package = json.loads((Path(__file__).resolve().parents[2] / "package.json").read_text())
        self.assertEqual(package["scripts"]["predev:admin"], "node scripts/setup-fonts.mjs")
        self.assertEqual(package["scripts"]["dev:admin"], "next dev -p 3101")


class G0GoldenFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cards = json.loads((FIXTURE_ROOT / "G0d9CHLpnnc-cards.json").read_text())
        cls.extraction = json.loads((FIXTURE_ROOT / "G0d9CHLpnnc-extraction.json").read_text())

    def test_golden_scale_and_classification_variety(self) -> None:
        self.assertEqual(len(self.cards["cards"]), 4)
        self.assertEqual(sum(len(card["steps"]) for card in self.cards["cards"]), 16)
        counts = self.extraction["step_3_classification"]["counts"]
        self.assertGreater(counts["STEP"], 0)
        self.assertGreater(counts["ⓘ"], 0)
        self.assertGreater(counts["삭제"], 0)

    def test_golden_four_major_workflows_materialize_as_ordered_segments(self) -> None:
        fixture_rows = self.extraction["step_3_classification"]["rows"]
        action_rows = [
            row for row in fixture_rows if row["verdict"] in {"STEP", "STEP 예고"}
        ]
        script = [
            {
                "utterance_id": row["utterance_id"],
                "start_seconds": row["start_seconds"],
                "end_seconds": row["start_seconds"] + 1,
                "text": row["text"],
            }
            for row in action_rows
        ]
        rows = {row["utterance_id"]: row for row in script}
        ordered = list(rows)
        _, anchors, _ = parse_classification_response(
            {
                "mode": "practice",
                "step_ids": [
                    row["utterance_id"] for row in action_rows if row["verdict"] == "STEP"
                ],
                "step_preview_ids": [
                    row["utterance_id"]
                    for row in action_rows
                    if row["verdict"] == "STEP 예고"
                ],
            },
            script,
        )
        plans, _ = parse_composition_response(
            boundary_response(
                [
                    boundary_item("UT-00038", title="MCP 연결을 확인해요", surface="연결 설정"),
                    boundary_item("UT-00048", title="디자인 토큰을 구성해요", surface="디자인 데이터"),
                    boundary_item("UT-00088", title="React 컴포넌트를 구현해요", surface="코드 편집기"),
                    boundary_item("UT-00141", title="화면을 캡처해 가져와요", surface="캡처와 가져오기"),
                ]
            ),
            anchors,
            rows,
            set(rows),
            ordered_action_ids=ordered,
        )
        surfaces = " ".join(
            plan["title"] + " " + " ".join(rows[item]["text"] for item in plan["step_anchor_ids"])
            for plan in plans
        ).casefold()
        self.assertEqual(len(plans), 4)
        for tokens in (("mcp",), ("토큰",), ("react", "리액트"), ("캡처", "스크린 플로우")):
            self.assertTrue(any(token in surfaces for token in tokens))
        self.assertEqual(
            len({item for plan in plans for item in plan["primary_step_anchor_ids"]}),
            len(ordered),
        )

    def test_golden_anchor_projection_uses_ultra_compact_schema(self) -> None:
        rows = self.extraction["step_3_classification"]["rows"]
        fields = {
            "STEP": "step_ids",
            "STEP 예고": "step_preview_ids",
        }
        compact = {
            "mode": "practice",
            "step_ids": [],
            "step_preview_ids": [],
        }
        for row in rows:
            field = fields.get(row["verdict"])
            if field:
                compact[field].append(row["utterance_id"])
        script = [
            {
                "utterance_id": row["utterance_id"],
                "start_seconds": row["start_seconds"],
                "end_seconds": row["start_seconds"] + 1,
                "text": row["text"],
            }
            for row in rows
        ]
        mode, projected, _ = parse_classification_response(compact, script)
        self.assertEqual(mode, "practice")
        self.assertEqual(set(compact), {"mode", "step_ids", "step_preview_ids"})
        self.assertTrue(projected)
        self.assertTrue(all(item["label"] not in {"INFO", "HOOK", "DROP"} for item in projected.values()))
        self.assertLess(len(projected), len(rows) // 2)

    def test_golden_real_action_missing_from_seed_can_be_supplemental(self) -> None:
        source_rows = self.extraction["step_3_classification"]["rows"]
        script = [
            {
                "utterance_id": row["utterance_id"],
                "start_seconds": row["start_seconds"],
                "end_seconds": row["start_seconds"] + 1,
                "text": row["text"],
            }
            for row in source_rows
        ]
        rows = {row["utterance_id"]: row for row in script}
        supplemental_id = "UT-00148"
        self.assertEqual(
            next(row["verdict"] for row in source_rows if row["utterance_id"] == supplemental_id),
            "STEP",
        )
        seed_id = next(
            row["utterance_id"]
            for row in source_rows
            if row["verdict"] == "STEP" and row["utterance_id"] != supplemental_id
        )
        _, seeds, _ = parse_classification_response(
            {"mode": "practice", "step_ids": [seed_id], "step_preview_ids": []},
            script,
        )
        plans, warnings = parse_composition_response(
            {
                "parts": [
                    {
                        "title": "실제 작업을 이어서 해요",
                        "action_objective": "source-backed 작업을 완료해요.",
                        "done_state": "작업 결과를 확인할 수 있어요.",
                        "step_anchor_ids": [seed_id, supplemental_id],
                    }
                ],
                "excluded_step_anchor_ids": [],
            },
            seeds,
            rows,
            set(rows),
        )
        self.assertIn(supplemental_id, plans[0]["supplemental_step_anchor_ids"])
        self.assertIn(f"composition:supplemental_action_anchor:{supplemental_id}", warnings)

    def test_golden_action_anchors_cover_four_major_workflows(self) -> None:
        rows = self.extraction["step_3_classification"]["rows"]
        anchor_text = " ".join(
            row["text"]
            for row in rows
            if row["verdict"] in {"STEP", "STEP 예고", "⚠", "⚠ 근거", "✓"}
        ).casefold()
        for tokens in (
            ("mcp",),
            ("토큰",),
            ("react", "리액트"),
            ("스크린 플로우", "스크린플로우"),
        ):
            self.assertTrue(any(token.casefold() in anchor_text for token in tokens))

    def test_golden_non_action_tail_is_not_promoted_to_anchor(self) -> None:
        rows = self.extraction["step_3_classification"]["rows"]
        tail_rows = [row for row in rows if float(row["start_seconds"]) >= 1580]
        self.assertTrue(any("인터뷰" in row["text"] for row in tail_rows))
        self.assertTrue(any("런칭" in row["text"] or "채널" in row["text"] for row in tail_rows))
        self.assertTrue(all(row["verdict"] == "삭제" for row in tail_rows))

    def test_golden_major_workflows_are_semantically_covered(self) -> None:
        card_surfaces = [json.dumps(card, ensure_ascii=False).casefold() for card in self.cards["cards"]]
        workflow_tokens = (("mcp",), ("토큰",), ("react", "리액트"), ("스크린플로우",))
        coverage = [
            [any(token.casefold() in surface for token in tokens) for surface in card_surfaces]
            for tokens in workflow_tokens
        ]
        self.assertTrue(
            any(
                all(coverage[workflow_index][card_index] for workflow_index, card_index in enumerate(order))
                for order in permutations(range(len(card_surfaces)), len(workflow_tokens))
            )
        )

    def test_golden_major_workflows_form_four_distinct_buckets(self) -> None:
        titles = [card["title"].casefold() for card in self.cards["cards"]]
        expected = (("mcp",), ("토큰",), ("커서", "react"), ("스크린플로우",))
        self.assertEqual(len(titles), 4)
        self.assertTrue(
            all(any(any(token in title for token in tokens) for title in titles) for tokens in expected)
        )

    def test_golden_auxiliary_actions_are_not_promoted_to_major_parts(self) -> None:
        titles = " ".join(card["title"] for card in self.cards["cards"]).casefold()
        self.assertNotIn("rename layers", titles)
        self.assertNotIn("레이어 이름 정리", titles)
        rename_rows = [
            row
            for row in self.extraction["step_3_classification"]["rows"]
            if "Rename Layers" in str(row.get("note") or "")
        ]
        self.assertTrue(rename_rows)
        self.assertTrue(all(row["verdict"] == "ⓘ" for row in rename_rows))

    def test_golden_late_capture_import_workflow_remains_independent(self) -> None:
        last_card = self.cards["cards"][-1]
        self.assertIn("스크린플로우", last_card["title"].casefold())
        self.assertGreaterEqual(len(last_card["steps"]), 3)
        self.assertTrue(any("Figma" in step["title"] for step in last_card["steps"]))

    def test_golden_user_facing_titles_prefer_action_style(self) -> None:
        titles = [
            card["title"]
            for card in self.cards["cards"]
        ] + [step["title"] for card in self.cards["cards"] for step in card["steps"]]
        self.assertTrue(all(not title.endswith(("하기", "구성", "설정")) for title in titles))

    def test_golden_step_density_is_inside_acceptance_band(self) -> None:
        part_count = len(self.cards["cards"])
        step_count = sum(len(card["steps"]) for card in self.cards["cards"])
        self.assertGreaterEqual(part_count, 3)
        self.assertLessEqual(part_count, 5)
        self.assertGreaterEqual(step_count, 10)
        self.assertLessEqual(step_count, 18)

    def test_golden_auxiliary_actions_are_not_promoted_to_main_parts(self) -> None:
        titles = " ".join(str(card.get("title") or "") for card in self.cards["cards"]).casefold()
        self.assertNotIn("rename layers", titles)
        self.assertNotIn("레이어명 정리", titles)
        self.assertNotIn("디자인 시스템 파일 활용", titles)

    def test_golden_drop_tail_and_prompts(self) -> None:
        reasons = {item["reason"] for item in self.cards["dropped"]}
        self.assertIn("channel_promo", reasons)
        self.assertIn("small_talk", reasons)
        prompts = [
            step["prompt"]
            for card in self.cards["cards"]
            for step in card["steps"]
            if "prompt" in step
        ]
        self.assertEqual(len(prompts), 3)


if __name__ == "__main__":
    unittest.main()
