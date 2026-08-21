from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone
from typing import Any

from content_chapters import (
    CONTENT_CHAPTER_DECISION_CRITERIA,
    CONTENT_CHAPTER_SCHEMA_VERSION,
    _source_creator_chapter_ids,
    add_content_chapter_foundation,
    build_segmentation_payload,
    format_timestamp,
    validate_content_chapters,
)
from runtime_generation_metrics import generation_stage


ROLE_AUDIT_RESPONSE_SCHEMA_VERSION = "content_chapter_role_audit_response_v0.3"
ROLE_AUDIT_CONTRACT_VERSION = "v0.3"
ROLE_AUDIT_METHOD = "qwen3_section_learning_block_audit_v0.3"
TWO_STAGE_SEGMENTATION_METHOD = "qwen3_semantic_two_stage_v0.1"
ROLE_AUDIT_MAX_TOKENS = 4096
LOW_CONFIDENCE_REVIEW_THRESHOLD = 0.75
VERY_SHORT_EXCLUSION_MAX_UTTERANCES = 2

NON_LEARNING_ROLES = {
    "promotion",
    "giveaway",
    "broadcast_ops",
    "small_talk",
    "off_topic",
    "duplicate",
    "other_non_learning",
}
LEARNING_DECISION_FIELDS = {
    "has_learning_block",
    "has_non_learning_block",
    "confidence",
}
EXCLUDE_DECISION_FIELDS = LEARNING_DECISION_FIELDS | {"non_learning_role"}
SPLIT_DECISION_FIELDS = LEARNING_DECISION_FIELDS | {"transitions"}
LEARNING_TRANSITION_FIELDS = {"start_utterance_id", "class"}
NON_LEARNING_TRANSITION_FIELDS = LEARNING_TRANSITION_FIELDS | {"role"}
TOP_LEVEL_FIELDS = {"decisions"}

ROLE_AUDIT_RESPONSE_SCHEMA = {
    "type": "object",
    "required": sorted(TOP_LEVEL_FIELDS),
    "additionalProperties": False,
    "properties": {
        "decisions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": sorted(LEARNING_DECISION_FIELDS),
                        "additionalProperties": False,
                        "properties": {
                            "has_learning_block": {"const": True},
                            "has_non_learning_block": {"const": False},
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": sorted(EXCLUDE_DECISION_FIELDS),
                        "additionalProperties": False,
                        "properties": {
                            "has_learning_block": {"const": False},
                            "has_non_learning_block": {"const": True},
                            "non_learning_role": {
                                "type": "string",
                                "enum": sorted(NON_LEARNING_ROLES),
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": sorted(SPLIT_DECISION_FIELDS),
                        "additionalProperties": False,
                        "properties": {
                            "has_learning_block": {"const": True},
                            "has_non_learning_block": {"const": True},
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "transitions": {
                                "type": "array",
                                "minItems": 2,
                                "items": {
                                    "oneOf": [
                                        {
                                            "type": "object",
                                            "required": sorted(
                                                LEARNING_TRANSITION_FIELDS
                                            ),
                                            "additionalProperties": False,
                                            "properties": {
                                                "start_utterance_id": {
                                                    "type": "string"
                                                },
                                                "class": {"const": "learning"},
                                            },
                                        },
                                        {
                                            "type": "object",
                                            "required": sorted(
                                                NON_LEARNING_TRANSITION_FIELDS
                                            ),
                                            "additionalProperties": False,
                                            "properties": {
                                                "start_utterance_id": {
                                                    "type": "string"
                                                },
                                                "class": {
                                                    "const": "non_learning"
                                                },
                                                "role": {
                                                    "type": "string",
                                                    "enum": sorted(
                                                        NON_LEARNING_ROLES
                                                    ),
                                                },
                                            },
                                        },
                                    ]
                                },
                            },
                        },
                    },
                ]
            },
        },
    },
}


class RoleAuditContractError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _semantic_text(row: dict[str, Any]) -> str:
    for field in ("final_normalized_text", "normalized_text", "raw_joined_text"):
        text = str(row.get(field) or "").strip()
        if text:
            return text
    return ""


def _compact_value(value: Any) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("|", "\\|")
    )


def build_role_audit_candidates(
    result: dict[str, Any],
    pass_a_output: dict[str, Any],
    source_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source = build_segmentation_payload(result, source_data)
    utterances = source["utterances"]
    by_id = {row["utterance_id"]: row for row in utterances}
    positions = {
        row["utterance_id"]: index for index, row in enumerate(utterances)
    }
    ranges: list[dict[str, Any]] = []

    for chapter in pass_a_output.get("content_chapters") or []:
        if not isinstance(chapter, dict):
            continue
        ids = list(chapter.get("source_utterance_ids") or [])
        ranges.append(
            {
                "source_utterance_ids": ids,
                "pass_a_learning_metadata": {
                    "title": chapter.get("title"),
                    "summary": chapter.get("summary"),
                    "boundary_reason": chapter.get("boundary_reason"),
                    "needs_review": bool(chapter.get("needs_review")),
                },
            }
        )
    generation = pass_a_output.get("content_chapter_generation") or {}
    for excluded in generation.get("excluded_ranges") or []:
        if not isinstance(excluded, dict):
            continue
        ids = list(excluded.get("source_utterance_ids") or [])
        ranges.append(
            {
                "source_utterance_ids": ids,
                "pass_a_learning_metadata": None,
            }
        )

    errors: list[str] = []
    sortable: list[tuple[int, list[str], dict[str, Any] | None]] = []
    for index, item in enumerate(ranges):
        ids = [str(value) for value in item["source_utterance_ids"]]
        if not ids:
            errors.append(f"pass_a_candidate[{index}]:missing_source_utterance_ids")
            continue
        unknown = [utterance_id for utterance_id in ids if utterance_id not in positions]
        if unknown:
            errors.append(
                f"pass_a_candidate[{index}]:unknown_source_utterance_ids:"
                + ",".join(unknown)
            )
            continue
        start = positions[ids[0]]
        expected = [
            row["utterance_id"]
            for row in utterances[start : start + len(ids)]
        ]
        if ids != expected:
            errors.append(f"pass_a_candidate[{index}]:non_contiguous_ownership")
            continue
        sortable.append(
            (start, ids, copy.deepcopy(item["pass_a_learning_metadata"]))
        )

    sortable.sort(key=lambda item: item[0])
    owned_ids = [
        utterance_id for _, ids, _ in sortable for utterance_id in ids
    ]
    ordered_ids = [row["utterance_id"] for row in utterances]
    if owned_ids != ordered_ids:
        errors.append("pass_a_candidates_do_not_cover_source_exactly_once")
    if errors:
        raise RoleAuditContractError(errors)

    candidates: list[dict[str, Any]] = []
    for candidate_index, (_, ids, metadata) in enumerate(sortable):
        candidates.append(
            {
                "candidate_index": candidate_index,
                "start_utterance_id": ids[0],
                "end_utterance_id": ids[-1],
                "source_utterance_ids": ids,
                "utterances": [copy.deepcopy(by_id[utterance_id]) for utterance_id in ids],
                "pass_a_learning_metadata": metadata,
            }
        )
    return candidates


def _prompt_contract(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": ROLE_AUDIT_RESPONSE_SCHEMA_VERSION,
        "task": "section_level_learning_value_and_role_audit",
        "candidate_count": len(candidates),
        "decision_position_rule": (
            "decisions[i] applies to input candidate block i; return exactly "
            f"{len(candidates)} decisions in the same order"
        ),
        "rules": [
            "Return exactly one positional decision for every candidate block, without candidate_index or warnings.",
            "Candidate input contains only deterministic boundaries and actual normalized text, never a provisional role, title, or summary.",
            "Step 1: independently check whether the candidate contains at least one substantial continuous learning block that a user would save, revisit, or apply later.",
            "Step 2: independently check whether the candidate contains at least one substantial continuous non-learning block without independent learning value.",
            "Step 3: if both blocks exist, return both booleans true and find every substantial learning/non-learning transition boundary.",
            "Step 4: if only one block class exists, return the corresponding true/false presence flags for the whole candidate.",
            "Never decide by majority length or primary purpose before checking both block types; a long ending cannot erase a substantial earlier learning workflow, and a long learning block cannot absorb a substantial giveaway or closing.",
            "Learning includes executable workflows, tool use or setup, context or reference preparation, agent or team design, problem solving, trial and improvement, comparisons and judgments, reusable explanations, image or video or web result creation, and deployment workflows.",
            "A substantial block is semantic and continuous, not defined by a fixed time or utterance-count threshold.",
            "Use promotion for a continuing book, course, service, sponsor, or channel promotion, or a like, subscription, review, or application request.",
            "Use giveaway for drawings, prizes, winner notices, and giveaway application instructions; use broadcast_ops for microphone, audio, stream status, absence, or broadcast management.",
            "Use small_talk for sustained unrelated casual talk, off_topic for a sustained unrelated topic, duplicate for substantive repetition, and other_non_learning for another continuing block without independent learning value.",
            "If learning and non-learning both exist, transitions[0] must start at candidate START and every transition must use a candidate-local utterance ID in strictly increasing order.",
            "Transition classes must alternate. Use class=learning without role, or class=non_learning with exactly one allowed role.",
            "For a learning workflow followed by giveaway or closing, preserve the learning start and add the actual non-learning transition; for promotion followed by practical work, preserve the promotion start and add the learning transition.",
            "Do not split for brief jokes, reactions, thanks, viewer replies, waits, exclamations, or one UI click inside a learning workflow.",
            "Do not split promotion from giveaway when no substantial learning block exists; return one non-learning-only decision with a representative role.",
            "Do not merge candidates and do not target any fixed number of learning sections, exclusions, or transitions.",
            "Return no title, summary, boundary_reason, needs_review, end ID, timestamp, seconds, duration, kind, reason, or candidate_index anywhere.",
            "Return no mode. Return only the two presence booleans, confidence, conditional non_learning_role, and conditional transition start/class/role fields permitted by the schema.",
        ],
        "response_schema": copy.deepcopy(ROLE_AUDIT_RESPONSE_SCHEMA),
    }


def build_role_audit_prompts(
    candidates: list[dict[str, Any]],
) -> tuple[str, str]:
    contract = _prompt_contract(candidates)
    blocks: list[str] = []
    for candidate in candidates:
        candidate_index = candidate["candidate_index"]
        blocks.extend(
            (
                f"[CANDIDATE {candidate_index}]",
                f"START={candidate['start_utterance_id']}",
                f"END={candidate['end_utterance_id']}",
                "",
            )
        )
        blocks.extend(
            "%s | %s"
            % (
                _compact_value(row["utterance_id"]),
                _compact_value(_semantic_text(row)),
            )
            for row in candidate["utterances"]
        )
        blocks.append(f"[END CANDIDATE {candidate_index}]")

    system_prompt = (
        "Audit every candidate for substantial continuous learning and non-learning blocks "
        "independently. Never use majority length or overall primary purpose to erase either "
        "kind of substantial block. When both exist, return alternating candidate-local "
        "learning/non_learning transitions; when only one exists, keep the whole candidate "
        "in that class. Brief filler is not a separate block, and non-learning role changes "
        "need no split without learning between them. Return exactly one positional decision "
        "per candidate in the same order and one strict JSON object matching the schema. "
        "Never return mode, prose metadata, warnings, candidate indexes, end IDs, timestamps, "
        "or review flags."
    )
    user_prompt = (
        "ROLE_AUDIT_CONTRACT\n"
        + json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\nCANDIDATES_BEGIN\n"
        + "\n".join(blocks)
        + "\nCANDIDATES_END"
    )
    return system_prompt, user_prompt


def _json_object(raw_text: str) -> dict[str, Any]:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise RoleAuditContractError(["response_text_is_empty"])
    text = raw_text.strip()
    if "```" in text:
        raise RoleAuditContractError(["markdown_fence_is_forbidden"])
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RoleAuditContractError(
            [f"response_must_be_one_exact_json_object:{exc.msg}"]
        ) from exc
    if not isinstance(payload, dict):
        raise RoleAuditContractError(["response_root_must_be_an_object"])
    return payload


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0.0 <= float(value) <= 1.0
    )


def _derived_mode(decision: dict[str, Any]) -> str | None:
    has_learning = decision.get("has_learning_block")
    has_non_learning = decision.get("has_non_learning_block")
    if has_learning is True and has_non_learning is False:
        return "learning"
    if has_learning is False and has_non_learning is True:
        return "exclude"
    if has_learning is True and has_non_learning is True:
        return "split"
    return None


def parse_role_audit_response(
    raw_text: str,
    expected_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = _json_object(raw_text)
    errors: list[str] = []
    missing_top = sorted(TOP_LEVEL_FIELDS - set(payload))
    unknown_top = sorted(set(payload) - TOP_LEVEL_FIELDS)
    if missing_top:
        errors.append("missing_top_level_fields:" + ",".join(missing_top))
    if unknown_top:
        errors.append("unknown_top_level_fields:" + ",".join(unknown_top))

    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        errors.append("decisions_must_be_a_list")
        decisions = []
    elif not decisions:
        errors.append("decisions_must_not_be_empty")
    if expected_candidates is not None and len(decisions) != len(
        expected_candidates
    ):
        errors.append(
            "decision_count_must_equal_candidate_count:"
            f"expected={len(expected_candidates)}:actual={len(decisions)}"
        )

    for decision_index, decision in enumerate(decisions):
        prefix = f"decisions[{decision_index}]"
        if not isinstance(decision, dict):
            errors.append(f"{prefix}:must_be_an_object")
            continue
        has_learning = decision.get("has_learning_block")
        has_non_learning = decision.get("has_non_learning_block")
        if not isinstance(has_learning, bool):
            errors.append(f"{prefix}:has_learning_block_must_be_boolean")
        if not isinstance(has_non_learning, bool):
            errors.append(f"{prefix}:has_non_learning_block_must_be_boolean")
        mode = _derived_mode(decision)
        if mode == "learning":
            required = LEARNING_DECISION_FIELDS
            allowed = LEARNING_DECISION_FIELDS
        elif mode == "exclude":
            required = EXCLUDE_DECISION_FIELDS
            allowed = EXCLUDE_DECISION_FIELDS
        elif mode == "split":
            required = SPLIT_DECISION_FIELDS
            allowed = SPLIT_DECISION_FIELDS
        else:
            required = LEARNING_DECISION_FIELDS
            allowed = (
                LEARNING_DECISION_FIELDS
                | EXCLUDE_DECISION_FIELDS
                | SPLIT_DECISION_FIELDS
            )
            if has_learning is False and has_non_learning is False:
                errors.append(f"{prefix}:both_presence_flags_cannot_be_false")
        keys = set(decision)
        missing = sorted(required - keys)
        unknown = sorted(keys - allowed)
        if missing:
            errors.append(f"{prefix}:missing_fields:" + ",".join(missing))
        if unknown:
            errors.append(f"{prefix}:unknown_fields:" + ",".join(unknown))
        if "confidence" in decision and not _is_confidence(
            decision["confidence"]
        ):
            errors.append(f"{prefix}:confidence_must_be_between_0_and_1")
        if (
            mode == "exclude"
            and decision.get("non_learning_role") not in NON_LEARNING_ROLES
        ):
            errors.append(f"{prefix}:non_learning_role_must_be_allowed")
        if mode != "split":
            continue
        transitions = decision.get("transitions")
        if not isinstance(transitions, list):
            errors.append(f"{prefix}:transitions_must_be_a_list")
            continue
        if not transitions:
            errors.append(f"{prefix}:transitions_must_not_be_empty")
        candidate = (
            expected_candidates[decision_index]
            if expected_candidates is not None
            and decision_index < len(expected_candidates)
            else None
        )
        candidate_ids = (
            candidate["source_utterance_ids"] if candidate is not None else []
        )
        positions = {
            utterance_id: index
            for index, utterance_id in enumerate(candidate_ids)
        }
        seen: set[str] = set()
        previous_position: int | None = None
        previous_class: str | None = None
        transition_classes: set[str] = set()
        for transition_index, transition in enumerate(transitions):
            subprefix = f"{prefix}.transitions[{transition_index}]"
            if not isinstance(transition, dict):
                errors.append(f"{subprefix}:must_be_an_object")
                continue
            transition_class = transition.get("class")
            if transition_class == "learning":
                required_transition = LEARNING_TRANSITION_FIELDS
                allowed_transition = LEARNING_TRANSITION_FIELDS
            elif transition_class == "non_learning":
                required_transition = NON_LEARNING_TRANSITION_FIELDS
                allowed_transition = NON_LEARNING_TRANSITION_FIELDS
            else:
                required_transition = LEARNING_TRANSITION_FIELDS
                allowed_transition = NON_LEARNING_TRANSITION_FIELDS
                errors.append(f"{subprefix}:unsupported_class")
            transition_keys = set(transition)
            missing_transition = sorted(required_transition - transition_keys)
            unknown_transition = sorted(transition_keys - allowed_transition)
            if missing_transition:
                errors.append(
                    f"{subprefix}:missing_fields:"
                    + ",".join(missing_transition)
                )
            if unknown_transition:
                errors.append(
                    f"{subprefix}:unknown_fields:"
                    + ",".join(unknown_transition)
                )
            start_id = transition.get("start_utterance_id")
            if not _nonempty_string(start_id):
                errors.append(
                    f"{subprefix}:start_utterance_id_must_be_a_nonempty_string"
                )
                continue
            if transition_class == "non_learning":
                if transition.get("role") not in NON_LEARNING_ROLES:
                    errors.append(f"{subprefix}:non_learning_role_must_be_allowed")
            elif transition_class == "learning" and "role" in transition:
                errors.append(f"{subprefix}:learning_transition_forbids_role")
            if transition_class in {"learning", "non_learning"}:
                transition_classes.add(transition_class)
                if transition_class == previous_class:
                    errors.append(f"{subprefix}:consecutive_classes_must_alternate")
                previous_class = transition_class
            if start_id in seen:
                errors.append(f"{subprefix}:duplicate_start_utterance_id:{start_id}")
            seen.add(start_id)
            if candidate is None:
                continue
            if start_id not in positions:
                errors.append(f"{subprefix}:start_outside_candidate:{start_id}")
                continue
            position = positions[start_id]
            if transition_index == 0 and start_id != candidate["start_utterance_id"]:
                errors.append(
                    f"{prefix}:first_transition_must_start_at_candidate_start:"
                    + candidate["start_utterance_id"]
                )
            if previous_position is not None and position <= previous_position:
                errors.append(f"{subprefix}:starts_not_strictly_increasing")
            previous_position = position
        if transition_classes != {"learning", "non_learning"}:
            errors.append(
                f"{prefix}:mixed_transitions_must_cover_both_classes"
            )

    if errors:
        raise RoleAuditContractError(errors)
    return copy.deepcopy(payload)


def validate_role_audit_response(
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    decisions = payload.get("decisions") or []
    if len(decisions) != len(candidates):
        return [
            "decision_count_must_equal_candidate_count:"
            f"expected={len(candidates)}:actual={len(decisions)}"
        ]
    for decision_index, candidate in enumerate(candidates):
        prefix = f"decisions[{decision_index}]"
        decision = decisions[decision_index]
        if not isinstance(decision, dict):
            errors.append(f"{prefix}:must_be_an_object")
            continue
        mode = _derived_mode(decision)
        if mode is None:
            errors.append(f"{prefix}:invalid_presence_flag_combination")
            continue
        if not _is_confidence(decision.get("confidence")):
            errors.append(f"{prefix}:invalid_confidence")
        if (
            mode == "exclude"
            and decision.get("non_learning_role") not in NON_LEARNING_ROLES
        ):
            errors.append(f"{prefix}:non_learning_role_must_be_allowed")
        if mode == "split":
            transitions = decision.get("transitions") or []
            if len(transitions) < 2:
                errors.append(f"{prefix}:mixed_transitions_must_have_at_least_two_items")
                continue
        else:
            transitions = [
                {
                    "start_utterance_id": candidate["start_utterance_id"],
                    "class": "learning" if mode == "learning" else "non_learning",
                    **(
                        {}
                        if mode == "learning"
                        else {"role": decision.get("non_learning_role")}
                    ),
                }
            ]
        candidate_ids = candidate["source_utterance_ids"]
        positions = {
            utterance_id: index for index, utterance_id in enumerate(candidate_ids)
        }
        seen: set[str] = set()
        previous_position: int | None = None
        previous_class: str | None = None
        transition_classes: set[str] = set()
        boundary_errors = False
        for transition_index, transition in enumerate(transitions):
            subprefix = f"{prefix}.transitions[{transition_index}]"
            if not isinstance(transition, dict):
                errors.append(f"{subprefix}:must_be_an_object")
                boundary_errors = True
                continue
            start_id = transition.get("start_utterance_id")
            if start_id in seen:
                errors.append(f"{subprefix}:duplicate_start_utterance_id:{start_id}")
                boundary_errors = True
            seen.add(start_id)
            if start_id not in positions:
                errors.append(f"{subprefix}:start_outside_candidate:{start_id}")
                boundary_errors = True
                continue
            position = positions[start_id]
            if transition_index == 0 and start_id != candidate["start_utterance_id"]:
                errors.append(
                    f"{prefix}:first_transition_must_start_at_candidate_start:"
                    + candidate["start_utterance_id"]
                )
                boundary_errors = True
            if previous_position is not None and position <= previous_position:
                errors.append(f"{subprefix}:starts_not_strictly_increasing")
                boundary_errors = True
            previous_position = position
            transition_class = transition.get("class")
            if transition_class not in {"learning", "non_learning"}:
                errors.append(f"{subprefix}:unsupported_class")
                boundary_errors = True
                continue
            if transition_class == previous_class:
                errors.append(f"{subprefix}:consecutive_classes_must_alternate")
                boundary_errors = True
            previous_class = transition_class
            transition_classes.add(transition_class)
            if transition_class == "learning" and "role" in transition:
                errors.append(f"{subprefix}:learning_transition_forbids_role")
                boundary_errors = True
            if (
                transition_class == "non_learning"
                and transition.get("role") not in NON_LEARNING_ROLES
            ):
                errors.append(f"{subprefix}:non_learning_role_must_be_allowed")
                boundary_errors = True

        if mode == "split" and transition_classes != {"learning", "non_learning"}:
            errors.append(f"{prefix}:mixed_transitions_must_cover_both_classes")
            boundary_errors = True

        if not boundary_errors and transitions:
            owned: list[str] = []
            for transition_index, transition in enumerate(transitions):
                start = positions[transition["start_utterance_id"]]
                end = (
                    positions[transitions[transition_index + 1]["start_utterance_id"]]
                    if transition_index + 1 < len(transitions)
                    else len(candidate_ids)
                )
                owned.extend(candidate_ids[start:end])
            if owned != candidate_ids:
                errors.append(f"{prefix}:candidate_coverage_not_exactly_once")
    return errors


def _materialized_subsections(
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    materialized: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = payload["decisions"][candidate["candidate_index"]]
        mode = _derived_mode(decision)
        if mode == "learning":
            transitions = [
                {
                    "start_utterance_id": candidate["start_utterance_id"],
                    "class": "learning",
                }
            ]
        elif mode == "exclude":
            transitions = [
                {
                    "start_utterance_id": candidate["start_utterance_id"],
                    "class": "non_learning",
                    "role": decision["non_learning_role"],
                }
            ]
        else:
            transitions = decision["transitions"]
        ids = candidate["source_utterance_ids"]
        positions = {utterance_id: index for index, utterance_id in enumerate(ids)}
        by_id = {
            row["utterance_id"]: row for row in candidate["utterances"]
        }
        learning_transition_count = sum(
            transition["class"] == "learning" for transition in transitions
        )
        for subsection_index, transition in enumerate(transitions):
            start = positions[transition["start_utterance_id"]]
            end = (
                positions[transitions[subsection_index + 1]["start_utterance_id"]]
                if subsection_index + 1 < len(transitions)
                else len(ids)
            )
            selected_ids = ids[start:end]
            role = (
                "learning"
                if transition["class"] == "learning"
                else transition["role"]
            )
            materialized.append(
                {
                    "candidate_index": candidate["candidate_index"],
                    "subsection_index": subsection_index,
                    "mode": mode,
                    "role": role,
                    "confidence": float(decision["confidence"]),
                    "pass_a_learning_metadata": copy.deepcopy(
                        candidate.get("pass_a_learning_metadata")
                    ),
                    "learning_metadata_requires_review": (
                        role == "learning"
                        and mode == "split"
                        and (
                            transition["start_utterance_id"]
                            != candidate["start_utterance_id"]
                            or learning_transition_count > 1
                        )
                    ),
                    "source_utterance_ids": selected_ids,
                    "utterances": [by_id[utterance_id] for utterance_id in selected_ids],
                }
            )
    return materialized


def _fragmentation_diagnostics(
    materialized: list[dict[str, Any]],
    total_utterances: int,
) -> dict[str, Any]:
    exclusions = [
        item
        for item in materialized
        if item["role"] in NON_LEARNING_ROLES
    ]
    exclusion_utterances = sum(
        len(item["source_utterance_ids"]) for item in exclusions
    )
    very_short = sum(
        len(item["source_utterance_ids"])
        <= VERY_SHORT_EXCLUSION_MAX_UTTERANCES
        for item in exclusions
    )
    return {
        "exclusion_section_count": len(exclusions),
        "exclusion_utterance_count": exclusion_utterances,
        "exclusion_ratio": (
            exclusion_utterances / total_utterances if total_utterances else 0.0
        ),
        "very_short_exclusion_section_count": very_short,
        "very_short_exclusion_max_utterances_candidate": (
            VERY_SHORT_EXCLUSION_MAX_UTTERANCES
        ),
        "exclusion_fragmentation_warning": very_short > 1,
        "diagnostic_only_no_rejection_threshold": True,
    }


def _coverage_errors(output: dict[str, Any], expected_ids: list[str]) -> list[str]:
    owned: list[str] = []
    for chapter in output.get("content_chapters") or []:
        owned.extend(chapter.get("source_utterance_ids") or [])
    generation = output.get("content_chapter_generation") or {}
    for excluded in generation.get("excluded_ranges") or []:
        owned.extend(excluded.get("source_utterance_ids") or [])
    errors: list[str] = []
    if set(owned) != set(expected_ids) or len(owned) != len(expected_ids):
        errors.append("role_audit_source_coverage_mismatch")
    if len(owned) != len(set(owned)):
        errors.append("role_audit_duplicate_ownership")
    return errors


def _materialize_role_audit(
    result: dict[str, Any],
    pass_a_output: dict[str, Any],
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
    source_data: dict[str, Any] | None,
    *,
    created_at: str | None,
) -> dict[str, Any]:
    source = build_segmentation_payload(result, source_data)
    materialized = _materialized_subsections(payload, candidates)
    chapters: list[dict[str, Any]] = []
    excluded_ranges: list[dict[str, Any]] = []
    excluded_ids: list[str] = []
    metadata_warnings: list[str] = []

    for item in materialized:
        rows = item["utterances"]
        ids = item["source_utterance_ids"]
        start = rows[0]["start_seconds"]
        end = rows[-1]["end_seconds"]
        common = {
            "start_utterance_id": ids[0],
            "end_utterance_id": ids[-1],
            "start_seconds": start,
            "end_seconds": end,
            "start_timestamp": format_timestamp(start),
            "end_timestamp": format_timestamp(end),
            "source_utterance_ids": ids,
            "utterance_count": len(ids),
            "role_audit_candidate_index": item["candidate_index"],
            "role_audit_subsection_index": item["subsection_index"],
        }
        confidence_needs_review = (
            item["confidence"] < LOW_CONFIDENCE_REVIEW_THRESHOLD
        )
        if item["role"] in NON_LEARNING_ROLES:
            excluded_ids.extend(ids)
            excluded_ranges.append(
                {
                    **common,
                    "reason": item["role"],
                    "confidence": item["confidence"],
                    "needs_review": confidence_needs_review,
                }
            )
            continue

        chapter_index = len(chapters)
        metadata = item.get("pass_a_learning_metadata") or {}
        metadata_complete = all(
            _nonempty_string(metadata.get(field))
            for field in ("title", "summary", "boundary_reason")
        )
        inherited_after_split = item["learning_metadata_requires_review"]
        if inherited_after_split:
            metadata_warnings.append(
                "learning_metadata_inherited_after_role_split:"
                f"candidate[{item['candidate_index']}].subsection[{item['subsection_index']}]"
            )
        if not metadata_complete:
            metadata_warnings.append(
                "pass_a_learning_metadata_unavailable_after_role_audit:"
                f"candidate[{item['candidate_index']}].subsection[{item['subsection_index']}]"
            )
        title = (
            metadata["title"]
            if metadata_complete
            else "학습 구간 · 메타데이터 검토 필요"
        )
        summary = (
            metadata["summary"]
            if metadata_complete
            else "PASS A 학습 메타데이터가 없어 원문 범위를 보존한 검토용 구간입니다."
        )
        boundary_reason = (
            metadata["boundary_reason"]
            if metadata_complete
            else "pass_a_learning_metadata_unavailable"
        )
        chapters.append(
            {
                **common,
                "content_chapter_id": f"CCH-{chapter_index + 1:02d}",
                "chapter_index": chapter_index,
                "title": title,
                "summary": summary,
                "source_creator_chapter_ids": _source_creator_chapter_ids(
                    rows,
                    source["creator_chapter_hints"],
                    start,
                    end,
                ),
                "boundary_reason": boundary_reason,
                "confidence": item["confidence"],
                "needs_review": bool(
                    confidence_needs_review
                    or metadata.get("needs_review")
                    or inherited_after_split
                    or not metadata_complete
                ),
            }
        )

    fragmentation = _fragmentation_diagnostics(
        materialized,
        len(source["utterances"]),
    )
    materialized_outputs = [*chapters, *excluded_ranges]
    confidences = [float(item["confidence"]) for item in materialized_outputs]
    quality = {
        "learning_section_count": len(chapters),
        "non_learning_section_count": len(excluded_ranges),
        "needs_review_section_count": sum(
            bool(item["needs_review"]) for item in materialized_outputs
        ),
        "average_confidence": (
            sum(confidences) / len(confidences) if confidences else 0.0
        ),
        "min_confidence": min(confidences, default=0.0),
        "quality_metrics_diagnostic_only": True,
    }
    warnings = list(dict.fromkeys(metadata_warnings))
    if excluded_ranges:
        warnings.append("excluded_ranges_require_human_review")
    if fragmentation["exclusion_fragmentation_warning"]:
        warnings.append("exclusion_fragmentation_warning")
    pass_a_generation = pass_a_output.get("content_chapter_generation") or {}
    needs_review = bool(
        warnings or any(item["needs_review"] for item in materialized_outputs)
    )

    output = copy.deepcopy(result)
    output["content_chapters"] = chapters
    output["content_chapter_generation"] = {
        "schema_version": CONTENT_CHAPTER_SCHEMA_VERSION,
        "segmentation_response_schema_version": pass_a_generation.get(
            "segmentation_response_schema_version"
        ),
        "semantic_segmentation_contract_version": pass_a_generation.get(
            "semantic_segmentation_contract_version"
        ),
        "role_audit_response_schema_version": ROLE_AUDIT_RESPONSE_SCHEMA_VERSION,
        "role_audit_contract_version": ROLE_AUDIT_CONTRACT_VERSION,
        "status": "needs_review" if needs_review else "completed",
        "method": TWO_STAGE_SEGMENTATION_METHOD,
        "role_audit_method": ROLE_AUDIT_METHOD,
        "source_scope": source["source_scope"],
        "scope_evidence": copy.deepcopy(source["scope_evidence"]),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "semantic_split_applied": True,
        "llm_invoked": True,
        "decision_criteria": list(CONTENT_CHAPTER_DECISION_CRITERIA),
        "pass_a_candidate_count": len(candidates),
        "pass_a_provisional_roles_used_for_final": False,
        "pass_a_provenance": {
            "method": pass_a_generation.get("method"),
            "segmentation_response_schema_version": pass_a_generation.get(
                "segmentation_response_schema_version"
            ),
            "semantic_segmentation_contract_version": pass_a_generation.get(
                "semantic_segmentation_contract_version"
            ),
            "materialized_section_count": pass_a_generation.get(
                "materialized_section_count"
            ),
            "generation_call_count": pass_a_generation.get(
                "generation_call_count"
            ),
            "prompt_character_count": pass_a_generation.get(
                "prompt_character_count"
            ),
            "response_character_count": pass_a_generation.get(
                "response_character_count"
            ),
            "generation_duration_seconds": pass_a_generation.get(
                "generation_duration_seconds"
            ),
        },
        "prompt_character_count": pass_a_generation.get(
            "prompt_character_count", 0
        ),
        "response_character_count": pass_a_generation.get(
            "response_character_count", 0
        ),
        "generation_duration_seconds": pass_a_generation.get(
            "generation_duration_seconds", 0.0
        ),
        "excluded_utterance_ids": excluded_ids,
        "excluded_ranges": excluded_ranges,
        "materialized_section_count": len(materialized),
        "materialized_utterance_count": len(source["utterances"]),
        **fragmentation,
        **quality,
        "segmentation_attempt_status": "accepted",
        "parsing_status": "passed",
        "validation_status": "passed",
        "role_audit_attempt_status": "accepted",
        "role_audit_parsing_status": "passed",
        "role_audit_validation_status": "passed",
        "role_audit_fallback_used": False,
        "fallback_used": False,
        "fallback_reason": None,
    }
    return output


def _role_audit_fallback(
    result: dict[str, Any],
    pass_a_output: dict[str, Any],
    source_data: dict[str, Any] | None,
    errors: list[str],
    *,
    fallback_reason: str,
    parsing_status: str,
    validation_status: str,
    audit_invoked: bool,
) -> dict[str, Any]:
    clean = copy.deepcopy(result)
    clean.pop("content_chapters", None)
    clean.pop("content_chapter_generation", None)
    fallback = add_content_chapter_foundation(clean, source_data)
    generation = fallback["content_chapter_generation"]
    pass_a_generation = pass_a_output.get("content_chapter_generation") or {}
    generation.update(
        {
            "segmentation_response_schema_version": pass_a_generation.get(
                "segmentation_response_schema_version"
            ),
            "semantic_segmentation_contract_version": pass_a_generation.get(
                "semantic_segmentation_contract_version"
            ),
            "role_audit_response_schema_version": ROLE_AUDIT_RESPONSE_SCHEMA_VERSION,
            "role_audit_contract_version": ROLE_AUDIT_CONTRACT_VERSION,
            "semantic_split_applied": False,
            "llm_invoked": True,
            "pass_a_candidate_count": pass_a_generation.get(
                "materialized_section_count"
            ),
            "pass_a_provisional_roles_used_for_final": False,
            "role_audit_method": ROLE_AUDIT_METHOD,
            "role_audit_attempt_status": "rejected",
            "role_audit_parsing_status": parsing_status,
            "role_audit_validation_status": validation_status,
            "role_audit_fallback_used": True,
            "fallback_used": True,
            "fallback_reason": fallback_reason,
            "generation_call_count": int(
                pass_a_generation.get("generation_call_count") or 1
            )
            + int(audit_invoked),
            "role_audit_generation_call_count": int(audit_invoked),
            "prompt_character_count": pass_a_generation.get(
                "prompt_character_count", 0
            ),
            "response_character_count": pass_a_generation.get(
                "response_character_count", 0
            ),
            "generation_duration_seconds": pass_a_generation.get(
                "generation_duration_seconds", 0.0
            ),
        }
    )
    generation.setdefault("warnings", []).extend(
        f"semantic_role_audit_rejected:{error}" for error in errors
    )
    generation["warning"] = generation["warnings"][0]
    return fallback


def apply_role_audit_response_atomically(
    result: dict[str, Any],
    pass_a_output: dict[str, Any],
    raw_text: str,
    source_data: dict[str, Any] | None = None,
    *,
    candidates: list[dict[str, Any]] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    try:
        expected = candidates or build_role_audit_candidates(
            result, pass_a_output, source_data
        )
    except RoleAuditContractError as exc:
        return _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            exc.errors,
            fallback_reason="content_chapter_role_audit_candidate_construction_failed",
            parsing_status="not_run",
            validation_status="not_run",
            audit_invoked=False,
        )
    try:
        payload = parse_role_audit_response(raw_text, expected)
    except RoleAuditContractError as exc:
        return _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            exc.errors,
            fallback_reason="content_chapter_role_audit_parser_rejected_response",
            parsing_status="failed",
            validation_status="not_run",
            audit_invoked=True,
        )

    validation_errors = validate_role_audit_response(payload, expected)
    if validation_errors:
        return _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            validation_errors,
            fallback_reason="content_chapter_role_audit_validator_rejected_response",
            parsing_status="passed",
            validation_status="failed",
            audit_invoked=True,
        )
    try:
        output = _materialize_role_audit(
            result,
            pass_a_output,
            payload,
            expected,
            source_data,
            created_at=created_at,
        )
        expected_ids = [
            row["utterance_id"]
            for row in build_segmentation_payload(result, source_data)["utterances"]
        ]
        final_errors = validate_content_chapters(output)
        final_errors.extend(_coverage_errors(output, expected_ids))
    except Exception as exc:
        return _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            [f"materialization_exception:{type(exc).__name__}:{str(exc)[:300]}"],
            fallback_reason="content_chapter_role_audit_materialization_exception",
            parsing_status="passed",
            validation_status="failed",
            audit_invoked=True,
        )
    if final_errors:
        return _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            final_errors,
            fallback_reason="content_chapter_role_audit_materialized_validation_failed",
            parsing_status="passed",
            validation_status="failed",
            audit_invoked=True,
        )
    return output


def run_content_chapter_role_audit(
    core: Any,
    result: dict[str, Any],
    pass_a_output: dict[str, Any],
    source_data: dict[str, Any] | None = None,
    *,
    model_name: str,
) -> dict[str, Any]:
    try:
        candidates = build_role_audit_candidates(result, pass_a_output, source_data)
    except RoleAuditContractError as exc:
        return _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            exc.errors,
            fallback_reason="content_chapter_role_audit_candidate_construction_failed",
            parsing_status="not_run",
            validation_status="not_run",
            audit_invoked=False,
        )
    system_prompt, user_prompt = build_role_audit_prompts(candidates)
    prompt_chars = len(system_prompt) + len(user_prompt)
    started = time.perf_counter()
    try:
        with generation_stage("content_chapter_role_audit"):
            raw_text = core._generate_local_llm_text_v033(
                model_name,
                system_prompt,
                user_prompt,
                max_tokens=ROLE_AUDIT_MAX_TOKENS,
            )
    except Exception as exc:
        duration = time.perf_counter() - started
        output = _role_audit_fallback(
            result,
            pass_a_output,
            source_data,
            [f"generator_exception:{type(exc).__name__}:{str(exc)[:300]}"],
            fallback_reason="content_chapter_role_audit_generator_exception",
            parsing_status="not_run",
            validation_status="not_run",
            audit_invoked=True,
        )
        generation = output["content_chapter_generation"]
        generation.update(
            {
                "model": model_name,
                "role_audit_prompt_character_count": prompt_chars,
                "role_audit_response_character_count": 0,
                "role_audit_generation_duration_seconds": round(duration, 6),
            }
        )
        return output

    duration = time.perf_counter() - started
    raw_text = str(raw_text or "")
    output = apply_role_audit_response_atomically(
        result,
        pass_a_output,
        raw_text,
        source_data,
        candidates=candidates,
    )
    generation = output["content_chapter_generation"]
    pass_a_calls = int(
        (pass_a_output.get("content_chapter_generation") or {}).get(
            "generation_call_count"
        )
        or 1
    )
    generation.update(
        {
            "model": model_name,
            "generation_call_count": pass_a_calls + 1,
            "role_audit_generation_call_count": 1,
            "role_audit_prompt_character_count": prompt_chars,
            "role_audit_response_character_count": len(raw_text),
            "role_audit_generation_duration_seconds": round(duration, 6),
        }
    )
    warnings = generation.get("warnings") or []
    generation["warning"] = warnings[0] if warnings else None
    return output
