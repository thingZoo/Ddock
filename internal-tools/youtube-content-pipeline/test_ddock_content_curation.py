from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from ddock_content_contract import OUTPUT_FILENAME, SCHEMA_VERSION
from ddock_content_curation import (
    CurationResponseError,
    build_script_contract,
    curate_ddock_content,
    ddock_content_output_path,
    extract_source_backed_tool_candidates,
    final_text_for_utterance,
    hash_preprocessed_result,
    parse_part_planning_response,
    parse_step_generation_response,
    parse_video_detail_response,
    render_surface_preview,
    write_ddock_content_atomic,
)
from ddock_content_validator import validate_ddock_content


def _row(number: int, chapter: int, text: str) -> dict:
    start = float((number - 1) * 10)
    return {
        "utterance_id": f"UT-{number:05d}",
        "chapter_id": f"CH-{chapter:02d}",
        "chapter_label": f"Chapter {chapter}",
        "start_seconds": start,
        "end_seconds": start + 8.0,
        "display_timestamp": f"00:{int(start):02d}",
        "raw_joined_text": "RAW " + text,
        "normalized_text": text,
    }


def _fixture(*, language: str = "ko") -> tuple[dict, dict]:
    rows = [
        _row(1, 1, "오늘 다룰 내용을 소개하고 인사합니다."),
        _row(2, 2, "Cursor 설정에서 MCP 탭을 열어요."),
        _row(3, 2, "/model 입력 → Sonnet 선택"),
        _row(4, 2, "CLAUDE.md 파일을 만들어요."),
        _row(5, 3, "실행 버튼을 눌러 결과를 확인해요."),
        _row(6, 3, "실제 프롬프트는 컴포넌트를 구현해 줘 입니다."),
        _row(7, 3, "API 키를 코드에 넣으면 비용이 발생할 수 있으니 .env 파일에 저장하세요."),
        _row(8, 3, "Sonnet을 선택하는 이유는 이 작업에 적절한 균형을 제공하기 때문입니다."),
        _row(9, 3, "여기서 잠깐 일반적인 이야기를 나눕니다."),
        _row(10, 4, "마무리 인사와 채널 홍보를 합니다."),
    ]
    result = {
        "schema_version": "script_preprocessing_v0.3.15.1",
        "video_id": "video-a",
        "source_url": "https://www.youtube.com/watch?v=video-a",
        "source_language": language,
        "processed_chapter": {
            "chapter_id": "FULL",
            "start_seconds": 0,
            "end_seconds": 98,
        },
        "creator_chapters": [
            {"label": f"Chapter {index}", "start_seconds": (index - 1) * 20}
            for index in range(1, 5)
        ],
        "normalized_utterances": rows,
        "content_chapter_generation": {"schema_version": "content_chapters_v0.1"},
        "content_chapters": [
            {
                "content_chapter_id": "CCH-01",
                "title": "intro",
                "source_utterance_ids": ["UT-00001"],
            },
            {
                "content_chapter_id": "CCH-02",
                "title": "setup",
                "source_utterance_ids": ["UT-00002", "UT-00003", "UT-00004"],
            },
            {
                "content_chapter_id": "CCH-03",
                "title": "execute",
                "source_utterance_ids": ["UT-00005", "UT-00006", "UT-00007", "UT-00008"],
            },
            {
                "content_chapter_id": "CCH-04",
                "title": "talk",
                "source_utterance_ids": ["UT-00009"],
            },
            {
                "content_chapter_id": "CCH-05",
                "title": "outro",
                "source_utterance_ids": ["UT-00010"],
            },
        ],
        "content_chapter_assets": {
            "items": [
                {
                    "content_chapter_id": chapter_id,
                    "selected_screenshot": {
                        "relative_path": f"{chapter_id}.jpg",
                        "storage_kind": "final_output",
                    },
                }
                for chapter_id in ("CCH-02", "CCH-03")
            ]
        },
    }
    source = {
        "source_url": result["source_url"],
        "metadata": {
            "video_id": "video-a",
            "title": "테스트 튜토리얼",
            "channel_title": "D:ock Test",
            "published_at": "2026-01-02T00:00:00Z",
            "duration_seconds": 98,
            "default_language": language,
            "view_count": "123",
            "like_count": "12",
            "description_raw": "Cursor 공식 안내 https://cursor.com/",
        },
    }
    return result, source


def _part_response(two_parts: bool = False) -> dict:
    parts = [
        {
            "title": "환경을 설정하고 결과를 확인해요",
            "summary": "설정부터 실행까지 한 흐름으로 따라갑니다.",
            "action_objective": "Cursor 환경을 설정하고 실행 결과를 확인한다",
            "source_utterance_ids": [f"UT-{value:05d}" for value in range(2, 9)],
            "action_utterance_ids": [f"UT-{value:05d}" for value in range(2, 8)],
            "needs_review": False,
        }
    ]
    if two_parts:
        parts = [
            {
                **parts[0],
                "source_utterance_ids": ["UT-00002", "UT-00003", "UT-00004"],
                "action_utterance_ids": ["UT-00002", "UT-00003", "UT-00004"],
            },
            {
                "title": "결과를 검증해요",
                "summary": None,
                "action_objective": "실행 결과와 주의 사항을 확인한다",
                "source_utterance_ids": ["UT-00005", "UT-00006", "UT-00007", "UT-00008"],
                "action_utterance_ids": ["UT-00005", "UT-00006", "UT-00007"],
                "needs_review": False,
            },
        ]
    return {
        "status": "completed",
        "content_chapter_assessments": [
            {
                "content_chapter_id": f"CCH-{index:02d}",
                "action_worthy": True,
                "decision_reason": "action workflow",
                "part_candidate": "setup-and-run",
            }
            for index in (2, 3)
        ],
        "parts": parts,
        "warnings": [],
    }


def _step_response() -> dict:
    return {
        "steps": [
            {
                "action_title": "MCP 설정을 열어요",
                "action_lines": [
                    {"source_utterance_ids": ["UT-00002"], "segments": [
                        {"type": "ui_label", "text": "Cursor"},
                        {"type": "text", "text": " 설정에서 "},
                        {"type": "ui_label", "text": "MCP"},
                        {"type": "text", "text": " 탭 열기"},
                    ]}
                ],
                "source_utterance_ids": ["UT-00002"],
                "prompt": None,
                "warning": None,
                "learn_more": [],
                "needs_review": False,
            },
            {
                "action_title": "모델을 Sonnet으로 바꿔요",
                "action_lines": [
                    {"source_utterance_ids": ["UT-00003"], "segments": [
                        {"type": "command", "text": "/model"},
                        {"type": "text", "text": " 입력 → "},
                        {"type": "ui_label", "text": "Sonnet"},
                        {"type": "text", "text": " 선택"},
                    ]}
                ],
                "source_utterance_ids": ["UT-00003"],
                "prompt": None,
                "warning": None,
                "learn_more": [],
                "needs_review": False,
            },
            {
                "action_title": "프로젝트 지침 파일을 만들어요",
                "action_lines": [
                    {"source_utterance_ids": ["UT-00004"], "segments": [
                        {"type": "filename", "text": "CLAUDE.md"},
                        {"type": "text", "text": " 파일 만들기"},
                    ]}
                ],
                "source_utterance_ids": ["UT-00004"],
                "prompt": None,
                "warning": None,
                "learn_more": [],
                "needs_review": False,
            },
            {
                "action_title": "실행하고 안전하게 결과를 확인해요",
                "action_lines": [
                    {"source_utterance_ids": ["UT-00005"], "segments": [{"type": "text", "text": "실행 버튼을 눌러 결과 확인"}]},
                    {"source_utterance_ids": ["UT-00007"], "segments": [
                        {"type": "filename", "text": ".env"},
                        {"type": "text", "text": " 파일에 API 키 저장"},
                    ]},
                ],
                "source_utterance_ids": ["UT-00005", "UT-00006", "UT-00007"],
                "prompt": {
                    "text": "컴포넌트를 구현해 줘",
                    "source_kind": "verbatim",
                    "source_utterance_ids": ["UT-00006"],
                },
                "warning": {
                    "title": "API 키를 코드에 넣지 마세요",
                    "body": "코드에 넣으면 비용이 발생할 수 있습니다.",
                    "source_utterance_ids": ["UT-00007"],
                },
                "learn_more": [
                    {
                        "question": "왜 Sonnet을 선택하나요?",
                        "body": "이 작업에 적절한 균형을 제공하기 때문입니다.",
                        "source_utterance_ids": ["UT-00008"],
                    }
                ],
                "needs_review": False,
            },
        ],
        "excluded_actions": [],
        "excluded_context_utterance_ids": [],
        "warnings": [],
    }


def _detail_response() -> dict:
    return {
        "recommendation": {
            "eyebrow": "추천해요",
            "title": "Cursor 설정을 직접 따라 해보고 싶은 분",
            "body": "MCP 설정부터 실행 결과 확인까지 따라갈 수 있어요.",
            "claims": [
                {
                    "text": "Cursor 설정을 직접 따라 해볼 수 있어요.",
                    "source_utterance_ids": ["UT-00002", "UT-00003"],
                },
                {
                    "text": "MCP 설정부터 실행 결과 확인까지 따라갈 수 있어요.",
                    "source_utterance_ids": ["UT-00002", "UT-00005"],
                },
            ],
        },
        "tools": [
            {
                "name": "Cursor",
                "canonical_name": "Cursor",
                "url": "https://cursor.com/",
                "description": "MCP 설정을 진행하는 도구입니다.",
                "source_utterance_ids": ["UT-00002"],
            }
        ],
        "tags": ["Cursor", "MCP", "환경 설정", "실행 검증"],
        "warnings": [],
    }


class FixtureGenerator:
    def __init__(self, *, no_actionable: bool = False, step_response: dict | None = None):
        self.calls: list[str] = []
        self.no_actionable = no_actionable
        self.step_response = step_response

    def __call__(self, _model: str, system: str, _user: str, _max_tokens: int) -> str:
        if "ddock_part_planning_v0.2" in system:
            self.calls.append("A")
            response = (
                {
                    "status": "no_actionable_content",
                    "content_chapter_assessments": [
                    ],
                    "parts": [],
                    "warnings": [],
                }
                if self.no_actionable
                else _part_response()
            )
        elif "ddock_step_generation_v0.2" in system:
            self.calls.append("B")
            response = self.step_response or _step_response()
        else:
            self.calls.append("C")
            response = _detail_response()
        return json.dumps(response, ensure_ascii=False)


class DdockContentCurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result, self.source = _fixture()
        self.generator = FixtureGenerator()
        self.package = curate_ddock_content(
            self.result,
            self.source,
            generator=self.generator,
            model_name="fixture-model",
        )

    def test_schema_and_three_pass_metrics(self) -> None:
        self.assertEqual(self.package["schema_version"], SCHEMA_VERSION)
        metrics = self.package["curation_generation"]
        self.assertEqual(metrics["part_planning_calls"], 1)
        self.assertEqual(metrics["step_generation_calls"], 1)
        self.assertEqual(metrics["video_detail_calls"], 1)
        self.assertEqual(metrics["total_model_calls"], 3)

    def test_four_script_chapters_are_not_four_parts(self) -> None:
        self.assertEqual(len(self.package["script_chapters"]), 4)
        self.assertEqual(len(self.package["catchup_parts"]), 1)

    def test_one_part_spans_two_script_chapters(self) -> None:
        part = self.package["catchup_parts"][0]
        self.assertEqual(part["source_script_chapter_ids"], ["CH-02", "CH-03"])

    def test_part_uses_only_actionable_subset_of_chapters(self) -> None:
        ids = self.package["catchup_parts"][0]["source_utterance_ids"]
        self.assertNotIn("UT-00001", ids)
        self.assertNotIn("UT-00009", ids)
        self.assertNotIn("UT-00010", ids)

    def test_pass_b_action_exclusion_preserves_part_context_ownership(self) -> None:
        response = copy.deepcopy(_step_response())
        response["steps"][-1]["source_utterance_ids"].remove("UT-00007")
        response["steps"][-1]["action_lines"].pop()
        response["excluded_actions"] = [
            {"utterance_id": "UT-00007", "reason": "covered only as caution context"}
        ]
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=FixtureGenerator(step_response=response),
            model_name="fixture-model",
        )
        part = package["catchup_parts"][0]
        self.assertIn("UT-00008", part["source_utterance_ids"])
        self.assertEqual(part["action_utterance_ids"], [f"UT-{value:05d}" for value in range(2, 8)])
        row = next(value for value in package["script"] if value["utterance_id"] == "UT-00008")
        self.assertEqual(row["catchup_part_ids"], ["PART-01"])
        self.assertIn(
            "pass_b:excluded_actions:1",
            part["generation_warnings"],
        )

    def test_one_part_has_four_steps(self) -> None:
        self.assertEqual(len(self.package["catchup_parts"]), 1)
        self.assertEqual(len(self.package["catchup_parts"][0]["steps"]), 4)

    def test_step_surface_has_at_most_four_lines(self) -> None:
        for step in self.package["catchup_parts"][0]["steps"]:
            self.assertGreaterEqual(len(step["action_lines"]), 1)
            self.assertLessEqual(len(step["action_lines"]), 4)

    def test_command_ui_and_filename_segments_are_preserved(self) -> None:
        steps = self.package["catchup_parts"][0]["steps"]
        types_and_text = [
            (segment["type"], segment["text"])
            for step in steps
            for line in step["action_lines"]
            for segment in line["segments"]
        ]
        self.assertIn(("command", "/model"), types_and_text)
        self.assertIn(("ui_label", "Sonnet"), types_and_text)
        self.assertIn(("filename", "CLAUDE.md"), types_and_text)

    def test_prompt_is_verbatim_and_evidenced(self) -> None:
        prompt = self.package["catchup_parts"][0]["steps"][3]["prompt"]
        self.assertEqual(prompt["text"], "컴포넌트를 구현해 줘")
        self.assertEqual(prompt["source_kind"], "verbatim")
        self.assertEqual(prompt["evidence"][0]["utterance_id"], "UT-00006")

    def test_steps_without_prompt_do_not_invent_one(self) -> None:
        steps = self.package["catchup_parts"][0]["steps"]
        self.assertTrue(all(step["prompt"] is None for step in steps[:3]))

    def test_warning_requires_source_evidence(self) -> None:
        warning = self.package["catchup_parts"][0]["steps"][3]["warning"]
        self.assertEqual(warning["evidence"][0]["utterance_id"], "UT-00007")

    def test_background_explanation_moves_to_learn_more(self) -> None:
        item = self.package["catchup_parts"][0]["steps"][3]["learn_more"][0]
        self.assertIn("왜", item["question"])
        self.assertEqual(item["evidence"][0]["utterance_id"], "UT-00008")

    def test_playback_uses_first_step_evidence_time(self) -> None:
        step = self.package["catchup_parts"][0]["steps"][1]
        self.assertEqual(step["playback_start_seconds"], 20.0)
        self.assertEqual(step["playback_end_seconds"], 28.0)

    def test_segment_script_target_is_parent_part(self) -> None:
        for step in self.package["catchup_parts"][0]["steps"]:
            self.assertEqual(step["parent_part_id"], "PART-01")

    def test_script_highlight_mapping_preserves_chapter_grouping(self) -> None:
        highlighted = [
            row["utterance_id"]
            for row in self.package["script"]
            if "PART-01" in row["catchup_part_ids"]
        ]
        self.assertEqual(highlighted, [f"UT-{value:05d}" for value in range(2, 9)])
        self.assertEqual(len(self.package["script_chapters"]), 4)

    def test_content_chapter_is_not_part(self) -> None:
        self.assertEqual(len(self.result["content_chapters"]), 5)
        self.assertEqual(len(self.package["catchup_parts"]), 1)

    def test_thumbnail_uses_unique_maximum_source_overlap(self) -> None:
        thumbnail = self.package["catchup_parts"][0]["thumbnail"]
        self.assertEqual(thumbnail["content_chapter_id"], "CCH-03")
        self.assertEqual(thumbnail["relative_path"], "CCH-03.jpg")

    def test_manual_normalized_text_is_used_without_raw_mutation(self) -> None:
        changed = copy.deepcopy(self.result)
        changed["normalized_utterances"][1]["normalized_text"] = "사람이 고친 최종 문장"
        raw_before = changed["normalized_utterances"][1]["raw_joined_text"]
        _, script = build_script_contract(changed)
        self.assertEqual(script[1]["text"], "사람이 고친 최종 문장")
        self.assertEqual(changed["normalized_utterances"][1]["raw_joined_text"], raw_before)

    def test_foreign_source_uses_same_contract_and_preserves_latin(self) -> None:
        foreign, source = _fixture(language="en")
        package = curate_ddock_content(
            foreign, source, generator=FixtureGenerator(), model_name="fixture-model"
        )
        self.assertEqual(package["source"]["source_language"], "en")
        self.assertIn("Cursor", json.dumps(package, ensure_ascii=False))

    def test_no_actionable_content_keeps_script_and_no_parts(self) -> None:
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=FixtureGenerator(no_actionable=True),
            model_name="fixture-model",
        )
        self.assertEqual(package["curation_generation"]["status"], "no_actionable_content")
        self.assertEqual(package["catchup_parts"], [])
        self.assertEqual(len(package["script"]), 10)
        self.assertEqual(package["curation_generation"]["total_model_calls"], 2)

    def test_preprocessed_result_is_deeply_immutable(self) -> None:
        before = copy.deepcopy(self.result)
        before_hash = hash_preprocessed_result(self.result)
        curate_ddock_content(
            self.result, self.source, generator=FixtureGenerator(), model_name="fixture-model"
        )
        self.assertEqual(self.result, before)
        self.assertEqual(hash_preprocessed_result(self.result), before_hash)

    def test_mvp_excluded_fields_are_absent(self) -> None:
        serialized = json.dumps(self.package)
        for field in ("logbook", "community_feed", "related_videos", "user_uploads"):
            self.assertNotIn(f'"{field}"', serialized)

    def test_validator_rejects_unknown_field(self) -> None:
        invalid = copy.deepcopy(self.package)
        invalid["orange"] = "#ff6600"
        report = validate_ddock_content(invalid)
        self.assertIn("package:unsupported_field:orange", report["errors"])

    def test_validator_rejects_five_action_lines(self) -> None:
        invalid = copy.deepcopy(self.package)
        invalid["catchup_parts"][0]["steps"][0]["action_lines"] *= 5
        report = validate_ddock_content(invalid)
        self.assertTrue(any("action_lines_must_have_1_to_4_items" in value for value in report["errors"]))

    def test_unsupported_command_rejects_part_generation(self) -> None:
        response = _step_response()
        response["steps"][0]["action_lines"] = [
            {
                "source_utterance_ids": ["UT-00002"],
                "segments": [{"type": "command", "text": "npm invented-command"}],
            }
        ]
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=FixtureGenerator(step_response=response),
            model_name="fixture-model",
        )
        self.assertEqual(package["curation_generation"]["status"], "completed_with_review")
        self.assertEqual(len(package["catchup_parts"][0]["steps"]), 3)
        self.assertNotIn("npm invented-command", json.dumps(package, ensure_ascii=False))
        self.assertTrue(any("unsupported_command_removed" in value for value in package["catchup_parts"][0]["generation_warnings"]))

    def test_invented_prompt_rejects_part_generation(self) -> None:
        response = _step_response()
        response["steps"][3]["prompt"]["text"] = "영상에 없는 완성 프롬프트"
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=FixtureGenerator(step_response=response),
            model_name="fixture-model",
        )
        self.assertEqual(package["catchup_parts"], [])
        self.assertTrue(any("not_verbatim_source" in value for value in package["curation_generation"]["warnings"]))

    def test_weakly_grounded_action_candidate_is_omitted(self) -> None:
        response = {
            "steps": [
                {
                    "action_title": "Figma 파일을 새로 배포해요",
                    "action_lines": [
                        {
                            "source_utterance_ids": ["UT-00002"],
                            "segments": [{"type": "text", "text": "Figma 파일을 배포합니다"}],
                        }
                    ],
                    "source_utterance_ids": ["UT-00002"],
                    "prompt": None,
                    "warning": None,
                    "learn_more": [],
                    "needs_review": False,
                }
            ],
            "excluded_actions": [
                {"utterance_id": f"UT-{value:05d}", "reason": "not used"}
                for value in range(3, 8)
            ],
            "excluded_context_utterance_ids": ["UT-00008"],
            "warnings": [],
        }
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=FixtureGenerator(step_response=response),
            model_name="fixture-model",
        )
        self.assertEqual(package["catchup_parts"], [])
        self.assertEqual(package["curation_generation"]["status"], "completed_with_review")
        self.assertTrue(any("at_least_one_step_required" in value for value in package["curation_generation"]["warnings"]))

    def test_atomic_writer_uses_title_based_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = write_ddock_content_atomic(
                temporary, self.result, self.package, self.source
            )
            self.assertEqual(path.name, OUTPUT_FILENAME)
            self.assertEqual(path.parent.name, "FULL")
            self.assertEqual(path.parent.parent.name, "테스트 튜토리얼 [video-a]")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.package)

    def test_invalid_package_is_not_published(self) -> None:
        invalid = copy.deepcopy(self.package)
        invalid["schema_version"] = "invalid"
        with tempfile.TemporaryDirectory() as temporary:
            expected = ddock_content_output_path(
                temporary, self.result, self.source
            )
            with self.assertRaises(ValueError):
                write_ddock_content_atomic(
                    temporary, self.result, invalid, self.source
                )
            self.assertFalse(expected.exists())

    def test_missing_engagement_counts_are_omitted(self) -> None:
        source = copy.deepcopy(self.source)
        source["metadata"].pop("view_count")
        source["metadata"].pop("like_count")
        package = curate_ddock_content(
            self.result, source, generator=FixtureGenerator(), model_name="fixture-model"
        )
        self.assertNotIn("view_count", package["source"])
        self.assertNotIn("like_count", package["source"])

    def test_surface_preview_marks_semantic_literals(self) -> None:
        preview = render_surface_preview(self.package)
        self.assertIn("[/model]", preview)
        self.assertIn("[Sonnet]", preview)
        self.assertIn("더 알아보기 1", preview)

    def test_one_part_generation_failure_preserves_other_part(self) -> None:
        def generator(_model: str, system: str, user: str, _max_tokens: int) -> str:
            if "ddock_part_planning_v0.2" in system:
                return json.dumps(_part_response(two_parts=True), ensure_ascii=False)
            if "ddock_video_detail_v0.2" in system:
                return json.dumps(_detail_response(), ensure_ascii=False)
            part_ids = json.loads(user)["part"]["source_utterance_ids"]
            if part_ids == ["UT-00002", "UT-00003", "UT-00004"]:
                raise RuntimeError("fixture isolated failure")
            response = _step_response()
            response["steps"] = [response["steps"][3]]
            return json.dumps(response, ensure_ascii=False)

        package = curate_ddock_content(
            self.result,
            self.source,
            generator=generator,
            model_name="fixture-model",
        )
        self.assertEqual(len(package["catchup_parts"]), 1)
        self.assertEqual(package["catchup_parts"][0]["part_id"], "PART-01")
        self.assertEqual(len(package["catchup_parts"][0]["steps"]), 1)
        self.assertEqual(package["curation_generation"]["status"], "completed_with_review")
        self.assertTrue(any("fixture isolated failure" in value for value in package["curation_generation"]["warnings"]))

    def test_concept_only_section_is_not_a_standalone_part(self) -> None:
        response = {
            "status": "completed",
            "content_chapter_assessments": [
                {
                    "content_chapter_id": "CCH-01",
                    "action_worthy": True,
                    "decision_reason": "incorrect concept classification",
                    "part_candidate": "concept",
                }
            ],
            "parts": [
                {
                    "title": "소개 개념을 알아봐요",
                    "summary": None,
                    "action_objective": "소개 개념을 이해한다",
                    "source_utterance_ids": ["UT-00001"],
                    "action_utterance_ids": ["UT-00001"],
                    "needs_review": False,
                }
            ],
            "warnings": [],
        }
        _, script = build_script_contract(self.result)
        _, plans, warnings = parse_part_planning_response(
            json.dumps(response, ensure_ascii=False),
            script,
            self.result["content_chapters"],
        )
        self.assertEqual(plans, [])
        self.assertTrue(any("concept_only_part_candidate_omitted" in value for value in warnings))

    def test_concept_explanation_adjacent_to_action_can_be_learn_more(self) -> None:
        part = self.package["catchup_parts"][0]
        self.assertIn("UT-00008", part["source_utterance_ids"])
        self.assertNotIn("UT-00008", part["action_utterance_ids"])
        self.assertEqual(
            part["steps"][-1]["learn_more"][0]["evidence"][0]["utterance_id"],
            "UT-00008",
        )

    def test_part_context_can_be_wider_than_action_source(self) -> None:
        part = self.package["catchup_parts"][0]
        self.assertGreater(len(part["source_utterance_ids"]), len(part["action_utterance_ids"]))

    def test_action_utterances_are_subset_of_part_context(self) -> None:
        part = self.package["catchup_parts"][0]
        self.assertTrue(set(part["action_utterance_ids"]).issubset(part["source_utterance_ids"]))

    def test_step_evidence_is_subset_of_part_action_source(self) -> None:
        part = self.package["catchup_parts"][0]
        allowed = set(part["action_utterance_ids"])
        self.assertTrue(all(set(step["source_utterance_ids"]).issubset(allowed) for step in part["steps"]))

    def test_learn_more_can_use_part_context_outside_step_evidence(self) -> None:
        step = self.package["catchup_parts"][0]["steps"][-1]
        learn_id = step["learn_more"][0]["evidence"][0]["utterance_id"]
        self.assertNotIn(learn_id, step["source_utterance_ids"])
        self.assertIn(learn_id, self.package["catchup_parts"][0]["source_utterance_ids"])

    def test_weak_initial_pass_b_failure_uses_one_targeted_retry(self) -> None:
        calls = {"b": 0}

        def generator(_model: str, system: str, _user: str, _max_tokens: int) -> str:
            if "ddock_part_planning_v0.2" in system:
                return json.dumps(_part_response(), ensure_ascii=False)
            if "ddock_video_detail_v0.2" in system:
                return json.dumps(_detail_response(), ensure_ascii=False)
            calls["b"] += 1
            if "TARGETED_REPAIR" not in system:
                return json.dumps({"steps": [], "excluded_actions": [], "excluded_context_utterance_ids": [], "warnings": []})
            return json.dumps(_step_response(), ensure_ascii=False)

        package = curate_ddock_content(self.result, self.source, generator=generator, model_name="fixture-model")
        self.assertEqual(calls["b"], 2)
        self.assertEqual(package["curation_generation"]["step_generation_retry_calls"], 1)
        self.assertEqual(len(package["catchup_parts"]), 1)

    def test_outside_allowed_source_is_repaired_when_context_is_valid(self) -> None:
        initial = _step_response()
        initial["steps"][-1]["learn_more"][0]["source_utterance_ids"] = ["UT-00010"]

        def generator(_model: str, system: str, _user: str, _max_tokens: int) -> str:
            if "ddock_part_planning_v0.2" in system:
                return json.dumps(_part_response(), ensure_ascii=False)
            if "ddock_video_detail_v0.2" in system:
                return json.dumps(_detail_response(), ensure_ascii=False)
            return json.dumps(_step_response() if "TARGETED_REPAIR" in system else initial, ensure_ascii=False)

        package = curate_ddock_content(self.result, self.source, generator=generator, model_name="fixture-model")
        self.assertEqual(len(package["catchup_parts"]), 1)
        self.assertEqual(package["curation_generation"]["step_generation_retry_calls"], 1)

    def test_source_backed_action_inside_part_context_is_promoted(self) -> None:
        part = copy.deepcopy(self.package["catchup_parts"][0])
        part["action_utterance_ids"].remove("UT-00004")
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        steps, _, warnings = parse_step_generation_response(
            json.dumps(_step_response(), ensure_ascii=False), part, rows
        )
        self.assertEqual(len(steps), 4)
        self.assertIn("UT-00004", part["action_utterance_ids"])
        self.assertTrue(any("source_backed_action_promoted:UT-00004" in value for value in warnings))

    def test_context_row_misclassified_as_excluded_action_is_ignored(self) -> None:
        response = _step_response()
        response["excluded_actions"] = [
            {"utterance_id": "UT-00008", "reason": "context only"}
        ]
        part = copy.deepcopy(self.package["catchup_parts"][0])
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        _, excluded, warnings = parse_step_generation_response(
            json.dumps(response, ensure_ascii=False), part, rows
        )
        self.assertEqual(excluded, [])
        self.assertTrue(any("context_only_exclusion_ignored:UT-00008" in value for value in warnings))

    def test_action_row_misclassified_as_excluded_context_is_filtered(self) -> None:
        response = _step_response()
        response["excluded_context_utterance_ids"] = ["UT-00002"]
        part = copy.deepcopy(self.package["catchup_parts"][0])
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        steps, _, warnings = parse_step_generation_response(
            json.dumps(response, ensure_ascii=False), part, rows
        )
        self.assertEqual(len(steps), 4)
        self.assertTrue(any("excluded_context_action_ids_ignored:UT-00002" in value for value in warnings))

    def test_verbatim_prompt_string_shorthand_is_normalized(self) -> None:
        response = _step_response()
        response["steps"][-1]["prompt"] = "컴포넌트를 구현해 줘"
        part = copy.deepcopy(self.package["catchup_parts"][0])
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        steps, _, warnings = parse_step_generation_response(
            json.dumps(response, ensure_ascii=False), part, rows
        )
        self.assertEqual(steps[-1]["prompt"]["text"], "컴포넌트를 구현해 줘")
        self.assertTrue(any("verbatim_string_normalized" in value for value in warnings))

    def test_exact_source_text_without_prompt_cue_is_not_exposed_as_prompt(self) -> None:
        response = _step_response()
        response["steps"][0]["prompt"] = "Cursor 설정에서 MCP 탭을 열어요."
        part = copy.deepcopy(self.package["catchup_parts"][0])
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        steps, _, warnings = parse_step_generation_response(
            json.dumps(response, ensure_ascii=False), part, rows
        )
        self.assertIsNone(steps[0]["prompt"])
        self.assertTrue(any("non_prompt_source_removed" in value for value in warnings))

    def test_concept_only_action_line_is_removed(self) -> None:
        response = _step_response()
        response["steps"] = [
            {
                "action_title": "Sonnet 선택 이유를 확인해요",
                "action_lines": [{
                    "source_utterance_ids": ["UT-00008"],
                    "segments": [{"type": "text", "text": "Sonnet 선택 이유를 확인해요"}],
                }],
                "source_utterance_ids": ["UT-00008"],
                "prompt": None,
                "warning": None,
                "learn_more": [],
                "needs_review": False,
            }
        ]
        part = copy.deepcopy(self.package["catchup_parts"][0])
        part["action_utterance_ids"].append("UT-00008")
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        with self.assertRaisesRegex(CurationResponseError, "at_least_one_step_required"):
            parse_step_generation_response(
                json.dumps(response, ensure_ascii=False), part, rows
            )

    def test_undersegmented_repair_result_is_retained_with_review_warning(self) -> None:
        ids = [f"UT-{value:05d}" for value in range(1, 14)]
        rows = {
            utterance_id: {
                "utterance_id": utterance_id,
                "start_seconds": float(index * 12),
                "end_seconds": float(index * 12 + 8),
                "text": "실행 버튼을 눌러 결과를 확인합니다.",
            }
            for index, utterance_id in enumerate(ids)
        }
        part = {"source_utterance_ids": ids, "action_utterance_ids": ids}
        response = {
            "steps": [{
                "action_title": "실행 버튼을 눌러 확인해요",
                "action_lines": [{
                    "source_utterance_ids": [ids[0]],
                    "segments": [{"type": "text", "text": "실행 버튼을 눌러 결과 확인"}],
                }],
                "source_utterance_ids": ids,
                "prompt": None,
                "warning": None,
                "learn_more": [],
                "needs_review": False,
            }],
            "excluded_actions": [],
            "excluded_context_utterance_ids": [],
            "warnings": [],
        }
        raw = json.dumps(response, ensure_ascii=False)
        with self.assertRaisesRegex(CurationResponseError, "undersegmented_long_part"):
            parse_step_generation_response(raw, copy.deepcopy(part), rows)
        steps, _, warnings = parse_step_generation_response(
            raw, copy.deepcopy(part), rows, allow_undersegmented=True
        )
        self.assertEqual(len(steps), 1)
        self.assertIn("undersegmented_long_part_retained_after_repair", warnings)

    def test_retry_failure_preserves_omitted_part_candidate(self) -> None:
        empty = {"steps": [], "excluded_actions": [], "excluded_context_utterance_ids": [], "warnings": []}
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=lambda _m, system, _u, _t: json.dumps(
                _part_response() if "ddock_part_planning_v0.2" in system
                else _detail_response() if "ddock_video_detail_v0.2" in system
                else empty,
                ensure_ascii=False,
            ),
            model_name="fixture-model",
        )
        self.assertEqual(package["catchup_parts"], [])
        self.assertEqual(len(package["curation_generation"]["omitted_part_candidates"]), 1)
        self.assertTrue(package["curation_generation"]["omitted_part_candidates"][0]["retry_attempted"])

    def test_candidate_failure_increments_needs_review(self) -> None:
        empty = {"steps": [], "excluded_actions": [], "excluded_context_utterance_ids": [], "warnings": []}
        package = curate_ddock_content(
            self.result,
            self.source,
            generator=lambda _m, system, _u, _t: json.dumps(
                _part_response() if "ddock_part_planning_v0.2" in system
                else _detail_response() if "ddock_video_detail_v0.2" in system
                else empty,
                ensure_ascii=False,
            ),
            model_name="fixture-model",
        )
        self.assertGreater(package["curation_generation"]["needs_review_count"], 0)
        self.assertEqual(package["curation_generation"]["status"], "completed_with_review")

    def test_one_removed_line_does_not_drop_multi_phase_part(self) -> None:
        response = _step_response()
        response["steps"][0]["action_lines"] = [
            {
                "source_utterance_ids": ["UT-00002"],
                "segments": [{"type": "text", "text": "근거에 없는 배포 작업 실행"}],
            }
        ]
        package = curate_ddock_content(
            self.result, self.source, generator=FixtureGenerator(step_response=response), model_name="fixture-model"
        )
        self.assertEqual(len(package["catchup_parts"]), 1)
        self.assertEqual(len(package["catchup_parts"][0]["steps"]), 3)

    def test_critical_middle_action_has_explicit_exclusion_reason(self) -> None:
        response = _step_response()
        response["steps"].pop(1)
        response["excluded_actions"] = [
            {"utterance_id": "UT-00003", "reason": "operation duplicated in the same panel"}
        ]
        package = curate_ddock_content(
            self.result, self.source, generator=FixtureGenerator(step_response=response), model_name="fixture-model"
        )
        excluded = package["catchup_parts"][0]["excluded_actions"]
        self.assertEqual(excluded[0]["utterance_id"], "UT-00003")
        self.assertTrue(excluded[0]["reason"])

    def test_final_normalized_text_has_precedence(self) -> None:
        row = _row(1, 1, "이전 normalized 문장")
        row["final_normalized_text"] = "최종 교정 문장"
        self.assertEqual(final_text_for_utterance(row), "최종 교정 문장")

    def test_human_confirmed_text_has_highest_precedence(self) -> None:
        row = _row(1, 1, "normalized")
        row["final_normalized_text"] = "automatic final"
        row["human_review"] = {"status": "corrected", "human_confirmed": True, "after": "사람이 확정한 문장"}
        self.assertEqual(final_text_for_utterance(row), "사람이 확정한 문장")

    def test_existing_asr_entity_correction_reaches_script(self) -> None:
        result, _ = _fixture()
        result["normalized_utterances"][1]["normalized_text"] = "Dev Mode를 열고 Figma를 확인해요."
        _, script = build_script_contract(result)
        self.assertEqual(script[1]["text"], "Dev Mode를 열고 Figma를 확인해요.")

    def test_recommendation_keeps_supported_claim_when_sibling_claim_is_weak(self) -> None:
        _, script = build_script_contract(self.result)
        response = _detail_response()
        response["recommendation"]["claims"].append(
            {"text": "매출이 열 배 늘어요.", "source_utterance_ids": ["UT-00002"]}
        )
        recommendation, _, _, warnings = parse_video_detail_response(
            json.dumps(response, ensure_ascii=False), script, self.source
        )
        self.assertIsNotNone(recommendation)
        self.assertEqual(len(recommendation["claims"]), 2)
        self.assertTrue(any("weakly_grounded_removed" in value for value in warnings))

    def test_no_recommendation_evidence_keeps_null(self) -> None:
        _, script = build_script_contract(self.result)
        response = _detail_response()
        response["recommendation"] = None
        recommendation, _, _, _ = parse_video_detail_response(
            json.dumps(response, ensure_ascii=False), script, self.source
        )
        self.assertIsNone(recommendation)

    def test_source_backed_canonical_tool_candidates_use_registry(self) -> None:
        _, script = build_script_contract(self.result)
        candidates = extract_source_backed_tool_candidates(script)
        self.assertIn("Cursor", [value["canonical_name"] for value in candidates])

    def test_unsupported_tool_is_not_added(self) -> None:
        _, script = build_script_contract(self.result)
        response = _detail_response()
        response["recommendation"] = None
        response["tools"][0].update({"name": "InventedTool", "canonical_name": "InventedTool"})
        _, tools, _, warnings = parse_video_detail_response(
            json.dumps(response, ensure_ascii=False), script, self.source
        )
        self.assertEqual(tools, [])
        self.assertTrue(any("unsupported_tool_literal" in value for value in warnings))

    def test_unsupported_tool_url_is_removed(self) -> None:
        _, script = build_script_contract(self.result)
        response = _detail_response()
        response["recommendation"] = None
        response["tools"][0]["url"] = "https://invented.example/"
        _, tools, _, warnings = parse_video_detail_response(
            json.dumps(response, ensure_ascii=False), script, self.source
        )
        self.assertIsNone(tools[0]["url"])
        self.assertTrue(any("unsupported_url_removed" in value for value in warnings))

    def test_repeated_fixture_keeps_major_part_structure(self) -> None:
        first = curate_ddock_content(self.result, self.source, generator=FixtureGenerator(), model_name="fixture-model")
        second = curate_ddock_content(self.result, self.source, generator=FixtureGenerator(), model_name="fixture-model")
        projection = lambda package: [
            (part["action_objective"], part["source_utterance_ids"], part["action_utterance_ids"], len(part["steps"]))
            for part in package["catchup_parts"]
        ]
        self.assertEqual(projection(first), projection(second))

    def test_runtime_has_no_g0_specific_hardcoding(self) -> None:
        source = Path(__file__).with_name("ddock_content_curation.py").read_text(encoding="utf-8")
        self.assertNotIn("G0d9CHLpnnc", source)

    def test_selected_screenshot_mapping_is_immutable(self) -> None:
        before = copy.deepcopy(self.result["content_chapter_assets"])
        curate_ddock_content(self.result, self.source, generator=FixtureGenerator(), model_name="fixture-model")
        self.assertEqual(self.result["content_chapter_assets"], before)

    def test_action_line_requires_own_evidence_ids(self) -> None:
        invalid = copy.deepcopy(self.package)
        invalid["catchup_parts"][0]["steps"][0]["action_lines"][0].pop("source_utterance_ids")
        report = validate_ddock_content(invalid)
        self.assertTrue(any("source_utterance_ids_required" in value for value in report["errors"]))

    def test_step_density_is_review_warning_not_forced_content(self) -> None:
        invalid = copy.deepcopy(self.package)
        invalid["catchup_parts"][0]["steps"] = invalid["catchup_parts"][0]["steps"][:2]
        report = validate_ddock_content(invalid)
        self.assertTrue(any("step_density_review" in value for value in report["warnings"]))

    def test_surface_why_leak_is_reported(self) -> None:
        invalid = copy.deepcopy(self.package)
        line = invalid["catchup_parts"][0]["steps"][0]["action_lines"][0]
        line["text"] += " 필요하기 때문이에요"
        line["segments"].append({"type": "text", "text": " 필요하기 때문이에요"})
        report = validate_ddock_content(invalid)
        self.assertTrue(any("surface_why_context" in value for value in report["warnings"]))

    def test_generation_metrics_separate_initial_and_retry_calls(self) -> None:
        metrics = self.package["curation_generation"]
        self.assertEqual(metrics["step_generation_initial_calls"], 1)
        self.assertEqual(metrics["step_generation_retry_calls"], 0)
        self.assertEqual(metrics["step_generation_calls"], 1)

    def test_strict_step_response_rejects_markdown_json(self) -> None:
        part = self.package["catchup_parts"][0]
        rows = {row["utterance_id"]: row for row in self.package["script"]}
        with self.assertRaises(CurationResponseError):
            parse_step_generation_response("```json\n{}\n```", part, rows)


if __name__ == "__main__":
    unittest.main()
