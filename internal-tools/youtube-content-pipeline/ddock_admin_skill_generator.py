from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ddock_content_contract import (
    CURATION_GENERATION_SCHEMA_VERSION,
    REVIEW_SCHEMA_VERSION,
)
from ddock_content_curation import (
    DEFAULT_MODEL,
    _action_line_is_supported,
    _attach_script_part_membership,
    _canonicalize_generated_names,
    _evidence,
    _is_action_worthy_source,
    _part_preview,
    _resolved_generator,
    _row_map,
    _script_review_status,
    _source_grounding_ratio,
    _thumbnail_for_part,
    audit_posthoc_chapter_copies,
    build_script_contract,
    build_source_contract,
    extract_source_backed_tool_candidates,
    format_timestamp,
    hash_preprocessed_result,
)
from ddock_content_validator import validate_ddock_content_review
from screenshot_output import atomic_write_json


PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "ddock_admin_skill_v0_1.md"
SUPPORTED_PREPROCESSING_PREFIX = "script_preprocessing_v0.3."
ANCHOR_ARRAY_LABELS = {
    "step_ids": "STEP",
    "step_preview_ids": "STEP_PREVIEW",
}
CLASSIFICATION_LABELS = frozenset(ANCHOR_ARRAY_LABELS.values())
ACTION_MARKER = re.compile(
    r"클릭|선택|입력|복사|붙여|설치|연결|실행|요청|열기|열어|"
    r"가져오|불러오|확인|만들|변경|등록|켜기|켜|검색|추출|추가|저장|구성"
)
PROMPT_CUE = re.compile(
    r"프롬프트|prompt|명령어|command|라고\s*요청|요청을|요청해|입력해|입력하",
    re.IGNORECASE,
)
PART_CONTEXT_RADIUS = 6
ProgressCallback = Callable[[str, dict[str, Any]], None]
Generator = Callable[[str, str, str, int], str]


class AdminSkillInputError(ValueError):
    pass


class AdminSkillResponseError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ordered_unique(values: list[str], rows: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        {value for value in values if value in rows},
        key=lambda value: (float(rows[value]["start_seconds"]), value),
    )


def _compact_rows(
    script: list[dict[str, Any]],
    *,
    labels: dict[str, dict[str, Any]] | None = None,
    allowed_ids: set[str] | None = None,
    include_chapter: bool = True,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for row in script:
        utterance_id = str(row["utterance_id"])
        if allowed_ids is not None and utterance_id not in allowed_ids:
            continue
        value = {
            "utterance_id": utterance_id,
            "start_seconds": row["start_seconds"],
            "end_seconds": row["end_seconds"],
            "text": row["text"],
        }
        if include_chapter:
            value["chapter_id"] = row.get("script_chapter_id")
        if labels and utterance_id in labels:
            value["anchor_role"] = labels[utterance_id]["label"]
        values.append(value)
    return values


def materialize_anchor_context(
    script: list[dict[str, Any]],
    anchor_ids: list[str] | set[str],
    *,
    radius: int = 2,
) -> list[str]:
    """Return a small ordered source window around each supplied action anchor."""
    ordered_ids = [str(row["utterance_id"]) for row in script]
    positions = {utterance_id: index for index, utterance_id in enumerate(ordered_ids)}
    selected: set[int] = set()
    for utterance_id in anchor_ids:
        position = positions.get(str(utterance_id))
        if position is None:
            continue
        selected.update(
            range(max(0, position - radius), min(len(ordered_ids), position + radius + 1))
        )
    return [ordered_ids[index] for index in sorted(selected)]


def materialize_source_span(
    script: list[dict[str, Any]],
    source_start_utterance_id: str,
    source_end_utterance_id: str,
) -> list[str]:
    """Return the inclusive ordered source span declared by PASS 2."""
    ordered_ids = [str(row["utterance_id"]) for row in script]
    positions = {utterance_id: index for index, utterance_id in enumerate(ordered_ids)}
    start = positions.get(str(source_start_utterance_id))
    end = positions.get(str(source_end_utterance_id))
    if start is None:
        raise AdminSkillResponseError(
            f"composition:unknown_source_start:{source_start_utterance_id}"
        )
    if end is None:
        raise AdminSkillResponseError(
            f"composition:unknown_source_end:{source_end_utterance_id}"
        )
    if start > end:
        raise AdminSkillResponseError("composition:source_span_reversed")
    return ordered_ids[start : end + 1]


def materialize_part_contexts(
    plans: list[dict[str, Any]],
    script: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    *,
    radius: int = PART_CONTEXT_RADIUS,
) -> None:
    """Attach bounded context without changing deterministic action ownership."""
    ordered_ids = [str(row["utterance_id"]) for row in script]
    positions = {utterance_id: index for index, utterance_id in enumerate(ordered_ids)}
    for index, plan in enumerate(plans):
        start_id = str(plan["action_start_utterance_id"])
        end_id = str(plan["action_end_utterance_id"])
        start = positions[start_id]
        end = positions[end_id]
        lower = max(0, start - radius)
        upper = min(len(ordered_ids) - 1, end + radius)
        if index > 0:
            previous_end = positions[str(plans[index - 1]["action_end_utterance_id"])]
            lower = max(lower, previous_end + 1)
        if index + 1 < len(plans):
            next_start = positions[str(plans[index + 1]["action_start_utterance_id"])]
            upper = min(upper, next_start - 1)
        plan["context_utterance_ids"] = _ordered_unique(
            ordered_ids[lower : upper + 1], rows
        )


def _has_multiple_explicit_done_states(value: str) -> bool:
    text = value.strip()
    if any(separator in text for separator in ("\n", ";", "→", "->")):
        return True
    return bool(re.search(r"(?:^|\s)\d+[.)]\s+", text))


def validate_preprocessed_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdminSkillInputError("preprocessed JSON root must be an object")
    schema = str(value.get("schema_version") or "")
    if not schema.startswith(SUPPORTED_PREPROCESSING_PREFIX):
        if schema == REVIEW_SCHEMA_VERSION:
            raise AdminSkillInputError("review JSON is not a preprocessing input")
        raise AdminSkillInputError(f"unsupported preprocessing schema: {schema or 'missing'}")
    video_id = str(value.get("video_id") or "").strip()
    if not video_id:
        raise AdminSkillInputError("video_id is required")
    rows = value.get("normalized_utterances")
    if not isinstance(rows, list) or not rows:
        raise AdminSkillInputError("normalized_utterances must be a non-empty array")
    valid_rows = 0
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        utterance_id = str(row.get("utterance_id") or "").strip()
        if not utterance_id or utterance_id in seen:
            continue
        try:
            float(row.get("start_seconds"))
            float(row.get("end_seconds"))
        except (TypeError, ValueError):
            continue
        if not str(row.get("final_text") or row.get("normalized_text") or row.get("text") or "").strip():
            continue
        seen.add(utterance_id)
        valid_rows += 1
    if valid_rows == 0:
        raise AdminSkillInputError("no valid normalized utterances")
    return value


def prepare_transcript(result: dict[str, Any]) -> dict[str, Any]:
    chapters, script = build_script_contract(result)
    if not script:
        raise AdminSkillInputError("preprocessing input produced an empty script")
    marker_ids = [
        str(row["utterance_id"])
        for row in script
        if ACTION_MARKER.search(str(row.get("text") or ""))
    ]
    duration = max(float(row["end_seconds"]) for row in script)
    marker_span_count = len(
        {
            int(float(row["start_seconds"]) // 180)
            for row in script
            if str(row["utterance_id"]) in set(marker_ids)
        }
    )
    score = min(1.0, len(marker_ids) / max(8.0, len(script) * 0.08))
    preliminary_mode = (
        "practice"
        if len(marker_ids) >= 4 and marker_span_count >= 2
        else "review"
        if len(marker_ids) >= 2
        else "information"
    )
    return {
        "script_chapters": chapters,
        "script": script,
        "duration_seconds": duration,
        "action_marker_utterance_ids": marker_ids,
        "action_marker_count": len(marker_ids),
        "action_marker_span_count": marker_span_count,
        "practice_signal_score": round(score, 6),
        "preliminary_mode": preliminary_mode,
    }


def _strict_json(raw: Any, context: str) -> dict[str, Any]:
    try:
        text = extract_first_balanced_json_object(str(raw or ""))
    except AdminSkillResponseError as exc:
        raise AdminSkillResponseError(f"{context}:{exc}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdminSkillResponseError(f"{context}:invalid_json:{exc.msg}") from exc
    if not isinstance(value, dict):
        raise AdminSkillResponseError(f"{context}:root_must_be_object")
    return value


def extract_first_balanced_json_object(raw: str) -> str:
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(raw):
        if start is None:
            if character == "{":
                start = index
                depth = 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]
    if start is not None:
        raise AdminSkillResponseError("truncated_json")
    raise AdminSkillResponseError("invalid_json:no_top_level_object")


class RawDumpRecorder:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.counts: dict[str, int] = {}

    @classmethod
    def from_environment(cls) -> "RawDumpRecorder":
        value = str(os.environ.get("DDOCK_ADMIN_SKILL_DUMP_RAW") or "").strip()
        return cls(Path(value).expanduser() if value else None)

    def write(
        self,
        *,
        stage: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        raw_output: str,
        parsed_output: dict[str, Any] | None,
        started_at: str,
        finished_at: str,
        runtime_seconds: float,
    ) -> None:
        if self.root is None:
            return
        self.counts[stage] = self.counts.get(stage, 0) + 1
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{stage}_{self.counts[stage]:03d}.json"
        atomic_write_json(
            path,
            {
                "stage": stage,
                "call_index": self.counts[stage],
                "system_prompt": system_prompt,
                "input": input_payload,
                "raw_output": raw_output,
                "parsed_output": parsed_output,
                "started_at": started_at,
                "finished_at": finished_at,
                "runtime_seconds": runtime_seconds,
            },
        )


def _invoke(
    generator: Generator,
    recorder: RawDumpRecorder,
    *,
    model_name: str,
    stage: str,
    system_prompt: str,
    payload: dict[str, Any],
    max_tokens: int,
) -> tuple[dict[str, Any], float, int]:
    started_at = _utc_now()
    started = time.perf_counter()
    raw = generator(
        model_name,
        system_prompt,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        max_tokens,
    )
    runtime = time.perf_counter() - started
    finished_at = _utc_now()
    parsed: dict[str, Any] | None = None
    try:
        parsed = _strict_json(raw, stage)
        return parsed, runtime, len(str(raw or ""))
    finally:
        recorder.write(
            stage=stage,
            system_prompt=system_prompt,
            input_payload=payload,
            raw_output=str(raw or ""),
            parsed_output=parsed,
            started_at=started_at,
            finished_at=finished_at,
            runtime_seconds=runtime,
        )


def parse_classification_response(
    value: dict[str, Any],
    script: list[dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]], list[str]]:
    mode = str(value.get("mode") or "").lower()
    warnings: list[str] = []
    if mode not in {"practice", "review", "information"}:
        raise AdminSkillResponseError(f"classification:invalid_mode:{mode or 'missing'}")
    expected_fields = {"mode", *ANCHOR_ARRAY_LABELS}
    unexpected_fields = sorted(set(value) - expected_fields)
    if unexpected_fields:
        raise AdminSkillResponseError(
            "classification:unexpected_fields:" + ",".join(unexpected_fields)
        )
    ordered_ids = [str(row["utterance_id"]) for row in script]
    known_ids = set(ordered_ids)
    normalized: dict[str, list[str]] = {}
    for field in ANCHOR_ARRAY_LABELS:
        items = value.get(field)
        if not isinstance(items, list):
            raise AdminSkillResponseError(f"classification:{field}_must_be_array")
        seen: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, str):
                raise AdminSkillResponseError(f"classification:{field}_id_must_be_string:{index}")
            utterance_id = item.strip()
            if utterance_id not in known_ids:
                raise AdminSkillResponseError(f"classification:unknown_id:{utterance_id}")
            seen.add(utterance_id)
        normalized[field] = [utterance_id for utterance_id in ordered_ids if utterance_id in seen]

    if not normalized["step_ids"]:
        raise AdminSkillResponseError("classification:no_step")
    step_ids = set(normalized["step_ids"])
    normalized["step_preview_ids"] = [
        utterance_id
        for utterance_id in normalized["step_preview_ids"]
        if utterance_id not in step_ids
    ]
    value.update(normalized)

    parsed: dict[str, dict[str, Any]] = {}
    for field, label in ANCHOR_ARRAY_LABELS.items():
        for utterance_id in normalized[field]:
            parsed[utterance_id] = {
                "label": label,
                "workflow_hint": None,
                "confidence": "model",
                "reason": "action_anchor",
            }

    marker_ids = [
        str(row["utterance_id"])
        for row in script
        if ACTION_MARKER.search(str(row.get("text") or ""))
    ]
    if len(marker_ids) >= 3 and not any(
        utterance_id in parsed
        and parsed[utterance_id]["label"] in {"STEP", "STEP_PREVIEW"}
        for utterance_id in marker_ids
    ):
        warnings.append("classification_action_signal_dropped_warning")
    duration = max(float(row["end_seconds"]) for row in script)
    tail_marker_ids = [
        str(row["utterance_id"])
        for row in script
        if float(row["start_seconds"]) >= duration * 0.65
        and ACTION_MARKER.search(str(row.get("text") or ""))
    ]
    if tail_marker_ids and not any(
        utterance_id in parsed and parsed[utterance_id]["label"] == "STEP"
        for utterance_id in tail_marker_ids
    ):
        warnings.append("classification_tail_coverage_warning")
    return mode, parsed, warnings


def build_pass_2_action_map(
    prepared: dict[str, Any],
    classifications: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create the private A-key → source provenance map for PASS 2."""
    script = prepared["script"]
    rows = _row_map(script)
    seed_ids = set(classifications)
    supplemental_ids = {
        str(row["utterance_id"])
        for row in script
        if str(row["utterance_id"]) not in seed_ids
        and ACTION_MARKER.search(str(row.get("text") or ""))
        and _is_action_worthy_source(str(row.get("text") or ""))
    }
    source_order = {
        str(row["utterance_id"]): index for index, row in enumerate(script)
    }
    ordered_ids = sorted(
        seed_ids.union(supplemental_ids),
        key=lambda utterance_id: (
            float(rows[utterance_id]["start_seconds"]),
            source_order[utterance_id],
        ),
    )
    width = max(2, len(str(len(ordered_ids))))
    return [
        {
            "action_key": f"A{index:0{width}d}",
            "source_utterance_id": utterance_id,
            "start_seconds": float(rows[utterance_id]["start_seconds"]),
            "end_seconds": float(rows[utterance_id]["end_seconds"]),
            "text": str(rows[utterance_id]["text"]),
            "source_order": source_order[utterance_id],
            "candidate_kind": (
                "pass_1_seed" if utterance_id in seed_ids else "supplemental_candidate"
            ),
            "anchor_role": (
                classifications[utterance_id]["label"]
                if utterance_id in classifications
                else None
            ),
        }
        for index, utterance_id in enumerate(ordered_ids, 1)
    ]


def build_pass_2_payload(
    mode: str,
    prepared: dict[str, Any],
    classifications: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build A-key-only ordered segmentation input with non-addressable context."""
    script = prepared["script"]
    action_map = build_pass_2_action_map(prepared, classifications)
    action_sources = {str(item["source_utterance_id"]) for item in action_map}
    context_ids = set(
        materialize_anchor_context(script, action_sources, radius=1)
    ) - action_sources
    ordered_context_ids = [
        str(row["utterance_id"])
        for row in script
        if str(row["utterance_id"]) in context_ids
    ]
    if len(ordered_context_ids) > 24:
        last = len(ordered_context_ids) - 1
        ordered_context_ids = [
            ordered_context_ids[round(index * last / 23)] for index in range(24)
        ]
    source_order = {
        str(row["utterance_id"]): index for index, row in enumerate(script)
    }
    source_rows = _row_map(script)
    context_by_key: dict[str, dict[str, list[str]]] = {
        str(item["action_key"]): {"previous": [], "next": []}
        for item in action_map
    }
    for context_id in ordered_context_ids:
        context_position = source_order[context_id]
        nearest = min(
            action_map,
            key=lambda item: (
                abs(int(item["source_order"]) - context_position),
                int(item["source_order"]),
            ),
        )
        direction = (
            "previous" if context_position < int(nearest["source_order"]) else "next"
        )
        context_by_key[str(nearest["action_key"])][direction].append(
            str(source_rows[context_id]["text"])
        )
    ordered_actions = []
    for item in action_map:
        contexts = context_by_key[str(item["action_key"])]
        ordered_actions.append(
            {
                "action_key": item["action_key"],
                "time": format_timestamp(float(item["start_seconds"])),
                "text": item["text"],
                "candidate_kind": item["candidate_kind"],
                "anchor_role": item["anchor_role"],
                "previous_context": " ".join(contexts["previous"]) or None,
                "next_context": " ".join(contexts["next"]) or None,
            }
        )
    return {
        "pass": "PASS_2_ORDERED_ACTION_SEGMENTATION",
        "mode": mode,
        "role": "ORDERED ACTION SEQUENCE → WORKFLOW BOUNDARY DETECTION",
        "scale_context": {
            "duration_seconds": prepared["duration_seconds"],
            "seed_action_count": sum(
                item["candidate_kind"] == "pass_1_seed" for item in action_map
            ),
            "supplemental_candidate_count": sum(
                item["candidate_kind"] == "supplemental_candidate"
                for item in action_map
            ),
            "context_snippet_count": len(ordered_context_ids),
            "part_heuristic": "3-5 for a 15-40 minute practice video; never force",
            "step_heuristic": "8-18 total and 3-6 per PART; never force",
        },
        "ordered_actions": ordered_actions,
    }


def _resolve_model_action_reference(
    value: Any,
    action_by_key: dict[str, dict[str, Any]],
    key_by_source: dict[str, str],
    rows: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    reference = str(value or "").strip()
    if reference in action_by_key:
        return reference, None
    if reference in key_by_source:
        return key_by_source[reference], "legacy_model_utterance_id_normalized"
    if reference in rows:
        return None, "context_only_reference"
    return None, "invalid_model_action_key"


WEAK_PREPARATION_MARKER = re.compile(
    r"source|reference|template|file|파일|소스|레퍼런스|참고|템플릿|찾|열|가져오",
    re.IGNORECASE,
)


def _append_ordered_quality_signals(
    plans: list[dict[str, Any]],
    action_map: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    source_to_action = {
        str(item["source_utterance_id"]): item for item in action_map
    }
    for index, plan in enumerate(plans):
        primary_ids = list(plan["primary_step_anchor_ids"])
        surface = " ".join(
            str(plan.get(field) or "")
            for field in ("title", "action_objective", "done_state")
        )
        if len(primary_ids) <= 2 and WEAK_PREPARATION_MARKER.search(surface):
            warnings.append(f"composition:weak_preparation_workflow:{index}")

    ordered = sorted(action_map, key=lambda item: int(item["source_order"]))
    gaps = [
        float(current["start_seconds"]) - float(previous["start_seconds"])
        for previous, current in zip(ordered, ordered[1:])
        if float(current["start_seconds"]) > float(previous["start_seconds"])
    ]
    if not gaps:
        return
    sorted_gaps = sorted(gaps)
    median = sorted_gaps[len(sorted_gaps) // 2]
    upper_quartile = sorted_gaps[(len(sorted_gaps) * 3) // 4]
    threshold = max(median * 3.0, upper_quartile * 2.0)
    global_positions = {
        str(item["source_utterance_id"]): index for index, item in enumerate(ordered)
    }
    candidates: list[tuple[float, str]] = []
    for plan in plans:
        primary = [
            source_to_action[utterance_id]
            for utterance_id in plan["primary_step_anchor_ids"]
            if utterance_id in source_to_action
        ]
        for previous, current in zip(primary, primary[1:]):
            gap = float(current["start_seconds"]) - float(previous["start_seconds"])
            current_source = str(current["source_utterance_id"])
            remaining = len(primary) - primary.index(current)
            if (
                gap > threshold
                and remaining >= 2
                and global_positions[current_source] >= len(ordered) // 2
            ):
                candidates.append((gap, str(current["action_key"])))
    if candidates:
        gap, action_key = max(candidates)
        warnings.append(
            "composition:possible_missing_workflow_boundary:"
            f"{action_key}:gap_ratio:{gap / max(median, 1e-9):.2f}"
        )


def _parse_ordered_segmentation_response(
    value: dict[str, Any],
    classifications: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    available_context_ids: set[str] | None,
    *,
    action_map: list[dict[str, Any]],
    allow_unaccounted: bool,
    quality_context: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Materialize contiguous workflows from model-selected start boundaries."""
    boundary_items = value.get("workflow_boundaries")
    auxiliary_items = value.get("auxiliary_actions", [])
    excluded_items = value.get("excluded_actions", [])
    if not isinstance(boundary_items, list):
        raise AdminSkillResponseError("composition:workflow_boundaries_must_be_array")
    if not isinstance(auxiliary_items, list):
        raise AdminSkillResponseError("composition:auxiliary_actions_must_be_array")
    if not isinstance(excluded_items, list):
        raise AdminSkillResponseError("composition:excluded_actions_must_be_array")

    action_map = [
        item
        for item in action_map
        if str(item.get("source_utterance_id") or "") in rows
    ]
    if not action_map:
        raise AdminSkillResponseError("composition:no_ordered_actions")
    action_by_key = {str(item["action_key"]): item for item in action_map}
    key_by_source = {
        str(item["source_utterance_id"]): str(item["action_key"])
        for item in action_map
    }
    ordered_action_keys = [str(item["action_key"]) for item in action_map]
    action_positions = {
        action_key: index for index, action_key in enumerate(ordered_action_keys)
    }
    ordered_script = sorted(
        rows.values(), key=lambda row: (float(row["start_seconds"]), str(row["utterance_id"]))
    )
    source_positions = {
        str(row["utterance_id"]): index for index, row in enumerate(ordered_script)
    }
    context_allowed = set(rows) if available_context_ids is None else available_context_ids
    warnings: list[str] = []

    usable: list[dict[str, Any]] = []
    seen_boundaries: set[str] = set()
    original_positions: list[int] = []
    for index, item in enumerate(boundary_items):
        if not isinstance(item, dict):
            warnings.append(f"composition:invalid_model_boundary_key:not_object:{index}")
            continue
        reference = item.get("start_action_key", item.get("start_anchor_id"))
        action_key, resolution = _resolve_model_action_reference(
            reference, action_by_key, key_by_source, rows
        )
        if resolution:
            warnings.append(f"composition:{resolution}:boundary:{reference or index}")
        if action_key is None:
            marker = (
                "context_only_reference"
                if resolution == "context_only_reference"
                else "invalid_model_boundary_key"
            )
            warnings.append(f"composition:{marker}:{reference or index}")
            continue
        title = str(item.get("title") or "").strip()
        objective = str(item.get("action_objective") or "").strip()
        done_state = str(item.get("done_state") or "").strip()
        surface = str(item.get("primary_tool_or_surface") or "").strip()
        if action_key in seen_boundaries:
            warnings.append(f"composition:duplicate_boundary_removed:{action_key}")
            continue
        if not title or not objective or not done_state or not surface:
            warnings.append(f"composition:invalid_boundary:missing_fields:{action_key}")
            continue
        if _has_multiple_explicit_done_states(done_state):
            warnings.append(f"composition:invalid_boundary:multiple_done_states:{action_key}")
            continue
        seen_boundaries.add(action_key)
        original_positions.append(action_positions[action_key])
        usable.append(
            {
                "start_action_key": action_key,
                "title": title,
                "action_objective": objective,
                "done_state": done_state,
                "primary_tool_or_surface": surface,
            }
        )
    if not usable:
        raise AdminSkillResponseError("composition:no_usable_workflow_boundaries")
    if original_positions != sorted(original_positions):
        warnings.append("composition:out_of_order_boundaries_normalized")
    usable.sort(key=lambda item: action_positions[str(item["start_action_key"])])
    boundary_keys = {str(item["start_action_key"]) for item in usable}

    excluded: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(excluded_items):
        if not isinstance(item, dict):
            warnings.append(f"composition:invalid_model_action_key:excluded:{index}")
            continue
        reference = item.get("action_key", item.get("utterance_id"))
        action_key, resolution = _resolve_model_action_reference(
            reference, action_by_key, key_by_source, rows
        )
        if resolution:
            warnings.append(f"composition:{resolution}:excluded:{reference or index}")
        if action_key is None:
            continue
        reason_category = str(item.get("reason_category") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not reason_category or not reason:
            warnings.append(f"composition:invalid_excluded_action:{action_key}")
            continue
        excluded[action_key] = (reason_category, reason)

    auxiliary: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(auxiliary_items):
        if not isinstance(item, dict):
            warnings.append(f"composition:invalid_model_action_key:auxiliary:{index}")
            continue
        reference = item.get("action_key", item.get("utterance_id"))
        action_key, resolution = _resolve_model_action_reference(
            reference, action_by_key, key_by_source, rows
        )
        if resolution:
            warnings.append(f"composition:{resolution}:auxiliary:{reference or index}")
        if action_key is None:
            continue
        reason_category = str(item.get("reason_category") or "").strip()
        direction = str(item.get("attach_to_previous_or_next") or "").strip().lower()
        if not reason_category or direction not in {"previous", "next"}:
            warnings.append(f"composition:invalid_auxiliary_action:{action_key}")
            continue
        if action_key in excluded:
            warnings.append(f"composition:conflicting_action_classification:{action_key}")
            continue
        auxiliary[action_key] = (direction, reason_category)

    for action_key in boundary_keys:
        if action_key in auxiliary or action_key in excluded:
            warnings.append(
                f"composition:boundary_action_classification_conflict:{action_key}"
            )
            auxiliary.pop(action_key, None)
            excluded.pop(action_key, None)

    core_keys = [
        action_key
        for action_key in ordered_action_keys
        if action_key not in excluded and action_key not in auxiliary
    ]
    if not core_keys:
        raise AdminSkillResponseError("composition:no_core_actions")
    core_set = set(core_keys)
    usable = [
        item for item in usable if str(item["start_action_key"]) in core_set
    ]
    if not usable:
        raise AdminSkillResponseError("composition:no_usable_workflow_boundaries")
    first_boundary = str(usable[0]["start_action_key"])
    if first_boundary != core_keys[0]:
        warnings.append(
            f"composition:first_boundary_normalized_to_first_core:{first_boundary}:{core_keys[0]}"
        )
        usable[0]["start_action_key"] = core_keys[0]
    core_index = {action_key: index for index, action_key in enumerate(core_keys)}

    segment_core_keys: list[list[str]] = []
    for index, boundary in enumerate(usable):
        start = core_index[str(boundary["start_action_key"])]
        end = (
            core_index[str(usable[index + 1]["start_action_key"])]
            if index + 1 < len(usable)
            else len(core_keys)
        )
        segment_core_keys.append(core_keys[start:end])

    boundary_source_positions = [
        source_positions[
            str(action_by_key[str(item["start_action_key"])]["source_utterance_id"])
        ]
        for item in usable
    ]
    segment_last_core_positions = [
        source_positions[
            str(action_by_key[primary_keys[-1]]["source_utterance_id"])
        ]
        for primary_keys in segment_core_keys
    ]
    auxiliary_by_segment: list[list[str]] = [[] for _ in usable]
    auxiliary_reasons: dict[str, str] = {}
    core_segment_by_key = {
        action_key: index
        for index, primary_keys in enumerate(segment_core_keys)
        for action_key in primary_keys
    }
    last_assigned_segment = 0
    for action_key in ordered_action_keys:
        if action_key in excluded:
            continue
        if action_key in core_segment_by_key:
            last_assigned_segment = core_segment_by_key[action_key]
            continue
        if action_key not in auxiliary:
            continue
        direction, reason_category = auxiliary[action_key]
        utterance_id = str(action_by_key[action_key]["source_utterance_id"])
        position = source_positions[utterance_id]
        previous_index = max(
            (index for index, start in enumerate(boundary_source_positions) if start < position),
            default=-1,
        )
        next_index = next(
            (index for index, start in enumerate(boundary_source_positions) if start > position),
            len(usable),
        )
        target = previous_index if direction == "previous" else next_index
        if (
            direction == "next"
            and previous_index >= 0
            and target == next_index
            and position <= segment_last_core_positions[previous_index]
        ):
            warnings.append(
                f"composition:auxiliary_direction_fallback:{action_key}:{direction}"
            )
            target = previous_index
        if target < 0 or target >= len(usable):
            fallback = next_index if direction == "previous" else previous_index
            if 0 <= fallback < len(usable):
                warnings.append(
                    f"composition:auxiliary_direction_fallback:{action_key}:{direction}"
                )
                target = fallback
            else:
                target = 0 if direction == "next" else len(usable) - 1
        if target < last_assigned_segment:
            warnings.append(
                f"composition:auxiliary_direction_fallback:{action_key}:{direction}"
            )
            target = last_assigned_segment
        auxiliary_by_segment[target].append(utterance_id)
        auxiliary_reasons[utterance_id] = reason_category
        last_assigned_segment = target

    plans: list[dict[str, Any]] = []
    used_actions: set[str] = set()
    for index, (boundary, primary_keys) in enumerate(
        zip(usable, segment_core_keys), 1
    ):
        if not primary_keys:
            warnings.append(
                f"composition:invalid_boundary:empty_segment:{boundary['start_action_key']}"
            )
            continue
        primary_candidates = [
            str(action_by_key[action_key]["source_utterance_id"])
            for action_key in primary_keys
        ]
        auxiliary_candidates = _ordered_unique(auxiliary_by_segment[index - 1], rows)
        candidates = _ordered_unique(primary_candidates + auxiliary_candidates, rows)
        used_actions.update(candidates)
        supplemental_candidates = _ordered_unique(
            [value for value in candidates if value not in classifications], rows
        )
        warnings.extend(
            f"composition:supplemental_action_anchor:{utterance_id}"
            for utterance_id in supplemental_candidates
        )
        start_id = candidates[0]
        end_id = candidates[-1]
        plan: dict[str, Any] = {
            "workflow_id": f"W{index}",
            "boundary_action_key": boundary["start_action_key"],
            "title": boundary["title"],
            "summary": None,
            "action_objective": boundary["action_objective"],
            "done_state": boundary["done_state"],
            "step_anchor_ids": candidates,
            "step_candidate_ids": candidates,
            "primary_step_anchor_ids": primary_candidates,
            "auxiliary_step_anchor_ids": auxiliary_candidates,
            "auxiliary_reason_categories": {
                utterance_id: auxiliary_reasons[utterance_id]
                for utterance_id in auxiliary_candidates
            },
            "primary_tool_or_surface": boundary["primary_tool_or_surface"],
            "supplemental_step_anchor_ids": supplemental_candidates,
            "anchor_metadata": [
                {
                    "action_key": key_by_source[utterance_id],
                    "utterance_id": utterance_id,
                    "discovered_by": "pass_1" if utterance_id in classifications else "pass_2",
                    "seeded_by_pass_1": utterance_id in classifications,
                    "needs_review": utterance_id not in classifications,
                }
                for utterance_id in candidates
            ],
            "action_start_utterance_id": start_id,
            "action_end_utterance_id": end_id,
            "action_start_seconds": float(rows[start_id]["start_seconds"]),
            "action_end_seconds": float(rows[end_id]["end_seconds"]),
            "action_span_utterance_ids": materialize_source_span(
                ordered_script, start_id, end_id
            ),
            "needs_review": False,
        }
        if _title_style_needs_review(boundary["title"]):
            warnings.append(
                f"composition:writing_style_review:part:{index - 1}:{boundary['title']}"
            )
        plans.append(plan)
    if not plans:
        raise AdminSkillResponseError("composition:no_actionable_parts")

    excluded_sources = {
        str(action_by_key[action_key]["source_utterance_id"])
        for action_key in excluded
    }
    for action_key, (reason_category, reason) in excluded.items():
        utterance_id = str(action_by_key[action_key]["source_utterance_id"])
        if utterance_id not in classifications:
            warnings.append(f"composition:supplemental_action_anchor:{utterance_id}")
        warnings.append(
            f"composition:excluded_anchor:{utterance_id}:{reason_category}:{reason}"
        )
    if excluded_sources and len(used_actions) <= len(excluded_sources):
        warnings.append(
            "composition:low_action_anchor_coverage:"
            f"assigned:{len(used_actions)}:unassigned_or_excluded:{len(excluded_sources)}"
        )
    if (
        quality_context
        and str(quality_context.get("mode") or "") == "practice"
        and 900 <= float(quality_context.get("duration_seconds") or 0) <= 2400
        and len(action_map) >= 8
        and len(plans) == 1
    ):
        warnings.append(
            "composition:one_workflow_quality_floor:"
            f"anchors:{len(action_map)}:duration:{float(quality_context['duration_seconds']):.1f}"
        )
    elif (
        quality_context
        and str(quality_context.get("mode") or "") == "practice"
        and 900 <= float(quality_context.get("duration_seconds") or 0) <= 2400
        and len(action_map) >= 12
        and len(plans) < 3
    ):
        warnings.append(
            "composition:too_few_workflow_boundaries:"
            f"boundaries:{len(plans)}:anchors:{len(action_map)}"
        )

    _append_ordered_quality_signals(plans, action_map, warnings)

    materialize_part_contexts(plans, ordered_script, rows)
    previous_end = -1
    for index, plan in enumerate(plans):
        start = source_positions[str(plan["action_start_utterance_id"])]
        end = source_positions[str(plan["action_end_utterance_id"])]
        if start <= previous_end:
            raise AdminSkillResponseError(
                f"composition:interleaved_part_anchor_clusters:{index - 1}:{index}"
            )
        previous_end = end
        if any(value not in context_allowed for value in plan["context_utterance_ids"]):
            raise AdminSkillResponseError(
                f"composition:context_outside_available_context:{index}"
            )
    return plans, warnings


NOUN_STYLE_TITLE_END = re.compile(
    r"(?:하기|구성|설정|구현|추가|연결|확인|실행|추출|생성|가져오기)$"
)


def _title_style_needs_review(value: Any) -> bool:
    title = re.sub(r"[.!?]+$", "", str(value or "").strip())
    return bool(title and NOUN_STYLE_TITLE_END.search(title))


def parse_composition_response(
    value: dict[str, Any],
    classifications: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    available_context_ids: set[str] | None = None,
    *,
    allow_unaccounted: bool = False,
    quality_context: dict[str, Any] | None = None,
    ordered_action_ids: list[str] | None = None,
    action_map: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if "workflow_boundaries" in value:
        if action_map is None:
            fallback_ids = ordered_action_ids or list(classifications)
            width = max(2, len(str(len(fallback_ids))))
            action_map = [
                {
                    "action_key": f"A{index:0{width}d}",
                    "source_utterance_id": utterance_id,
                    "start_seconds": float(rows[utterance_id]["start_seconds"]),
                    "end_seconds": float(rows[utterance_id]["end_seconds"]),
                    "text": str(rows[utterance_id]["text"]),
                    "source_order": index - 1,
                    "candidate_kind": (
                        "pass_1_seed"
                        if utterance_id in classifications
                        else "supplemental_candidate"
                    ),
                }
                for index, utterance_id in enumerate(fallback_ids, 1)
                if utterance_id in rows
            ]
        return _parse_ordered_segmentation_response(
            value,
            classifications,
            rows,
            available_context_ids,
            action_map=action_map,
            allow_unaccounted=allow_unaccounted,
            quality_context=quality_context,
        )
    workflow_schema = "workflows" in value
    items = value.get("workflows") if workflow_schema else value.get("parts")
    if not isinstance(items, list):
        raise AdminSkillResponseError("composition:workflows_must_be_array")
    excluded_items = (
        value.get("excluded_actions")
        if workflow_schema
        else value.get("excluded_step_anchor_ids")
    )
    if not isinstance(excluded_items, list):
        raise AdminSkillResponseError(
            "composition:excluded_actions_must_be_array"
        )
    auxiliary_items = value.get("auxiliary_actions", []) if workflow_schema else []
    if not isinstance(auxiliary_items, list):
        raise AdminSkillResponseError("composition:auxiliary_actions_must_be_array")
    actionable = {
        utterance_id
        for utterance_id, item in classifications.items()
        if item["label"] in {"STEP", "STEP_PREVIEW"}
    }
    context_allowed = set(rows) if available_context_ids is None else available_context_ids
    ordered_script = sorted(
        rows.values(), key=lambda row: (float(row["start_seconds"]), str(row["utterance_id"]))
    )
    positions = {
        str(row["utterance_id"]): index for index, row in enumerate(ordered_script)
    }
    excluded: set[str] = set()
    warnings: list[str] = []
    for index, item in enumerate(excluded_items):
        if not isinstance(item, dict):
            raise AdminSkillResponseError(
                f"composition:excluded_anchor_not_object:{index}"
            )
        utterance_id = str(item.get("utterance_id") or "").strip()
        reason_category = str(item.get("reason_category") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if utterance_id not in rows:
            raise AdminSkillResponseError(
                f"composition:unknown_source_utterance_id:{utterance_id or index}"
            )
        if utterance_id in excluded:
            raise AdminSkillResponseError(
                f"composition:duplicate_excluded_anchor:{utterance_id}"
            )
        if not reason_category:
            raise AdminSkillResponseError(
                f"composition:excluded_anchor_reason_category_required:{utterance_id}"
            )
        if not reason:
            raise AdminSkillResponseError(
                f"composition:excluded_anchor_reason_required:{utterance_id}"
            )
        excluded.add(utterance_id)
        if utterance_id not in actionable:
            warnings.append(
                f"composition:supplemental_action_anchor:{utterance_id}"
            )
        warnings.append(
            f"composition:excluded_anchor:{utterance_id}:{reason_category}:{reason}"
        )
    workflow_ids: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            workflow_ids.append("")
            continue
        workflow_id = str(item.get("workflow_id") or f"W{index + 1}").strip()
        if not workflow_id:
            raise AdminSkillResponseError(f"composition:workflow_id_required:{index}")
        if workflow_id in workflow_ids:
            raise AdminSkillResponseError(
                f"composition:duplicate_workflow_id:{workflow_id}"
            )
        workflow_ids.append(workflow_id)
    auxiliary_by_workflow: dict[str, list[str]] = {
        workflow_id: [] for workflow_id in workflow_ids
    }
    auxiliary_reasons: dict[str, str] = {}
    auxiliary_seen: set[str] = set()
    for index, item in enumerate(auxiliary_items):
        if not isinstance(item, dict):
            raise AdminSkillResponseError(
                f"composition:auxiliary_action_not_object:{index}"
            )
        utterance_id = str(item.get("utterance_id") or "").strip()
        workflow_id = str(item.get("attach_to_workflow_id") or "").strip()
        reason_category = str(item.get("reason_category") or "").strip()
        if utterance_id not in rows:
            raise AdminSkillResponseError(
                f"composition:unknown_source_utterance_id:{utterance_id or index}"
            )
        if workflow_id not in auxiliary_by_workflow:
            raise AdminSkillResponseError(
                f"composition:unknown_auxiliary_workflow:{workflow_id or index}"
            )
        if not reason_category:
            raise AdminSkillResponseError(
                f"composition:auxiliary_reason_category_required:{utterance_id}"
            )
        if utterance_id in auxiliary_seen or utterance_id in excluded:
            raise AdminSkillResponseError(
                f"composition:duplicate_anchor_accounting:{utterance_id}"
            )
        auxiliary_seen.add(utterance_id)
        auxiliary_by_workflow[workflow_id].append(utterance_id)
        auxiliary_reasons[utterance_id] = reason_category
    used_actions: set[str] = set()
    plans: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise AdminSkillResponseError(f"composition:item_not_object:{index}")
        title = str(item.get("title") or "").strip()
        objective = str(item.get("action_objective") or "").strip()
        done_state = str(item.get("done_state") or "").strip()
        workflow_id = workflow_ids[index]
        primary_tool_or_surface = str(
            item.get("primary_tool_or_surface") or ""
        ).strip()
        if not done_state:
            raise AdminSkillResponseError(f"composition:done_state_required:{index}")
        if _has_multiple_explicit_done_states(done_state):
            raise AdminSkillResponseError(f"composition:multiple_done_states:{index}")
        candidate_values = (
            item.get("anchor_ids") if workflow_schema else item.get("step_anchor_ids")
        )
        if not isinstance(candidate_values, list):
            raise AdminSkillResponseError(
                f"composition:anchor_ids_must_be_array:{index}"
            )
        normalized_candidates = [str(value) for value in candidate_values]
        if len(normalized_candidates) != len(set(normalized_candidates)):
            raise AdminSkillResponseError(
                f"composition:duplicate_anchor_in_part:{index}"
            )
        unknown_source = [value for value in normalized_candidates if value not in rows]
        if unknown_source:
            raise AdminSkillResponseError(
                f"composition:unknown_source_utterance_id:{unknown_source[0]}"
            )
        primary_candidates = _ordered_unique(normalized_candidates, rows)
        auxiliary_candidates = _ordered_unique(
            auxiliary_by_workflow.get(workflow_id, []), rows
        )
        category_overlap = set(primary_candidates).intersection(auxiliary_candidates)
        if category_overlap:
            raise AdminSkillResponseError(
                "composition:duplicate_anchor_accounting:"
                f"{_ordered_unique(list(category_overlap), rows)[0]}"
            )
        candidates = _ordered_unique(primary_candidates + auxiliary_candidates, rows)
        supplemental_candidates = _ordered_unique(
            [value for value in candidates if value not in actionable], rows
        )
        repeated = [value for value in candidates if value in used_actions or value in excluded]
        if repeated:
            raise AdminSkillResponseError(
                f"composition:duplicate_anchor_accounting:{repeated[0]}"
            )
        if not title or not objective or not primary_candidates:
            raise AdminSkillResponseError(f"composition:invalid_part:{index}")
        if workflow_schema and not primary_tool_or_surface:
            raise AdminSkillResponseError(
                f"composition:primary_tool_or_surface_required:{index}"
            )
        used_actions.update(candidates)
        warnings.extend(
            f"composition:supplemental_action_anchor:{utterance_id}"
            for utterance_id in supplemental_candidates
        )
        start_id = candidates[0]
        end_id = candidates[-1]
        action_span_ids = materialize_source_span(ordered_script, start_id, end_id)
        plan: dict[str, Any] = {
            "workflow_id": workflow_id,
            "title": title,
            "summary": None,
            "action_objective": objective,
            "done_state": done_state,
            "step_anchor_ids": candidates,
            "step_candidate_ids": candidates,
            "primary_step_anchor_ids": primary_candidates,
            "auxiliary_step_anchor_ids": auxiliary_candidates,
            "auxiliary_reason_categories": {
                utterance_id: auxiliary_reasons[utterance_id]
                for utterance_id in auxiliary_candidates
            },
            "primary_tool_or_surface": primary_tool_or_surface or None,
            "supplemental_step_anchor_ids": supplemental_candidates,
            "anchor_metadata": [
                {
                    "utterance_id": utterance_id,
                    "discovered_by": "pass_2" if utterance_id in supplemental_candidates else "pass_1",
                    "seeded_by_pass_1": utterance_id not in supplemental_candidates,
                    "needs_review": utterance_id in supplemental_candidates,
                }
                for utterance_id in candidates
            ],
            "action_start_utterance_id": start_id,
            "action_end_utterance_id": end_id,
            "action_start_seconds": float(rows[start_id]["start_seconds"]),
            "action_end_seconds": float(rows[end_id]["end_seconds"]),
            "action_span_utterance_ids": action_span_ids,
            "needs_review": False,
        }
        if _title_style_needs_review(title):
            warnings.append(f"composition:writing_style_review:part:{index}:{title}")
        plans.append(plan)
    if not plans:
        raise AdminSkillResponseError("composition:no_actionable_parts")
    missing = _ordered_unique(list(actionable - used_actions - excluded), rows)
    if missing:
        if not allow_unaccounted:
            raise AdminSkillResponseError(
                f"composition:unaccounted_anchor:{missing[0]}"
            )
        warnings.extend(
            f"composition:unaccounted_anchor:{utterance_id}" for utterance_id in missing
        )
    if (excluded or missing) and len(used_actions) <= len(excluded) + len(missing):
        warnings.append(
            "composition:low_action_anchor_coverage:"
            f"assigned:{len(used_actions)}:unassigned_or_excluded:{len(excluded) + len(missing)}"
        )
    if (
        quality_context
        and str(quality_context.get("mode") or "") == "practice"
        and 900 <= float(quality_context.get("duration_seconds") or 0) <= 2400
        and len(actionable) >= 8
        and len(plans) == 1
    ):
        warnings.append(
            "composition:one_workflow_quality_floor:"
            f"anchors:{len(actionable)}:duration:{float(quality_context['duration_seconds']):.1f}"
        )
    plans.sort(key=lambda plan: positions[str(plan["action_start_utterance_id"])])
    for index in range(1, len(plans)):
        previous_end = positions[str(plans[index - 1]["action_end_utterance_id"])]
        current_start = positions[str(plans[index]["action_start_utterance_id"])]
        if current_start <= previous_end:
            raise AdminSkillResponseError(
                f"composition:interleaved_part_anchor_clusters:{index - 1}:{index}"
            )
    materialize_part_contexts(plans, ordered_script, rows)
    for index, plan in enumerate(plans):
        context_ids = plan["context_utterance_ids"]
        if any(value not in context_allowed for value in context_ids):
            raise AdminSkillResponseError(
                f"composition:context_outside_available_context:{index}"
            )
    return plans, warnings


def _composition_repair_diagnostics(
    value: dict[str, Any],
    classifications: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Describe only deterministic PASS 2 defects for one targeted repair."""
    if isinstance(value.get("workflow_boundaries"), list):
        ordered_ids = _ordered_unique(list(rows), rows)
        positions = {
            utterance_id: index for index, utterance_id in enumerate(ordered_ids)
        }
        starts = [
            str(item.get("start_anchor_id") or "").strip()
            for item in value["workflow_boundaries"]
            if isinstance(item, dict)
        ]
        valid = [utterance_id for utterance_id in starts if utterance_id in positions]
        return {
            "invalid_boundary_ids": [
                utterance_id or "missing"
                for utterance_id in starts
                if utterance_id not in positions
            ],
            "duplicate_boundary_ids": sorted(
                {
                    utterance_id
                    for utterance_id in valid
                    if valid.count(utterance_id) > 1
                }
            ),
            "boundaries_out_of_order": [positions[value] for value in valid]
            != sorted(positions[value] for value in valid),
            "one_workflow_quality_floor": len(set(valid)) == 1,
        }
    actionable = {
        utterance_id
        for utterance_id, item in classifications.items()
        if item["label"] in {"STEP", "STEP_PREVIEW"}
    }
    ordered_ids = _ordered_unique(list(rows), rows)
    positions = {utterance_id: index for index, utterance_id in enumerate(ordered_ids)}
    workflow_schema = isinstance(value.get("workflows"), list)
    parts = (
        value.get("workflows")
        if workflow_schema
        else value.get("parts") if isinstance(value.get("parts"), list) else []
    )
    excluded_items = (
        value.get("excluded_actions")
        if workflow_schema and isinstance(value.get("excluded_actions"), list)
        else value.get("excluded_step_anchor_ids")
        if isinstance(value.get("excluded_step_anchor_ids"), list)
        else []
    )
    auxiliary_items = (
        value.get("auxiliary_actions")
        if workflow_schema and isinstance(value.get("auxiliary_actions"), list)
        else []
    )
    owners: dict[str, list[str]] = {}
    valid_clusters: list[tuple[int, int, int, list[str]]] = []
    invalid_indices: list[int] = []
    auxiliary_warnings: list[dict[str, Any]] = []
    auxiliary_markers = (
        "cleanup",
        "rename",
        "layer name",
        "레이어명",
        "정리",
        "reference",
        "참고",
        "tip",
        "팁",
    )
    for index, item in enumerate(parts):
        if not isinstance(item, dict):
            invalid_indices.append(index)
            continue
        raw_ids = item.get("anchor_ids") if workflow_schema else item.get("step_anchor_ids")
        anchor_ids = (
            [str(item_id) for item_id in raw_ids if str(item_id) in rows]
            if isinstance(raw_ids, list)
            else []
        )
        if (
            not str(item.get("title") or "").strip()
            or not str(item.get("action_objective") or "").strip()
            or not str(item.get("done_state") or "").strip()
            or not anchor_ids
        ):
            invalid_indices.append(index)
        for utterance_id in anchor_ids:
            owners.setdefault(utterance_id, []).append(f"part:{index}")
        if anchor_ids:
            cluster_positions = [positions[item_id] for item_id in anchor_ids]
            valid_clusters.append(
                (min(cluster_positions), max(cluster_positions), index, anchor_ids)
            )
        title = str(item.get("title") or "").casefold()
        if len(anchor_ids) == 1 or any(marker in title for marker in auxiliary_markers):
            auxiliary_warnings.append(
                {
                    "part_index": index,
                    "step_anchor_ids": anchor_ids,
                    "reason": "review_independent_observable_done_state",
                }
            )
    for index, item in enumerate(excluded_items):
        if not isinstance(item, dict):
            continue
        utterance_id = str(item.get("utterance_id") or "").strip()
        if utterance_id in actionable:
            owners.setdefault(utterance_id, []).append(f"excluded:{index}")
    for index, item in enumerate(auxiliary_items):
        if not isinstance(item, dict):
            continue
        utterance_id = str(item.get("utterance_id") or "").strip()
        if utterance_id in rows:
            owners.setdefault(utterance_id, []).append(f"auxiliary:{index}")
    valid_clusters.sort(key=lambda cluster: cluster[0])
    interleaved: list[dict[str, Any]] = []
    for previous, current in zip(valid_clusters, valid_clusters[1:]):
        if current[0] <= previous[1]:
            interleaved.append(
                {
                    "part_indices": [previous[2], current[2]],
                    "step_anchor_ids": [previous[3], current[3]],
                }
            )
    return {
        "invalid_part_indices": sorted(set(invalid_indices)),
        "interleaved_anchor_clusters": interleaved,
        "unassigned_anchor_ids": _ordered_unique(
            [utterance_id for utterance_id in actionable if utterance_id not in owners],
            rows,
        ),
        "duplicate_anchor_ownership": [
            {"utterance_id": utterance_id, "owners": owner_values}
            for utterance_id, owner_values in sorted(owners.items())
            if len(owner_values) > 1
        ],
        "auxiliary_part_warnings": auxiliary_warnings,
        "one_workflow_quality_floor": len(parts) == 1 and len(actionable) >= 8,
    }


def _exact_prompt(
    value: Any,
    allowed_ids: set[str],
    rows: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, "prompt_removed:not_object"
    ids = _ordered_unique(
        [str(item) for item in value.get("source_utterance_ids") or [] if str(item) in allowed_ids],
        rows,
    )
    text = re.sub(r"\s+", " ", str(value.get("text") or "")).strip()
    source_text = "\n".join(str(rows[item]["text"]) for item in ids)
    normalized_source = re.sub(r"\s+", " ", source_text)
    if not ids or not text or text not in normalized_source or not PROMPT_CUE.search(source_text):
        return None, "prompt_removed:not_verbatim_or_missing_cue"
    return {
        "text": text,
        "source_kind": "verbatim",
        "evidence": _evidence(ids, rows),
    }, None


def _optional_warning(
    value: Any,
    allowed_ids: set[str],
    rows: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, "warning_removed:not_object"
    ids = _ordered_unique(
        [str(item) for item in value.get("source_utterance_ids") or [] if str(item) in allowed_ids],
        rows,
    )
    title = str(value.get("title") or "").strip()
    body = str(value.get("body") or "").strip()
    source = "\n".join(str(rows[item]["text"]) for item in ids)
    if not ids or not title or not body or min(
        _source_grounding_ratio(title, source), _source_grounding_ratio(body, source)
    ) < 0.18:
        return None, "warning_removed:weak_grounding"
    return {"title": title, "body": body, "evidence": _evidence(ids, rows)}, None


def _learn_more(
    values: Any,
    allowed_ids: set[str],
    rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(values, list):
        return [], []
    parsed: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            warnings.append(f"learn_more_removed:not_object:{index}")
            continue
        ids = _ordered_unique(
            [str(item) for item in value.get("source_utterance_ids") or [] if str(item) in allowed_ids],
            rows,
        )
        question = str(value.get("question") or "").strip()
        body = str(value.get("body") or "").strip()
        source = "\n".join(str(rows[item]["text"]) for item in ids)
        if not ids or not question or not body or _source_grounding_ratio(body, source) < 0.16:
            warnings.append(f"learn_more_removed:weak_grounding:{index}")
            continue
        parsed.append(
            {
                "question": question,
                "body": body,
                "evidence": _evidence(ids, rows),
                "source_timestamp": format_timestamp(rows[ids[0]]["start_seconds"]),
            }
        )
    return parsed, warnings


def parse_step_response(
    value: dict[str, Any],
    plan: dict[str, Any],
    rows: dict[str, dict[str, Any]],
    *,
    allow_unaccounted: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str], list[str]]:
    items = value.get("steps")
    if not isinstance(items, list):
        raise AdminSkillResponseError("steps:steps_must_be_array")
    action_allowed = set(plan["step_anchor_ids"])
    part_allowed = set(plan["context_utterance_ids"])
    steps: list[dict[str, Any]] = []
    used: set[str] = set()
    warnings: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            warnings.append(f"step_removed:not_object:{index}")
            continue
        raw_anchor_ids = item.get("anchor_ids")
        if not isinstance(raw_anchor_ids, list):
            raise AdminSkillResponseError(f"steps:anchor_ids_must_be_array:{index}")
        normalized_anchor_ids = [str(value) for value in raw_anchor_ids]
        if len(normalized_anchor_ids) != len(set(normalized_anchor_ids)):
            raise AdminSkillResponseError(f"steps:duplicate_anchor:{index}")
        unknown_anchor_ids = [
            value for value in normalized_anchor_ids if value not in action_allowed
        ]
        if unknown_anchor_ids:
            raise AdminSkillResponseError(
                f"steps:unknown_anchor:{unknown_anchor_ids[0]}"
            )
        repeated_anchor_ids = [value for value in normalized_anchor_ids if value in used]
        if repeated_anchor_ids:
            raise AdminSkillResponseError(
                f"steps:duplicate_anchor_accounting:{repeated_anchor_ids[0]}"
            )
        anchor_ids = _ordered_unique(normalized_anchor_ids, rows)
        if not anchor_ids:
            raise AdminSkillResponseError(f"steps:anchor_ids_required:{index}")
        raw_lines = item.get("action_lines")
        raw_lines = raw_lines if isinstance(raw_lines, list) else []
        lines: list[dict[str, Any]] = []
        step_ids: list[str] = []
        for line_index, line in enumerate(raw_lines[:4]):
            if not isinstance(line, dict):
                continue
            ids = _ordered_unique(
                [str(value) for value in line.get("source_utterance_ids") or [] if str(value) in part_allowed],
                rows,
            )
            text = str(line.get("text") or "").strip()
            source = "\n".join(str(rows[value]["text"]) for value in ids)
            if not ids or not text or not _action_line_is_supported(text, source):
                warnings.append(f"weak_grounding:action_line_removed:{index}:{line_index}")
                continue
            lines.append(
                {
                    "text": text,
                    "segments": [{"type": "text", "text": text}],
                    "source_utterance_ids": ids,
                }
            )
            step_ids.extend(ids)
        step_ids = _ordered_unique(step_ids + anchor_ids, rows)
        if not lines or not step_ids:
            warnings.append(f"step_removed:no_supported_action_lines:{index}")
            continue
        prompt, prompt_warning = _exact_prompt(item.get("prompt"), part_allowed, rows)
        warning, warning_warning = _optional_warning(item.get("warning"), part_allowed, rows)
        learn_more, learn_warnings = _learn_more(item.get("learn_more"), part_allowed, rows)
        if prompt_warning:
            warnings.append(prompt_warning)
        if warning_warning:
            warnings.append(warning_warning)
        warnings.extend(learn_warnings)
        start = min(float(rows[value]["start_seconds"]) for value in step_ids)
        end = max(float(rows[value]["end_seconds"]) for value in step_ids)
        action_title = str(item.get("action_title") or lines[0]["text"]).strip()
        if _title_style_needs_review(action_title):
            warnings.append(f"writing_style_review:step:{index}:{action_title}")
        steps.append(
            {
                "action_title": action_title,
                "action_lines": lines,
                "source_utterance_ids": step_ids,
                "evidence": _evidence(step_ids, rows),
                "playback_start_seconds": start,
                "playback_end_seconds": end,
                "prompt": prompt,
                "warning": warning,
                "learn_more": learn_more,
                "needs_review": bool(item.get("needs_review")),
            }
        )
        used.update(anchor_ids)
    checkpoint_value = value.get("checkpoint")
    checkpoint: dict[str, Any] | None = None
    if isinstance(checkpoint_value, dict):
        checkpoint_ids = _ordered_unique(
            [str(item) for item in checkpoint_value.get("source_utterance_ids") or [] if str(item) in part_allowed],
            rows,
        )
        checkpoint_text = str(checkpoint_value.get("text") or "").strip()
        source = "\n".join(str(rows[item]["text"]) for item in checkpoint_ids)
        if checkpoint_ids and checkpoint_text and _source_grounding_ratio(checkpoint_text, source) >= 0.16:
            checkpoint = {
                "text": checkpoint_text,
                "source_utterance_ids": checkpoint_ids,
                "evidence": _evidence(checkpoint_ids, rows),
            }
        else:
            warnings.append("checkpoint_removed:weak_grounding")
    excluded_values = value.get("excluded_anchor_ids")
    if not isinstance(excluded_values, list):
        raise AdminSkillResponseError("steps:excluded_anchor_ids_must_be_array")
    excluded: list[str] = []
    for index, item in enumerate(excluded_values):
        if not isinstance(item, dict):
            raise AdminSkillResponseError(
                f"steps:excluded_anchor_not_object:{index}"
            )
        utterance_id = str(item.get("utterance_id") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if utterance_id not in action_allowed:
            raise AdminSkillResponseError(
                f"steps:unknown_excluded_anchor:{utterance_id or index}"
            )
        if utterance_id in used or utterance_id in excluded:
            raise AdminSkillResponseError(
                f"steps:duplicate_anchor_accounting:{utterance_id}"
            )
        if not reason:
            raise AdminSkillResponseError(
                f"steps:excluded_anchor_reason_required:{utterance_id}"
            )
        excluded.append(utterance_id)
        warnings.append(f"excluded_anchor:{utterance_id}:{reason}")
    missing = _ordered_unique(list(action_allowed - used - set(excluded)), rows)
    if missing:
        if not allow_unaccounted:
            raise AdminSkillResponseError(f"steps:unaccounted_anchor:{missing[0]}")
        warnings.extend(f"unaccounted_action_anchor:{utterance_id}" for utterance_id in missing)
    return steps, checkpoint, _ordered_unique(excluded, rows), warnings


def _unaccounted_step_anchor_ids(
    plan: dict[str, Any],
    steps: list[dict[str, Any]],
    excluded_ids: list[str],
    rows: dict[str, dict[str, Any]],
) -> list[str]:
    represented = {
        utterance_id
        for step in steps
        for utterance_id in step["source_utterance_ids"]
        if utterance_id in set(plan["step_anchor_ids"])
    }
    return _ordered_unique(
        list(set(plan["step_anchor_ids"]) - represented - set(excluded_ids)), rows
    )


def _materialize_part(
    plan: dict[str, Any],
    steps: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None,
    rows: dict[str, dict[str, Any]],
    result: dict[str, Any],
    *,
    excluded_ids: list[str] | None = None,
    unresolved_ids: list[str] | None = None,
) -> dict[str, Any]:
    action_ids = _ordered_unique(
        list(plan["step_anchor_ids"])
        + [
            value
            for step in steps
            for value in step["source_utterance_ids"]
        ],
        rows,
    )
    excluded_ids = _ordered_unique(list(excluded_ids or []), rows)
    unresolved_ids = _ordered_unique(list(unresolved_ids or []), rows)
    optional_ids = [
        str(evidence["utterance_id"])
        for step in steps
        for block in (
            ([step["prompt"]] if step["prompt"] else [])
            + ([step["warning"]] if step["warning"] else [])
            + step["learn_more"]
        )
        for evidence in block["evidence"]
    ]
    if checkpoint:
        optional_ids.extend(checkpoint["source_utterance_ids"])
    source_ids = _ordered_unique(action_ids + optional_ids, rows)
    start = float(plan["action_start_seconds"])
    end = float(plan["action_end_seconds"])
    chapter_ids: list[str] = []
    for value in source_ids:
        chapter_id = rows[value].get("script_chapter_id")
        if chapter_id and chapter_id not in chapter_ids:
            chapter_ids.append(chapter_id)
    return {
        "part_id": "",
        "order": 0,
        "title": plan["title"],
        "summary": plan["summary"],
        "action_objective": plan["action_objective"],
        "source_utterance_ids": source_ids,
        "action_utterance_ids": action_ids,
        "source_script_chapter_ids": chapter_ids,
        "start_seconds": start,
        "end_seconds": end,
        "start_timestamp": format_timestamp(start),
        "end_timestamp": format_timestamp(end),
        "evidence": _evidence(source_ids, rows),
        "thumbnail": _thumbnail_for_part(source_ids, result),
        "steps": steps,
        "needs_review": bool(
            plan["needs_review"]
            or not steps
            or unresolved_ids
            or any(step["needs_review"] for step in steps)
        ),
        "review_reasons": (
            (["zero_step_part"] if not steps else [])
            + (["unaccounted_action_anchor"] if unresolved_ids else [])
        ),
        "generation_warnings": [
            f"unaccounted_action_anchor:{utterance_id}" for utterance_id in unresolved_ids
        ]
        + [
            f"supplemental_action_anchor:{utterance_id}"
            for utterance_id in plan.get("supplemental_step_anchor_ids", [])
        ],
        "excluded_actions": [
            {
                "utterance_id": utterance_id,
                "reason": "모델이 STEP에서 제외해 관리자 확인이 필요합니다.",
                "reason_category": "ambiguous_source",
            }
            for utterance_id in excluded_ids
        ]
        + [
            {
                "utterance_id": utterance_id,
                "reason": "자동 STEP으로 표현되지 않아 관리자 확인이 필요합니다.",
                "reason_category": "unaccounted_action_anchor",
            }
            for utterance_id in unresolved_ids
        ],
    }


def _renumber(parts: list[dict[str, Any]]) -> None:
    for part_index, part in enumerate(parts, 1):
        part_id = f"PART-{part_index:02d}"
        part["part_id"] = part_id
        part["order"] = part_index
        for step_index, step in enumerate(part["steps"], 1):
            step["step_id"] = f"{part_id}-STEP-{step_index:02d}"
            step["parent_part_id"] = part_id
            step["order"] = step_index


def _project_phases(
    parts: list[dict[str, Any]],
    unused_ids: list[str],
    classifications: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    phases: list[dict[str, Any]] = []
    for part in parts:
        for step in part["steps"]:
            context_ids = _ordered_unique(
                [
                    evidence["utterance_id"]
                    for item in step["learn_more"]
                    for evidence in item["evidence"]
                ]
                + ([evidence["utterance_id"] for evidence in step["warning"]["evidence"]] if step["warning"] else []),
                rows,
            )
            phases.append(
                {
                    "phase_id": "",
                    "order": 0,
                    "phase_label": step["action_title"],
                    "operation": " / ".join(line["text"] for line in step["action_lines"]),
                    "tool_or_surface": None,
                    "expected_result": None,
                    "action_utterance_ids": list(step["source_utterance_ids"]),
                    "context_utterance_ids": context_ids,
                    "assigned_part_id": part["part_id"],
                    "needs_review": bool(step["needs_review"]),
                    "review_reasons": ["step_needs_review"] if step["needs_review"] else [],
                }
            )
    assigned_ids = {
        value
        for phase in phases
        for value in phase["action_utterance_ids"]
    }
    unassigned_ids = _ordered_unique(
        [value for value in unused_ids if value not in assigned_ids], rows
    )
    ordered_row_ids = _ordered_unique(list(rows), rows)
    positions = {utterance_id: index for index, utterance_id in enumerate(ordered_row_ids)}
    clusters: list[list[str]] = []
    for utterance_id in unassigned_ids:
        if (
            clusters
            and positions[utterance_id] == positions[clusters[-1][-1]] + 1
        ):
            clusters[-1].append(utterance_id)
        else:
            clusters.append([utterance_id])
    for cluster in clusters:
        label = classifications.get(cluster[0], {})
        phases.append(
            {
                "phase_id": "",
                "order": 0,
                "phase_label": label.get("workflow_hint") or "확인되지 않은 작업",
                "operation": " ".join(str(rows[value]["text"]) for value in cluster),
                "tool_or_surface": None,
                "expected_result": None,
                "action_utterance_ids": cluster,
                "context_utterance_ids": [],
                "assigned_part_id": None,
                "needs_review": True,
                "review_reasons": ["unassigned_phase", "unaccounted_action_anchor"],
            }
        )
    unassigned: list[dict[str, Any]] = []
    for index, phase in enumerate(phases, 1):
        phase["phase_id"] = f"PHASE-{index:03d}"
        phase["order"] = index
        if phase["assigned_part_id"] is None:
            unassigned.append({**copy.deepcopy(phase), "excluded_reason": None})
    return phases, unassigned


def _review_queue(
    parts: list[dict[str, Any]],
    unassigned: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    warnings: list[str],
    script_status: dict[str, Any],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []

    def add(
        item_type: str,
        severity: str,
        message: str,
        *,
        part_id: str | None = None,
        phase_id: str | None = None,
        step_id: str | None = None,
        utterance_ids: list[str] | None = None,
    ) -> None:
        queue.append(
            {
                "review_id": f"REV-{len(queue) + 1:03d}",
                "type": item_type,
                "severity": severity,
                "part_id": part_id,
                "phase_id": phase_id,
                "step_id": step_id,
                "utterance_ids": list(utterance_ids or []),
                "message": message,
            }
        )

    def semantic_tokens(part: dict[str, Any]) -> set[str]:
        text = " ".join(
            str(part.get(field) or "")
            for field in ("title", "action_objective", "summary")
        ).casefold()
        stop = {"하기", "해요", "상태", "완료", "작업", "구성", "만들기"}
        return {
            token
            for token in re.findall(r"[0-9a-z가-힣]+", text)
            if len(token) >= 2 and token not in stop
        }

    for phase in unassigned:
        add(
            "unassigned_phase",
            "blocking",
            "이 작업을 PART에 연결하거나 명시적으로 제외해 주세요.",
            phase_id=phase["phase_id"],
            utterance_ids=phase["action_utterance_ids"],
        )
        add(
            "unaccounted_action_anchor",
            "blocking",
            "자동 PART에 포함되지 않은 작업을 확인해 주세요.",
            phase_id=phase["phase_id"],
            utterance_ids=phase["action_utterance_ids"],
        )
    checkpoint_parts = {item["part_id"] for item in checkpoints}
    for part in parts:
        if part["needs_review"]:
            add(
                "part_needs_review",
                "blocking",
                "이 PART의 생성 결과를 확인해 주세요.",
                part_id=part["part_id"],
                utterance_ids=part["source_utterance_ids"],
            )
        for excluded in part["excluded_actions"]:
            if excluded.get("reason_category") == "unaccounted_action_anchor":
                add(
                    "unaccounted_action_anchor",
                    "blocking",
                    "자동 STEP에 포함되지 않은 작업을 확인해 주세요.",
                    part_id=part["part_id"],
                    utterance_ids=[str(excluded["utterance_id"])],
                )
        for warning in part["generation_warnings"]:
            if warning.startswith("supplemental_action_anchor:"):
                utterance_id = warning.rsplit(":", 1)[-1]
                add(
                    "supplemental_action_anchor",
                    "warning",
                    "PASS 2가 source에서 추가로 발견한 작업이에요.",
                    part_id=part["part_id"],
                    utterance_ids=[utterance_id],
                )
        for step in part["steps"]:
            if step["needs_review"]:
                add(
                    "step_needs_review",
                    "blocking",
                    "이 STEP의 생성 결과를 확인해 주세요.",
                    part_id=part["part_id"],
                    step_id=step["step_id"],
                    utterance_ids=step["source_utterance_ids"],
                )
        if part["part_id"] not in checkpoint_parts:
            add(
                "checkpoint_missing",
                "warning",
                "완료 결과를 확인할 수 있는 원본 근거를 찾지 못했습니다.",
                part_id=part["part_id"],
            )
    for left, right in zip(parts, parts[1:]):
        left_tokens = semantic_tokens(left)
        right_tokens = semantic_tokens(right)
        overlap = len(left_tokens.intersection(right_tokens))
        denominator = min(len(left_tokens), len(right_tokens))
        gap = max(0.0, float(right["start_seconds"]) - float(left["end_seconds"]))
        if denominator and overlap / denominator >= 0.5 and gap <= 180:
            add(
                "possible_duplicate_part",
                "warning",
                f"{left['part_id']}와 {right['part_id']}의 목표가 비슷해 병합 여부를 확인해 주세요.",
                part_id=left["part_id"],
                utterance_ids=list(
                    dict.fromkeys(
                        list(left["action_utterance_ids"])
                        + list(right["action_utterance_ids"])
                    )
                ),
            )
    warning_types = {
        "prompt_removed": "prompt_removed",
        "weak_grounding": "weak_grounding",
        "warning_removed": "weak_grounding",
        "learn_more_removed": "weak_grounding",
        "checkpoint_removed": "weak_grounding",
        "low_action_anchor_coverage": "low_action_anchor_coverage",
        "writing_style_review": "writing_style_review",
        "one_workflow_quality_floor": "workflow_grouping_review",
        "too_few_workflow_boundaries": "workflow_grouping_review",
        "invalid_boundary": "workflow_grouping_review",
        "duplicate_boundary": "workflow_grouping_review",
        "out_of_order_boundaries": "workflow_grouping_review",
        "auxiliary_direction_fallback": "workflow_grouping_review",
        "weak_preparation_workflow": "workflow_grouping_review",
        "possible_missing_workflow_boundary": "workflow_grouping_review",
        "conflicting_action_classification": "workflow_grouping_review",
        "boundary_action_classification_conflict": "workflow_grouping_review",
        "invalid_model_action_key": "workflow_grouping_review",
        "invalid_model_boundary_key": "workflow_grouping_review",
        "context_only_reference": "workflow_grouping_review",
    }
    for warning in warnings:
        item_type = next((value for marker, value in warning_types.items() if marker in warning), None)
        if item_type:
            add(item_type, "warning", warning)
    if not script_status.get("human_verified"):
        add(
            "script_not_human_verified",
            "warning",
            "전처리 스크립트가 전체 사람 검수를 완료하지 않았습니다.",
        )
    return queue


def _load_resume_raw_record(root: Path, stage: str) -> dict[str, Any]:
    path = root / "raw" / f"{stage}_001.json"
    if not path.is_file():
        raise AdminSkillInputError(f"resume raw is missing: {path}")
    value = _load_json(path)
    if str(value.get("stage") or "") != stage:
        raise AdminSkillInputError(f"resume raw stage mismatch: {path}")
    parsed = value.get("parsed_output")
    if not isinstance(parsed, dict):
        raise AdminSkillInputError(f"resume raw parsed_output is missing: {path}")
    raw_output = value.get("raw_output")
    if not isinstance(raw_output, str) or not raw_output.strip():
        raw_output = json.dumps(parsed, ensure_ascii=False)
    return {**value, "path": str(path), "raw_output": raw_output}


def replay_pass_2_candidates(
    result: dict[str, Any],
    resume_from: Path,
) -> dict[str, Any]:
    """Replay immutable PASS 1/2 evidence and select one valid materialization."""
    result = validate_preprocessed_input(result)
    prepared = prepare_transcript(result)
    script = prepared["script"]
    rows = _row_map(script)
    pass_1_record = _load_resume_raw_record(resume_from, "pass_1_action_anchors")
    mode, classifications, classification_warnings = parse_classification_response(
        copy.deepcopy(pass_1_record["parsed_output"]), script
    )
    action_map = build_pass_2_action_map(prepared, classifications)
    quality_context = {
        "mode": mode,
        "duration_seconds": prepared["duration_seconds"],
    }
    records: list[tuple[str, dict[str, Any]]] = [
        ("initial", _load_resume_raw_record(resume_from, "pass_2_composition"))
    ]
    repair_path = resume_from / "raw" / "pass_2_composition_repair_001.json"
    if repair_path.is_file():
        records.append(
            ("repair", _load_resume_raw_record(resume_from, "pass_2_composition_repair"))
        )

    reports: list[dict[str, Any]] = []
    valid_candidates: list[tuple[tuple[int, ...], dict[str, Any]]] = []
    key_by_source = {
        str(item["source_utterance_id"]): str(item["action_key"])
        for item in action_map
    }
    source_positions = {
        str(row["utterance_id"]): index for index, row in enumerate(script)
    }
    duration = float(prepared["duration_seconds"])
    for candidate_name, record in records:
        try:
            plans, warnings = parse_composition_response(
                copy.deepcopy(record["parsed_output"]),
                classifications,
                rows,
                set(rows),
                allow_unaccounted=True,
                quality_context=quality_context,
                action_map=action_map,
            )
            invalid_refs = sum(
                "invalid_model" in warning or "context_only_reference" in warning
                for warning in warnings
            )
            unaccounted = sum("unaccounted" in warning for warning in warnings)
            weak_workflows = sum(
                "weak_preparation_workflow" in warning for warning in warnings
            )
            style_warnings = sum("writing_style_review" in warning for warning in warnings)
            chronological = all(
                source_positions[str(left["action_end_utterance_id"])]
                < source_positions[str(right["action_start_utterance_id"])]
                for left, right in zip(plans, plans[1:])
            )
            late_workflow = bool(
                len(plans) >= 2
                and float(plans[-1]["action_start_seconds"]) >= duration * 0.6
            )
            workflow_recoverability = min(4, len(plans))
            materialized_parts = []
            for plan in plans:
                action_keys = [
                    key_by_source[utterance_id]
                    for utterance_id in plan["step_anchor_ids"]
                    if utterance_id in key_by_source
                ]
                materialized_parts.append(
                    {
                        "title": plan["title"],
                        "action_objective": plan["action_objective"],
                        "done_state": plan["done_state"],
                        "first_action_key": action_keys[0] if action_keys else None,
                        "last_action_key": action_keys[-1] if action_keys else None,
                        "action_count": len(action_keys),
                        "source_start_utterance_id": plan["action_start_utterance_id"],
                        "source_end_utterance_id": plan["action_end_utterance_id"],
                        "source_start_seconds": plan["action_start_seconds"],
                        "source_end_seconds": plan["action_end_seconds"],
                    }
                )
            report = {
                "candidate": candidate_name,
                "valid": True,
                "part_count": len(plans),
                "major_workflow_recoverability": workflow_recoverability,
                "late_independent_workflow": late_workflow,
                "invalid_action_ref_count": invalid_refs,
                "unaccounted_action_count": unaccounted,
                "weak_preparation_workflow_count": weak_workflows,
                "writing_style_warning_count": style_warnings,
                "chronological": chronological,
                "warnings": warnings,
                "materialized_parts": materialized_parts,
            }
            score = (
                1,
                workflow_recoverability,
                int(late_workflow),
                -invalid_refs,
                -weak_workflows,
                -style_warnings,
                int(chronological),
                int(candidate_name == "repair"),
            )
            valid_candidates.append(
                (
                    score,
                    {
                        "name": candidate_name,
                        "record": record,
                        "plans": plans,
                        "warnings": warnings,
                        "report": report,
                    },
                )
            )
            reports.append(report)
        except AdminSkillResponseError as exc:
            reports.append(
                {
                    "candidate": candidate_name,
                    "valid": False,
                    "error": str(exc),
                }
            )
    if not valid_candidates:
        raise AdminSkillResponseError("resume:no_valid_pass_2_candidate")
    _, selected = max(valid_candidates, key=lambda item: item[0])
    return {
        "mode": mode,
        "prepared": prepared,
        "classifications": classifications,
        "classification_warnings": classification_warnings,
        "action_map": action_map,
        "pass_1_record": pass_1_record,
        "selected_candidate": selected["name"],
        "selected_record": selected["record"],
        "selected_plans": selected["plans"],
        "selected_warnings": selected["warnings"],
        "candidate_reports": reports,
        "selection_reason": (
            "valid materialization → workflow recoverability → late workflow → "
            "invalid refs → weak preparation → writing style → chronology → repair tie-break"
        ),
    }


class ResumeReplayGenerator:
    """Serve immutable PASS 1/2 evidence and delegate only PASS 3 model calls."""

    def __init__(self, replay: dict[str, Any], live_generator: Generator) -> None:
        self.replay = replay
        self.live_generator = live_generator
        self.pass_1_replay_calls = 0
        self.pass_2_replay_calls = 0
        self.pass_3_model_calls = 0

    def __call__(self, model: str, system: str, user: str, max_tokens: int) -> str:
        payload = json.loads(user)
        pass_name = str(payload.get("pass") or "")
        if pass_name == "PASS_1_ACTION_ANCHOR_DETECTION":
            self.pass_1_replay_calls += 1
            return str(self.replay["pass_1_record"]["raw_output"])
        if pass_name in {
            "PASS_2_ORDERED_ACTION_SEGMENTATION",
            "PASS_2_TARGETED_REPAIR",
        }:
            self.pass_2_replay_calls += 1
            return str(self.replay["selected_record"]["raw_output"])
        if pass_name in {
            "PASS_3_PER_PART_STEP_GENERATION",
            "PASS_3_TARGETED_REPAIR",
        }:
            self.pass_3_model_calls += 1
            return self.live_generator(model, system, user, max_tokens)
        raise AdminSkillInputError(f"resume:unexpected_model_pass:{pass_name or 'missing'}")


def generate_admin_skill_review(
    result: dict[str, Any],
    source_data: dict[str, Any] | None = None,
    *,
    core: Any | None = None,
    generator: Generator | None = None,
    model_name: str | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    result = validate_preprocessed_input(result)
    before = hash_preprocessed_result(result)
    started = time.perf_counter()
    model = str(model_name or DEFAULT_MODEL)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    recorder = RawDumpRecorder.from_environment()
    warnings: list[str] = []
    timing: dict[str, Any] = {
        "model_load_seconds": 0.0,
        "classification_seconds": 0.0,
        "part_composition_seconds": 0.0,
        "part_composition_repair_seconds": 0.0,
        "step_generation_seconds": 0.0,
        "step_generation_repair_seconds": 0.0,
    }

    def emit(stage: str, **details: Any) -> None:
        if progress:
            progress(stage, details)

    emit("preparing")
    prepared = prepare_transcript(result)
    chapters = prepared["script_chapters"]
    script = prepared["script"]
    rows = _row_map(script)
    source = build_source_contract(result, source_data)

    if generator is None:
        loader = getattr(core, "_load_local_llm_v032", None)
        if not callable(loader):
            raise AdminSkillInputError("existing local Qwen loader is unavailable")
        load_started = time.perf_counter()
        loader(model)
        timing["model_load_seconds"] = time.perf_counter() - load_started
    resolved_generator, generation_mode = _resolved_generator(core, generator)

    emit("classifying", utterance_count=len(script))
    classification_payload = {
        "pass": "PASS_1_ACTION_ANCHOR_DETECTION",
        "preparation": {
            "duration_seconds": prepared["duration_seconds"],
            "action_marker_count": prepared["action_marker_count"],
            "action_marker_span_count": prepared["action_marker_span_count"],
            "action_marker_utterance_ids": prepared["action_marker_utterance_ids"],
            "practice_signal_score": prepared["practice_signal_score"],
            "preliminary_mode": prepared["preliminary_mode"],
        },
        "rows": _compact_rows(script, include_chapter=False),
    }
    classification_input_chars = len(
        json.dumps(classification_payload, ensure_ascii=False, separators=(",", ":"))
    )
    classification_raw, classification_seconds, classification_output_chars = _invoke(
        resolved_generator,
        recorder,
        model_name=model,
        stage="pass_1_action_anchors",
        system_prompt=prompt,
        payload=classification_payload,
        max_tokens=2000,
    )
    timing["classification_seconds"] = classification_seconds
    mode, classifications, classification_warnings = parse_classification_response(
        classification_raw, script
    )
    warnings.extend(classification_warnings)

    anchor_ids = set(classifications)
    pass_2_context_ids = set(rows)
    emit("composing", relevant_count=len(anchor_ids))
    action_map = build_pass_2_action_map(prepared, classifications)
    composition_payload = build_pass_2_payload(mode, prepared, classifications)
    composition_input_chars = len(
        json.dumps(composition_payload, ensure_ascii=False, separators=(",", ":"))
    )
    composition_input_row_count = len(composition_payload["ordered_actions"]) + int(
        composition_payload["scale_context"]["context_snippet_count"]
    )
    ordered_action_ids = [
        str(item["source_utterance_id"])
        for item in action_map
    ]
    composition_quality_context = {
        "mode": mode,
        "duration_seconds": prepared["duration_seconds"],
    }
    composition_raw, composition_seconds, _ = _invoke(
        resolved_generator,
        recorder,
        model_name=model,
        stage="pass_2_composition",
        system_prompt=prompt,
        payload=composition_payload,
        max_tokens=7000,
    )
    timing["part_composition_seconds"] = composition_seconds
    composition_repair_count = 0
    plans: list[dict[str, Any]] = []
    composition_warnings: list[str] = []
    try:
        plans, composition_warnings = parse_composition_response(
            composition_raw,
            classifications,
            rows,
            pass_2_context_ids,
            quality_context=composition_quality_context,
            action_map=action_map,
        )
        quality_floor_warning = next(
            (
                warning
                for warning in composition_warnings
                if warning.startswith(
                    (
                        "composition:one_workflow_quality_floor",
                        "composition:too_few_workflow_boundaries",
                        "composition:weak_preparation_workflow",
                        "composition:possible_missing_workflow_boundary",
                    )
                )
            ),
            None,
        )
        if quality_floor_warning:
            raise AdminSkillResponseError(quality_floor_warning)
    except AdminSkillResponseError as exc:
        composition_repair_count = 1
        emit("repairing_composition", reason=str(exc))
        split_keys = [
            warning.split(":", 3)[2]
            for warning in composition_warnings
            if warning.startswith("composition:possible_missing_workflow_boundary:")
        ]
        action_positions = {
            str(item["action_key"]): index for index, item in enumerate(action_map)
        }
        tail_actions: list[dict[str, Any]] = []
        for action_key in split_keys:
            start = action_positions.get(action_key)
            if start is None:
                continue
            tail_actions.extend(
                {
                    "action_key": item["action_key"],
                    "time": format_timestamp(float(item["start_seconds"])),
                    "text": item["text"],
                }
                for item in action_map[start : start + 8]
            )
        repair_payload = {
            "pass": "PASS_2_TARGETED_REPAIR",
            "validation_error": str(exc),
            "current_boundaries": [
                {
                    "start_action_key": plan.get("boundary_action_key"),
                    "title": plan["title"],
                    "done_state": plan["done_state"],
                    "primary_tool_or_surface": plan.get("primary_tool_or_surface"),
                }
                for plan in plans
            ],
            "quality_hints": [
                warning
                for warning in composition_warnings
                if warning.startswith(
                    (
                        "composition:one_workflow_quality_floor",
                        "composition:too_few_workflow_boundaries",
                        "composition:weak_preparation_workflow",
                        "composition:possible_missing_workflow_boundary",
                    )
                )
            ],
            "candidate_late_split_actions": tail_actions,
            "ordered_actions": composition_payload["ordered_actions"],
            "required_output_schema": {
                "workflow_boundaries": [
                    {
                        "start_action_key": "A01",
                        "title": "string",
                        "action_objective": "string",
                        "done_state": "string",
                        "primary_tool_or_surface": "string",
                    }
                ],
                "auxiliary_actions": [
                    {
                        "action_key": "A02",
                        "reason_category": "string",
                        "attach_to_previous_or_next": "previous|next",
                    }
                ],
                "excluded_actions": [
                    {
                        "action_key": "A03",
                        "reason_category": "string",
                        "reason": "string",
                    }
                ],
            },
            "repair_constraints": [
                "Return the PASS 2 ordered-boundary schema only.",
                "Reference only action_key values present in ordered_actions; never output source utterance IDs.",
                "Context text is read-only evidence and cannot be classified or selected.",
                "Return only start_action_key boundaries for independently completable workflows; never return member lists.",
                "The first boundary must be the first core action after auxiliary and excluded decisions.",
                "Boundary action keys must exist in ordered_actions and be strictly increasing.",
                "Multiple independently useful done states were collapsed; add a boundary at each distinct done state.",
                "Recheck a supplied candidate late split when the tail has an independent completed result.",
                "Attach a weak preparation-only workflow to its adjacent workflow unless it has an independently useful result.",
                "Do not return source ranges or workflow anchor lists; Python computes membership and spans.",
                "Connected setup, data/configuration creation, and implementation may be separate workflows when their done states differ.",
                "A primary tool/surface, output type, import/export, or user-purpose change is a strong boundary.",
                "Attach cleanup, naming, reference, and minor supporting settings as auxiliary actions unless independently useful.",
                "For a 15-40 minute practice video with many actions, 3-5 workflows is a strong heuristic, never a quota.",
            ],
        }
        composition_raw, repair_seconds, _ = _invoke(
            resolved_generator,
            recorder,
            model_name=model,
            stage="pass_2_composition_repair",
            system_prompt=prompt,
            payload=repair_payload,
            max_tokens=7000,
        )
        timing["part_composition_repair_seconds"] = repair_seconds
        plans, composition_warnings = parse_composition_response(
            composition_raw,
            classifications,
            rows,
            pass_2_context_ids,
            allow_unaccounted=True,
            quality_context=composition_quality_context,
            action_map=action_map,
        )
    warnings.extend(composition_warnings)
    supplemental_action_ids = _ordered_unique(
        [
            utterance_id
            for plan in plans
            for utterance_id in plan.get("supplemental_step_anchor_ids", [])
        ]
        + [
            warning.split(":", 2)[-1]
            for warning in composition_warnings
            if warning.startswith("composition:supplemental_action_anchor:")
        ],
        rows,
    )

    parts: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    unused_ids: list[str] = []
    step_call_seconds: list[float] = []
    step_repair_seconds: list[float] = []
    step_repair_count = 0
    for index, plan in enumerate(plans, 1):
        emit("writing_steps", part_index=index, part_count=len(plans), title=plan["title"])
        part_ids = set(plan["context_utterance_ids"])
        step_payload = {
            "pass": "PASS_3_PER_PART_STEP_GENERATION",
            "part": {
                key: plan[key]
                for key in (
                    "title",
                    "action_objective",
                    "done_state",
                    "step_anchor_ids",
                )
            },
            "action_span": {
                "start_utterance_id": plan["action_start_utterance_id"],
                "end_utterance_id": plan["action_end_utterance_id"],
                "start_seconds": plan["action_start_seconds"],
                "end_seconds": plan["action_end_seconds"],
            },
            "rows": _compact_rows(
                script,
                labels=classifications,
                allowed_ids=part_ids,
                include_chapter=False,
            ),
        }
        try:
            step_raw, step_seconds, _ = _invoke(
                resolved_generator,
                recorder,
                model_name=model,
                stage=f"pass_3_part_{index:02d}",
                system_prompt=prompt,
                payload=step_payload,
                max_tokens=6000,
            )
            step_call_seconds.append(step_seconds)
            steps, checkpoint, excluded, step_warnings = parse_step_response(
                step_raw, plan, rows, allow_unaccounted=True
            )
        except Exception as exc:
            steps = []
            checkpoint = None
            excluded = []
            step_warnings = [f"initial_step_response_unusable:{exc}"]
        unresolved = _unaccounted_step_anchor_ids(plan, steps, excluded, rows)
        if unresolved:
            step_repair_count += 1
            emit(
                "repairing_steps",
                part_index=index,
                part_count=len(plans),
                unaccounted_anchor_ids=unresolved,
            )
            repair_plan = {
                **plan,
                "step_anchor_ids": unresolved,
                "context_utterance_ids": unresolved,
            }
            repair_payload = {
                "pass": "PASS_3_TARGETED_REPAIR",
                "part": {
                    "title": plan["title"],
                    "action_objective": plan["action_objective"],
                    "done_state": plan["done_state"],
                },
                "unaccounted_anchor_ids": unresolved,
                "rows": _compact_rows(
                    script,
                    labels=classifications,
                    allowed_ids=set(unresolved),
                    include_chapter=False,
                ),
                "repair_constraints": [
                    "Return only additional STEPs or explicit exclusions for the supplied anchors.",
                    "Do not rewrite or repeat already valid STEPs.",
                    "Account for each supplied anchor once.",
                ],
            }
            try:
                repair_raw, repair_seconds, _ = _invoke(
                    resolved_generator,
                    recorder,
                    model_name=model,
                    stage=f"pass_3_part_{index:02d}_repair",
                    system_prompt=prompt,
                    payload=repair_payload,
                    max_tokens=2500,
                )
                step_repair_seconds.append(repair_seconds)
                repair_steps, repair_checkpoint, repair_excluded, repair_warnings = (
                    parse_step_response(
                        repair_raw,
                        repair_plan,
                        rows,
                        allow_unaccounted=True,
                    )
                )
                steps.extend(repair_steps)
                excluded = _ordered_unique(excluded + repair_excluded, rows)
                if checkpoint is None and repair_checkpoint is not None:
                    checkpoint = repair_checkpoint
                step_warnings.extend(
                    f"targeted_repair:{warning}" for warning in repair_warnings
                )
            except Exception as exc:
                step_warnings.append(f"targeted_repair_failed:{exc}")
            unresolved = _unaccounted_step_anchor_ids(plan, steps, excluded, rows)
        warnings.extend(f"part_{index:02d}:{warning}" for warning in step_warnings)
        unused_ids.extend(excluded + unresolved)
        if not steps:
            warnings.append(f"part_{index:02d}:zero_step_part_preserved")
        part = _materialize_part(
            plan,
            steps,
            checkpoint,
            rows,
            result,
            excluded_ids=excluded,
            unresolved_ids=unresolved,
        )
        parts.append(part)
        if checkpoint:
            checkpoints.append({"part_index": len(parts) - 1, **checkpoint})
    timing["step_generation_seconds"] = sum(step_call_seconds)
    timing["step_generation_repair_seconds"] = sum(step_repair_seconds)
    if not parts:
        raise AdminSkillResponseError("generation:no_supported_parts")

    _renumber(parts)
    for checkpoint in checkpoints:
        checkpoint["part_id"] = parts[int(checkpoint.pop("part_index"))]["part_id"]
    _canonicalize_generated_names(parts, None, [], [], [], script)
    _attach_script_part_membership(script, parts)

    actionable_ids = (
        set(ordered_action_ids)
        if "workflow_boundaries" in composition_raw
        else {
            key
            for key, value in classifications.items()
            if value["label"] in {"STEP", "STEP_PREVIEW"}
        }
    )
    pass_2_assigned_ids = {
        value for plan in plans for value in plan["step_anchor_ids"]
    }
    explicitly_excluded_ids = {
        warning.split(":", 4)[2]
        for warning in composition_warnings
        if warning.startswith("composition:excluded_anchor:")
    }
    pass_2_unassigned_ids = _ordered_unique(
        list(actionable_ids - pass_2_assigned_ids - explicitly_excluded_ids), rows
    )
    unused_ids = _ordered_unique(
        unused_ids + pass_2_unassigned_ids, rows
    )
    action_phases, unassigned_phases = _project_phases(
        parts, pass_2_unassigned_ids, classifications, rows
    )
    script_status = _script_review_status(result)
    queue = _review_queue(parts, unassigned_phases, checkpoints, warnings, script_status)
    review_reasons = list(
        dict.fromkeys(
            [f"{item['type']}:{item['review_id']}" for item in queue]
        )
    )
    model_seconds = (
        timing["classification_seconds"]
        + timing["part_composition_seconds"]
        + timing["part_composition_repair_seconds"]
        + timing["step_generation_seconds"]
        + timing["step_generation_repair_seconds"]
    )
    total_runtime = time.perf_counter() - started
    classification_counts = {
        label: sum(value["label"] == label for value in classifications.values())
        for label in sorted(CLASSIFICATION_LABELS)
    }
    generation = {
        "schema_version": CURATION_GENERATION_SCHEMA_VERSION,
        "status": "completed_with_review" if queue else "completed",
        "model": model,
        "pass_architecture": [
            "PASS_0_TRANSCRIPT_PREPARATION",
            "PASS_1_ACTION_ANCHOR_DETECTION",
            "PASS_2_PART_COMPOSITION",
            "PASS_3_PER_PART_STEP_GENERATION",
        ],
        "part_planning_calls": 2 + composition_repair_count,
        "action_phase_discovery_calls": 0,
        "part_composition_calls": 1 + composition_repair_count,
        "step_generation_calls": len(plans) + step_repair_count,
        "step_generation_initial_calls": len(plans),
        "step_generation_retry_calls": step_repair_count,
        "video_detail_calls": 0,
        "total_model_calls": 2 + composition_repair_count + len(plans) + step_repair_count,
        "model_generation_seconds": model_seconds,
        "total_runtime_seconds": total_runtime,
        "created_at": _utc_now(),
        "warnings": warnings,
        "needs_review_count": len(review_reasons),
        "review_reasons": review_reasons,
        "omitted_part_candidates": [],
        "high_action_coverage_warnings": [
            {
                "content_chapter_id": rows[value].get("script_chapter_id"),
                "action_utterance_ids": [value],
                "reason": "classified_action_unassigned_after_step_generation",
            }
            for value in unused_ids
        ],
        "phase_accounting": [
            {
                "part_id": part["part_id"],
                "phases": [],
                "phase_count": sum(
                    phase["assigned_part_id"] == part["part_id"] for phase in action_phases
                ),
                "assigned_phase_indices": [
                    index
                    for index, phase in enumerate(action_phases)
                    if phase["assigned_part_id"] == part["part_id"]
                ],
                "excluded_phases": [],
                "unassigned_phase_indices": [],
            }
            for part in parts
        ],
        "posthoc_chapter_copy_audit": audit_posthoc_chapter_copies(parts, chapters, result),
        "recommendation_accounting": {
            "claim_count": 0,
            "prose_sentence_count": 0,
            "unaccounted_prose_claims": [],
        },
        "script_review_status": script_status,
        "deterministic_generation": generation_mode,
        "source_preprocessed_sha256": before,
        "admin_skill": {
            "schema_version": "ddock_admin_skill_generation_v0.1",
            "mode": mode,
            "preparation": {
                key: prepared[key]
                for key in (
                    "duration_seconds",
                    "action_marker_count",
                    "action_marker_span_count",
                    "practice_signal_score",
                    "preliminary_mode",
                )
            },
            "classification_counts": classification_counts,
            "classification_input_chars": classification_input_chars,
            "classification_input_token_estimate": (classification_input_chars + 3) // 4,
            "classification_output_chars": classification_output_chars,
            "pass_2_role": "ordered_action_segmentation",
            "pass_2_input_chars": composition_input_chars,
            "pass_2_input_token_estimate": (composition_input_chars + 3) // 4,
            "pass_2_input_row_count": composition_input_row_count,
            "pass_2_action_anchor_count": sum(
                item["candidate_kind"] == "pass_1_seed" for item in action_map
            ),
            "pass_2_supplemental_candidate_count": sum(
                item["candidate_kind"] == "supplemental_candidate"
                for item in action_map
            ),
            "pass_2_context_row_count": int(
                composition_payload["scale_context"]["context_snippet_count"]
            ),
            "pass_2_ordered_sequence_size": len(ordered_action_ids),
            "pass_2_boundary_count": len(plans),
            "pass_2_interleaving_possible": False,
            "anchor_count": len(classifications),
            "seed_action_anchor_count": len(classifications),
            "supplemental_action_anchor_count": len(supplemental_action_ids),
            "supplemental_action_utterance_ids": supplemental_action_ids,
            "final_action_anchor_count": len(
                set(classifications).union(supplemental_action_ids)
            ),
            "step_anchor_count": len(classification_raw["step_ids"]),
            "step_preview_anchor_count": len(classification_raw["step_preview_ids"]),
            "warning_anchor_count": 0,
            "checkpoint_anchor_count": 0,
            "pass_2_targeted_repair_count": composition_repair_count,
            "pass_3_targeted_repair_count": step_repair_count,
            "checkpoint_count": len(checkpoints),
            "checkpoints": checkpoints,
            "timing": timing,
            "unused_action_utterance_ids": unused_ids,
            "external_llm_api_calls": 0,
            "web_requests": 0,
        },
    }
    emit("finalizing")
    review = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "source": source,
        "video_detail": {
            "recommendation": None,
            "tools": [],
            "tags": [],
            "part_preview": _part_preview(parts),
        },
        "script_chapters": chapters,
        "script": script,
        "draft_parts": parts,
        "action_phases": action_phases,
        "unassigned_phases": unassigned_phases,
        "review_queue": queue,
        "curation_generation": generation,
    }
    report = validate_ddock_content_review(review)
    if report["errors"]:
        raise AdminSkillResponseError(
            "review_validation_failed:" + ";".join(report["errors"])
        )
    if hash_preprocessed_result(result) != before:
        raise RuntimeError("preprocessed_result_mutated_during_admin_skill_generation")
    emit("complete", part_count=len(parts), step_count=sum(len(part["steps"]) for part in parts))
    return review


def resume_admin_skill_review(
    result: dict[str, Any],
    resume_from: Path,
    source_data: dict[str, Any] | None = None,
    *,
    core: Any | None = None,
    generator: Generator | None = None,
    model_name: str | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Resume from immutable PASS 1/2 raw evidence and run PASS 3 only."""
    resume_started = time.perf_counter()
    result = validate_preprocessed_input(result)
    replay = replay_pass_2_candidates(result, resume_from)
    if progress:
        progress(
            "replaying_pass_2",
            {
                "selected_candidate": replay["selected_candidate"],
                "candidate_count": len(replay["candidate_reports"]),
                "part_count": len(replay["selected_plans"]),
            },
        )
    model = str(model_name or DEFAULT_MODEL)
    model_load_seconds = 0.0
    if generator is None:
        loader = getattr(core, "_load_local_llm_v032", None)
        if not callable(loader):
            raise AdminSkillInputError("existing local Qwen loader is unavailable")
        load_started = time.perf_counter()
        loader(model)
        model_load_seconds = time.perf_counter() - load_started
    live_generator, generation_mode = _resolved_generator(core, generator)
    replay_generator = ResumeReplayGenerator(replay, live_generator)
    review = generate_admin_skill_review(
        result,
        source_data,
        core=core,
        generator=replay_generator,
        model_name=model,
        progress=progress,
    )
    generation = review["curation_generation"]
    skill = generation["admin_skill"]
    timing = skill["timing"]
    timing["model_load_seconds"] = model_load_seconds
    timing["classification_seconds"] = 0.0
    timing["part_composition_seconds"] = 0.0
    timing["part_composition_repair_seconds"] = 0.0
    pass_3_seconds = float(timing["step_generation_seconds"]) + float(
        timing["step_generation_repair_seconds"]
    )
    generation["part_planning_calls"] = 0
    generation["part_composition_calls"] = 0
    generation["total_model_calls"] = replay_generator.pass_3_model_calls
    generation["model_generation_seconds"] = pass_3_seconds
    generation["total_runtime_seconds"] = time.perf_counter() - resume_started
    generation["deterministic_generation"] = generation_mode
    skill["pass_2_targeted_repair_count"] = 0
    skill["resume"] = {
        "source_actual_directory": str(resume_from.resolve()),
        "pass_1_model_calls": 0,
        "pass_2_model_calls": 0,
        "pass_3_model_calls": replay_generator.pass_3_model_calls,
        "pass_1_raw_replay_count": replay_generator.pass_1_replay_calls,
        "pass_2_raw_replay_count": replay_generator.pass_2_replay_calls,
        "source_actual_pass_2_repair_present": any(
            report.get("candidate") == "repair"
            for report in replay["candidate_reports"]
        ),
        "selected_candidate": replay["selected_candidate"],
        "selection_reason": replay["selection_reason"],
        "candidate_reports": replay["candidate_reports"],
        "materialized_parts": next(
            report["materialized_parts"]
            for report in replay["candidate_reports"]
            if report.get("candidate") == replay["selected_candidate"]
        ),
    }
    report = validate_ddock_content_review(review)
    if report["errors"]:
        raise AdminSkillResponseError(
            "resume_review_validation_failed:" + ";".join(report["errors"])
        )
    return review


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdminSkillInputError(f"{path}: JSON root must be an object")
    return value


def _stream_progress(stage: str, details: dict[str, Any]) -> None:
    print(
        json.dumps({"type": "progress", "stage": stage, **details}, ensure_ascii=False),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local AI admin review draft")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--preprocessed", type=Path)
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Replay immutable PASS 1/2 raw evidence and invoke only PASS 3",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    if args.stdin:
        loaded = json.load(sys.stdin)
        if not isinstance(loaded, dict):
            raise AdminSkillInputError("stdin JSON root must be an object")
        result = loaded
    else:
        result = _load_json(args.preprocessed)
    source_data = _load_json(args.source) if args.source else None
    from v0315_1_patch import apply

    core = apply()
    if args.resume_from:
        review = resume_admin_skill_review(
            result,
            args.resume_from,
            source_data,
            core=core,
            model_name=args.model,
            progress=_stream_progress if args.stream else None,
        )
    else:
        review = generate_admin_skill_review(
            result,
            source_data,
            core=core,
            model_name=args.model,
            progress=_stream_progress if args.stream else None,
        )
    if args.output:
        atomic_write_json(args.output, review)
    if args.stream:
        print(json.dumps({"type": "result", "review": review}, ensure_ascii=False), flush=True)
    else:
        print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if "--stream" in sys.argv:
            print(
                json.dumps(
                    {"type": "error", "message": str(exc), "error_type": type(exc).__name__},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        raise
