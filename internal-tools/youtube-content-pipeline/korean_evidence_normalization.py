from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable


POLICY_VERSION = "korean_metadata_context_evidence_v0.1"
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Z][A-Z0-9&+.-]{1,}")
_HANGUL_RE = re.compile(r"^[가-힣]+$")
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9&+.-]{1,}$")
_KOREAN_SUFFIXES = (
    "하였습니다",
    "했습니다",
    "합니다",
    "하기",
    "됩니다",
    "입니다",
    "이었어요",
    "겠습니다",
    "았습니다",
    "었습니다",
    "습니다",
    "였어요",
    "이에요",
    "예요",
    "하면서",
    "하며",
    "해서",
    "하는",
    "하고",
    "한",
    "에서",
    "으로",
    "처럼",
    "보다",
    "라는",
    "라고",
    "들과",
    "들을",
    "들이",
    "들은",
    "에서는",
    "에게",
    "께서",
    "까지",
    "부터",
    "랑",
    "로",
    "와",
    "과",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "도",
    "의",
    "에",
    "만",
)


@dataclass
class _Evidence:
    compact: str
    display: str
    metadata_priority: int = 0
    metadata_sources: tuple[str, ...] = ()
    transcript_count: int = 0
    official_entity: bool = False
    context_anchors: tuple[str, ...] = ()

    @property
    def support(self) -> int:
        return self.metadata_priority * 3 + min(self.transcript_count, 10)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _kind(value: str) -> str | None:
    compact = _compact(value)
    if _HANGUL_RE.fullmatch(compact):
        return "hangul"
    if _ACRONYM_RE.fullmatch(compact):
        return "acronym"
    return None


def _split_suffix(value: str) -> tuple[str, str]:
    token = str(value or "")
    if not _HANGUL_RE.fullmatch(token):
        return token, ""
    stem = token
    collected_suffix = ""
    for _ in range(3):
        matched = False
        for suffix in _KOREAN_SUFFIXES:
            if not stem.endswith(suffix):
                continue
            candidate = stem[: -len(suffix)]
            if len(candidate) >= 2:
                stem = candidate
                collected_suffix = suffix + collected_suffix
                matched = True
                break
            if len(suffix) > 1:
                return "", token
        if not matched:
            break
    return stem, collected_suffix


def _distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, 1):
        current = [row]
        for column, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _metadata_records(source: dict[str, Any]) -> list[tuple[str, int, str]]:
    metadata = source.get("metadata") or {}
    records = [
        (str(metadata.get("title") or ""), 3, "video_title"),
        (
            str(metadata.get("description_raw") or ""),
            2,
            "youtube_description",
        ),
    ]
    for chapter in source.get("creator_chapters") or []:
        if isinstance(chapter, dict):
            records.append(
                (
                    str(chapter.get("label") or ""),
                    3,
                    "creator_chapter_label",
                )
            )
    return records


def _phrases(text: str, *, include_bigrams: bool) -> list[str]:
    matches = list(_TOKEN_RE.finditer(str(text or "")))
    values = [_split_suffix(match.group(0))[0] for match in matches]
    if not include_bigrams:
        return values
    for index in range(len(matches) - 1):
        first = matches[index]
        second = matches[index + 1]
        between = text[first.end() : second.start()]
        left = _split_suffix(first.group(0))[0]
        right = _split_suffix(second.group(0))[0]
        if (
            between.strip()
            or not _HANGUL_RE.fullmatch(left)
            or not _HANGUL_RE.fullmatch(right)
            or len(left) < 2
            or len(right) < 2
        ):
            continue
        compact = left + right
        if 4 <= len(compact) <= 10:
            values.append(f"{left} {right}")
    return values


def _collect_evidence(
    result: dict[str, Any],
    source: dict[str, Any],
    canonicalize: Callable[[str], str] | None,
) -> dict[str, _Evidence]:
    evidence: dict[str, _Evidence] = {}
    source_sets: dict[str, set[str]] = {}
    context_sets: dict[str, set[str]] = {}
    for text, priority, source_name in _metadata_records(source):
        for phrase in _phrases(text, include_bigrams=True):
            compact = _compact(phrase)
            if len(compact) < 3 or _kind(compact) is None:
                continue
            current = evidence.get(compact)
            if current is None:
                current = _Evidence(compact=compact, display=phrase)
                evidence[compact] = current
            if priority > current.metadata_priority:
                current.metadata_priority = priority
                current.display = phrase
            source_sets.setdefault(compact, set()).add(source_name)
            if callable(canonicalize):
                current.official_entity = (
                    canonicalize(current.display) != current.display
                )
        if callable(canonicalize):
            metadata_tokens = list(_TOKEN_RE.finditer(text))
            for index, token_match in enumerate(metadata_tokens):
                acronym = token_match.group(0)
                if not _ACRONYM_RE.fullmatch(acronym):
                    continue
                for neighbor in metadata_tokens[
                    max(0, index - 2) : index + 3
                ]:
                    alias = _split_suffix(neighbor.group(0))[0]
                    canonical = canonicalize(alias)
                    if canonical != alias and re.search(r"[A-Za-z]", canonical):
                        context_sets.setdefault(acronym, set()).add(canonical)

    transcript_counts: Counter[str] = Counter()
    transcript_display: dict[str, str] = {}
    for row in result.get("normalized_utterances") or []:
        if not isinstance(row, dict):
            continue
        for phrase in _phrases(
            str(row.get("normalized_text") or ""),
            include_bigrams=False,
        ):
            compact = _compact(phrase)
            if len(compact) < 3 or _kind(compact) is None:
                continue
            transcript_counts[compact] += 1
            transcript_display.setdefault(compact, phrase)

    for compact, count in transcript_counts.items():
        current = evidence.get(compact)
        if current is None:
            current = _Evidence(
                compact=compact,
                display=transcript_display[compact],
            )
            evidence[compact] = current
        current.transcript_count = count

    for compact, current in evidence.items():
        current.metadata_sources = tuple(sorted(source_sets.get(compact, set())))
        current.context_anchors = tuple(sorted(context_sets.get(compact, set())))
    return evidence


def _best_repair(
    observed: str,
    evidence: dict[str, _Evidence],
    candidate_index: dict[tuple[str, int], list[_Evidence]],
    *,
    observed_window_size: int,
    row_text: str,
) -> tuple[_Evidence, int] | None:
    compact = _compact(observed)
    observed_kind = _kind(compact)
    exact = evidence.get(compact)
    if observed_kind is None or (
        exact is not None
        and (
            exact.metadata_priority
            or (
                observed_kind == "acronym"
                and exact.transcript_count >= 3
            )
        )
    ):
        return None
    candidates: list[tuple[int, int, str, _Evidence]] = []
    for candidate in candidate_index.get(
        (observed_kind, len(compact)),
        [],
    ):
        if observed_kind == "hangul":
            if len(compact) < 3:
                continue
            if observed_window_size == 1:
                if not (
                    candidate.official_entity
                    or candidate.transcript_count >= 5
                    or (
                        candidate.metadata_priority >= 3
                        and " " in candidate.display
                    )
                ):
                    continue
            elif (
                len(candidate.display.split()) != 1
                or candidate.metadata_priority < 2
                or len(candidate.compact) != 4
            ):
                continue
        elif not (
            candidate.context_anchors
            and any(anchor in row_text for anchor in candidate.context_anchors)
        ):
            continue
        distance = _distance(compact, candidate.compact)
        maximum = 1
        if (
            observed_kind == "hangul"
            and len(compact) >= 4
            and candidate.metadata_priority >= 3
            and candidate.transcript_count >= 5
        ):
            maximum = 2
        if distance == 0 or distance > maximum:
            continue
        candidates.append(
            (distance, -candidate.support, candidate.compact, candidate)
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:3])
    best = candidates[0]
    if len(candidates) > 1 and candidates[1][:2] == best[:2]:
        return None
    return best[3], best[0]


def _candidate_index(
    evidence: dict[str, _Evidence],
) -> dict[tuple[str, int], list[_Evidence]]:
    index: dict[tuple[str, int], list[_Evidence]] = {}
    for candidate in evidence.values():
        candidate_kind = _kind(candidate.compact)
        if candidate_kind == "hangul":
            if (
                " " not in candidate.display
                and _split_suffix(candidate.display)[1]
            ):
                continue
            if not (
                (
                    len(candidate.compact) >= 4
                    and candidate.metadata_priority >= 2
                )
                or candidate.official_entity
                or (
                    candidate.metadata_priority >= 3
                    and 1 <= candidate.transcript_count <= 5
                )
            ):
                continue
        elif candidate_kind == "acronym":
            if not (
                candidate.context_anchors
                and (
                    candidate.metadata_priority
                    or candidate.transcript_count >= 3
                )
            ):
                continue
        else:
            continue
        index.setdefault(
            (candidate_kind, len(candidate.compact)),
            [],
        ).append(candidate)
    return index


def _row_repairs(
    text: str,
    evidence: dict[str, _Evidence],
    candidate_index: dict[tuple[str, int], list[_Evidence]],
) -> tuple[str, list[dict[str, Any]]]:
    output = str(text or "")
    changes: list[dict[str, Any]] = []
    for window_size in (2, 1):
        matches = list(_TOKEN_RE.finditer(output))
        replacements: list[tuple[int, int, str, dict[str, Any]]] = []
        occupied: list[tuple[int, int]] = []
        for index in range(len(matches) - window_size + 1):
            window = matches[index : index + window_size]
            start, end = window[0].start(), window[-1].end()
            if any(
                start < used_end and end > used_start
                for used_start, used_end in occupied
            ):
                continue
            if window_size == 2:
                between = output[window[0].end() : window[1].start()]
                if between.strip():
                    continue
                if any(len(match.group(0)) < 2 for match in window):
                    continue
            observed = output[start:end]
            observed_parts = [
                _split_suffix(match.group(0))
                for match in window
            ]
            if any(not part[0] for part in observed_parts):
                continue
            if (
                window_size == 2
                and any(len(part[0]) != 2 for part in observed_parts)
            ):
                continue
            observed_core = " ".join(part[0] for part in observed_parts)
            trailing_suffix = observed_parts[-1][1]
            repair = _best_repair(
                observed_core,
                evidence,
                candidate_index,
                observed_window_size=window_size,
                row_text=output,
            )
            if repair is None:
                continue
            candidate, distance = repair
            replacement = candidate.display + trailing_suffix
            replacements.append(
                (
                    start,
                    end,
                    replacement,
                    {
                        "before": observed,
                        "after": replacement,
                        "distance": distance,
                        "metadata_sources": list(candidate.metadata_sources),
                        "transcript_evidence_count": candidate.transcript_count,
                    },
                )
            )
            occupied.append((start, end))
        for start, end, replacement, record in reversed(replacements):
            output = output[:start] + replacement + output[end:]
            changes.append(record)
    changes.reverse()
    return output, changes


def _next_normalization_number(items: list[dict[str, Any]]) -> int:
    maximum = 0
    for item in items:
        match = re.fullmatch(r"NM-(\d+)", str(item.get("normalization_id") or ""))
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum + 1


def apply_korean_evidence_normalization(
    result: dict[str, Any],
    source: dict[str, Any],
    *,
    canonicalize: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Repair only uniquely supported Korean ASR variants; never mutate provenance."""
    if not isinstance(result, dict) or not isinstance(source, dict):
        return result
    language = str(
        result.get("source_language")
        or (source.get("transcript") or {}).get("language_code")
        or ""
    ).lower()
    if not language.startswith("ko") or result.get("translation_required") is True:
        return result

    evidence = _collect_evidence(result, source, canonicalize)
    candidate_index = _candidate_index(evidence)
    normalization_items = result.setdefault("normalization_items", [])
    next_number = _next_normalization_number(normalization_items)
    applied = 0
    repaired_rows = 0
    for row in result.get("normalized_utterances") or []:
        if not isinstance(row, dict):
            continue
        before = str(row.get("normalized_text") or "")
        repaired, changes = _row_repairs(
            before,
            evidence,
            candidate_index,
        )
        if callable(canonicalize):
            repaired = canonicalize(repaired)
            for change in changes:
                change["after"] = canonicalize(change["after"])
        if repaired == before:
            continue
        row["normalized_text"] = repaired
        row["auto_normalized_text"] = repaired
        row_ids = row.setdefault("normalization_item_ids", [])
        for change in changes:
            normalization_id = f"NM-{next_number:05d}"
            next_number += 1
            row_ids.append(normalization_id)
            sources = change["metadata_sources"] or ["repeated_video_context"]
            normalization_items.append(
                {
                    "normalization_id": normalization_id,
                    "raw_text": change["before"],
                    "normalized_text": change["after"],
                    "normalization_type": "korean_video_evidence_asr_repair_v0316",
                    "confidence": "high",
                    "evidence_sources": sources,
                    "evidence_distance": change["distance"],
                    "video_context_occurrences": change[
                        "transcript_evidence_count"
                    ],
                    "affected_segment_ids": copy.deepcopy(
                        row.get("source_segment_ids") or []
                    ),
                    "review_status": "auto_approved",
                }
            )
            applied += 1
        repaired_rows += 1

    result["korean_evidence_normalization"] = {
        "policy_version": POLICY_VERSION,
        "status": "applied" if applied else "no_supported_repairs",
        "evidence_candidate_count": len(evidence),
        "eligible_candidate_count": sum(
            len(items) for items in candidate_index.values()
        ),
        "applied_change_count": applied,
        "repaired_utterance_count": repaired_rows,
        "model_invoked": False,
        "uncertainty_policy": "leave_unchanged_and_keep_needs_review",
        "fidelity_guards": [
            "same_compact_length",
            "unique_best_candidate",
            "metadata_or_repeated_context_required",
            "numbers_and_non_target_tokens_untouched",
            "raw_provenance_untouched",
            "row_boundaries_untouched",
        ],
        "source_scope": [
            "video_title",
            "youtube_description",
            "creator_chapter_label",
            "repeated_video_context",
        ],
    }
    report = result.setdefault("processing_report", {})
    report["korean_evidence_repair_count"] = applied
    return result
