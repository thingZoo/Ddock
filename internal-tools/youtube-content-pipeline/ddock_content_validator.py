from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Iterable

from ddock_content_contract import (
    ACTION_LINE_FIELDS,
    EVIDENCE_FIELDS,
    EXCLUDED_ACTION_FIELDS,
    FORBIDDEN_MVP_FIELDS,
    GENERATION_FIELDS,
    LEARN_MORE_FIELDS,
    PART_FIELDS,
    PART_PREVIEW_FIELDS,
    PROMPT_FIELDS,
    RECOMMENDATION_FIELDS,
    RECOMMENDATION_CLAIM_FIELDS,
    RICH_SEGMENT_TYPES,
    SCHEMA_VERSION,
    SCRIPT_CHAPTER_FIELDS,
    SCRIPT_ROW_FIELDS,
    SEGMENT_FIELDS,
    SOURCE_FIELDS,
    STEP_FIELDS,
    THUMBNAIL_FIELDS,
    TOOL_FIELDS,
    TOP_LEVEL_FIELDS,
    VIDEO_DETAIL_FIELDS,
    WARNING_FIELDS,
)


_ACTION_SIGNAL = re.compile(
    r"열|들어가|접속|클릭|누르|버튼|입력|붙여|작성|복사|가져오|"
    r"불러오|추출|선택|고르|지정|연결|추가|설치|등록|생성|만들|"
    r"구성|구축|구현|실행|빌드|요청|적용|확인|검토|비교|수정|변경|저장"
)
_DIRECT_OPERATION_SIGNAL = re.compile(
    r"클릭|누르|버튼|입력|붙여|복사|선택|연결|추가|설치|등록|"
    r"검색|요청|실행|저장|파일|탭|메뉴|플러그인|사이트|모드|"
    r"켜|끄|열어|들어가|가져오|불러오|리네임|변경|수정|만들어|구성해"
)
_CONCEPT_ONLY_SIGNAL = re.compile(
    r"개념|정의|차이|의미|이유|왜|때문|과정|구조|원리|"
    r"라고 생각|이라고 보|설명|배경"
)
_CONCEPT_OVERRIDE_SIGNAL = re.compile(
    r"클릭|누르|입력|복사|붙여|설치|실행|요청|버튼|탭|메뉴"
)
_WHY_LEAK = re.compile(r"때문|왜냐|이유는|하려고|덕분")


def _action_worthy_text(value: Any) -> bool:
    text = str(value or "")
    if not _ACTION_SIGNAL.search(text) or not _DIRECT_OPERATION_SIGNAL.search(text):
        return False
    if _CONCEPT_ONLY_SIGNAL.search(text) and not _CONCEPT_OVERRIDE_SIGNAL.search(text):
        return False
    return True


def _unknown_fields(value: Any, allowed: frozenset[str], prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix}:must_be_object"]
    return [f"{prefix}:unsupported_field:{key}" for key in value if key not in allowed]


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unique(values: Iterable[Any]) -> bool:
    items = list(values)
    return len(items) == len(set(items))


def _safe_relative_jpg(value: Any) -> bool:
    if not _nonempty_text(value):
        return False
    path = PurePosixPath(str(value))
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and bool(path.parts)
        and path.suffix.lower() in {".jpg", ".jpeg"}
    )


def _validate_evidence(
    evidence: Any,
    *,
    known_rows: dict[str, dict[str, Any]],
    allowed_ids: set[str] | None,
    prefix: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    ids: list[str] = []
    if not isinstance(evidence, list) or not evidence:
        return [f"{prefix}:evidence_required"], ids
    for index, item in enumerate(evidence):
        item_prefix = f"{prefix}.evidence[{index}]"
        errors.extend(_unknown_fields(item, EVIDENCE_FIELDS, item_prefix))
        if not isinstance(item, dict):
            continue
        utterance_id = str(item.get("utterance_id") or "")
        if utterance_id not in known_rows:
            errors.append(f"{item_prefix}:unknown_utterance_id:{utterance_id}")
            continue
        if allowed_ids is not None and utterance_id not in allowed_ids:
            errors.append(f"{item_prefix}:outside_parent_evidence:{utterance_id}")
        ids.append(utterance_id)
        row = known_rows[utterance_id]
        for field in ("start_seconds", "end_seconds"):
            if not _number(item.get(field)):
                errors.append(f"{item_prefix}:{field}_must_be_number")
            elif abs(float(item[field]) - float(row[field])) > 1e-6:
                errors.append(f"{item_prefix}:{field}_does_not_match_source")
    if len(ids) != len(set(ids)):
        errors.append(f"{prefix}:duplicate_evidence")
    return errors, ids


def _validate_thumbnail(value: Any, prefix: str) -> list[str]:
    if value is None:
        return []
    errors = _unknown_fields(value, THUMBNAIL_FIELDS, prefix)
    if not isinstance(value, dict):
        return errors
    if not _nonempty_text(value.get("content_chapter_id")):
        errors.append(f"{prefix}:content_chapter_id_required")
    if not _safe_relative_jpg(value.get("relative_path")):
        errors.append(f"{prefix}:unsafe_relative_path")
    if not isinstance(value.get("overlap_utterance_count"), int):
        errors.append(f"{prefix}:overlap_utterance_count_must_be_integer")
    if not _number(value.get("overlap_ratio")):
        errors.append(f"{prefix}:overlap_ratio_must_be_number")
    return errors


def validate_ddock_content(package: Any) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(package, dict):
        return {"errors": ["package:must_be_object"], "warnings": []}

    errors.extend(_unknown_fields(package, TOP_LEVEL_FIELDS, "package"))
    forbidden = sorted(set(package).intersection(FORBIDDEN_MVP_FIELDS))
    errors.extend(f"package:forbidden_mvp_field:{name}" for name in forbidden)
    if package.get("schema_version") != SCHEMA_VERSION:
        errors.append("package:invalid_schema_version")

    source = package.get("source")
    errors.extend(_unknown_fields(source, SOURCE_FIELDS, "source"))
    if not isinstance(source, dict) or not _nonempty_text(source.get("video_id")):
        errors.append("source:video_id_required")

    script = package.get("script")
    if not isinstance(script, list):
        errors.append("script:must_be_array")
        script = []
    known_rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(script):
        prefix = f"script[{index}]"
        errors.extend(_unknown_fields(row, SCRIPT_ROW_FIELDS, prefix))
        if not isinstance(row, dict):
            continue
        utterance_id = str(row.get("utterance_id") or "")
        if not utterance_id:
            errors.append(f"{prefix}:utterance_id_required")
            continue
        if utterance_id in known_rows:
            errors.append(f"{prefix}:duplicate_utterance_id:{utterance_id}")
        if not _number(row.get("start_seconds")) or not _number(row.get("end_seconds")):
            errors.append(f"{prefix}:timestamp_range_required")
        elif float(row["start_seconds"]) > float(row["end_seconds"]):
            errors.append(f"{prefix}:invalid_timestamp_range")
        if not _nonempty_text(row.get("text")):
            errors.append(f"{prefix}:text_required")
        if not isinstance(row.get("catchup_part_ids"), list):
            errors.append(f"{prefix}:catchup_part_ids_must_be_array")
        known_rows[utterance_id] = row

    chapters = package.get("script_chapters")
    if not isinstance(chapters, list):
        errors.append("script_chapters:must_be_array")
        chapters = []
    chapter_ids: list[str] = []
    chapter_membership: dict[str, str] = {}
    for index, chapter in enumerate(chapters):
        prefix = f"script_chapters[{index}]"
        errors.extend(_unknown_fields(chapter, SCRIPT_CHAPTER_FIELDS, prefix))
        if not isinstance(chapter, dict):
            continue
        chapter_id = str(chapter.get("chapter_id") or "")
        chapter_ids.append(chapter_id)
        if chapter.get("order") != index + 1:
            errors.append(f"{prefix}:invalid_order")
        utterance_ids = chapter.get("utterance_ids")
        if not isinstance(utterance_ids, list):
            errors.append(f"{prefix}:utterance_ids_must_be_array")
            continue
        for utterance_id in utterance_ids:
            if utterance_id not in known_rows:
                errors.append(f"{prefix}:unknown_utterance_id:{utterance_id}")
            if utterance_id in chapter_membership:
                errors.append(f"{prefix}:duplicate_chapter_membership:{utterance_id}")
            chapter_membership[str(utterance_id)] = chapter_id
    if not _unique(chapter_ids):
        errors.append("script_chapters:duplicate_chapter_id")

    for utterance_id, row in known_rows.items():
        chapter_id = row.get("script_chapter_id")
        if chapter_id is not None and chapter_id not in set(chapter_ids):
            errors.append(f"script:{utterance_id}:unknown_script_chapter_id:{chapter_id}")
        if chapter_id is not None and chapter_membership.get(utterance_id) != chapter_id:
            errors.append(f"script:{utterance_id}:chapter_membership_mismatch")

    parts = package.get("catchup_parts")
    if not isinstance(parts, list):
        errors.append("catchup_parts:must_be_array")
        parts = []
    part_ids: list[str] = []
    part_memberships: dict[str, set[str]] = {}
    step_ids: list[str] = []
    for part_index, part in enumerate(parts):
        prefix = f"catchup_parts[{part_index}]"
        errors.extend(_unknown_fields(part, PART_FIELDS, prefix))
        if not isinstance(part, dict):
            continue
        part_id = str(part.get("part_id") or "")
        part_ids.append(part_id)
        if part.get("order") != part_index + 1:
            errors.append(f"{prefix}:invalid_order")
        if not _nonempty_text(part.get("title")):
            errors.append(f"{prefix}:title_required")
        source_ids = part.get("source_utterance_ids")
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"{prefix}:source_utterance_ids_required")
            source_ids = []
        if not _unique(source_ids):
            errors.append(f"{prefix}:duplicate_source_utterance_ids")
        unknown = [value for value in source_ids if value not in known_rows]
        errors.extend(f"{prefix}:unknown_source_utterance_id:{value}" for value in unknown)
        allowed_ids = set(source_ids)
        action_ids = part.get("action_utterance_ids")
        if not isinstance(action_ids, list) or not action_ids:
            errors.append(f"{prefix}:action_utterance_ids_required")
            action_ids = []
        if not _unique(action_ids):
            errors.append(f"{prefix}:duplicate_action_utterance_ids")
        action_allowed = set(str(value) for value in action_ids)
        if not action_allowed.issubset(allowed_ids):
            errors.append(f"{prefix}:action_source_outside_part_context")
        if action_ids and not any(
            value in known_rows and _action_worthy_text(known_rows[value].get("text"))
            for value in action_ids
        ):
            errors.append(f"{prefix}:concept_only_part_without_action_signal")
        evidence_errors, evidence_ids = _validate_evidence(
            part.get("evidence"),
            known_rows=known_rows,
            allowed_ids=allowed_ids,
            prefix=prefix,
        )
        errors.extend(evidence_errors)
        if evidence_ids != source_ids:
            errors.append(f"{prefix}:evidence_must_match_source_utterance_ids")
        valid_source_ids = [value for value in source_ids if value in known_rows]
        if valid_source_ids:
            expected_start = min(float(known_rows[value]["start_seconds"]) for value in valid_source_ids)
            expected_end = max(float(known_rows[value]["end_seconds"]) for value in valid_source_ids)
            if not _number(part.get("start_seconds")) or abs(float(part["start_seconds"]) - expected_start) > 1e-6:
                errors.append(f"{prefix}:start_seconds_does_not_match_source")
            if not _number(part.get("end_seconds")) or abs(float(part["end_seconds"]) - expected_end) > 1e-6:
                errors.append(f"{prefix}:end_seconds_does_not_match_source")
        errors.extend(_validate_thumbnail(part.get("thumbnail"), f"{prefix}.thumbnail"))
        part_memberships[part_id] = allowed_ids

        steps = part.get("steps")
        if not isinstance(steps, list):
            errors.append(f"{prefix}:steps_must_be_array")
            steps = []
        if steps and not 3 <= len(steps) <= 6:
            warnings.append(f"{prefix}:step_density_review:{len(steps)}:recommended_3_to_6")
        previous_step_ids: set[str] | None = None
        used_part_action_ids: set[str] = set()
        for step_index, step in enumerate(steps):
            step_prefix = f"{prefix}.steps[{step_index}]"
            errors.extend(_unknown_fields(step, STEP_FIELDS, step_prefix))
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id") or "")
            step_ids.append(step_id)
            if step.get("parent_part_id") != part_id:
                errors.append(f"{step_prefix}:parent_part_id_mismatch")
            if step.get("order") != step_index + 1:
                errors.append(f"{step_prefix}:invalid_order")
            if not _nonempty_text(step.get("action_title")):
                errors.append(f"{step_prefix}:action_title_required")
            lines = step.get("action_lines")
            if not isinstance(lines, list) or not 1 <= len(lines) <= 4:
                errors.append(f"{step_prefix}:action_lines_must_have_1_to_4_items")
                lines = []
            for line_index, line in enumerate(lines):
                line_prefix = f"{step_prefix}.action_lines[{line_index}]"
                errors.extend(_unknown_fields(line, ACTION_LINE_FIELDS, line_prefix))
                if not isinstance(line, dict) or not _nonempty_text(line.get("text")):
                    errors.append(f"{line_prefix}:text_required")
                    continue
                segments = line.get("segments")
                if not isinstance(segments, list) or not segments:
                    errors.append(f"{line_prefix}:segments_required")
                    continue
                joined = ""
                for segment_index, segment in enumerate(segments):
                    segment_prefix = f"{line_prefix}.segments[{segment_index}]"
                    errors.extend(_unknown_fields(segment, SEGMENT_FIELDS, segment_prefix))
                    if not isinstance(segment, dict):
                        continue
                    if segment.get("type") not in RICH_SEGMENT_TYPES:
                        errors.append(f"{segment_prefix}:invalid_type")
                    if not _nonempty_text(segment.get("text")):
                        errors.append(f"{segment_prefix}:text_required")
                    joined += str(segment.get("text") or "")
                if joined != line.get("text"):
                    errors.append(f"{line_prefix}:text_must_equal_joined_segments")
                line_ids = line.get("source_utterance_ids")
                if not isinstance(line_ids, list) or not line_ids:
                    errors.append(f"{line_prefix}:source_utterance_ids_required")
                elif not set(str(value) for value in line_ids).issubset(
                    set(str(value) for value in step.get("source_utterance_ids") or [])
                ):
                    errors.append(f"{line_prefix}:source_outside_step_evidence")
                elif not any(
                    value in known_rows
                    and _action_worthy_text(known_rows[value].get("text"))
                    for value in line_ids
                ):
                    errors.append(f"{line_prefix}:concept_only_action_line")
                if _WHY_LEAK.search(str(line.get("text") or "")):
                    warnings.append(f"{line_prefix}:surface_why_context_should_move_to_learn_more")
                if len(str(line.get("text") or "")) > 80:
                    warnings.append(f"{line_prefix}:surface_text_over_80_characters")

            step_source = step.get("source_utterance_ids")
            if not isinstance(step_source, list) or not step_source:
                errors.append(f"{step_prefix}:source_utterance_ids_required")
                step_source = []
            step_allowed = set(str(value) for value in step_source)
            if not step_allowed.issubset(action_allowed):
                errors.append(f"{step_prefix}:source_outside_parent_action_evidence")
            used_part_action_ids.update(step_allowed)
            evidence_errors, evidence_ids = _validate_evidence(
                step.get("evidence"),
                known_rows=known_rows,
                allowed_ids=action_allowed,
                prefix=step_prefix,
            )
            errors.extend(evidence_errors)
            if evidence_ids != step_source:
                errors.append(f"{step_prefix}:evidence_must_match_source_utterance_ids")
            if evidence_ids:
                starts = [float(known_rows[value]["start_seconds"]) for value in evidence_ids]
                ends = [float(known_rows[value]["end_seconds"]) for value in evidence_ids]
                if not _number(step.get("playback_start_seconds")) or float(step["playback_start_seconds"]) not in starts:
                    errors.append(f"{step_prefix}:playback_start_not_in_evidence")
                if not _number(step.get("playback_end_seconds")) or float(step["playback_end_seconds"]) not in ends:
                    errors.append(f"{step_prefix}:playback_end_not_in_evidence")

            for field, allowed_fields in (("prompt", PROMPT_FIELDS), ("warning", WARNING_FIELDS)):
                block = step.get(field)
                if block is None:
                    continue
                block_prefix = f"{step_prefix}.{field}"
                errors.extend(_unknown_fields(block, allowed_fields, block_prefix))
                if not isinstance(block, dict):
                    continue
                block_errors, _ = _validate_evidence(
                    block.get("evidence"),
                    known_rows=known_rows,
                    allowed_ids=(step_allowed if field == "prompt" else allowed_ids),
                    prefix=block_prefix,
                )
                errors.extend(block_errors)
                if field == "prompt" and block.get("source_kind") != "verbatim":
                    errors.append(f"{block_prefix}:source_kind_must_be_verbatim")
            learn_more = step.get("learn_more")
            if not isinstance(learn_more, list):
                errors.append(f"{step_prefix}:learn_more_must_be_array")
                learn_more = []
            for learn_index, item in enumerate(learn_more):
                learn_prefix = f"{step_prefix}.learn_more[{learn_index}]"
                errors.extend(_unknown_fields(item, LEARN_MORE_FIELDS, learn_prefix))
                if not isinstance(item, dict):
                    continue
                learn_errors, _ = _validate_evidence(
                    item.get("evidence"),
                    known_rows=known_rows,
                    allowed_ids=allowed_ids,
                    prefix=learn_prefix,
                )
                errors.extend(learn_errors)
            if previous_step_ids is not None and step_allowed:
                overlap = len(previous_step_ids.intersection(step_allowed))
                denominator = min(len(previous_step_ids), len(step_allowed))
                if denominator and overlap / denominator >= 0.8:
                    warnings.append(f"{step_prefix}:large_adjacent_step_overlap")
            previous_step_ids = step_allowed

        excluded_actions = part.get("excluded_actions")
        if not isinstance(excluded_actions, list):
            errors.append(f"{prefix}:excluded_actions_must_be_array")
            excluded_actions = []
        excluded_ids: set[str] = set()
        for index, excluded in enumerate(excluded_actions):
            excluded_prefix = f"{prefix}.excluded_actions[{index}]"
            errors.extend(_unknown_fields(excluded, EXCLUDED_ACTION_FIELDS, excluded_prefix))
            if not isinstance(excluded, dict):
                continue
            utterance_id = str(excluded.get("utterance_id") or "")
            if utterance_id not in action_allowed:
                errors.append(f"{excluded_prefix}:outside_part_action_evidence")
            if not _nonempty_text(excluded.get("reason")):
                errors.append(f"{excluded_prefix}:reason_required")
            if utterance_id in excluded_ids:
                errors.append(f"{excluded_prefix}:duplicate_utterance_id")
            excluded_ids.add(utterance_id)
        if used_part_action_ids.intersection(excluded_ids):
            errors.append(f"{prefix}:action_used_and_excluded")
        if used_part_action_ids.union(excluded_ids) != action_allowed:
            errors.append(f"{prefix}:action_evidence_not_fully_accounted")

    if not _unique(part_ids):
        errors.append("catchup_parts:duplicate_part_id")
    if not _unique(step_ids):
        errors.append("catchup_parts:duplicate_step_id")

    for left_index, left_id in enumerate(part_ids):
        for right_id in part_ids[left_index + 1 :]:
            left = part_memberships.get(left_id, set())
            right = part_memberships.get(right_id, set())
            denominator = min(len(left), len(right))
            if denominator and len(left.intersection(right)) / denominator >= 0.5:
                warnings.append(f"catchup_parts:large_overlap:{left_id}:{right_id}")

    part_id_set = set(part_ids)
    for utterance_id, row in known_rows.items():
        references = row.get("catchup_part_ids") or []
        if not isinstance(references, list):
            continue
        for part_id in references:
            if part_id not in part_id_set:
                errors.append(f"script:{utterance_id}:unknown_part_reference:{part_id}")
            elif utterance_id not in part_memberships.get(part_id, set()):
                errors.append(f"script:{utterance_id}:part_reference_without_membership:{part_id}")
        expected = [part_id for part_id in part_ids if utterance_id in part_memberships.get(part_id, set())]
        if references != expected:
            errors.append(f"script:{utterance_id}:catchup_part_ids_mismatch")

    detail = package.get("video_detail")
    errors.extend(_unknown_fields(detail, VIDEO_DETAIL_FIELDS, "video_detail"))
    if isinstance(detail, dict):
        recommendation = detail.get("recommendation")
        if recommendation is not None:
            errors.extend(_unknown_fields(recommendation, RECOMMENDATION_FIELDS, "video_detail.recommendation"))
            if isinstance(recommendation, dict):
                rec_errors, _ = _validate_evidence(
                    recommendation.get("evidence"),
                    known_rows=known_rows,
                    allowed_ids=None,
                    prefix="video_detail.recommendation",
                )
                errors.extend(rec_errors)
                claims = recommendation.get("claims")
                if not isinstance(claims, list) or not claims:
                    errors.append("video_detail.recommendation:claims_required")
                    claims = []
                for index, claim in enumerate(claims):
                    prefix = f"video_detail.recommendation.claims[{index}]"
                    errors.extend(_unknown_fields(claim, RECOMMENDATION_CLAIM_FIELDS, prefix))
                    if not isinstance(claim, dict) or not _nonempty_text(claim.get("text")):
                        errors.append(f"{prefix}:text_required")
                        continue
                    claim_errors, _ = _validate_evidence(
                        claim.get("evidence"),
                        known_rows=known_rows,
                        allowed_ids=None,
                        prefix=prefix,
                    )
                    errors.extend(claim_errors)
        tools = detail.get("tools")
        if not isinstance(tools, list):
            errors.append("video_detail:tools_must_be_array")
            tools = []
        for index, tool in enumerate(tools):
            prefix = f"video_detail.tools[{index}]"
            errors.extend(_unknown_fields(tool, TOOL_FIELDS, prefix))
            if isinstance(tool, dict):
                tool_errors, _ = _validate_evidence(
                    tool.get("evidence"),
                    known_rows=known_rows,
                    allowed_ids=None,
                    prefix=prefix,
                )
                errors.extend(tool_errors)
        tags = detail.get("tags")
        if not isinstance(tags, list) or len(tags) > 8:
            errors.append("video_detail:tags_must_be_array_of_at_most_8")
        previews = detail.get("part_preview")
        if not isinstance(previews, list):
            errors.append("video_detail:part_preview_must_be_array")
            previews = []
        if len(previews) != len(parts):
            errors.append("video_detail:part_preview_count_mismatch")
        for index, preview in enumerate(previews):
            prefix = f"video_detail.part_preview[{index}]"
            errors.extend(_unknown_fields(preview, PART_PREVIEW_FIELDS, prefix))
            if isinstance(preview, dict):
                if preview.get("part_id") not in part_id_set:
                    errors.append(f"{prefix}:unknown_part_id")
                errors.extend(_validate_thumbnail(preview.get("thumbnail"), f"{prefix}.thumbnail"))

    generation = package.get("curation_generation")
    errors.extend(_unknown_fields(generation, GENERATION_FIELDS, "curation_generation"))
    if isinstance(generation, dict):
        counts = [
            int(generation.get("part_planning_calls") or 0),
            int(generation.get("step_generation_initial_calls") or 0),
            int(generation.get("step_generation_retry_calls") or 0),
            int(generation.get("video_detail_calls") or 0),
        ]
        if int(generation.get("total_model_calls") or 0) != sum(counts):
            errors.append("curation_generation:total_model_calls_mismatch")
        if int(generation.get("step_generation_calls") or 0) != sum(counts[1:3]):
            errors.append("curation_generation:step_generation_calls_mismatch")
        if not isinstance(generation.get("review_reasons"), list):
            errors.append("curation_generation:review_reasons_must_be_array")
        omitted = generation.get("omitted_part_candidates")
        if not isinstance(omitted, list):
            errors.append("curation_generation:omitted_part_candidates_must_be_array")
        coverage = generation.get("high_action_coverage_warnings")
        if not isinstance(coverage, list):
            errors.append("curation_generation:high_action_coverage_warnings_must_be_array")
        if int(generation.get("needs_review_count") or 0) != len(
            generation.get("review_reasons") or []
        ):
            errors.append("curation_generation:needs_review_count_mismatch")

    return {"errors": errors, "warnings": warnings}


def require_valid_ddock_content(package: Any) -> dict[str, list[str]]:
    report = validate_ddock_content(package)
    if report["errors"]:
        raise ValueError("ddock_content_validation_failed:" + ";".join(report["errors"]))
    return report
