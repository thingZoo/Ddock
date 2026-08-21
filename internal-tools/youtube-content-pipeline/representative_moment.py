from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from content_chapter_segmentation import _semantic_text_for_prompt
from content_chapters import format_timestamp


REPRESENTATIVE_SELECTION_METHOD = "deterministic_text_relevance_v0.1"
METADATA_WEIGHT = 0.2
UNCERTAIN_METADATA_WEIGHT = 0.05
_METADATA_WARNING_PREFIXES = (
    "learning_metadata_inherited_after_role_split",
    "pass_a_learning_metadata_unavailable_after_role_audit",
)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


class RepresentativeMomentError(ValueError):
    pass


def _seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _text_features(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    features: set[str] = set()
    for token in _WORD_RE.findall(normalized):
        features.add("word:" + token)
        for size in (2, 3):
            if len(token) < size:
                continue
            features.update(
                "char:" + token[index : index + size]
                for index in range(len(token) - size + 1)
            )
    return features


def _metadata_is_uncertain(
    chapter: dict[str, Any],
    generation_warnings: list[str] | None,
) -> bool:
    if bool(chapter.get("needs_review")):
        return True
    candidate = chapter.get("role_audit_candidate_index")
    subsection = chapter.get("role_audit_subsection_index")
    marker = (
        f"candidate[{candidate}].subsection[{subsection}]"
        if candidate is not None and subsection is not None
        else None
    )
    for warning in generation_warnings or []:
        value = str(warning)
        if not value.startswith(_METADATA_WARNING_PREFIXES):
            continue
        if marker is None or marker in value:
            return True
    return False


def _ordered_chapter_rows(
    content_chapter: dict[str, Any],
    normalized_utterances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ids = content_chapter.get("source_utterance_ids")
    if not isinstance(source_ids, list) or not source_ids:
        raise RepresentativeMomentError("chapter_missing_source_utterance_ids")
    normalized_ids = [str(value or "").strip() for value in source_ids]
    if any(not value for value in normalized_ids):
        raise RepresentativeMomentError("chapter_has_empty_source_utterance_id")
    if len(normalized_ids) != len(set(normalized_ids)):
        raise RepresentativeMomentError("chapter_has_duplicate_source_utterance_ids")

    by_id: dict[str, dict[str, Any]] = {}
    for row in normalized_utterances or []:
        if not isinstance(row, dict):
            continue
        utterance_id = str(row.get("utterance_id") or "").strip()
        if utterance_id and utterance_id not in by_id:
            by_id[utterance_id] = row
    missing = [utterance_id for utterance_id in normalized_ids if utterance_id not in by_id]
    if missing:
        raise RepresentativeMomentError(
            "chapter_source_utterances_missing:" + ",".join(missing)
        )

    rows = [by_id[utterance_id] for utterance_id in normalized_ids]
    chapter_start = _seconds(content_chapter.get("start_seconds"))
    chapter_end = _seconds(content_chapter.get("end_seconds"))
    if chapter_start is None or chapter_end is None or chapter_end < chapter_start:
        raise RepresentativeMomentError("chapter_has_invalid_timestamp_range")
    for row in rows:
        start = _seconds(row.get("start_seconds"))
        end = _seconds(row.get("end_seconds"))
        if start is None or end is None or end < start:
            raise RepresentativeMomentError(
                "utterance_has_invalid_timestamp:" + str(row.get("utterance_id"))
            )
        # source_utterance_ids are the semantic ownership contract. Boundary
        # utterances can legitimately cross a creator/content timestamp because
        # speech groups are not split at an arbitrary chapter edge. Reject only
        # rows that do not overlap the chapter at all; _target_for_row clamps the
        # representative timestamp back into the chapter range.
        if end < chapter_start - 1e-6 or start > chapter_end + 1e-6:
            raise RepresentativeMomentError(
                "utterance_does_not_overlap_chapter_range:"
                + str(row.get("utterance_id"))
            )
    return rows


def _score_chapter_rows(
    content_chapter: dict[str, Any],
    normalized_utterances: list[dict[str, Any]],
    *,
    generation_warnings: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float, bool, int]:
    if not isinstance(content_chapter, dict):
        raise RepresentativeMomentError("content_chapter_must_be_an_object")
    rows = _ordered_chapter_rows(content_chapter, normalized_utterances)
    feature_sets = [_text_features(_semantic_text_for_prompt(row)) for row in rows]
    feature_frequency = Counter(
        feature for features in feature_sets for feature in features
    )
    nonempty_feature_rows = sum(bool(features) for features in feature_sets)

    metadata_text = " ".join(
        str(content_chapter.get(field) or "")
        for field in ("title", "summary", "boundary_reason")
    )
    metadata_features = _text_features(metadata_text)
    metadata_uncertain = _metadata_is_uncertain(
        content_chapter, generation_warnings
    )
    metadata_weight = (
        UNCERTAIN_METADATA_WEIGHT if metadata_uncertain else METADATA_WEIGHT
    )
    if not metadata_features:
        metadata_weight = 0.0
    centrality_weight = 1.0 - metadata_weight

    scores: list[dict[str, Any]] = []
    row_count = len(rows)
    for index, (row, features) in enumerate(zip(rows, feature_sets)):
        if not features:
            centrality = 0.0
            metadata_relevance = 0.0
        else:
            if nonempty_feature_rows == 1:
                centrality = 1.0
            else:
                centrality = sum(
                    max(0, feature_frequency[feature] - 1)
                    for feature in features
                ) / max(1, len(features) * (nonempty_feature_rows - 1))
            metadata_relevance = (
                len(features & metadata_features)
                / max(1, len(features | metadata_features))
                if metadata_features
                else 0.0
            )
        combined = (
            centrality_weight * centrality
            + metadata_weight * metadata_relevance
        )
        scores.append(
            {
                "index": index,
                "utterance_id": str(row["utterance_id"]),
                "centrality": centrality,
                "metadata_relevance": metadata_relevance,
                "combined": combined,
            }
        )
    return (
        rows,
        scores,
        metadata_weight,
        metadata_uncertain,
        nonempty_feature_rows,
    )


def _score_sort_key(
    scores: list[dict[str, Any]], index: int, row_count: int
) -> tuple[float, float, float, float, int]:
    center = (row_count - 1) / 2
    return (
        scores[index]["combined"],
        scores[index]["centrality"],
        scores[index]["metadata_relevance"],
        -abs(index - center),
        -index,
    )


def _target_for_row(
    row: dict[str, Any], content_chapter: dict[str, Any]
) -> float:
    utterance_start = _seconds(row.get("start_seconds"))
    utterance_end = _seconds(row.get("end_seconds"))
    chapter_start = _seconds(content_chapter.get("start_seconds"))
    chapter_end = _seconds(content_chapter.get("end_seconds"))
    if None in (utterance_start, utterance_end, chapter_start, chapter_end):
        raise RepresentativeMomentError("representative_timestamp_is_invalid")
    target = (utterance_start + utterance_end) / 2
    return min(max(target, chapter_start), chapter_end)


def rank_representative_moments(
    content_chapter: dict[str, Any],
    normalized_utterances: list[dict[str, Any]],
    *,
    generation_warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Rank chapter utterances with the selector's deterministic relevance."""
    rows, scores, _, _, _ = _score_chapter_rows(
        content_chapter,
        normalized_utterances,
        generation_warnings=generation_warnings,
    )
    row_count = len(rows)
    ranked_indices = sorted(
        range(row_count),
        key=lambda index: _score_sort_key(scores, index, row_count),
        reverse=True,
    )
    ranked: list[dict[str, Any]] = []
    for index in ranked_indices:
        score = scores[index]
        target = _target_for_row(rows[index], content_chapter)
        ranked.append(
            {
                "source_utterance_id": str(rows[index]["utterance_id"]),
                "target_seconds": round(target, 6),
                "target_timestamp": format_timestamp(target),
                "semantic_score": round(float(score["combined"]), 6),
                "centrality_score": round(float(score["centrality"]), 6),
                "metadata_relevance_score": round(
                    float(score["metadata_relevance"]), 6
                ),
                "has_semantic_signal": bool(score["combined"] > 0),
                "source_order": index,
            }
        )
    return ranked


def select_representative_moment(
    content_chapter: dict[str, Any],
    normalized_utterances: list[dict[str, Any]],
    *,
    generation_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Select one semantic moment without model inference or frame analysis."""
    (
        rows,
        scores,
        metadata_weight,
        metadata_uncertain,
        nonempty_feature_rows,
    ) = _score_chapter_rows(
        content_chapter,
        normalized_utterances,
        generation_warnings=generation_warnings,
    )

    valid_relevance = any(item["combined"] > 0 for item in scores)
    fallback_used = not valid_relevance
    row_count = len(rows)
    if fallback_used:
        selected_index = row_count // 2
    else:
        selected_index = max(
            range(row_count),
            key=lambda index: _score_sort_key(scores, index, row_count),
        )

    selected = rows[selected_index]
    target = _target_for_row(selected, content_chapter)
    selected_score = scores[selected_index]

    return {
        "representative_utterance_id": str(selected["utterance_id"]),
        "target_seconds": round(target, 6),
        "target_timestamp": format_timestamp(target),
        "selection_method": REPRESENTATIVE_SELECTION_METHOD,
        "selection_score": round(float(selected_score["combined"]), 6),
        "fallback_used": fallback_used,
        "diagnostics": {
            "centrality_score": round(
                float(selected_score["centrality"]), 6
            ),
            "metadata_relevance_score": round(
                float(selected_score["metadata_relevance"]), 6
            ),
            "metadata_weight": metadata_weight,
            "metadata_uncertain": metadata_uncertain,
            "evaluated_utterance_count": row_count,
            "text_bearing_utterance_count": nonempty_feature_rows,
        },
    }
