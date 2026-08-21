from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timezone
from typing import Any


CONTENT_CHAPTER_SCHEMA_VERSION = "content_chapters_v0.1"
CONTENT_CHAPTER_METHOD = "deterministic_available_scope_seed_v0.1"
CONTENT_CHAPTER_DECISION_CRITERIA = (
    "single_clear_topic_or_work_step",
    "distinct_user_benefit_from_neighboring_sections",
    "independent_example_process_result_or_explanation",
    "worth_revisiting_as_a_learning_card",
    "visual_or_workflow_transition_supported_by_meaning_change",
)

_CREATOR_CHAPTER_ID_RE = re.compile(r"^CH-\d+$")
_BOUNDARY_TOLERANCE_SECONDS = 1e-6


def _as_seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def format_timestamp(seconds: Any) -> str:
    value = _as_seconds(seconds)
    if value is None:
        return ""
    total = int(value)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def analyze_source_scope(result: dict[str, Any]) -> dict[str, Any]:
    processed = result.get("processed_chapter") or {}
    processed_id = str(processed.get("chapter_id") or "").strip()
    translation_scope = str(result.get("translation_scope") or "").strip().lower()
    evidence: list[str] = []
    warnings: list[str] = []

    if processed_id == "FULL":
        evidence.append("processed_chapter.chapter_id=FULL")
        if translation_scope:
            evidence.append(f"translation_scope={translation_scope}")
        return {
            "source_scope": "whole_video",
            "evidence": evidence,
            "warnings": warnings,
        }

    if processed_id:
        evidence.append(f"processed_chapter.chapter_id={processed_id}")
        if translation_scope == "whole_video":
            warnings.append(
                "translation_scope_whole_video_conflicts_with_non_full_processed_chapter"
            )
        return {
            "source_scope": "processed_chapter_only",
            "evidence": evidence,
            "warnings": warnings,
        }

    if translation_scope == "whole_video":
        evidence.append("translation_scope=whole_video")
        return {
            "source_scope": "whole_video",
            "evidence": evidence,
            "warnings": warnings,
        }

    if translation_scope == "chapter":
        evidence.append("translation_scope=chapter")
        return {
            "source_scope": "processed_chapter_only",
            "evidence": evidence,
            "warnings": warnings,
        }

    warnings.append("source_scope_cannot_be_proven_from_current_result")
    return {
        "source_scope": "unknown",
        "evidence": evidence,
        "warnings": warnings,
    }


def _valid_utterances(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for item in result.get("normalized_utterances", []) or []:
        if not isinstance(item, dict):
            warnings.append("ignored_non_object_normalized_utterance")
            continue
        utterance_id = str(item.get("utterance_id") or "").strip()
        start = _as_seconds(item.get("start_seconds"))
        end = _as_seconds(item.get("end_seconds"))
        if not utterance_id or start is None or end is None or end < start:
            warnings.append("ignored_utterance_without_valid_id_or_timestamp")
            continue
        if utterance_id in seen_ids:
            warnings.append(f"ignored_duplicate_utterance_id:{utterance_id}")
            continue
        seen_ids.add(utterance_id)
        valid.append(
            {
                "utterance_id": utterance_id,
                "start_seconds": start,
                "end_seconds": end,
                "normalized_text": str(item.get("normalized_text") or ""),
                "final_normalized_text": str(
                    item.get("final_normalized_text")
                    or item.get("normalized_text")
                    or ""
                ),
                "raw_joined_text": str(item.get("raw_joined_text") or ""),
                "chapter_id": item.get("chapter_id"),
                "creator_chapter_id": item.get("creator_chapter_id"),
                "chapter_label": item.get("chapter_label"),
                "chapter_index": item.get("chapter_index"),
                "chapter_assignment_status": item.get(
                    "chapter_assignment_status"
                ),
                "validation_warnings": copy.deepcopy(
                    item.get("validation_warnings") or []
                ),
                "translation_quality_warnings": copy.deepcopy(
                    item.get("translation_quality_warnings") or []
                ),
                "source_asr_review_warnings": copy.deepcopy(
                    item.get("source_asr_review_warnings") or []
                ),
                "semantic_audit_warnings": copy.deepcopy(
                    item.get("semantic_audit_warnings") or []
                ),
            }
        )

    valid.sort(
        key=lambda row: (
            row["start_seconds"],
            row["end_seconds"],
            row["utterance_id"],
        )
    )
    return valid, warnings


def _creator_chapter_hints(
    result: dict[str, Any],
    source_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    source = source_data if isinstance(source_data, dict) else {}
    chapters = source.get("creator_chapters")
    if not isinstance(chapters, list):
        chapters = result.get("creator_chapters")
    if not isinstance(chapters, list):
        return []

    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    duration = _as_seconds(metadata.get("duration_seconds"))
    hints: list[dict[str, Any]] = []
    starts = [
        _as_seconds(item.get("start_seconds")) if isinstance(item, dict) else None
        for item in chapters
    ]

    for index, item in enumerate(chapters):
        if not isinstance(item, dict):
            continue
        start = starts[index]
        if start is None:
            continue
        end = _as_seconds(item.get("end_seconds"))
        if end is None and index + 1 < len(starts):
            end = starts[index + 1]
        if end is None:
            end = duration
        if end is not None and end < start:
            end = None
        chapter_id = str(item.get("chapter_id") or f"CH-{index + 1:02d}")
        hints.append(
            {
                "chapter_id": chapter_id,
                "chapter_index": index,
                "title": str(item.get("label") or item.get("title") or ""),
                "start_seconds": start,
                "end_seconds": end,
            }
        )
    return hints


def _source_creator_chapter_ids(
    utterances: list[dict[str, Any]],
    creator_hints: list[dict[str, Any]],
    start: float,
    end: float,
) -> list[str]:
    found: list[str] = []

    def add(value: Any) -> None:
        chapter_id = str(value or "").strip()
        if _CREATOR_CHAPTER_ID_RE.fullmatch(chapter_id) and chapter_id not in found:
            found.append(chapter_id)

    for utterance in utterances:
        add(utterance.get("creator_chapter_id"))
        add(utterance.get("chapter_id"))

    for hint in creator_hints:
        hint_start = _as_seconds(hint.get("start_seconds"))
        hint_end = _as_seconds(hint.get("end_seconds"))
        if hint_start is None:
            continue
        overlaps = hint_start < end and (hint_end is None or hint_end > start)
        if overlaps:
            add(hint.get("chapter_id"))
    return found


def build_segmentation_payload(
    result: dict[str, Any],
    source_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope = analyze_source_scope(result)
    utterances, utterance_warnings = _valid_utterances(result)
    creator_hints = _creator_chapter_hints(result, source_data)
    timestamp_range = None
    if utterances:
        timestamp_range = {
            "start_seconds": utterances[0]["start_seconds"],
            "end_seconds": max(item["end_seconds"] for item in utterances),
        }

    return {
        "source_scope": scope["source_scope"],
        "scope_evidence": list(scope["evidence"]),
        "warnings": list(scope["warnings"]) + utterance_warnings,
        "processed_chapter": copy.deepcopy(result.get("processed_chapter") or {}),
        "creator_chapter_hints": copy.deepcopy(creator_hints),
        "available_timestamp_range": timestamp_range,
        "utterances": copy.deepcopy(utterances),
        "decision_criteria": list(CONTENT_CHAPTER_DECISION_CRITERIA),
        "constraints": {
            "boundaries_must_use_utterance_start_or_end": True,
            "utterances_must_not_be_split": True,
            "creator_chapters_are_hints_not_required_output_boundaries": True,
            "do_not_claim_whole_video_when_scope_is_partial_or_unknown": True,
        },
    }


def validate_content_chapters(result: dict[str, Any]) -> list[str]:
    chapters = result.get("content_chapters", [])
    if not isinstance(chapters, list):
        return ["content_chapters_must_be_a_list"]

    utterances, _ = _valid_utterances(result)
    by_id = {item["utterance_id"]: item for item in utterances}
    position_by_id = {
        item["utterance_id"]: index for index, item in enumerate(utterances)
    }
    allowed_starts = [item["start_seconds"] for item in utterances]
    allowed_ends = [item["end_seconds"] for item in utterances]
    global_start = min(allowed_starts) if allowed_starts else None
    global_end = max(allowed_ends) if allowed_ends else None
    seen_ids: set[str] = set()
    previous_end: float | None = None
    previous_source_max_position: int | None = None
    warnings: list[str] = []

    def matches(value: float, candidates: list[float]) -> bool:
        return any(abs(value - candidate) <= _BOUNDARY_TOLERANCE_SECONDS for candidate in candidates)

    for expected_index, chapter in enumerate(chapters):
        prefix = f"content_chapters[{expected_index}]"
        if not isinstance(chapter, dict):
            warnings.append(f"{prefix}:must_be_an_object")
            continue
        chapter_id = str(chapter.get("content_chapter_id") or "")
        if not chapter_id or chapter_id in seen_ids:
            warnings.append(f"{prefix}:missing_or_duplicate_id")
        seen_ids.add(chapter_id)
        if chapter.get("chapter_index") != expected_index:
            warnings.append(f"{prefix}:chapter_index_mismatch")

        start = _as_seconds(chapter.get("start_seconds"))
        end = _as_seconds(chapter.get("end_seconds"))
        if start is None or end is None or end < start:
            warnings.append(f"{prefix}:invalid_timestamp_range")
            continue
        if global_start is not None and start < global_start - _BOUNDARY_TOLERANCE_SECONDS:
            warnings.append(f"{prefix}:starts_before_available_transcript")
        if global_end is not None and end > global_end + _BOUNDARY_TOLERANCE_SECONDS:
            warnings.append(f"{prefix}:ends_after_available_transcript")
        if not matches(start, allowed_starts):
            warnings.append(f"{prefix}:start_is_not_an_utterance_boundary")
        if not matches(end, allowed_ends):
            warnings.append(f"{prefix}:end_is_not_an_utterance_boundary")
        source_ids = chapter.get("source_utterance_ids")
        if not isinstance(source_ids, list) or not source_ids:
            warnings.append(f"{prefix}:missing_source_utterance_ids")
            continue
        current_source_positions = [
            position_by_id[str(utterance_id)]
            for utterance_id in source_ids
            if str(utterance_id) in position_by_id
        ]
        if current_source_positions:
            ordered_source_positions = sorted(current_source_positions)
            first_source = utterances[ordered_source_positions[0]]
            last_source = utterances[ordered_source_positions[-1]]
            if (
                abs(start - first_source["start_seconds"])
                > _BOUNDARY_TOLERANCE_SECONDS
            ):
                warnings.append(
                    f"{prefix}:start_does_not_match_first_source_utterance"
                )
            if (
                abs(end - last_source["end_seconds"])
                > _BOUNDARY_TOLERANCE_SECONDS
            ):
                warnings.append(
                    f"{prefix}:end_does_not_match_last_source_utterance"
                )
        if (
            previous_end is not None
            and start < previous_end - _BOUNDARY_TOLERANCE_SECONDS
            and (
                not current_source_positions
                or previous_source_max_position is None
                or min(current_source_positions) <= previous_source_max_position
            )
        ):
            warnings.append(f"{prefix}:overlaps_previous_content_chapter")
        for utterance_id in source_ids:
            source = by_id.get(str(utterance_id))
            if source is None:
                warnings.append(f"{prefix}:unknown_source_utterance_id:{utterance_id}")
                continue
            if (
                source["start_seconds"] < start - _BOUNDARY_TOLERANCE_SECONDS
                or source["end_seconds"] > end + _BOUNDARY_TOLERANCE_SECONDS
            ):
                warnings.append(f"{prefix}:source_utterance_outside_chapter:{utterance_id}")

        previous_end = end
        if current_source_positions:
            previous_source_max_position = max(current_source_positions)

        if chapter.get("start_timestamp") != format_timestamp(start):
            warnings.append(f"{prefix}:start_timestamp_mismatch")
        if chapter.get("end_timestamp") != format_timestamp(end):
            warnings.append(f"{prefix}:end_timestamp_mismatch")

    return warnings


def add_content_chapter_foundation(
    result: dict[str, Any],
    source_data: dict[str, Any] | None = None,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError("preprocessing result must be a dictionary")

    output = copy.deepcopy(result)
    if "content_chapters" in output:
        if "content_chapter_generation" not in output:
            output["content_chapter_generation"] = {
                "schema_version": CONTENT_CHAPTER_SCHEMA_VERSION,
                "status": "needs_review",
                "method": "preserve_existing_content_chapters",
                "source_scope": analyze_source_scope(output)["source_scope"],
                "scope_evidence": analyze_source_scope(output)["evidence"],
                "created_at": created_at or datetime.now(timezone.utc).isoformat(),
                "warnings": ["existing_content_chapters_missing_generation_metadata"],
                "semantic_split_applied": False,
                "llm_invoked": False,
                "decision_criteria": list(CONTENT_CHAPTER_DECISION_CRITERIA),
            }
        return output

    payload = build_segmentation_payload(output, source_data)
    generation = {
        "schema_version": CONTENT_CHAPTER_SCHEMA_VERSION,
        "status": "skipped",
        "method": CONTENT_CHAPTER_METHOD,
        "source_scope": payload["source_scope"],
        "scope_evidence": payload["scope_evidence"],
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "warnings": list(payload["warnings"]),
        "semantic_split_applied": False,
        "llm_invoked": False,
        "decision_criteria": list(CONTENT_CHAPTER_DECISION_CRITERIA),
    }
    output["content_chapters"] = []
    output["content_chapter_generation"] = generation

    if payload["source_scope"] == "unknown":
        generation["warnings"].append("content_chapters_skipped_for_unknown_scope")
        return output

    utterances = payload["utterances"]
    if not utterances:
        generation["warnings"].append("content_chapters_skipped_without_timestamped_utterances")
        return output

    start = utterances[0]["start_seconds"]
    end = max(item["end_seconds"] for item in utterances)
    processed = payload["processed_chapter"]
    processed_label = str(processed.get("label") or "").strip()
    if payload["source_scope"] == "whole_video":
        title = "전체 처리 범위 · 의미 분할 검토 필요"
    elif processed_label:
        title = f"{processed_label} · 의미 분할 검토 필요"
    else:
        title = "현재 처리 범위 · 의미 분할 검토 필요"

    output["content_chapters"] = [
        {
            "content_chapter_id": "CCH-01",
            "chapter_index": 0,
            "title": title,
            "start_seconds": start,
            "end_seconds": end,
            "start_timestamp": format_timestamp(start),
            "end_timestamp": format_timestamp(end),
            "summary": (
                "사용 가능한 normalized utterance 전체를 보존한 초기 범위입니다. "
                "의미 기반 분할과 최종 요약은 아직 적용되지 않았습니다."
            ),
            "source_utterance_ids": [item["utterance_id"] for item in utterances],
            "source_creator_chapter_ids": _source_creator_chapter_ids(
                utterances,
                payload["creator_chapter_hints"],
                start,
                end,
            ),
            "boundary_reason": "available_scope_start_and_end_utterance_boundaries",
            "confidence": 0.0,
            "needs_review": True,
        }
    ]
    generation["status"] = "needs_review"
    generation["warnings"].append("semantic_content_segmentation_not_run")
    validation_warnings = validate_content_chapters(output)
    if validation_warnings:
        output["content_chapters"] = []
        generation["status"] = "failed"
        generation["warnings"].extend(validation_warnings)
    return output
