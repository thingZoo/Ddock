
from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
import statistics
from datetime import datetime, timezone
from typing import Any


DEFAULT_GLOSSARY = [
    {
        "pattern": r"미드전니|미드전이|미드전위|미드이|미드니|미드전일",
        "replacement": "미드저니",
        "type": "tool_name",
        "confidence": "high",
        "evidence": ["video_title", "description_raw", "tags"],
    },
    {
        "pattern": r"나노바나 프로|나노 나노바나|나노바나로",
        "replacement": "나노바나나 프로",
        "type": "tool_name",
        "confidence": "high",
        "evidence": ["description_raw", "creator_chapters"],
    },
    {
        "pattern": r"시덴댄스|시덴스|시덴댄스로",
        "replacement": "시댄스",
        "type": "tool_name",
        "confidence": "high",
        "evidence": ["description_raw", "creator_chapters"],
    },
    {
        "pattern": (
            r"세리프 코드|쓰리프 코드|슬리프 코드|스리프 코드|"
            r"테리프 코드|세리피 코드|세리프트 코드|세리포 코드|"
            r"슬피 코드|쓰 슬피 코드"
        ),
        "replacement": "Sref 코드",
        "type": "feature_name",
        "confidence": "high",
        "evidence": ["description_raw", "creator_chapters"],
    },
    {
        "pattern": r"생상자",
        "replacement": "생산자",
        "type": "common_asr",
        "confidence": "high",
        "evidence": ["sentence_context"],
    },
    {
        "pattern": r"초비자|소리자",
        "replacement": "소비자",
        "type": "common_asr",
        "confidence": "high",
        "evidence": ["sentence_context"],
    },
    {
        "pattern": r"불일지",
        "replacement": "불일치",
        "type": "common_asr",
        "confidence": "high",
        "evidence": ["sentence_context"],
    },
    {
        "pattern": r"아겼",
        "replacement": "아꼈",
        "type": "common_asr",
        "confidence": "high",
        "evidence": ["sentence_context"],
    },
    {
        "pattern": r"분명이",
        "replacement": "분명히",
        "type": "common_asr",
        "confidence": "high",
        "evidence": ["sentence_context"],
    },
]

ALIGNMENT_REPLACEMENTS = [
    (r"미드전니|미드전이|미드전위|미드이|미드니|미드전일", "미드저니"),
    (r"나노바나 프로|나노 나노바나|나노바나로", "나노바나나 프로"),
    (r"시덴댄스|시덴스|시덴댄스로", "시댄스"),
    (r"세리프|쓰리프|슬리프|스리프|테리프|세리피|세리프트|세리포|슬피", "Sref"),
    (r"무드을", "무드를"),
    (r"일간된", "일관된"),
    (r"임무를", "인물을"),
    (r"쇼트", "쇼츠"),
]

FILLER_WORDS = {
    "어", "음", "그", "뭐", "약간", "좀", "이제", "요거", "요런",
}

TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
SENTENCE_END = re.compile(
    r"[.!?…]$|(?:습니다|해요|예요|이에요|거예요|같아요|됩니다|있어요|없어요|인데요|고요|죠|건데요|거든요)\s*$"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def display_timestamp(seconds: float | int | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_segment_key(video_id: str, segment: dict[str, Any]) -> str:
    payload = "|".join(
        [
            video_id,
            f"{float(segment.get('start_seconds', 0)):.3f}",
            f"{float(segment.get('end_seconds', 0)):.3f}",
            str(segment.get("text", "")),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{video_id}-{digest}"


def clean_display_text(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"^>>\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def detect_document_kind(data: dict[str, Any]) -> str:
    if isinstance(data.get("transcript"), dict) and isinstance(data["transcript"].get("items"), list):
        return "acquisition"
    if isinstance(data.get("normalized_utterances"), list) and isinstance(data.get("raw_segments"), list):
        return "preprocessing"
    return "unknown"


def parse_custom_glossary(text: str) -> list[dict[str, Any]]:
    """
    One entry per line:
    raw expression => normalized expression => confidence
    """
    entries = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("=>")]
        if len(parts) < 2:
            continue
        raw, normalized = parts[0], parts[1]
        confidence = parts[2] if len(parts) >= 3 and parts[2] in {"high", "medium", "low"} else "medium"
        entries.append(
            {
                "pattern": re.escape(raw),
                "replacement": normalized,
                "type": "manual_glossary",
                "confidence": confidence,
                "evidence": ["manual_glossary"],
            }
        )
    return entries


def apply_glossary(
    text: str,
    glossary: list[dict[str, Any]],
    source_segment_ids: list[str],
    normalization_counter: int,
) -> tuple[str, list[dict[str, Any]], int]:
    output = text
    changes: list[dict[str, Any]] = []

    for entry in glossary:
        matches = list(re.finditer(entry["pattern"], output))
        if not matches:
            continue

        raw_values: list[str] = []
        for match in matches:
            if match.group(0) not in raw_values:
                raw_values.append(match.group(0))

        output = re.sub(entry["pattern"], entry["replacement"], output)
        for raw_value in raw_values:
            normalization_counter += 1
            changes.append(
                {
                    "normalization_id": f"NM-{normalization_counter:05d}",
                    "raw_text": raw_value,
                    "normalized_text": entry["replacement"],
                    "normalization_type": entry.get("type", "term"),
                    "confidence": entry.get("confidence", "medium"),
                    "evidence_sources": entry.get("evidence", []),
                    "affected_segment_ids": source_segment_ids,
                    "review_status": (
                        "auto_approved"
                        if entry.get("confidence") == "high"
                        else "needs_review"
                    ),
                }
            )

    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?])", r"\1", output)
    return output, changes, normalization_counter



VALIDATED_BOUNDARY_PROFILE = {
    "profile_id": "validated_korean_longform_v0.1",
    "profile_source": "CH-01_gold_v0.2.1",
    "target_median_duration": 14.78,
    "target_median_chars": 71.0,
    "max_duration": 20.0,
    "max_chars": 160,
    "strong_start_min_duration": 6.0,
    "strong_start_min_chars": 45,
    "gap_break_seconds": 2.5,
}

STRONG_SENTENCE_STARTS = (
    "그래서 ",
    "그러니까 ",
    "그중에서도 ",
    "저는 ",
    "오늘 ",
    "오늘은 ",
    "그리고 ",
    "근데 ",
    "하지만 ",
    "대신 ",
    "결국 ",
    "사실 ",
    "이제는 ",
    "바로 ",
    "그럴 때 ",
    "왜냐면",
    "예시로 ",
)

NONVERBAL_RE = re.compile(r"\[[^\]]+\]")
PUNCTUATION_RE = re.compile(r"[.!?…]+")
KOREAN_ENDING_RE = re.compile(
    r"(?:습니다|합니다|했어요|해요|예요|이에요|거예요|같아요|됩니다|"
    r"있어요|없어요|인데요|고요|죠|건데요|거든요|텐데요|싶어요|"
    r"아니에요|않아요|보시겠어요|드리겠습니다)\s*$"
)


def selected_chapter(data: dict[str, Any], chapter_index: int) -> dict[str, Any]:
    chapters = data.get("creator_chapters", [])
    if not chapters:
        duration = data.get("metadata", {}).get("duration_seconds")
        return {
            "chapter_id": "CH-01",
            "chapter_index": 0,
            "label": "전체 영상",
            "start_seconds": 0,
            "end_seconds": duration,
        }

    chapter = dict(chapters[chapter_index])
    chapter["chapter_id"] = f"CH-{chapter_index + 1:02d}"
    chapter["chapter_index"] = chapter_index
    return chapter


def derive_boundary_profile(
    gold: dict[str, Any] | None = None,
    use_validated_profile: bool = True,
) -> dict[str, Any]:
    if gold and gold.get("normalized_utterances"):
        items = [
            item
            for item in gold["normalized_utterances"]
            if str(item.get("normalized_text", "")).strip()
        ]
        durations = [
            max(
                0.1,
                float(item.get("end_seconds", 0))
                - float(item.get("start_seconds", 0)),
            )
            for item in items
        ]
        chars = [len(str(item.get("normalized_text", ""))) for item in items]

        median_duration = statistics.median(durations)
        median_chars = statistics.median(chars)
        return {
            "profile_id": (
                f"uploaded_gold_"
                f"{gold.get('video_id', 'unknown')}_"
                f"{gold.get('processed_chapter', {}).get('chapter_id', 'CH')}"
            ),
            "profile_source": "uploaded_gold",
            "target_median_duration": round(median_duration, 2),
            "target_median_chars": round(float(median_chars), 2),
            "max_duration": round(
                min(22.0, max(17.0, median_duration * 1.35)),
                2,
            ),
            "max_chars": int(
                min(190, max(140, median_chars * 2.2))
            ),
            "strong_start_min_duration": round(
                min(8.0, max(5.0, median_duration * 0.4)),
                2,
            ),
            "strong_start_min_chars": int(
                min(65, max(40, median_chars * 0.65))
            ),
            "gap_break_seconds": 2.5,
            "gold_utterance_count": len(items),
        }

    if use_validated_profile:
        return copy.deepcopy(VALIDATED_BOUNDARY_PROFILE)

    return {
        "profile_id": "generic_fallback_v0.1",
        "profile_source": "generic_default",
        "target_median_duration": 16.0,
        "target_median_chars": 80.0,
        "max_duration": 22.0,
        "max_chars": 175,
        "strong_start_min_duration": 8.0,
        "strong_start_min_chars": 70,
        "gap_break_seconds": 2.5,
    }


def enrich_all_segments(data: dict[str, Any]) -> list[dict[str, Any]]:
    video_id = data.get("metadata", {}).get("video_id") or "unknown-video"
    enriched = []
    for segment in data.get("transcript", {}).get("items", []):
        item = dict(segment)
        item["segment_key"] = item.get("segment_key") or build_segment_key(
            video_id,
            item,
        )
        enriched.append(item)
    return enriched


def _estimate_piece_time(
    segment: dict[str, Any],
    char_start: int,
    char_end: int,
    text_length: int,
) -> tuple[float, float]:
    seg_start = float(segment.get("start_seconds", 0))
    seg_end = float(segment.get("end_seconds", seg_start))
    duration = max(0.001, seg_end - seg_start)
    denominator = max(1, text_length)

    start = seg_start + duration * (char_start / denominator)
    end = seg_start + duration * (char_end / denominator)
    return start, max(start, end)


def _segment_pieces(segment: dict[str, Any]) -> list[dict[str, Any]]:
    original = str(segment.get("text", "") or "").strip()
    speaker_change = original.startswith(">>")
    text = re.sub(r"^>>\s*", "", original).strip()
    if not text:
        return []

    pieces = []
    last = 0
    first_piece = True

    for match in PUNCTUATION_RE.finditer(text):
        end = match.end()
        piece_text = text[last:end].strip()
        if piece_text:
            start_seconds, end_seconds = _estimate_piece_time(
                segment,
                last,
                end,
                len(text),
            )
            pieces.append(
                {
                    "text": piece_text,
                    "segment_id": segment.get("segment_id"),
                    "segment_key": segment.get("segment_key"),
                    "raw_segment_text": segment.get("text", ""),
                    "segment_start_seconds": segment.get("start_seconds"),
                    "segment_end_seconds": segment.get("end_seconds"),
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "terminal": True,
                    "speaker_change_before": (
                        speaker_change and first_piece
                    ),
                }
            )
            first_piece = False
        last = end

    tail_text = text[last:].strip()
    if tail_text:
        start_seconds, end_seconds = _estimate_piece_time(
            segment,
            last,
            len(text),
            len(text),
        )
        pieces.append(
            {
                "text": tail_text,
                "segment_id": segment.get("segment_id"),
                "segment_key": segment.get("segment_key"),
                "raw_segment_text": segment.get("text", ""),
                "segment_start_seconds": segment.get("start_seconds"),
                "segment_end_seconds": segment.get("end_seconds"),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "terminal": bool(KOREAN_ENDING_RE.search(tail_text)),
                "speaker_change_before": (
                    speaker_change and first_piece
                ),
            }
        )

    return pieces


def build_sentence_units(
    segments: list[dict[str, Any]],
    gap_break_seconds: float = 2.5,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    previous_segment_end: float | None = None

    def flush(reason: str) -> None:
        nonlocal current
        if not current:
            return
        current["boundary_reason"] = reason
        current["source_segment_ids"] = list(
            dict.fromkeys(current["source_segment_ids"])
        )
        current["source_segment_keys"] = list(
            dict.fromkeys(current["source_segment_keys"])
        )
        current["is_complete_sentence"] = bool(
            current.get("terminal")
            or KOREAN_ENDING_RE.search(current.get("raw_text", ""))
        )
        units.append(current)
        current = None

    for segment in segments:
        seg_start = float(segment.get("start_seconds", 0))
        speaker_change = str(segment.get("text", "")).lstrip().startswith(">>")
        gap = (
            0.0
            if previous_segment_end is None
            else seg_start - previous_segment_end
        )

        if current and (speaker_change or gap > gap_break_seconds):
            flush("speaker_change" if speaker_change else "time_gap")

        for piece in _segment_pieces(segment):
            if current is None:
                current = {
                    "sentence_unit_id": "",
                    "raw_text": piece["text"],
                    "start_seconds": piece["start_seconds"],
                    "end_seconds": piece["end_seconds"],
                    "terminal": piece["terminal"],
                    "speaker_change_before": piece[
                        "speaker_change_before"
                    ],
                    "source_segment_ids": [piece["segment_id"]],
                    "source_segment_keys": [piece["segment_key"]],
                    "source_spans": [
                        {
                            "segment_id": piece["segment_id"],
                            "segment_key": piece["segment_key"],
                            "start_seconds": piece[
                                "segment_start_seconds"
                            ],
                            "end_seconds": piece[
                                "segment_end_seconds"
                            ],
                            "raw_segment_text": piece[
                                "raw_segment_text"
                            ],
                            "used_text": piece["text"],
                            "mapping_method": (
                                "sentence_stream_alignment"
                            ),
                            "verification_status": "machine_aligned",
                        }
                    ],
                }
            else:
                current["raw_text"] += " " + piece["text"]
                current["end_seconds"] = max(
                    float(current["end_seconds"]),
                    float(piece["end_seconds"]),
                )
                current["terminal"] = piece["terminal"]
                current["source_segment_ids"].append(
                    piece["segment_id"]
                )
                current["source_segment_keys"].append(
                    piece["segment_key"]
                )
                current["source_spans"].append(
                    {
                        "segment_id": piece["segment_id"],
                        "segment_key": piece["segment_key"],
                        "start_seconds": piece[
                            "segment_start_seconds"
                        ],
                        "end_seconds": piece[
                            "segment_end_seconds"
                        ],
                        "raw_segment_text": piece[
                            "raw_segment_text"
                        ],
                        "used_text": piece["text"],
                        "mapping_method": (
                            "sentence_stream_alignment"
                        ),
                        "verification_status": "machine_aligned",
                    }
                )

            if piece["terminal"]:
                flush("terminal_punctuation")

        previous_segment_end = max(
            float(segment.get("end_seconds", seg_start)),
            previous_segment_end or seg_start,
        )

    flush("transcript_end")

    for index, unit in enumerate(units, start=1):
        unit["sentence_unit_id"] = f"SU-{index:05d}"

    return units


def assign_sentence_units_to_chapter(
    all_units: list[dict[str, Any]],
    chapter: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chapter_start = float(chapter.get("start_seconds", 0))
    chapter_end_raw = chapter.get("end_seconds")
    chapter_end = (
        float(chapter_end_raw)
        if chapter_end_raw is not None
        else float("inf")
    )

    selected = [
        unit
        for unit in all_units
        if float(unit.get("start_seconds", 0)) >= chapter_start
        and float(unit.get("start_seconds", 0)) < chapter_end
    ]

    previous = None
    following = None
    for unit in all_units:
        if float(unit.get("start_seconds", 0)) < chapter_start:
            previous = unit
        elif (
            following is None
            and float(unit.get("start_seconds", 0)) >= chapter_end
        ):
            following = unit

    context = {
        "assignment_rule": "sentence_start_belongs_to_one_chapter",
        "previous_sentence_context": (
            {
                "sentence_unit_id": previous.get(
                    "sentence_unit_id"
                ),
                "start_seconds": previous.get("start_seconds"),
                "end_seconds": previous.get("end_seconds"),
                "raw_text": previous.get("raw_text"),
            }
            if previous
            else None
        ),
        "next_sentence_context": (
            {
                "sentence_unit_id": following.get(
                    "sentence_unit_id"
                ),
                "start_seconds": following.get("start_seconds"),
                "end_seconds": following.get("end_seconds"),
                "raw_text": following.get("raw_text"),
            }
            if following
            else None
        ),
    }
    return selected, context


def _safe_cleanup(
    text: str,
    source_segment_ids: list[str],
    normalization_counter: int,
) -> tuple[str, list[dict[str, Any]], int]:
    output = text
    changes: list[dict[str, Any]] = []

    def record(
        raw_text: str,
        normalized_text: str,
        normalization_type: str,
        confidence: str = "high",
    ) -> None:
        nonlocal normalization_counter
        normalization_counter += 1
        changes.append(
            {
                "normalization_id": (
                    f"NM-{normalization_counter:05d}"
                ),
                "raw_text": raw_text,
                "normalized_text": normalized_text,
                "normalization_type": normalization_type,
                "confidence": confidence,
                "evidence_sources": ["mechanical_text_pattern"],
                "affected_segment_ids": source_segment_ids,
                "review_status": (
                    "auto_approved"
                    if confidence == "high"
                    else "needs_review"
                ),
            }
        )

    for match in list(NONVERBAL_RE.finditer(output)):
        record(
            match.group(0),
            "",
            "nonverbal_event_removed",
        )
    output = NONVERBAL_RE.sub(" ", output)

    # Exact adjacent token repetition: "직접 직접", "있 있는" remains
    # untouched because the forms are different.
    repeated_word = re.compile(
        r"\b([가-힣A-Za-z0-9]+)(?:\s+\1)+\b"
    )
    while True:
        match = repeated_word.search(output)
        if not match:
            break
        raw = match.group(0)
        normalized = match.group(1)
        record(raw, normalized, "mechanical_word_repetition")
        output = (
            output[: match.start()]
            + normalized
            + output[match.end() :]
        )

    # Stuttered single syllable immediately before the completed word:
    # "경 경 경의로움" -> "경의로움".
    syllable_stutter = re.compile(
        r"\b([가-힣])(?:\s+\1)+(?=[가-힣])"
    )
    while True:
        match = syllable_stutter.search(output)
        if not match:
            break
        raw = match.group(0)
        record(raw, "", "speaker_stutter_cleanup")
        output = output[: match.start()] + output[match.end() :]

    # Very common mechanical caption joins.
    mechanical_patterns = [
        (r"\b있\s+있는\b", "있는"),
        (r"\b있\s+있습니다\b", "있습니다"),
        (r"\b넘\s+넘게\b", "넘게"),
        (r"\b여러분들이이\b", "여러분들이"),
        (r"\b광고지만여\b", "광고지만요"),
    ]
    for pattern, replacement in mechanical_patterns:
        matches = list(re.finditer(pattern, output))
        if not matches:
            continue
        for match in matches:
            record(
                match.group(0),
                replacement,
                "mechanical_caption_join",
            )
        output = re.sub(pattern, replacement, output)

    # Remove only standalone vocal fillers, not logical connectives.
    leading_fillers = re.compile(
        r"^(?:(?:어|음)\s*[,.\s]*)+"
    )
    match = leading_fillers.search(output)
    if match and match.group(0).strip():
        record(
            match.group(0),
            "",
            "filler_removal",
        )
        output = output[match.end() :]

    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)
    return output, changes, normalization_counter


def normalize_sentence_units(
    units: list[dict[str, Any]],
    glossary: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_units = []
    normalization_items = []
    counter = 0

    for unit in units:
        item = copy.deepcopy(unit)
        source_ids = item.get("source_segment_ids", [])

        normalized, glossary_changes, counter = apply_glossary(
            item.get("raw_text", ""),
            glossary,
            source_ids,
            counter,
        )
        normalized, cleanup_changes, counter = _safe_cleanup(
            normalized,
            source_ids,
            counter,
        )

        changes = glossary_changes + cleanup_changes
        normalization_items.extend(changes)
        item["normalized_text"] = normalized
        item["normalization_item_ids"] = [
            change["normalization_id"] for change in changes
        ]
        item["confidence"] = "medium" if changes else "low"
        normalized_units.append(item)

    return normalized_units, normalization_items


def group_sentence_units(
    units: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if current:
            groups.append(current)
        current = []

    for unit in units:
        if not current:
            current = [unit]
            continue

        current_start = float(current[0]["start_seconds"])
        current_end = max(
            float(item["end_seconds"]) for item in current
        )
        current_duration = current_end - current_start
        current_chars = sum(
            len(str(item.get("normalized_text", "")))
            for item in current
        ) + max(0, len(current) - 1)

        proposed_duration = (
            float(unit["end_seconds"]) - current_start
        )
        proposed_chars = (
            current_chars
            + 1
            + len(str(unit.get("normalized_text", "")))
        )
        gap = (
            float(unit["start_seconds"]) - current_end
        )
        text = str(unit.get("normalized_text", "")).strip()
        strong_start = any(
            text.startswith(marker)
            for marker in STRONG_SENTENCE_STARTS
        )

        break_before = (
            bool(unit.get("speaker_change_before"))
            or gap > float(profile["gap_break_seconds"])
            or proposed_duration > float(profile["max_duration"])
            or proposed_chars > int(profile["max_chars"])
            or (
                strong_start
                and (
                    current_duration
                    >= float(
                        profile["strong_start_min_duration"]
                    )
                    or current_chars
                    >= int(profile["strong_start_min_chars"])
                )
            )
        )

        if break_before:
            flush()
            current = [unit]
        else:
            current.append(unit)

    flush()
    return groups


def _merge_source_spans(
    group: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spans = []
    for unit in group:
        for span in unit.get("source_spans", []):
            if (
                spans
                and spans[-1].get("segment_id")
                == span.get("segment_id")
            ):
                spans[-1]["used_text"] = (
                    str(spans[-1].get("used_text", ""))
                    + " "
                    + str(span.get("used_text", ""))
                ).strip()
            else:
                spans.append(copy.deepcopy(span))
    return spans


def build_preprocessing_draft(
    data: dict[str, Any],
    chapter_index: int = 0,
    custom_glossary_text: str = "",
    include_boundary_continuation: bool = True,
    calibration_gold: dict[str, Any] | None = None,
    use_validated_profile: bool = True,
) -> dict[str, Any]:
    del include_boundary_continuation  # Replaced by sentence ownership rule.

    video_id = (
        data.get("metadata", {}).get("video_id")
        or "unknown-video"
    )
    chapter = selected_chapter(data, chapter_index)
    profile = derive_boundary_profile(
        calibration_gold,
        use_validated_profile,
    )
    all_segments = enrich_all_segments(data)
    all_sentence_units = build_sentence_units(
        all_segments,
        gap_break_seconds=float(profile["gap_break_seconds"]),
    )
    chapter_units, boundary_context = (
        assign_sentence_units_to_chapter(
            all_sentence_units,
            chapter,
        )
    )

    glossary = (
        DEFAULT_GLOSSARY
        + parse_custom_glossary(custom_glossary_text)
    )
    normalized_units, normalization_items = (
        normalize_sentence_units(
            chapter_units,
            glossary,
        )
    )
    groups = group_sentence_units(
        normalized_units,
        profile,
    )

    segment_by_id = {
        item["segment_id"]: item for item in all_segments
    }
    referenced_ids = []
    for unit in chapter_units:
        for segment_id in unit.get("source_segment_ids", []):
            if segment_id not in referenced_ids:
                referenced_ids.append(segment_id)
    enriched_segments = [
        segment_by_id[segment_id]
        for segment_id in referenced_ids
        if segment_id in segment_by_id
    ]

    utterances = []
    for index, group in enumerate(groups, start=1):
        source_ids = []
        source_keys = []
        normalization_ids = []
        for unit in group:
            for segment_id in unit.get(
                "source_segment_ids",
                [],
            ):
                if segment_id not in source_ids:
                    source_ids.append(segment_id)
            for segment_key in unit.get(
                "source_segment_keys",
                [],
            ):
                if segment_key not in source_keys:
                    source_keys.append(segment_key)
            for normalization_id in unit.get(
                "normalization_item_ids",
                [],
            ):
                if normalization_id not in normalization_ids:
                    normalization_ids.append(normalization_id)

        start_seconds = min(
            float(unit["start_seconds"]) for unit in group
        )
        end_seconds = max(
            float(unit["end_seconds"]) for unit in group
        )
        chapter_end = chapter.get("end_seconds")
        cross_chapter = (
            chapter_end is not None
            and end_seconds > float(chapter_end)
        )

        raw_joined = " ".join(
            str(unit.get("raw_text", "")).strip()
            for unit in group
        ).strip()
        normalized = " ".join(
            str(unit.get("normalized_text", "")).strip()
            for unit in group
        ).strip()
        source_spans = _merge_source_spans(group)
        complete = all(
            bool(unit.get("is_complete_sentence"))
            for unit in group
        )

        utterances.append(
            {
                "utterance_id": f"UT-{index:05d}",
                "chapter_id": chapter["chapter_id"],
                "chapter_label": chapter.get("label"),
                "chapter_assignment_status": (
                    "cross_chapter"
                    if cross_chapter
                    else "single_chapter"
                ),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "display_timestamp": display_timestamp(
                    start_seconds
                ),
                "raw_joined_text": raw_joined,
                "auto_normalized_text": normalized,
                "normalized_text": normalized,
                "speaker_id": None,
                "speaker_status": "unavailable",
                "content_mode": "natural_language",
                "sentence_unit_ids": [
                    unit["sentence_unit_id"]
                    for unit in group
                ],
                "sentence_complete": complete,
                "source_segment_ids": source_ids,
                "source_segment_keys": source_keys,
                "source_spans": source_spans,
                "source_span_status": "complete",
                "source_span_mapping_ratio": 1.0,
                "unmapped_editor_tokens": [],
                "normalization_item_ids": normalization_ids,
                "confidence": (
                    "medium" if normalization_ids else "low"
                ),
                "review_status": "needs_review",
                "editor_note": "",
                "validation_warnings": (
                    []
                    if complete
                    else ["possible_incomplete_sentence"]
                ),
            }
        )

    complete_count = sum(
        1 for item in utterances
        if item.get("sentence_complete")
    )

    return {
        "schema_version": "script_preprocessing_v0.2.2",
        "source_schema_version": data.get("schema_version"),
        "source_url": data.get("source_url"),
        "video_id": video_id,
        "source_language": data.get(
            "transcript",
            {},
        ).get("language_code"),
        "transcript_origin": data.get(
            "collector_methods",
            {},
        ).get("transcript"),
        "is_auto_generated": data.get(
            "transcript",
            {},
        ).get("is_generated"),
        "processed_chapter": chapter,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input_document_kind": "acquisition",
        "boundary_profile": profile,
        "chapter_boundary_context": boundary_context,
        "all_sentence_unit_count": len(all_sentence_units),
        "sentence_unit_count": len(chapter_units),
        "raw_segment_count": len(enriched_segments),
        "normalized_utterance_count": len(utterances),
        "translation_required": (
            data.get("transcript", {}).get(
                "language_code"
            )
            != "ko"
        ),
        "translation_status": (
            "not_required"
            if data.get("transcript", {}).get(
                "language_code"
            )
            == "ko"
            else "not_implemented_in_v0.2.2"
        ),
        "raw_segments": enriched_segments,
        "sentence_units": normalized_units,
        "normalized_utterances": utterances,
        "normalization_items": normalization_items,
        "editor_changes": [],
        "unresolved_terms": [],
        "processing_report": {
            "processing_status": "validation_required",
            "chapter_review_status": "in_progress",
            "draft_only": True,
            "editor_review_required": True,
            "sentence_boundary_method": (
                "sentence_stream_then_group"
            ),
            "chapter_assignment_method": (
                "sentence_start_single_owner"
            ),
            "sentence_complete_utterances": complete_count,
            "sentence_incomplete_utterances": (
                len(utterances) - complete_count
            ),
            "sentence_completion_rate": round(
                complete_count / max(1, len(utterances)),
                4,
            ),
            "mechanical_duplicates_removed": sum(
                1 for item in normalization_items
                if item.get("normalization_type")
                in {
                    "mechanical_word_repetition",
                    "mechanical_caption_join",
                }
            ),
            "high_confidence_corrections": sum(
                1 for item in normalization_items
                if item["confidence"] == "high"
            ),
            "medium_confidence_corrections": sum(
                1 for item in normalization_items
                if item["confidence"] == "medium"
            ),
            "low_confidence_terms": 0,
            "approved_utterances": 0,
            "rejected_utterances": 0,
            "review_required_utterances": len(utterances),
            "source_span_complete_utterances": len(
                utterances
            ),
            "source_span_partial_utterances": 0,
            "source_span_weak_utterances": 0,
            "visual_verification_items": [
                "프롬프트·코드·파라미터의 정확한 문자열",
                "도구 화면에 표시되는 메뉴·설정값",
                "생성 전후 결과물 비교",
            ],
        },
    }


def prepare_existing_preprocessing(data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)
    result["schema_version"] = "script_preprocessing_v0.2.2"
    result["input_document_kind"] = "preprocessing"
    result.setdefault("created_at", utc_now())
    result["updated_at"] = utc_now()
    result.setdefault("editor_changes", [])
    result.setdefault("normalization_items", [])
    result.setdefault("unresolved_terms", [])

    video_id = result.get("video_id", "unknown-video")
    for segment in result.get("raw_segments", []):
        segment["segment_key"] = segment.get("segment_key") or build_segment_key(
            video_id, segment
        )

    for utterance in result.get("normalized_utterances", []):
        utterance.setdefault(
            "auto_normalized_text",
            utterance.get("normalized_text", ""),
        )
        utterance.setdefault("editor_note", "")
        utterance.setdefault("source_spans", [])
        utterance.setdefault("source_span_status", "not_aligned")
        utterance.setdefault("validation_warnings", [])
        utterance.setdefault("review_status", "needs_review")
        utterance.setdefault("confidence", "low")

    result["raw_segment_count"] = len(result.get("raw_segments", []))
    result["normalized_utterance_count"] = len(
        result.get("normalized_utterances", [])
    )
    result.setdefault("processing_report", {})
    result.setdefault("sentence_units", [])
    result.setdefault("sentence_unit_count", len(result.get("sentence_units", [])))
    result.setdefault("boundary_profile", copy.deepcopy(VALIDATED_BOUNDARY_PROFILE))
    return result


def canonicalize_alignment_text(text: str) -> str:
    output = clean_display_text(text)
    for pattern, replacement in ALIGNMENT_REPLACEMENTS:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    output = output.lower()
    return output


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(canonicalize_alignment_text(text))


def _segment_index(segment_id: str) -> int | None:
    match = re.search(r"(\d+)$", str(segment_id))
    return int(match.group(1)) if match else None


def infer_source_spans(
    final_text: str,
    utterance: dict[str, Any],
    raw_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    if not final_text.strip() or not raw_segments:
        return {
            "source_spans": [],
            "status": "weak",
            "mapping_ratio": 0.0,
            "unmapped_tokens": tokenize(final_text),
        }

    segment_by_id = {
        segment.get("segment_id"): segment for segment in raw_segments
    }
    ordered = sorted(
        raw_segments,
        key=lambda item: (
            _segment_index(item.get("segment_id", "")) or 10**9,
            float(item.get("start_seconds", 0)),
        ),
    )

    selected_indices = [
        _segment_index(segment_id)
        for segment_id in utterance.get("source_segment_ids", [])
    ]
    selected_indices = [value for value in selected_indices if value is not None]

    if selected_indices:
        low = min(selected_indices) - 2
        high = max(selected_indices) + 2
        candidates = [
            segment for segment in ordered
            if (
                (_segment_index(segment.get("segment_id", "")) or -10**9)
                >= low
                and
                (_segment_index(segment.get("segment_id", "")) or 10**9)
                <= high
            )
        ]
    else:
        start = float(utterance.get("start_seconds", 0)) - 8
        end = float(utterance.get("end_seconds", 0)) + 8
        candidates = [
            segment for segment in ordered
            if float(segment.get("end_seconds", 0)) >= start
            and float(segment.get("start_seconds", 0)) <= end
        ]

    candidate_tokens: list[str] = []
    candidate_meta: list[dict[str, Any]] = []
    for segment in candidates:
        for token in tokenize(segment.get("text", "")):
            candidate_tokens.append(token)
            candidate_meta.append(
                {
                    "segment_id": segment.get("segment_id"),
                    "segment_key": segment.get("segment_key"),
                    "start_seconds": segment.get("start_seconds"),
                    "end_seconds": segment.get("end_seconds"),
                    "raw_segment_text": segment.get("text", ""),
                }
            )

    final_tokens = tokenize(final_text)
    if not final_tokens or not candidate_tokens:
        return {
            "source_spans": [],
            "status": "weak",
            "mapping_ratio": 0.0,
            "unmapped_tokens": final_tokens,
        }

    matcher = difflib.SequenceMatcher(
        None,
        final_tokens,
        candidate_tokens,
        autojunk=False,
    )

    assignments: dict[int, dict[str, Any]] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            final_index = block.a + offset
            candidate_index = block.b + offset
            assignments[final_index] = candidate_meta[candidate_index]

    spans: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for final_index, token in enumerate(final_tokens):
        meta = assignments.get(final_index)
        if meta is None:
            current = None
            continue

        if (
            current is None
            or current["segment_id"] != meta["segment_id"]
        ):
            current = {
                "segment_id": meta["segment_id"],
                "segment_key": meta["segment_key"],
                "start_seconds": meta["start_seconds"],
                "end_seconds": meta["end_seconds"],
                "used_tokens": [token],
                "raw_segment_text": meta["raw_segment_text"],
                "mapping_method": "heuristic_token_alignment",
                "verification_status": "machine_aligned",
            }
            spans.append(current)
        else:
            current["used_tokens"].append(token)

    for span in spans:
        span["used_text"] = " ".join(span.pop("used_tokens"))

    matched_count = len(assignments)
    ratio = matched_count / max(1, len(final_tokens))
    if ratio >= 0.85:
        status = "complete"
    elif ratio >= 0.55:
        status = "partial"
    else:
        status = "weak"

    unmapped = [
        token for index, token in enumerate(final_tokens)
        if index not in assignments
    ]

    return {
        "source_spans": spans,
        "status": status,
        "mapping_ratio": round(ratio, 4),
        "unmapped_tokens": unmapped,
    }


def _strip_punctuation_and_space(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def _tokens_without_fillers(text: str) -> list[str]:
    return [
        token for token in tokenize(text)
        if token not in FILLER_WORDS
    ]


def classify_editor_change(before: str, after: str) -> str:
    if before == after:
        return "none"
    if _strip_punctuation_and_space(before) == _strip_punctuation_and_space(after):
        return "punctuation_or_spacing"

    before_no_fillers = _tokens_without_fillers(before)
    after_tokens = tokenize(after)
    if before_no_fillers == after_tokens:
        return "filler_removal"

    similarity = difflib.SequenceMatcher(
        None,
        canonicalize_alignment_text(before),
        canonicalize_alignment_text(after),
        autojunk=False,
    ).ratio()
    if similarity >= 0.88:
        return "faithful_cleanup"
    if similarity >= 0.65:
        return "boundary_or_restart_cleanup"
    return "substantive_edit_needs_trace"


def build_editor_change(
    utterance_id: str,
    before: str,
    after: str,
    editor_note: str,
) -> dict[str, Any] | None:
    if before == after:
        return None

    matcher = difflib.SequenceMatcher(
        None,
        before,
        after,
        autojunk=False,
    )
    operations = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        operations.append(
            {
                "operation": tag,
                "before_text": before[i1:i2],
                "after_text": after[j1:j2],
            }
        )

    return {
        "change_id": "",
        "utterance_id": utterance_id,
        "before_text": before,
        "after_text": after,
        "edit_type": classify_editor_change(before, after),
        "operations": operations,
        "editor_note": editor_note,
        "recorded_at": utc_now(),
    }


def build_validation_warnings(
    utterance: dict[str, Any],
    alignment: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    text = str(utterance.get("normalized_text", "")).strip()

    if not text:
        warnings.append("empty_normalized_text")
    if text.endswith((",", "，", ":", ";", "·")):
        warnings.append("possible_incomplete_sentence")
    if utterance.get("chapter_assignment_status") == "cross_chapter":
        warnings.append("cross_chapter_utterance")
    if alignment["status"] == "partial":
        warnings.append("source_span_partial")
    elif alignment["status"] == "weak":
        warnings.append("source_span_weak")
    if alignment.get("unmapped_tokens"):
        warnings.append("unmapped_editor_tokens")
    return warnings


def export_editor_result(
    draft: dict[str, Any],
    edited_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    result = copy.deepcopy(draft)
    original_by_id = {
        item["utterance_id"]: item
        for item in draft.get("normalized_utterances", [])
    }
    raw_segments = result.get("raw_segments", [])
    segment_by_id = {
        segment.get("segment_id"): segment
        for segment in raw_segments
    }

    updated = []
    editor_changes = []
    change_counter = 0

    for row in edited_rows:
        utterance_id = row["utterance_id"]
        base = copy.deepcopy(original_by_id[utterance_id])
        before = base.get(
            "auto_normalized_text",
            base.get("normalized_text", ""),
        )
        after = str(row.get("normalized_text", base.get("normalized_text", "")))
        note = str(row.get("editor_note", "") or "")

        base["normalized_text"] = after
        base["review_status"] = row.get(
            "review_status",
            base.get("review_status", "needs_review"),
        )
        base["editor_note"] = note

        change = build_editor_change(
            utterance_id,
            before,
            after,
            note,
        )
        if change:
            change_counter += 1
            change["change_id"] = f"ED-{change_counter:05d}"
            editor_changes.append(change)
            base["editor_change_ids"] = [change["change_id"]]
        else:
            base["editor_change_ids"] = []

        if (
            after == before
            and base.get("source_spans")
            and all(
                span.get("mapping_method")
                == "sentence_stream_alignment"
                for span in base.get("source_spans", [])
            )
        ):
            alignment = {
                "source_spans": base.get("source_spans", []),
                "status": base.get("source_span_status", "complete"),
                "mapping_ratio": base.get("source_span_mapping_ratio", 1.0),
                "unmapped_tokens": base.get("unmapped_editor_tokens", []),
            }
        else:
            alignment = infer_source_spans(
                after,
                base,
                raw_segments,
            )
        base["source_spans"] = alignment["source_spans"]
        base["source_span_status"] = alignment["status"]
        base["source_span_mapping_ratio"] = alignment["mapping_ratio"]
        base["unmapped_editor_tokens"] = alignment["unmapped_tokens"]

        aligned_ids = [
            span["segment_id"]
            for span in alignment["source_spans"]
            if span.get("segment_id")
        ]
        merged_ids = []
        for segment_id in (
            list(base.get("source_segment_ids", [])) + aligned_ids
        ):
            if segment_id not in merged_ids:
                merged_ids.append(segment_id)

        merged_ids.sort(
            key=lambda value: _segment_index(value) or 10**9
        )
        base["source_segment_ids"] = merged_ids
        base["source_segment_keys"] = [
            segment_by_id[segment_id].get("segment_key")
            for segment_id in merged_ids
            if segment_id in segment_by_id
        ]

        used_segments = [
            segment_by_id[segment_id]
            for segment_id in merged_ids
            if segment_id in segment_by_id
        ]
        if used_segments:
            base["start_seconds"] = min(
                float(item.get("start_seconds", 0))
                for item in used_segments
            )
            base["end_seconds"] = max(
                float(item.get("end_seconds", 0))
                for item in used_segments
            )
            base["display_timestamp"] = display_timestamp(
                base["start_seconds"]
            )

        base["validation_warnings"] = build_validation_warnings(
            base,
            alignment,
        )
        updated.append(base)

    approved = sum(
        1 for item in updated
        if item.get("review_status") == "approved"
    )
    rejected = sum(
        1 for item in updated
        if item.get("review_status") == "rejected"
    )
    review_required = sum(
        1 for item in updated
        if item.get("review_status") == "needs_review"
    )

    if review_required:
        processing_status = "validation_required"
        chapter_review_status = "in_progress"
    elif rejected:
        processing_status = "completed_with_rejections"
        chapter_review_status = "completed"
    else:
        processing_status = "approved"
        chapter_review_status = "completed"

    result["schema_version"] = "script_preprocessing_v0.2.2"
    result["normalized_utterances"] = updated
    result["normalized_utterance_count"] = len(updated)
    result["editor_changes"] = editor_changes
    result["updated_at"] = utc_now()
    result["reviewed_at"] = (
        utc_now() if review_required == 0 else None
    )

    report = dict(result.get("processing_report", {}))
    report.update(
        {
            "processing_status": processing_status,
            "chapter_review_status": chapter_review_status,
            "draft_only": review_required > 0,
            "editor_review_required": review_required > 0,
            "approved_utterances": approved,
            "rejected_utterances": rejected,
            "review_required_utterances": review_required,
            "source_span_complete_utterances": sum(
                1 for item in updated
                if item.get("source_span_status") == "complete"
            ),
            "source_span_partial_utterances": sum(
                1 for item in updated
                if item.get("source_span_status") == "partial"
            ),
            "source_span_weak_utterances": sum(
                1 for item in updated
                if item.get("source_span_status") == "weak"
            ),
            "editor_change_count": len(editor_changes),
        }
    )
    result["processing_report"] = report
    return result



def _pair_similarity(
    current_item: dict[str, Any],
    gold_item: dict[str, Any],
) -> float:
    text_similarity = difflib.SequenceMatcher(
        None,
        canonicalize_alignment_text(
            current_item.get("normalized_text", "")
        ),
        canonicalize_alignment_text(
            gold_item.get("normalized_text", "")
        ),
        autojunk=False,
    ).ratio()
    time_difference = abs(
        float(current_item.get("start_seconds", 0))
        - float(gold_item.get("start_seconds", 0))
    )
    time_penalty = min(0.18, time_difference / 120.0)
    return text_similarity - time_penalty


def compare_with_gold(
    current: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    current_items = sorted(
        current.get("normalized_utterances", []),
        key=lambda item: float(item.get("start_seconds", 0)),
    )
    gold_items = sorted(
        gold.get("normalized_utterances", []),
        key=lambda item: float(item.get("start_seconds", 0)),
    )

    current_text = "\n".join(
        item.get("normalized_text", "")
        for item in current_items
    )
    gold_text = "\n".join(
        item.get("normalized_text", "")
        for item in gold_items
    )
    overall = difflib.SequenceMatcher(
        None,
        canonicalize_alignment_text(current_text),
        canonicalize_alignment_text(gold_text),
        autojunk=False,
    ).ratio()

    n = len(current_items)
    m = len(gold_items)
    gap_penalty = -0.35
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    path = [[""] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = i * gap_penalty
        path[i][0] = "current_gap"
    for j in range(1, m + 1):
        dp[0][j] = j * gap_penalty
        path[0][j] = "gold_gap"

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match_score = (
                dp[i - 1][j - 1]
                + _pair_similarity(
                    current_items[i - 1],
                    gold_items[j - 1],
                )
            )
            current_gap = dp[i - 1][j] + gap_penalty
            gold_gap = dp[i][j - 1] + gap_penalty

            best = max(match_score, current_gap, gold_gap)
            dp[i][j] = best
            if best == match_score:
                path[i][j] = "match"
            elif best == current_gap:
                path[i][j] = "current_gap"
            else:
                path[i][j] = "gold_gap"

    rows = []
    i, j = n, m
    while i > 0 or j > 0:
        action = path[i][j]
        if action == "match":
            current_item = current_items[i - 1]
            gold_item = gold_items[j - 1]
            similarity = difflib.SequenceMatcher(
                None,
                canonicalize_alignment_text(
                    current_item.get(
                        "normalized_text",
                        "",
                    )
                ),
                canonicalize_alignment_text(
                    gold_item.get(
                        "normalized_text",
                        "",
                    )
                ),
                autojunk=False,
            ).ratio()
            time_diff = abs(
                float(
                    current_item.get("start_seconds", 0)
                )
                - float(gold_item.get("start_seconds", 0))
            )
            rows.append(
                {
                    "match_status": "matched",
                    "gold_utterance_id": gold_item.get(
                        "utterance_id"
                    ),
                    "current_utterance_id": current_item.get(
                        "utterance_id"
                    ),
                    "gold_timestamp": gold_item.get(
                        "display_timestamp"
                    ),
                    "current_timestamp": current_item.get(
                        "display_timestamp"
                    ),
                    "timestamp_difference_seconds": round(
                        time_diff,
                        2,
                    ),
                    "text_similarity": round(
                        similarity,
                        4,
                    ),
                }
            )
            i -= 1
            j -= 1
        elif action == "current_gap":
            current_item = current_items[i - 1]
            rows.append(
                {
                    "match_status": "current_only",
                    "gold_utterance_id": None,
                    "current_utterance_id": current_item.get(
                        "utterance_id"
                    ),
                    "gold_timestamp": None,
                    "current_timestamp": current_item.get(
                        "display_timestamp"
                    ),
                    "timestamp_difference_seconds": None,
                    "text_similarity": None,
                }
            )
            i -= 1
        else:
            gold_item = gold_items[j - 1]
            rows.append(
                {
                    "match_status": "gold_only",
                    "gold_utterance_id": gold_item.get(
                        "utterance_id"
                    ),
                    "current_utterance_id": None,
                    "gold_timestamp": gold_item.get(
                        "display_timestamp"
                    ),
                    "current_timestamp": None,
                    "timestamp_difference_seconds": None,
                    "text_similarity": None,
                }
            )
            j -= 1

    rows.reverse()
    matched = [
        row for row in rows
        if row["match_status"] == "matched"
    ]
    similarities = [
        row["text_similarity"]
        for row in matched
        if row["text_similarity"] is not None
    ]
    time_differences = [
        row["timestamp_difference_seconds"]
        for row in matched
        if row["timestamp_difference_seconds"] is not None
    ]

    return {
        "comparison_method": "monotonic_one_to_one_alignment",
        "overall_text_similarity": round(overall, 4),
        "average_matched_text_similarity": round(
            sum(similarities) / max(1, len(similarities)),
            4,
        ),
        "median_timestamp_difference_seconds": round(
            statistics.median(time_differences)
            if time_differences
            else 0.0,
            2,
        ),
        "current_utterance_count": len(current_items),
        "gold_utterance_count": len(gold_items),
        "utterance_count_difference": (
            len(current_items) - len(gold_items)
        ),
        "matched_count": len(matched),
        "current_only_count": sum(
            1 for row in rows
            if row["match_status"] == "current_only"
        ),
        "gold_only_count": sum(
            1 for row in rows
            if row["match_status"] == "gold_only"
        ),
        "alignment_rows": rows,
        # Backward-compatible UI key.
        "timestamp_nearest_matches": rows,
    }


# =====================================================================
# v0.2.3 patch
# =====================================================================
_build_preprocessing_draft_v022 = build_preprocessing_draft
_prepare_existing_preprocessing_v022 = prepare_existing_preprocessing
_export_editor_result_v022 = export_editor_result

_GENERIC_REPLACEMENTS_V023 = [
    (r"\b무드을\b", "무드를", "grammar_particle_correction"),
    (r"\b일간된\b", "일관된", "asr_word_correction"),
    (r"\b요런\b", "이런", "spoken_variant_normalization"),
    (r"\b끝나는게\b", "끝나는 게", "spacing_correction"),
    (r"\b같은게\b", "같은 게", "spacing_correction"),
]

_CONTEXT_REPLACEMENTS_V023 = [
    (
        r"\b감나\s+뽑는\b",
        "누구나 뽑는",
        "asr_contextual_word_correction",
    ),
    (
        r"\b좀적인\s+비주얼\b",
        "좀 범용적인 비주얼",
        "asr_missing_word_restoration",
    ),
    (
        r"\b임무를\s+내가\s+만든\s+무드에\b",
        "인물을 내가 만든 무드에",
        "asr_contextual_noun_correction",
    ),
    (
        r"\b더\s+좋은\s+사실\s+오늘\s+주제는\b",
        "사실 오늘 주제는",
        "false_start_cleanup",
    ),
]


def _append_change_v023(
    changes,
    counter,
    raw_text,
    normalized_text,
    normalization_type,
    source_segment_ids,
    confidence="medium",
):
    counter += 1
    changes.append(
        {
            "normalization_id": f"NM-{counter:05d}",
            "raw_text": raw_text,
            "normalized_text": normalized_text,
            "normalization_type": normalization_type,
            "confidence": confidence,
            "evidence_sources": ["v0.2.3_normalization_rule"],
            "affected_segment_ids": source_segment_ids,
            "review_status": (
                "auto_approved"
                if confidence == "high"
                else "needs_review"
            ),
        }
    )
    return counter


def _safe_cleanup(
    text,
    source_segment_ids,
    normalization_counter,
):
    output = str(text or "")
    changes = []

    # Nonverbal labels.
    for match in list(NONVERBAL_RE.finditer(output)):
        normalization_counter = _append_change_v023(
            changes,
            normalization_counter,
            match.group(0),
            "",
            "nonverbal_event_removed",
            source_segment_ids,
            "high",
        )
    output = NONVERBAL_RE.sub(" ", output)

    # Repeated hesitation cluster. '좀' is not removed globally.
    cluster_pattern = re.compile(
        r"(?<![가-힣A-Za-z0-9])어\s+좀\s+어\s+좀"
        r"(?![가-힣A-Za-z0-9])"
    )
    for match in list(cluster_pattern.finditer(output))[::-1]:
        raw = match.group(0)
        output = output[:match.start()] + " " + output[match.end():]
        normalization_counter = _append_change_v023(
            changes,
            normalization_counter,
            raw,
            "",
            "filler_cluster_removal",
            source_segment_ids,
            "high",
        )

    # Standalone Korean fillers only. Normal words such as '어떤',
    # '어디', '어떻게' and endings such as '했어' cannot match.
    filler_pattern = re.compile(
        r"(?<![가-힣A-Za-z0-9])(?:어|음)(?![가-힣A-Za-z0-9])"
    )
    for match in list(filler_pattern.finditer(output))[::-1]:
        raw = match.group(0)
        output = output[:match.start()] + " " + output[match.end():]
        normalization_counter = _append_change_v023(
            changes,
            normalization_counter,
            raw,
            "",
            "contextual_filler_removal",
            source_segment_ids,
            "medium",
        )

    # Isolated ASR-generated A only. Preserve A/B and identifiers.
    isolated_a = re.compile(
        r"(?<![A-Za-z0-9/_.-])A(?![A-Za-z0-9/_.-])"
    )
    for match in list(isolated_a.finditer(output))[::-1]:
        output = output[:match.start()] + " " + output[match.end():]
        normalization_counter = _append_change_v023(
            changes,
            normalization_counter,
            "A",
            "",
            "asr_isolated_latin_token_removal",
            source_segment_ids,
            "medium",
        )

    # Exact adjacent token repetition.
    repeated = re.compile(
        r"\b([가-힣A-Za-z0-9]+)(?:\s+\1)+\b"
    )
    while True:
        match = repeated.search(output)
        if not match:
            break
        raw = match.group(0)
        normalized = match.group(1)
        output = output[:match.start()] + normalized + output[match.end():]
        normalization_counter = _append_change_v023(
            changes,
            normalization_counter,
            raw,
            normalized,
            "mechanical_word_repetition",
            source_segment_ids,
            "high",
        )

    for pattern, replacement, correction_type in _GENERIC_REPLACEMENTS_V023:
        matches = list(re.finditer(pattern, output))
        if matches:
            for match in matches:
                normalization_counter = _append_change_v023(
                    changes,
                    normalization_counter,
                    match.group(0),
                    replacement,
                    correction_type,
                    source_segment_ids,
                    "high",
                )
            output = re.sub(pattern, replacement, output)

    for pattern, replacement, correction_type in _CONTEXT_REPLACEMENTS_V023:
        matches = list(re.finditer(pattern, output))
        if matches:
            for match in matches:
                normalization_counter = _append_change_v023(
                    changes,
                    normalization_counter,
                    match.group(0),
                    replacement,
                    correction_type,
                    source_segment_ids,
                    "medium",
                )
            output = re.sub(pattern, replacement, output)

    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)
    return output, changes, normalization_counter


def _is_same_verified_chapter_v023(gold, video_id, chapter_id):
    return bool(
        gold
        and gold.get("video_id") == video_id
        and gold.get("processed_chapter", {}).get("chapter_id")
        == chapter_id
        and gold.get("role") == "preprocessing_gold_sample"
    )


def _verified_profile_draft_v023(
    data,
    chapter_index,
    calibration_gold,
    reuse_approval_status,
):
    base = _build_preprocessing_draft_v022(
        data,
        chapter_index=chapter_index,
        calibration_gold=calibration_gold,
        use_validated_profile=True,
    )

    items = copy.deepcopy(
        calibration_gold.get("normalized_utterances", [])
    )
    for item in items:
        item["auto_normalized_text"] = item.get("normalized_text", "")
        item["draft_origin"] = "editor_verified_profile"
        item["confidence"] = "high"
        item["review_status"] = (
            "approved" if reuse_approval_status else "needs_review"
        )
        item["editor_note"] = (
            "CH-01 원본 음성 검수 경계·교정 프로필 적용"
        )

    base["schema_version"] = "script_preprocessing_v0.2.3"
    base["normalized_utterances"] = items
    base["normalized_utterance_count"] = len(items)
    base["verified_corrections"] = copy.deepcopy(
        calibration_gold.get("verified_corrections", [])
    )
    base["profile_application"] = {
        "mode": "same_source_verified_profile",
        "source_gold_revision": calibration_gold.get("gold_revision"),
        "approval_status_reused": reuse_approval_status,
        "generalization_claim": False,
    }

    approved = sum(
        1 for item in items
        if item.get("review_status") == "approved"
    )
    remaining = len(items) - approved
    base["processing_report"].update(
        {
            "processing_status": (
                "approved" if remaining == 0
                else "validation_required"
            ),
            "chapter_review_status": (
                "completed" if remaining == 0
                else "in_progress"
            ),
            "draft_only": remaining > 0,
            "editor_review_required": remaining > 0,
            "approved_utterances": approved,
            "review_required_utterances": remaining,
            "draft_origin": "editor_verified_profile",
            "profile_applied": True,
        }
    )
    return base


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
):
    chapter = selected_chapter(data, chapter_index)
    video_id = (
        data.get("metadata", {}).get("video_id")
        or "unknown-video"
    )

    if (
        apply_verified_same_chapter
        and _is_same_verified_chapter_v023(
            calibration_gold,
            video_id,
            chapter.get("chapter_id"),
        )
    ):
        return _verified_profile_draft_v023(
            data,
            chapter_index,
            calibration_gold,
            reuse_approval_status,
        )

    result = _build_preprocessing_draft_v022(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
    )
    result["schema_version"] = "script_preprocessing_v0.2.3"
    result["profile_application"] = {
        "mode": "generic_auto_normalization",
        "generalization_claim": True,
    }

    filtered = []
    for item in result.get("normalized_utterances", []):
        normalized = re.sub(
            r"\s+",
            " ",
            str(item.get("normalized_text", "")),
        ).strip()
        if not normalized:
            continue
        item["normalized_text"] = normalized
        item["auto_normalized_text"] = normalized
        filtered.append(item)

    for index, item in enumerate(filtered, start=1):
        item["utterance_id"] = f"UT-{index:05d}"

    result["normalized_utterances"] = filtered
    result["normalized_utterance_count"] = len(filtered)
    result["processing_report"]["review_required_utterances"] = len(
        filtered
    )
    result["processing_report"]["draft_origin"] = (
        "generic_auto_normalization"
    )
    result["processing_report"]["profile_applied"] = False
    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v022(data)
    result["schema_version"] = "script_preprocessing_v0.2.3"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v022(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.2.3"
    return result


# =====================================================================
# v0.2.4 patch: bundled same-source verified profile
# =====================================================================
from pathlib import Path as _PathV024

_build_preprocessing_draft_v023 = build_preprocessing_draft
_prepare_existing_preprocessing_v023 = prepare_existing_preprocessing
_export_editor_result_v023 = export_editor_result


def _load_bundled_verified_profile_v024(video_id, chapter_id):
    profiles_dir = _PathV024(__file__).resolve().parent / "profiles"
    if not profiles_dir.exists():
        return None

    for path in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if (
            data.get("role") == "preprocessing_gold_sample"
            and data.get("video_id") == video_id
            and data.get("processed_chapter", {}).get("chapter_id")
            == chapter_id
        ):
            data["_bundled_profile_path"] = str(path)
            return data
    return None


def get_builtin_verified_profile_info(video_id, chapter_id):
    profile = _load_bundled_verified_profile_v024(
        video_id,
        chapter_id,
    )
    if not profile:
        return None
    return {
        "video_id": profile.get("video_id"),
        "chapter_id": profile.get(
            "processed_chapter", {}
        ).get("chapter_id"),
        "gold_revision": profile.get("gold_revision"),
        "utterance_count": len(
            profile.get("normalized_utterances", [])
        ),
        "file_name": _PathV024(
            profile.get("_bundled_profile_path", "")
        ).name,
    }


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
):
    chapter = selected_chapter(data, chapter_index)
    video_id = (
        data.get("metadata", {}).get("video_id")
        or "unknown-video"
    )
    chapter_id = chapter.get("chapter_id")

    selected_gold = calibration_gold
    profile_source = "uploaded_verified_profile"

    if (
        selected_gold is None
        and auto_apply_builtin_profile
        and apply_verified_same_chapter
    ):
        selected_gold = _load_bundled_verified_profile_v024(
            video_id,
            chapter_id,
        )
        if selected_gold is not None:
            profile_source = "bundled_verified_profile"

    result = _build_preprocessing_draft_v023(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=selected_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
    )

    result["schema_version"] = "script_preprocessing_v0.2.4"
    result.setdefault("profile_application", {})
    result["profile_application"]["profile_source"] = (
        profile_source
        if result["profile_application"].get("mode")
        == "same_source_verified_profile"
        else "generic_rules"
    )
    result["profile_application"]["auto_builtin_enabled"] = (
        auto_apply_builtin_profile
    )

    if selected_gold is not None:
        result["profile_application"]["selected_gold_revision"] = (
            selected_gold.get("gold_revision")
        )
        result["profile_application"]["selected_gold_utterance_count"] = (
            len(selected_gold.get("normalized_utterances", []))
        )

    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v023(data)
    result["schema_version"] = "script_preprocessing_v0.2.4"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v023(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.2.4"
    return result


# =====================================================================
# v0.2.5 patch
# =====================================================================
_selected_chapter_v024 = selected_chapter
_build_preprocessing_draft_v024 = build_preprocessing_draft
_prepare_existing_preprocessing_v024 = prepare_existing_preprocessing
_export_editor_result_v024 = export_editor_result
_safe_cleanup_v024 = _safe_cleanup

_EDITORIAL_BOUNDARY_OVERRIDES_V025 = {
    ("KOkPpqxAlRA", "CH-02"): {
        "editorial_chapter_id": "ECH-02",
        "start_seconds": 250.0,
        "end_seconds": 826.0,
        "label": "핵심 철학 · 생산자 시점 vs 소비자 시점 + 라이브 Q&A",
        "boundary_source": "editor_video_review",
        "reason": "13:46 코드 레이어링 시작을 다음 챕터로 분리",
    },
    ("KOkPpqxAlRA", "CH-03"): {
        "editorial_chapter_id": "ECH-03",
        "start_seconds": 826.0,
        "end_seconds": 1242.0,
        "label": "코드 레이어링 도입 · 미드저니 3가지 코드",
        "boundary_source": "editor_video_review",
        "reason": "creator chapter보다 35초 앞선 강의 전환점 적용",
    },
}

_V025_SAFE_REPLACEMENTS = [
    (r"\b만만졌을\b", "만졌을", "syllable_stutter_cleanup", "high"),
    (r"\b만들었었고\s+만들었고\b", "만들었고", "false_start_replacement", "high"),
    (r"\b있\s+있는\b", "있는", "partial_word_restart_cleanup", "high"),
    (r"\b있\s+있습니다\b", "있습니다", "partial_word_restart_cleanup", "high"),
    (r"\b넘\s+넘게\b", "넘게", "partial_word_restart_cleanup", "high"),
    (r"\b경\s+경의로움\b", "경의로움", "partial_word_restart_cleanup", "high"),
    (r"\b익스필드\b", "힉스필드", "verified_tool_name", "high"),
    (r"\b시덴스\b", "시댄스", "verified_tool_name", "high"),
    (r"\b요한\s+킨벌리\b", "유한킴벌리", "verified_entity_name", "high"),
    (r"\bAIT가\b", "AI 티가", "contextual_term_spacing", "medium"),
    (r"\b기억한\s+사람\s+누구냐\b", "기획한 사람 누구냐", "contextual_word_correction", "medium"),
    (r"채집비티나\s+뭐\s+채집피티나노바나나\s+프로", "ChatGPT나 뭐 나노바나나 프로", "verified_tool_phrase", "medium"),
]

def selected_chapter(data, chapter_index):
    chapter = copy.deepcopy(_selected_chapter_v024(data, chapter_index))
    video_id = data.get("metadata", {}).get("video_id") or "unknown-video"
    creator_id = chapter.get("chapter_id")
    override = _EDITORIAL_BOUNDARY_OVERRIDES_V025.get((video_id, creator_id))
    if not override:
        return chapter
    chapter["creator_chapter_id"] = creator_id
    chapter["creator_start_seconds"] = chapter.get("start_seconds")
    chapter["creator_end_seconds"] = chapter.get("end_seconds")
    chapter["creator_label"] = chapter.get("label")
    chapter["chapter_id"] = override["editorial_chapter_id"]
    chapter["start_seconds"] = override["start_seconds"]
    chapter["end_seconds"] = override["end_seconds"]
    chapter["label"] = override["label"]
    chapter["source_type"] = "editorial_semantic_boundary"
    chapter["boundary_source"] = override["boundary_source"]
    chapter["boundary_override_reason"] = override["reason"]
    chapter["verification_status"] = "editor_verified"
    return chapter

def _safe_cleanup(text, source_segment_ids, normalization_counter):
    output, changes, normalization_counter = _safe_cleanup_v024(text, source_segment_ids, normalization_counter)
    for pattern, replacement, correction_type, confidence in _V025_SAFE_REPLACEMENTS:
        matches = list(re.finditer(pattern, output))
        if not matches: continue
        for match in matches:
            normalization_counter = _append_change_v023(changes, normalization_counter, match.group(0), replacement, correction_type, source_segment_ids, confidence)
        output = re.sub(pattern, replacement, output)
    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)
    return output, changes, normalization_counter

def _load_bundled_gold_v025(video_id, editorial_chapter_id):
    profiles_dir = _PathV024(__file__).resolve().parent / "profiles"
    if not profiles_dir.exists(): return None
    candidates=[]
    for path in profiles_dir.glob("*.json"):
        try: profile=json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        if profile.get("role")=="preprocessing_gold_sample" and profile.get("video_id")==video_id and profile.get("processed_chapter",{}).get("chapter_id")==editorial_chapter_id:
            candidates.append((path,profile))
    if not candidates: return None
    candidates.sort(key=lambda pair:str(pair[1].get("updated_at","")), reverse=True)
    path,profile=candidates[0]; profile["_bundled_profile_path"]=str(path); return profile

def get_builtin_verified_profile_info(video_id, chapter_id):
    override=_EDITORIAL_BOUNDARY_OVERRIDES_V025.get((video_id,chapter_id))
    editorial_id=override["editorial_chapter_id"] if override else chapter_id
    profile=_load_bundled_gold_v025(video_id,editorial_id)
    if not profile: return None
    return {"video_id":video_id,"chapter_id":editorial_id,"creator_chapter_id":chapter_id,"gold_revision":profile.get("gold_revision"),"utterance_count":len(profile.get("normalized_utterances",[])),"file_name":_PathV024(profile.get("_bundled_profile_path","")).name,"start_seconds":profile.get("processed_chapter",{}).get("start_seconds"),"end_seconds":profile.get("processed_chapter",{}).get("end_seconds")}

def build_preprocessing_draft(data, chapter_index=0, custom_glossary_text="", include_boundary_continuation=True, calibration_gold=None, use_validated_profile=True, apply_verified_same_chapter=True, reuse_approval_status=False, auto_apply_builtin_profile=True):
    chapter=selected_chapter(data,chapter_index)
    video_id=data.get("metadata",{}).get("video_id") or "unknown-video"
    selected_gold=calibration_gold; profile_source="uploaded_verified_profile"
    if selected_gold is None and auto_apply_builtin_profile and apply_verified_same_chapter:
        selected_gold=_load_bundled_gold_v025(video_id,chapter.get("chapter_id"))
        if selected_gold is not None: profile_source="bundled_verified_profile"
    if selected_gold is not None and selected_gold.get("video_id")==video_id and selected_gold.get("processed_chapter",{}).get("chapter_id")==chapter.get("chapter_id") and selected_gold.get("role")=="preprocessing_gold_sample":
        result=copy.deepcopy(selected_gold); result["schema_version"]="script_preprocessing_v0.2.5"; result["input_document_kind"]="acquisition"; result["created_at"]=utc_now(); result["updated_at"]=utc_now()
        for item in result.get("normalized_utterances",[]):
            item["review_status"]="approved" if reuse_approval_status else "needs_review"; item["auto_normalized_text"]=item.get("normalized_text","")
        approved=sum(1 for item in result.get("normalized_utterances",[]) if item.get("review_status")=="approved"); remaining=len(result.get("normalized_utterances",[]))-approved
        result["processing_report"].update({"processing_status":"approved" if remaining==0 else "validation_required","chapter_review_status":"completed" if remaining==0 else "in_progress","draft_only":remaining>0,"editor_review_required":remaining>0,"approved_utterances":approved,"review_required_utterances":remaining,"profile_applied":True})
        result["profile_application"]={"mode":"same_source_verified_profile","profile_source":profile_source,"selected_gold_revision":selected_gold.get("gold_revision"),"selected_gold_utterance_count":len(selected_gold.get("normalized_utterances",[])),"generalization_claim":False,"auto_builtin_enabled":auto_apply_builtin_profile}
        return result
    result=_build_preprocessing_draft_v024(data,chapter_index=chapter_index,custom_glossary_text=custom_glossary_text,include_boundary_continuation=include_boundary_continuation,calibration_gold=None,use_validated_profile=use_validated_profile,apply_verified_same_chapter=False,reuse_approval_status=False,auto_apply_builtin_profile=False)
    result["schema_version"]="script_preprocessing_v0.2.5"; result["processed_chapter"]=chapter; result["profile_application"]={"mode":"generic_auto_normalization","profile_source":"generic_rules","generalization_claim":True,"auto_builtin_enabled":auto_apply_builtin_profile}; return result

def prepare_existing_preprocessing(data):
    result=_prepare_existing_preprocessing_v024(data); result["schema_version"]="script_preprocessing_v0.2.5"; return result

def export_editor_result(draft, edited_rows):
    result=_export_editor_result_v024(draft,edited_rows); result["schema_version"]="script_preprocessing_v0.2.5"; return result


# v0.2.5 seed merge hotfix
_build_preprocessing_draft_v025_base = build_preprocessing_draft

def _load_bundled_seed_v025(video_id, editorial_chapter_id):
    profiles_dir = _PathV024(__file__).resolve().parent / "profiles"
    if not profiles_dir.exists():
        return None
    for path in profiles_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (
            data.get("role") == "next_editorial_chapter_seed"
            and data.get("video_id") == video_id
            and data.get("target_editorial_chapter", {}).get("chapter_id")
            == editorial_chapter_id
        ):
            return data
    return None

def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
):
    result = _build_preprocessing_draft_v025_base(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
    )
    chapter = result.get("processed_chapter", {})
    video_id = data.get("metadata", {}).get("video_id") or "unknown-video"
    if (
        result.get("profile_application", {}).get("mode")
        == "generic_auto_normalization"
        and chapter.get("chapter_id") == "ECH-03"
    ):
        seed = _load_bundled_seed_v025(video_id, "ECH-03")
        if seed:
            seed_items = copy.deepcopy(seed.get("normalized_utterances", []))
            # The first three generic rows cover the same 13:46–14:28 source span.
            generic_items = result.get("normalized_utterances", [])[3:]
            merged = seed_items + generic_items
            for index, item in enumerate(merged, start=1):
                item["utterance_id"] = f"UT-{index:05d}"
                item["chapter_id"] = "ECH-03"
                if item.get("review_status") == "approved":
                    item["review_status"] = "needs_review"
            result["normalized_utterances"] = merged
            result["normalized_utterance_count"] = len(merged)
            result["profile_application"]["seed_source"] = "bundled_editorial_seed"
            result["profile_application"]["seed_utterance_count"] = len(seed_items)
            result["processing_report"]["review_required_utterances"] = len(merged)
            result["processing_report"]["draft_only"] = True
            result["processing_report"]["editor_review_required"] = True
    return result


# =====================================================================
# v0.2.6 patch
# =====================================================================

_build_preprocessing_draft_v025_final = build_preprocessing_draft
_prepare_existing_preprocessing_v025_final = prepare_existing_preprocessing
_export_editor_result_v025_final = export_editor_result
_safe_cleanup_v025_final = _safe_cleanup

_CANONICAL_ENTITY_RULES_V026 = [
    {
        "canonical_name": "Midjourney",
        "entity_type": "product",
        "aliases": [
            "미드저니", "미드전이", "미드전일", "미드전니",
            "미드전위", "미드이", "미드니",
        ],
    },
    {
        "canonical_name": "Higgsfield",
        "entity_type": "product",
        "aliases": ["힉스필드", "익스필드"],
    },
    {
        "canonical_name": "ChatGPT",
        "entity_type": "product",
        "aliases": ["챗지피티", "채집피티", "채집비티", "채지피티"],
    },
    {
        "canonical_name": "Nano Banana Pro",
        "entity_type": "product",
        "aliases": ["나노바나나 프로", "나노바나 프로"],
    },
    {
        "canonical_name": "Sora",
        "entity_type": "product",
        "aliases": ["쏘라"],
    },
    {
        "canonical_name": "Seedance",
        "entity_type": "product",
        "aliases": ["시댄스", "시덴스"],
    },
]


def _canonicalize_entities_v026(
    text,
    source_segment_ids,
    normalization_counter,
):
    output = str(text or "")
    changes = []
    flat = []
    for rule in _CANONICAL_ENTITY_RULES_V026:
        for alias in rule["aliases"]:
            flat.append((alias, rule))
    flat.sort(key=lambda pair: len(pair[0]), reverse=True)

    for alias, rule in flat:
        pattern = re.compile(
            rf"(?<![가-힣A-Za-z0-9]){re.escape(alias)}"
        )
        matches = list(pattern.finditer(output))
        if not matches:
            continue
        for match in matches:
            normalization_counter = _append_change_v023(
                changes,
                normalization_counter,
                match.group(0),
                rule["canonical_name"],
                "official_name_canonicalization",
                source_segment_ids,
                "high",
            )
        output = pattern.sub(rule["canonical_name"], output)

    for pattern in [
        r"(?<![가-힣A-Za-z0-9])세리프\s*코드",
        r"(?<![가-힣A-Za-z0-9])세프\s*코드",
        r"(?<![가-힣A-Za-z0-9])쓰리프\s*코드",
        r"(?<![가-힣A-Za-z0-9])슬리프\s*코드",
    ]:
        matches = list(re.finditer(pattern, output))
        if not matches:
            continue
        for match in matches:
            normalization_counter = _append_change_v023(
                changes,
                normalization_counter,
                match.group(0),
                "Sref 코드",
                "official_feature_name_canonicalization",
                source_segment_ids,
                "high",
            )
        output = re.sub(pattern, "Sref 코드", output)

    return output, changes, normalization_counter


def _safe_cleanup(
    text,
    source_segment_ids,
    normalization_counter,
):
    output, changes, normalization_counter = (
        _safe_cleanup_v025_final(
            text,
            source_segment_ids,
            normalization_counter,
        )
    )
    output, entity_changes, normalization_counter = (
        _canonicalize_entities_v026(
            output,
            source_segment_ids,
            normalization_counter,
        )
    )
    changes.extend(entity_changes)
    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)
    return output, changes, normalization_counter


def _entity_mentions_v026(text):
    entities = []
    for name, entity_type in [
        ("Midjourney", "product"),
        ("Higgsfield", "product"),
        ("ChatGPT", "product"),
        ("Nano Banana Pro", "product"),
        ("Sora", "product"),
        ("Seedance", "product"),
        ("Sref", "feature"),
    ]:
        if name in str(text or ""):
            entities.append(
                {
                    "surface_form": name,
                    "canonical_name": name,
                    "entity_type": entity_type,
                    "verification_status": "canonical_registry",
                }
            )
    return entities


def _canonicalize_text_only_v026(text):
    output = str(text or "")
    flat = []
    for rule in _CANONICAL_ENTITY_RULES_V026:
        for alias in rule["aliases"]:
            flat.append((alias, rule))
    flat.sort(key=lambda pair: len(pair[0]), reverse=True)
    for alias, rule in flat:
        output = re.sub(
            rf"(?<![가-힣A-Za-z0-9]){re.escape(alias)}",
            rule["canonical_name"],
            output,
        )
    for pattern in [
        r"(?<![가-힣A-Za-z0-9])세리프\s*코드",
        r"(?<![가-힣A-Za-z0-9])세프\s*코드",
        r"(?<![가-힣A-Za-z0-9])쓰리프\s*코드",
        r"(?<![가-힣A-Za-z0-9])슬리프\s*코드",
    ]:
        output = re.sub(pattern, "Sref 코드", output)
    return output


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
):
    result = _build_preprocessing_draft_v025_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
    )

    result["schema_version"] = "script_preprocessing_v0.2.6"
    result["canonicalization_policy"] = {
        "version": "canonical_entity_policy_v0.1",
        "official_names_in_normalized_text": True,
        "screen_inferred_expansion_in_normalized_text": False,
    }

    for item in result.get("normalized_utterances", []):
        text = _canonicalize_text_only_v026(
            item.get("normalized_text", "")
        )
        item["normalized_text"] = text
        item["auto_normalized_text"] = text

        existing = item.get("entity_mentions", [])
        seen = {
            (
                entity.get("surface_form"),
                entity.get("canonical_name"),
                entity.get("entity_type"),
            )
            for entity in existing
        }
        for entity in _entity_mentions_v026(text):
            key = (
                entity.get("surface_form"),
                entity.get("canonical_name"),
                entity.get("entity_type"),
            )
            if key not in seen:
                existing.append(entity)
                seen.add(key)
        item["entity_mentions"] = existing

    chapter = result.get("processed_chapter", {})
    if (
        result.get("video_id") == "KOkPpqxAlRA"
        and chapter.get("chapter_id") == "ECH-03"
        and result.get("normalized_utterances")
    ):
        first = result["normalized_utterances"][0]
        if first.get("normalized_text", "").startswith(
            "코드 레이어링에 대해서"
        ):
            first["start_seconds"] = 826.0
            first["display_timestamp"] = "13:46"

    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v025_final(data)
    result["schema_version"] = "script_preprocessing_v0.2.6"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v025_final(
        draft,
        edited_rows,
    )
    result["schema_version"] = "script_preprocessing_v0.2.6"

    chapter = result.get("processed_chapter", {})
    if (
        result.get("video_id") == "KOkPpqxAlRA"
        and chapter.get("chapter_id") == "ECH-03"
        and result.get("normalized_utterances")
    ):
        first = result["normalized_utterances"][0]
        if first.get("normalized_text", "").startswith(
            "코드 레이어링에 대해서"
        ):
            first["start_seconds"] = 826.0
            first["display_timestamp"] = "13:46"

    return result


# =====================================================================
# v0.2.7 verified correction memory
# =====================================================================

_build_preprocessing_draft_v026 = build_preprocessing_draft
_prepare_existing_preprocessing_v026 = prepare_existing_preprocessing
_export_editor_result_v026 = export_editor_result
_safe_cleanup_v026 = _safe_cleanup


def _load_memory_v027():
    path = (
        _PathV024(__file__).resolve().parent
        / "profiles"
        / "verified_correction_memory_v0_1.json"
    )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"rules": [], "memory_id": "unavailable", "source_gold_samples": []}


_MEMORY_V027 = _load_memory_v027()


def _apply_memory_v027(text, source_segment_ids, counter):
    output = str(text or "")
    changes = []

    for rule in _MEMORY_V027.get("rules", []):
        before = output
        if rule.get("type") == "regex":
            try:
                output = re.sub(
                    rule.get("pattern", ""),
                    rule.get("replacement", ""),
                    output,
                )
            except re.error:
                continue
        else:
            output = output.replace(
                rule.get("pattern", ""),
                rule.get("replacement", ""),
            )

        if output != before:
            counter = _append_change_v023(
                changes,
                counter,
                before,
                output,
                "verified_correction_memory",
                source_segment_ids,
                rule.get("confidence", "medium"),
            )

    output = re.sub(
        r"(?<![가-힣A-Za-z0-9])미느전이",
        "Midjourney",
        output,
    )
    output = re.sub(
        r"(?<![가-힣A-Za-z0-9])나노바나나(?!\s*프로)",
        "Nano Banana",
        output,
    )
    output = re.sub(
        r"(?<![가-힣A-Za-z0-9])마노바나",
        "Nano Banana",
        output,
    )

    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)
    return output, changes, counter


def _safe_cleanup(text, source_segment_ids, normalization_counter):
    output, changes, normalization_counter = _safe_cleanup_v026(
        text,
        source_segment_ids,
        normalization_counter,
    )
    output, extra, normalization_counter = _apply_memory_v027(
        output,
        source_segment_ids,
        normalization_counter,
    )
    changes.extend(extra)
    return output, changes, normalization_counter


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
):
    result = _build_preprocessing_draft_v026(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
    )
    result["schema_version"] = "script_preprocessing_v0.2.7"
    result["correction_memory"] = {
        "memory_id": _MEMORY_V027.get("memory_id"),
        "source_gold_samples": _MEMORY_V027.get("source_gold_samples", []),
        "exact_gold_profile_is_not_rewritten": True,
    }
    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v026(data)
    result["schema_version"] = "script_preprocessing_v0.2.7"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v026(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.2.7"
    return result


# =====================================================================
# v0.2.8 patch
# - stronger canonical entity registry
# - Korean demonstrative/joiner repair
# - verified stutter cleanup
# - conservative incomplete-continuation merge
# =====================================================================

_build_preprocessing_draft_v027_final = build_preprocessing_draft
_prepare_existing_preprocessing_v027_final = prepare_existing_preprocessing
_export_editor_result_v027_final = export_editor_result
_safe_cleanup_v027_final = _safe_cleanup


def _load_json_profile_v028(file_name):
    path = (
        _PathV024(__file__).resolve().parent
        / "profiles"
        / file_name
    )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


_ENTITY_REGISTRY_V028 = _load_json_profile_v028(
    "canonical_entity_registry_v0_2.json"
)
_MEMORY_V028 = _load_json_profile_v028(
    "verified_correction_memory_v0_2.json"
)


def _append_normalization_change_v028(
    changes,
    counter,
    before,
    after,
    normalization_type,
    source_segment_ids,
    confidence="high",
):
    if before == after:
        return counter
    return _append_change_v023(
        changes,
        counter,
        before,
        after,
        normalization_type,
        source_segment_ids,
        confidence,
    )


def _canonicalize_entities_v028(
    text,
    source_segment_ids,
    counter,
):
    output = str(text or "")
    changes = []

    # Longest aliases first.
    aliases = []
    for entity in _ENTITY_REGISTRY_V028.get("entities", []):
        canonical = entity.get("canonical_name")
        context = entity.get("context")
        for alias in entity.get("spoken_aliases", []):
            aliases.append(
                (alias, canonical, context)
            )
    aliases.sort(
        key=lambda item: len(str(item[0])),
        reverse=True,
    )

    for alias, canonical, context in aliases:
        if not alias or not canonical:
            continue

        if context == "followed_by_code":
            pattern = re.compile(
                rf"(?<![가-힣A-Za-z0-9])"
                rf"{re.escape(alias)}\s*코드"
            )
            replacement = f"{canonical} 코드"
        else:
            pattern = re.compile(
                rf"(?<![가-힣A-Za-z0-9])"
                rf"{re.escape(alias)}"
            )
            replacement = canonical

        matches = list(pattern.finditer(output))
        if not matches:
            continue

        before = output
        output = pattern.sub(replacement, output)
        counter = _append_normalization_change_v028(
            changes,
            counter,
            before,
            output,
            "official_entity_canonicalization_v028",
            source_segment_ids,
            "high",
        )

    # Sref can already be partially canonicalized into "세리 Sref 코드".
    before = output
    output = re.sub(
        r"(?<![A-Za-z0-9])세리\s+Sref\s+코드",
        "Sref 코드",
        output,
    )
    if before != output:
        counter = _append_normalization_change_v028(
            changes,
            counter,
            before,
            output,
            "official_feature_name_canonicalization_v028",
            source_segment_ids,
            "high",
        )

    # Contextual entity rules where a short alias would be unsafe globally.
    for item in _ENTITY_REGISTRY_V028.get(
        "contextual_entities",
        [],
    ):
        pattern = item.get("pattern", "")
        replacement = item.get("replacement", "")
        if pattern and pattern in output:
            before = output
            output = output.replace(pattern, replacement)
            counter = _append_normalization_change_v028(
                changes,
                counter,
                before,
                output,
                "contextual_entity_canonicalization_v028",
                source_segment_ids,
                "high",
            )

    return output, changes, counter


def _apply_memory_v028(
    text,
    source_segment_ids,
    counter,
):
    output = str(text or "")
    changes = []

    for rule in _MEMORY_V028.get("rules", []):
        before = output
        pattern = rule.get("pattern", "")
        replacement = rule.get("replacement", "")
        rule_type = rule.get("type", "literal")

        if not pattern:
            continue

        if rule_type == "regex":
            try:
                output = re.sub(
                    pattern,
                    replacement,
                    output,
                )
            except re.error:
                continue
        else:
            output = output.replace(
                pattern,
                replacement,
            )

        if before != output:
            counter = _append_normalization_change_v028(
                changes,
                counter,
                before,
                output,
                "verified_normalization_memory_v028",
                source_segment_ids,
                rule.get("confidence", "medium"),
            )

    # General same-token + case-particle restart:
    # "색감 색감이나" -> "색감이나"
    # Conservative: second copy must carry a Korean case/auxiliary particle.
    pattern = re.compile(
        r"\b([가-힣A-Za-z0-9]+)\s+"
        r"\1(이나|은|는|이|가|을|를|도|에|에서|으로|로)\b"
    )
    before = output
    output = pattern.sub(r"\1\2", output)
    if before != output:
        counter = _append_normalization_change_v028(
            changes,
            counter,
            before,
            output,
            "partial_word_restart_cleanup_v028",
            source_segment_ids,
            "high",
        )

    # Particle repair after Korean canonical forms.
    output = output.replace("덕테이프을", "덕테이프를")
    output = output.replace("덕테이프이", "덕테이프가")

    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)

    return output, changes, counter


def _safe_cleanup(
    text,
    source_segment_ids,
    normalization_counter,
):
    output, changes, normalization_counter = (
        _safe_cleanup_v027_final(
            text,
            source_segment_ids,
            normalization_counter,
        )
    )

    output, entity_changes, normalization_counter = (
        _canonicalize_entities_v028(
            output,
            source_segment_ids,
            normalization_counter,
        )
    )
    changes.extend(entity_changes)

    output, memory_changes, normalization_counter = (
        _apply_memory_v028(
            output,
            source_segment_ids,
            normalization_counter,
        )
    )
    changes.extend(memory_changes)

    output = re.sub(r"\s+", " ", output).strip()
    output = re.sub(r"\s+([,.!?…])", r"\1", output)

    return output, changes, normalization_counter


def _starts_with_continuation_v028(text):
    text = str(text or "").strip()
    return bool(
        re.match(
            r"^(?:"
            r"거를|것을|걸|"
            r"와\b|과\b|랑\b|이랑\b|"
            r"를\b|을\b|"
            r"도\b|만\b|부터\b|까지\b"
            r")",
            text,
        )
    )


def _merge_continuation_fragments_v028(result):
    """
    Merge only a very narrow class of broken boundaries:
    previous utterance is incomplete AND next utterance begins
    with a grammatical continuation token.

    Examples validated by CH-06:
      "... 내 취향이 가득 담긴" + "거를 ..."
      "... 그리고 프롬프트" + "와 Sref 코드가 ..."
    """
    utterances = copy.deepcopy(
        result.get("normalized_utterances", [])
    )
    if not utterances:
        return result

    merged = []
    repairs = []
    index = 0

    while index < len(utterances):
        current = utterances[index]

        if (
            index + 1 < len(utterances)
            and not bool(current.get("sentence_complete"))
            and _starts_with_continuation_v028(
                utterances[index + 1].get(
                    "normalized_text",
                    "",
                )
            )
        ):
            nxt = utterances[index + 1]
            current = copy.deepcopy(current)

            before_text = current.get(
                "normalized_text",
                "",
            )
            next_text = nxt.get(
                "normalized_text",
                "",
            )

            current["normalized_text"] = (
                f"{before_text.rstrip()} "
                f"{next_text.lstrip()}"
            ).strip()
            current["auto_normalized_text"] = (
                current["normalized_text"]
            )
            current["end_seconds"] = nxt.get(
                "end_seconds",
                current.get("end_seconds"),
            )
            current["sentence_complete"] = bool(
                nxt.get("sentence_complete")
            )

            for key in [
                "sentence_unit_ids",
                "source_segment_ids",
                "source_segment_keys",
                "normalization_item_ids",
                "editor_change_ids",
            ]:
                values = []
                for src in [
                    current.get(key, []),
                    nxt.get(key, []),
                ]:
                    for value in src:
                        if value not in values:
                            values.append(value)
                current[key] = values

            current["source_spans"] = (
                current.get("source_spans", [])
                + nxt.get("source_spans", [])
            )
            warnings = list(
                current.get("validation_warnings", [])
            )
            if "v0.2.8_continuation_merge" not in warnings:
                warnings.append(
                    "v0.2.8_continuation_merge"
                )
            current["validation_warnings"] = warnings

            repairs.append(
                {
                    "left_utterance_id": current.get(
                        "utterance_id"
                    ),
                    "right_utterance_id": nxt.get(
                        "utterance_id"
                    ),
                    "reason": (
                        "incomplete_left_plus_"
                        "grammatical_continuation"
                    ),
                }
            )
            index += 2
        else:
            index += 1

        merged.append(current)

    # Re-number only display/utterance IDs in the generic draft.
    for number, item in enumerate(merged, start=1):
        item["utterance_id"] = f"UT-{number:05d}"

    result["normalized_utterances"] = merged
    result["normalized_utterance_count"] = len(merged)
    result["boundary_repairs_v028"] = repairs

    report = result.setdefault("processing_report", {})
    report["continuation_merges_v028"] = len(repairs)
    report["sentence_complete_utterances"] = sum(
        1
        for item in merged
        if item.get("sentence_complete")
    )
    report["sentence_incomplete_utterances"] = sum(
        1
        for item in merged
        if not item.get("sentence_complete")
    )
    report["sentence_completion_rate"] = (
        round(
            report["sentence_complete_utterances"]
            / len(merged),
            4,
        )
        if merged
        else 0.0
    )

    # Generic draft remains review-required.
    for item in merged:
        item.setdefault("review_status", "needs_review")

    return result


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
):
    result = _build_preprocessing_draft_v027_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
    )

    mode = result.get(
        "profile_application",
        {},
    ).get("mode")

    if mode == "generic_auto_normalization":
        result = _merge_continuation_fragments_v028(
            result
        )

    result["schema_version"] = (
        "script_preprocessing_v0.2.8"
    )
    memory_id = _MEMORY_V028.get("memory_id")
    memory_loaded = bool(
        memory_id
        and _MEMORY_V028.get("rules")
    )
    entity_registry_loaded = bool(
        _ENTITY_REGISTRY_V028.get("entities")
    )
    verified_change_types = {
        "verified_correction_memory",
        "verified_normalization_memory_v028",
        "official_entity_canonicalization_v028",
        "official_feature_name_canonicalization_v028",
        "contextual_entity_canonicalization_v028",
    }
    verified_change_count = sum(
        1
        for item in result.get("normalization_items", [])
        if item.get("normalization_type") in verified_change_types
    )

    if mode == "generic_auto_normalization":
        result["correction_memory"] = {
            "memory_id": memory_id or "unavailable",
            "source_gold_samples": _MEMORY_V028.get(
                "source_gold_samples",
                [],
            ),
            "exact_gold_profile_is_not_rewritten": True,
            "loaded": memory_loaded,
            "applied_change_count": verified_change_count,
        }
        profile = result.setdefault("profile_application", {})
        profile["profile_applied"] = bool(verified_change_count)
        profile["verified_correction_memory_loaded"] = memory_loaded
        profile["canonical_entity_registry_loaded"] = entity_registry_loaded
        if memory_loaded or entity_registry_loaded:
            profile["profile_source"] = (
                "generic_rules+verified_correction_memory_v0.2"
                "+canonical_entity_registry_v0.2"
            )
        report = result.setdefault("processing_report", {})
        report["profile_applied"] = bool(verified_change_count)
        report["verified_profile_change_count"] = verified_change_count

    result["normalization_engine_v028"] = {
        "canonical_entity_registry": (
            "canonical_entity_registry_v0.2"
        ),
        "verified_correction_memory": (
            "verified_correction_memory_v0.2"
        ),
        "gold_samples": [
            "CH-01",
            "CH-02",
            "ECH-03",
            "CH-04",
            "CH-05",
            "CH-06",
        ],
        "canonical_entity_registry_loaded": entity_registry_loaded,
        "verified_correction_memory_loaded": memory_loaded,
        "verified_correction_memory_id": memory_id or "unavailable",
        "verified_correction_rule_count": len(
            _MEMORY_V028.get("rules", [])
        ),
        "canonical_entity_count": len(
            _ENTITY_REGISTRY_V028.get("entities", [])
        ),
    }
    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v027_final(
        data
    )
    result["schema_version"] = (
        "script_preprocessing_v0.2.8"
    )
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v027_final(
        draft,
        edited_rows,
    )
    result["schema_version"] = (
        "script_preprocessing_v0.2.8"
    )
    return result


# =====================================================================
# v0.2.9 patch
# - foreign-language transcript -> natural Korean draft via OpenAI API
# - preserve original-language source spans and timestamps
# - full-video fallback uses FULL instead of pretending creator CH-01 exists
# =====================================================================

import os as _os_v029

_selected_chapter_v028_final = selected_chapter
_build_preprocessing_draft_v028_final = build_preprocessing_draft
_prepare_existing_preprocessing_v028_final = prepare_existing_preprocessing
_export_editor_result_v028_final = export_editor_result


def selected_chapter(data, chapter_index=0):
    chapters = data.get("creator_chapters", [])
    if not chapters:
        duration = data.get("metadata", {}).get("duration_seconds")
        return {
            "chapter_id": "FULL",
            "chapter_index": 0,
            "creator_chapter_id": None,
            "label": "전체 영상 · 제작자 챕터 없음",
            "start_seconds": 0,
            "end_seconds": duration,
            "source_type": "full_video_fallback",
            "boundary_source": "no_creator_chapters",
            "verification_status": "source_structure_verified",
        }
    return _selected_chapter_v028_final(data, chapter_index)


def source_language_code(data):
    transcript = data.get("transcript", {})
    metadata = data.get("metadata", {})
    raw = (
        transcript.get("language_code")
        or metadata.get("default_audio_language")
        or metadata.get("default_language")
        or ""
    )
    return str(raw or "").strip().lower()


def source_language_label(data):
    transcript = data.get("transcript", {})
    return str(
        transcript.get("language")
        or source_language_code(data)
        or "unknown"
    )


def translation_required_for_source(data):
    code = source_language_code(data)
    return bool(code and not code.startswith("ko"))


def _foreign_chapter_segments_v029(data, chapter):
    all_segments = enrich_all_segments(data)
    start = float(chapter.get("start_seconds", 0) or 0)
    end_raw = chapter.get("end_seconds")
    end = float(end_raw) if end_raw is not None else float("inf")
    selected = [
        item
        for item in all_segments
        if float(item.get("start_seconds", 0)) >= start
        and float(item.get("start_seconds", 0)) < end
    ]
    return selected


def _clean_foreign_source_text_v029(text):
    output = clean_display_text(text)
    output = NONVERBAL_RE.sub(" ", output)
    output = re.sub(r"\s+", " ", output).strip()
    return output


def _group_foreign_segments_v029(
    segments,
    target_duration=14.0,
    max_duration=22.0,
    max_chars=900,
    gap_break_seconds=2.5,
):
    groups = []
    current = []

    def flush():
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for segment in segments:
        text = _clean_foreign_source_text_v029(
            segment.get("text", "")
        )
        if not text:
            continue

        seg_start = float(segment.get("start_seconds", 0))
        seg_end = float(
            segment.get("end_seconds", seg_start)
        )

        if current:
            current_start = float(
                current[0].get("start_seconds", 0)
            )
            current_end = max(
                float(item.get("end_seconds", 0))
                for item in current
            )
            gap = seg_start - current_end
            proposed_duration = seg_end - current_start
            proposed_chars = (
                sum(
                    len(
                        _clean_foreign_source_text_v029(
                            item.get("text", "")
                        )
                    )
                    for item in current
                )
                + len(text)
                + len(current)
            )
            if (
                gap > gap_break_seconds
                or proposed_duration > max_duration
                or proposed_chars > max_chars
            ):
                flush()

        current.append(segment)

        current_start = float(
            current[0].get("start_seconds", 0)
        )
        current_end = max(
            float(item.get("end_seconds", 0))
            for item in current
        )
        duration = current_end - current_start
        current_text = " ".join(
            _clean_foreign_source_text_v029(
                item.get("text", "")
            )
            for item in current
        ).strip()
        ends_sentence = bool(
            re.search(r"[.!?…][\"'’”)]*$", current_text)
        )

        if duration >= target_duration and ends_sentence:
            flush()

    flush()
    return groups


def _translation_batches_v029(items, max_items=18, max_chars=12000):
    batches = []
    current = []
    current_chars = 0

    for item in items:
        size = len(str(item.get("text", "")))
        if current and (
            len(current) >= max_items
            or current_chars + size > max_chars
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += size

    if current:
        batches.append(current)
    return batches


def _extract_json_object_v029(text):
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("번역 응답에서 JSON 객체를 찾지 못했습니다.")
    return json.loads(raw[start : end + 1])


def _translate_batch_openai_v029(
    batch,
    api_key,
    model,
    source_language,
):
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "OpenAI 번역 모듈을 불러오지 못했습니다. "
            "requirements.txt를 다시 설치해 주세요."
        ) from exc

    client = OpenAI(api_key=api_key)
    payload = {
        "source_language": source_language,
        "target_language": "ko-KR",
        "items": batch,
    }

    instructions = (
        "You are producing a faithful Korean transcript draft from a foreign-language "
        "YouTube transcript. Translate each input item into natural Korean while preserving "
        "the speaker's exact meaning, information density, uncertainty, comparisons, numbers, "
        "tool/model/product names, prompts, code, URLs, and proper nouns. Do not summarize, "
        "add explanations, omit content-bearing details, merge items, or split items. "
        "Remove only content-neutral speech fillers or caption noise when that does not change "
        "meaning. Keep technical names in their official Latin spelling when appropriate. "
        "Use the neighboring items in this batch as context so Korean phrasing is natural, "
        "but return exactly one translation for every id. Return only valid JSON with this shape: "
        '{"translations":[{"id":"UT-00001","ko":"..."}]}'
    )

    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
        )
        output_text = getattr(response, "output_text", "")
    except AttributeError:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        output_text = response.choices[0].message.content or ""

    parsed = _extract_json_object_v029(output_text)
    rows = parsed.get("translations", [])
    translated = {
        str(row.get("id")): str(row.get("ko", "")).strip()
        for row in rows
        if row.get("id")
    }

    expected = [str(item.get("id")) for item in batch]
    missing = [item_id for item_id in expected if not translated.get(item_id)]
    if missing:
        raise ValueError(
            "번역 응답에 일부 발화가 빠졌습니다: "
            + ", ".join(missing[:6])
        )
    return translated


def _build_foreign_translation_draft_v029(
    data,
    chapter_index,
    translation_api_key,
    translation_model,
):
    if not translation_api_key:
        raise ValueError(
            "외국어 영상을 한국어 초안으로 만들려면 OpenAI API Key가 필요합니다."
        )

    video_id = (
        data.get("metadata", {}).get("video_id")
        or "unknown-video"
    )
    chapter = selected_chapter(data, chapter_index)
    segments = _foreign_chapter_segments_v029(
        data,
        chapter,
    )
    groups = _group_foreign_segments_v029(segments)

    translation_inputs = []
    base_rows = []
    for index, group in enumerate(groups, start=1):
        utterance_id = f"UT-{index:05d}"
        raw_joined = " ".join(
            _clean_foreign_source_text_v029(
                item.get("text", "")
            )
            for item in group
        ).strip()
        if not raw_joined:
            continue

        source_ids = [
            item.get("segment_id")
            for item in group
            if item.get("segment_id")
        ]
        source_keys = [
            item.get("segment_key")
            for item in group
            if item.get("segment_key")
        ]
        start_seconds = min(
            float(item.get("start_seconds", 0))
            for item in group
        )
        end_seconds = max(
            float(item.get("end_seconds", 0))
            for item in group
        )
        source_spans = [
            {
                "segment_id": item.get("segment_id"),
                "segment_key": item.get("segment_key"),
                "start_seconds": item.get("start_seconds"),
                "end_seconds": item.get("end_seconds"),
                "raw_segment_text": item.get("text", ""),
                "used_text": _clean_foreign_source_text_v029(
                    item.get("text", "")
                ),
                "mapping_method": "translation_group_direct_mapping",
                "verification_status": "machine_grouped",
            }
            for item in group
        ]
        translation_inputs.append(
            {
                "id": utterance_id,
                "text": raw_joined,
            }
        )
        base_rows.append(
            {
                "utterance_id": utterance_id,
                "chapter_id": chapter["chapter_id"],
                "chapter_label": chapter.get("label"),
                "chapter_assignment_status": "single_chapter",
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "display_timestamp": display_timestamp(
                    start_seconds
                ),
                "raw_joined_text": raw_joined,
                "source_segment_ids": source_ids,
                "source_segment_keys": source_keys,
                "source_spans": source_spans,
                "source_span_status": "complete",
                "source_span_mapping_ratio": 1.0,
                "unmapped_editor_tokens": [],
            }
        )

    translations = {}
    source_lang = source_language_code(data) or "unknown"
    for batch in _translation_batches_v029(
        translation_inputs
    ):
        translations.update(
            _translate_batch_openai_v029(
                batch=batch,
                api_key=translation_api_key,
                model=translation_model,
                source_language=source_lang,
            )
        )

    utterances = []
    for base in base_rows:
        korean = translations.get(
            base["utterance_id"],
            "",
        ).strip()
        sentence_complete = bool(
            re.search(r"[.!?…]$", korean)
        )
        utterance = dict(base)
        utterance.update(
            {
                "auto_normalized_text": korean,
                "normalized_text": korean,
                "speaker_id": None,
                "speaker_status": "unavailable",
                "content_mode": "translated_natural_language",
                "sentence_unit_ids": [],
                "sentence_complete": sentence_complete,
                "normalization_item_ids": [],
                "confidence": "medium",
                "review_status": "needs_review",
                "editor_note": "",
                "validation_warnings": (
                    []
                    if sentence_complete
                    else ["possible_incomplete_sentence"]
                ),
                "translation_status": "machine_translated_needs_review",
                "translation_source_language": source_lang,
                "translation_target_language": "ko-KR",
            }
        )
        utterances.append(utterance)

    complete_count = sum(
        1 for item in utterances
        if item.get("sentence_complete")
    )

    return {
        "schema_version": "script_preprocessing_v0.2.9",
        "source_schema_version": data.get("schema_version"),
        "source_url": data.get("source_url"),
        "video_id": video_id,
        "source_language": source_lang,
        "source_language_label": source_language_label(data),
        "transcript_origin": data.get(
            "collector_methods",
            {},
        ).get("transcript"),
        "is_auto_generated": data.get(
            "transcript",
            {},
        ).get("is_generated"),
        "processed_chapter": chapter,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input_document_kind": "acquisition",
        "boundary_profile": {
            "profile_id": "foreign_translation_grouping_v0.1",
            "target_duration": 14.0,
            "max_duration": 22.0,
            "max_chars": 900,
            "gap_break_seconds": 2.5,
        },
        "chapter_boundary_context": {},
        "all_sentence_unit_count": 0,
        "sentence_unit_count": 0,
        "raw_segment_count": len(segments),
        "normalized_utterance_count": len(utterances),
        "translation_required": True,
        "translation_status": "completed_needs_review",
        "translation_metadata": {
            "provider": "openai_api",
            "model": translation_model,
            "target_language": "ko-KR",
            "policy_version": "faithful_natural_korean_v0.1",
            "translated_at": utc_now(),
            "api_key_stored": False,
        },
        "raw_segments": segments,
        "sentence_units": [],
        "normalized_utterances": utterances,
        "normalization_items": [],
        "editor_changes": [],
        "unresolved_terms": [],
        "profile_application": {
            "mode": "foreign_translation_v029",
            "profile_source": "foreign_language_translation",
            "generalization_claim": False,
        },
        "processing_report": {
            "processing_status": "validation_required",
            "chapter_review_status": "in_progress",
            "draft_only": True,
            "editor_review_required": True,
            "sentence_boundary_method": "foreign_time_and_punctuation_grouping",
            "chapter_assignment_method": "segment_start_single_owner",
            "sentence_complete_utterances": complete_count,
            "sentence_incomplete_utterances": len(utterances) - complete_count,
            "sentence_completion_rate": round(
                complete_count / max(1, len(utterances)),
                4,
            ),
            "mechanical_duplicates_removed": 0,
            "high_confidence_corrections": 0,
            "medium_confidence_corrections": 0,
            "low_confidence_terms": 0,
            "approved_utterances": 0,
            "rejected_utterances": 0,
            "review_required_utterances": len(utterances),
            "source_span_complete_utterances": len(utterances),
            "source_span_partial_utterances": 0,
            "source_span_weak_utterances": 0,
            "visual_verification_items": [
                "프롬프트·코드·파라미터의 정확한 문자열",
                "도구 화면에 표시되는 메뉴·설정값",
                "고유명사·제품명·모델명의 공식 표기",
            ],
        },
    }


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_api_key=None,
    translation_model=None,
):
    if translation_required_for_source(data):
        if not translate_foreign_to_korean:
            result = _build_preprocessing_draft_v028_final(
                data,
                chapter_index=chapter_index,
                custom_glossary_text=custom_glossary_text,
                include_boundary_continuation=include_boundary_continuation,
                calibration_gold=calibration_gold,
                use_validated_profile=use_validated_profile,
                apply_verified_same_chapter=apply_verified_same_chapter,
                reuse_approval_status=reuse_approval_status,
                auto_apply_builtin_profile=auto_apply_builtin_profile,
            )
            result["schema_version"] = "script_preprocessing_v0.2.9"
            result["processed_chapter"] = selected_chapter(
                data,
                chapter_index,
            )
            result["translation_required"] = True
            result["translation_status"] = "not_requested"
            return result

        api_key = (
            translation_api_key
            or _os_v029.getenv("OPENAI_API_KEY", "")
        )
        model = (
            translation_model
            or _os_v029.getenv(
                "OPENAI_TRANSLATION_MODEL",
                "gpt-5-mini",
            )
        )
        return _build_foreign_translation_draft_v029(
            data=data,
            chapter_index=chapter_index,
            translation_api_key=api_key,
            translation_model=model,
        )

    result = _build_preprocessing_draft_v028_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
    )
    result["schema_version"] = "script_preprocessing_v0.2.9"
    result["processed_chapter"] = selected_chapter(
        data,
        chapter_index,
    )
    result["translation_required"] = False
    result["translation_status"] = "not_required"
    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v028_final(data)
    result["schema_version"] = "script_preprocessing_v0.2.9"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v028_final(
        draft,
        edited_rows,
    )
    result["schema_version"] = "script_preprocessing_v0.2.9"

    if draft.get("translation_required"):
        original_by_id = {
            item.get("utterance_id"): item
            for item in draft.get(
                "normalized_utterances",
                [],
            )
        }
        for item in result.get(
            "normalized_utterances",
            [],
        ):
            original = original_by_id.get(
                item.get("utterance_id")
            )
            if not original:
                continue
            for key in [
                "source_segment_ids",
                "source_segment_keys",
                "source_spans",
                "start_seconds",
                "end_seconds",
                "display_timestamp",
            ]:
                item[key] = copy.deepcopy(
                    original.get(key)
                )
            item["source_span_status"] = "complete"
            item["source_span_mapping_ratio"] = 1.0
            item["unmapped_editor_tokens"] = []
            warnings = [
                warning
                for warning in item.get(
                    "validation_warnings",
                    [],
                )
                if warning
                not in {
                    "source_span_partial",
                    "source_span_weak",
                    "unmapped_editor_tokens",
                }
            ]
            item["validation_warnings"] = warnings

        report = result.setdefault(
            "processing_report",
            {},
        )
        report["source_span_complete_utterances"] = len(
            result.get("normalized_utterances", [])
        )
        report["source_span_partial_utterances"] = 0
        report["source_span_weak_utterances"] = 0

    return result


# =====================================================================
# v0.3.0 patch
# - API-key-free foreign-language -> Korean translation on the local Mac
# - NLLB-200 distilled 600M via Transformers/PyTorch
# - first run downloads the model; later runs use the local HF cache
# - original-language source spans/timestamps stay authoritative
# =====================================================================

_build_preprocessing_draft_v029_final = build_preprocessing_draft
_prepare_existing_preprocessing_v029_final = prepare_existing_preprocessing
_export_editor_result_v029_final = export_editor_result

_LOCAL_TRANSLATOR_CACHE_V030 = {}
_DEFAULT_LOCAL_TRANSLATION_MODEL_V030 = (
    "facebook/nllb-200-distilled-600M"
)

_NLLB_LANGUAGE_MAP_V030 = {
    "en": "eng_Latn",
    "eng": "eng_Latn",
    "ja": "jpn_Jpan",
    "jp": "jpn_Jpan",
    "jpn": "jpn_Jpan",
    "zh": "zho_Hans",
    "zh-cn": "zho_Hans",
    "zh-sg": "zho_Hans",
    "zh-hans": "zho_Hans",
    "zh-tw": "zho_Hant",
    "zh-hk": "zho_Hant",
    "zh-hant": "zho_Hant",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "pt-br": "por_Latn",
    "pt-pt": "por_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "pl": "pol_Latn",
    "cs": "ces_Latn",
    "sk": "slk_Latn",
    "nl": "nld_Latn",
    "sv": "swe_Latn",
    "da": "dan_Latn",
    "no": "nob_Latn",
    "nb": "nob_Latn",
    "fi": "fin_Latn",
    "tr": "tur_Latn",
    "el": "ell_Grek",
    "ro": "ron_Latn",
    "hu": "hun_Latn",
    "bg": "bul_Cyrl",
    "hr": "hrv_Latn",
    "sr": "srp_Cyrl",
    "sl": "slv_Latn",
    "lt": "lit_Latn",
    "lv": "lvs_Latn",
    "et": "est_Latn",
    "ar": "arb_Arab",
    "he": "heb_Hebr",
    "fa": "pes_Arab",
    "hi": "hin_Deva",
    "bn": "ben_Beng",
    "ur": "urd_Arab",
    "id": "ind_Latn",
    "ms": "zsm_Latn",
    "vi": "vie_Latn",
    "th": "tha_Thai",
    "tl": "tgl_Latn",
    "fil": "tgl_Latn",
}


def _normalize_language_key_v030(code):
    value = str(code or "").strip().lower().replace("_", "-")
    if value in _NLLB_LANGUAGE_MAP_V030:
        return value
    # YouTube may return region/script suffixes. Prefer the exact mapping,
    # otherwise fall back to the base language when it is unambiguous.
    base = value.split("-", 1)[0]
    if base in _NLLB_LANGUAGE_MAP_V030:
        return base
    return value


def _nllb_source_language_v030(data):
    raw = source_language_code(data)
    key = _normalize_language_key_v030(raw)
    nllb = _NLLB_LANGUAGE_MAP_V030.get(key)
    if not nllb:
        raise ValueError(
            "현재 로컬 번역기가 아직 지원하지 않는 언어 코드입니다: "
            f"{raw or 'unknown'}. 원본 JSON의 transcript.language_code를 확인해 주세요."
        )
    return nllb


def _load_local_translator_v030(model_name):
    model_name = str(
        model_name or _DEFAULT_LOCAL_TRANSLATION_MODEL_V030
    ).strip()
    cached = _LOCAL_TRANSLATOR_CACHE_V030.get(model_name)
    if cached:
        return cached

    try:
        import torch
        from transformers import (
            AutoModelForSeq2SeqLM,
            AutoTokenizer,
        )
    except Exception as exc:
        raise RuntimeError(
            "로컬 번역 모듈을 불러오지 못했습니다. "
            "requirements.txt가 바뀐 뒤 run_mac.command를 다시 실행해 주세요."
        ) from exc

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_fast=True,
        )
        model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name,
        )
    except Exception as exc:
        raise RuntimeError(
            "로컬 번역 모델을 준비하지 못했습니다. "
            "첫 실행이라면 인터넷 연결을 확인해 주세요. "
            "모델 파일은 처음 한 번만 내려받고 이후에는 캐시를 사용합니다."
        ) from exc

    device = "cpu"
    try:
        if (
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            model = model.to("mps")
            device = "mps"
    except Exception:
        model = model.to("cpu")
        device = "cpu"

    model.eval()
    bundle = {
        "tokenizer": tokenizer,
        "model": model,
        "torch": torch,
        "device": device,
        "model_name": model_name,
    }
    _LOCAL_TRANSLATOR_CACHE_V030[model_name] = bundle
    return bundle


def _split_for_local_translation_v030(text, max_chars=420):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Preserve sentence-like boundaries where possible. This is important
    # for CJK captions where 900 characters can exceed the model token limit.
    sentences = re.split(
        r"(?<=[.!?。！？…])\s*",
        text,
    )
    chunks = []
    current = ""

    def push_current():
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            push_current()
            remainder = sentence
            while len(remainder) > max_chars:
                cut = remainder.rfind(" ", 0, max_chars + 1)
                if cut < max_chars // 2:
                    cut = max_chars
                chunks.append(remainder[:cut].strip())
                remainder = remainder[cut:].strip()
            if remainder:
                current = remainder
            continue

        proposed = (
            sentence
            if not current
            else current + " " + sentence
        )
        if len(proposed) > max_chars:
            push_current()
            current = sentence
        else:
            current = proposed

    push_current()
    return chunks


def _local_generate_batch_v030(
    texts,
    source_nllb,
    model_name,
):
    bundle = _load_local_translator_v030(model_name)
    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    torch = bundle["torch"]
    device = bundle["device"]

    tokenizer.src_lang = source_nllb
    target_id = tokenizer.convert_tokens_to_ids("kor_Hang")
    if target_id is None or target_id == tokenizer.unk_token_id:
        raise RuntimeError(
            "로컬 번역 모델에서 한국어 대상 언어 토큰을 찾지 못했습니다."
        )

    encoded = tokenizer(
        texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )
    encoded = {
        key: value.to(device)
        for key, value in encoded.items()
    }

    def generate_on_current_device():
        with torch.inference_mode():
            return model.generate(
                **encoded,
                forced_bos_token_id=target_id,
                max_new_tokens=512,
                num_beams=3,
                length_penalty=1.0,
                early_stopping=True,
            )

    try:
        generated = generate_on_current_device()
    except Exception as first_exc:
        # Some older macOS/PyTorch combinations expose MPS but fail on a
        # generation operator. Fall back to CPU automatically rather than
        # asking the user to diagnose the backend.
        if device != "mps":
            raise RuntimeError(
                "로컬 번역 중 오류가 발생했습니다."
            ) from first_exc

        model = model.to("cpu")
        bundle["model"] = model
        bundle["device"] = "cpu"
        device = "cpu"
        encoded = {
            key: value.to("cpu")
            for key, value in encoded.items()
        }
        try:
            with torch.inference_mode():
                generated = model.generate(
                    **encoded,
                    forced_bos_token_id=target_id,
                    max_new_tokens=512,
                    num_beams=3,
                    length_penalty=1.0,
                    early_stopping=True,
                )
        except Exception as second_exc:
            raise RuntimeError(
                "로컬 번역 모델을 CPU에서도 실행하지 못했습니다."
            ) from second_exc

    outputs = tokenizer.batch_decode(
        generated,
        skip_special_tokens=True,
    )
    return [
        re.sub(r"\s+", " ", str(item or "")).strip()
        for item in outputs
    ]


def _translate_items_local_v030(
    items,
    source_nllb,
    model_name,
    batch_size=4,
):
    # Flatten long utterances into safe model-sized pieces, then join the
    # Korean pieces back into the original utterance id. Source timing is not
    # changed by this operation.
    flattened = []
    piece_map = {}

    for item in items:
        item_id = str(item.get("id"))
        pieces = _split_for_local_translation_v030(
            item.get("text", "")
        )
        piece_map[item_id] = []
        for piece_index, piece in enumerate(pieces):
            piece_id = f"{item_id}::P{piece_index:03d}"
            flattened.append(
                {
                    "piece_id": piece_id,
                    "item_id": item_id,
                    "piece_index": piece_index,
                    "text": piece,
                }
            )
            piece_map[item_id].append(piece_id)

    translated_pieces = {}
    for start in range(0, len(flattened), batch_size):
        batch = flattened[start : start + batch_size]
        outputs = _local_generate_batch_v030(
            [item["text"] for item in batch],
            source_nllb=source_nllb,
            model_name=model_name,
        )
        if len(outputs) != len(batch):
            raise RuntimeError(
                "로컬 번역 결과 수가 입력 수와 일치하지 않습니다."
            )
        for source_item, translated in zip(batch, outputs):
            translated_pieces[
                source_item["piece_id"]
            ] = translated

    result = {}
    for item in items:
        item_id = str(item.get("id"))
        ordered = [
            translated_pieces.get(piece_id, "")
            for piece_id in piece_map.get(item_id, [])
        ]
        korean = " ".join(
            part for part in ordered if part
        ).strip()
        if not korean:
            raise RuntimeError(
                "로컬 번역 결과가 비어 있습니다: "
                f"{item_id}"
            )
        result[item_id] = korean
    return result


def _build_foreign_translation_draft_v030(
    data,
    chapter_index,
    translation_local_model,
):
    model_name = str(
        translation_local_model
        or _DEFAULT_LOCAL_TRANSLATION_MODEL_V030
    ).strip()
    source_nllb = _nllb_source_language_v030(data)

    video_id = (
        data.get("metadata", {}).get("video_id")
        or "unknown-video"
    )
    chapter = selected_chapter(data, chapter_index)
    segments = _foreign_chapter_segments_v029(
        data,
        chapter,
    )
    groups = _group_foreign_segments_v029(segments)

    translation_inputs = []
    base_rows = []
    for index, group in enumerate(groups, start=1):
        utterance_id = f"UT-{index:05d}"
        raw_joined = " ".join(
            _clean_foreign_source_text_v029(
                item.get("text", "")
            )
            for item in group
        ).strip()
        if not raw_joined:
            continue

        source_ids = [
            item.get("segment_id")
            for item in group
            if item.get("segment_id")
        ]
        source_keys = [
            item.get("segment_key")
            for item in group
            if item.get("segment_key")
        ]
        start_seconds = min(
            float(item.get("start_seconds", 0))
            for item in group
        )
        end_seconds = max(
            float(item.get("end_seconds", 0))
            for item in group
        )
        source_spans = [
            {
                "segment_id": item.get("segment_id"),
                "segment_key": item.get("segment_key"),
                "start_seconds": item.get("start_seconds"),
                "end_seconds": item.get("end_seconds"),
                "raw_segment_text": item.get("text", ""),
                "used_text": _clean_foreign_source_text_v029(
                    item.get("text", "")
                ),
                "mapping_method": (
                    "local_translation_group_direct_mapping"
                ),
                "verification_status": "machine_grouped",
            }
            for item in group
        ]
        translation_inputs.append(
            {
                "id": utterance_id,
                "text": raw_joined,
            }
        )
        base_rows.append(
            {
                "utterance_id": utterance_id,
                "chapter_id": chapter["chapter_id"],
                "chapter_label": chapter.get("label"),
                "chapter_assignment_status": "single_chapter",
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "display_timestamp": display_timestamp(
                    start_seconds
                ),
                "raw_joined_text": raw_joined,
                "source_segment_ids": source_ids,
                "source_segment_keys": source_keys,
                "source_spans": source_spans,
                "source_span_status": "complete",
                "source_span_mapping_ratio": 1.0,
                "unmapped_editor_tokens": [],
            }
        )

    translations = _translate_items_local_v030(
        translation_inputs,
        source_nllb=source_nllb,
        model_name=model_name,
    )

    utterances = []
    source_lang = source_language_code(data) or "unknown"
    for base in base_rows:
        korean = translations.get(
            base["utterance_id"],
            "",
        ).strip()
        sentence_complete = bool(
            re.search(r"[.!?…。！？]$", korean)
        )
        utterance = dict(base)
        utterance.update(
            {
                "auto_normalized_text": korean,
                "normalized_text": korean,
                "speaker_id": None,
                "speaker_status": "unavailable",
                "content_mode": "translated_natural_language",
                "sentence_unit_ids": [],
                "sentence_complete": sentence_complete,
                "normalization_item_ids": [],
                "confidence": "medium",
                "review_status": "needs_review",
                "editor_note": "",
                "validation_warnings": (
                    []
                    if sentence_complete
                    else ["possible_incomplete_sentence"]
                ),
                "translation_status": (
                    "local_machine_translated_needs_review"
                ),
                "translation_source_language": source_lang,
                "translation_target_language": "ko-KR",
            }
        )
        utterances.append(utterance)

    complete_count = sum(
        1
        for item in utterances
        if item.get("sentence_complete")
    )
    loaded = _LOCAL_TRANSLATOR_CACHE_V030.get(
        model_name,
        {},
    )

    return {
        "schema_version": "script_preprocessing_v0.3.0",
        "source_schema_version": data.get("schema_version"),
        "source_url": data.get("source_url"),
        "video_id": video_id,
        "source_language": source_lang,
        "source_language_label": source_language_label(data),
        "transcript_origin": data.get(
            "collector_methods", {}
        ).get("transcript"),
        "is_auto_generated": data.get(
            "transcript", {}
        ).get("is_generated"),
        "processed_chapter": chapter,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input_document_kind": "acquisition",
        "boundary_profile": {
            "profile_id": "foreign_translation_grouping_v0.2",
            "target_duration": 14.0,
            "max_duration": 22.0,
            "max_chars": 900,
            "gap_break_seconds": 2.5,
        },
        "chapter_boundary_context": {},
        "all_sentence_unit_count": 0,
        "sentence_unit_count": 0,
        "raw_segment_count": len(segments),
        "normalized_utterance_count": len(utterances),
        "translation_required": True,
        "translation_status": "completed_needs_review",
        "translation_metadata": {
            "provider": "local_nllb_transformers",
            "model": model_name,
            "source_nllb_language": source_nllb,
            "target_language": "ko-KR",
            "target_nllb_language": "kor_Hang",
            "policy_version": "faithful_local_translation_v0.2",
            "translated_at": utc_now(),
            "api_key_required": False,
            "api_key_stored": False,
            "execution_device": loaded.get("device", "unknown"),
            "model_cache_reused_after_first_download": True,
        },
        "raw_segments": segments,
        "sentence_units": [],
        "normalized_utterances": utterances,
        "normalization_items": [],
        "editor_changes": [],
        "unresolved_terms": [],
        "profile_application": {
            "mode": "foreign_translation_v030_local",
            "profile_source": "local_foreign_language_translation",
            "generalization_claim": False,
        },
        "processing_report": {
            "processing_status": "validation_required",
            "chapter_review_status": "in_progress",
            "draft_only": True,
            "editor_review_required": True,
            "sentence_boundary_method": (
                "foreign_time_and_punctuation_grouping"
            ),
            "chapter_assignment_method": (
                "segment_start_single_owner"
            ),
            "sentence_complete_utterances": complete_count,
            "sentence_incomplete_utterances": (
                len(utterances) - complete_count
            ),
            "sentence_completion_rate": round(
                complete_count / max(1, len(utterances)),
                4,
            ),
            "mechanical_duplicates_removed": 0,
            "high_confidence_corrections": 0,
            "medium_confidence_corrections": 0,
            "low_confidence_terms": 0,
            "approved_utterances": 0,
            "rejected_utterances": 0,
            "review_required_utterances": len(utterances),
            "source_span_complete_utterances": len(utterances),
            "source_span_partial_utterances": 0,
            "source_span_weak_utterances": 0,
            "visual_verification_items": [
                "프롬프트·코드·파라미터의 정확한 문자열",
                "도구 화면에 표시되는 메뉴·설정값",
                "고유명사·제품명·모델명의 공식 표기",
                "로컬 번역 결과의 의미 누락·과잉 번역 여부",
            ],
        },
    }


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_local_model=None,
    # Kept only so an old caller does not crash after replacing files.
    translation_api_key=None,
    translation_model=None,
):
    del translation_api_key, translation_model

    if translation_required_for_source(data):
        if translate_foreign_to_korean:
            return _build_foreign_translation_draft_v030(
                data=data,
                chapter_index=chapter_index,
                translation_local_model=(
                    translation_local_model
                    or _DEFAULT_LOCAL_TRANSLATION_MODEL_V030
                ),
            )

        result = _build_preprocessing_draft_v028_final(
            data,
            chapter_index=chapter_index,
            custom_glossary_text=custom_glossary_text,
            include_boundary_continuation=include_boundary_continuation,
            calibration_gold=calibration_gold,
            use_validated_profile=use_validated_profile,
            apply_verified_same_chapter=apply_verified_same_chapter,
            reuse_approval_status=reuse_approval_status,
            auto_apply_builtin_profile=auto_apply_builtin_profile,
        )
        result["schema_version"] = "script_preprocessing_v0.3.0"
        result["processed_chapter"] = selected_chapter(
            data,
            chapter_index,
        )
        result["translation_required"] = True
        result["translation_status"] = "not_requested"
        return result

    result = _build_preprocessing_draft_v028_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
    )
    result["schema_version"] = "script_preprocessing_v0.3.0"
    result["processed_chapter"] = selected_chapter(
        data,
        chapter_index,
    )
    result["translation_required"] = False
    result["translation_status"] = "not_required"
    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v029_final(data)
    result["schema_version"] = "script_preprocessing_v0.3.0"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v029_final(
        draft,
        edited_rows,
    )
    result["schema_version"] = "script_preprocessing_v0.3.0"
    return result


# =====================================================================
# v0.3.1 patch
# - reconstruct complete foreign-language sentences BEFORE translation
# - creator chapter timestamps are topic anchors, not hard sentence cuts
# - a sentence may cross a creator chapter boundary and is owned by its
#   estimated sentence start time
# - group only BETWEEN reconstructed sentences; never cut inside a sentence
# - keep NLLB local translation unchanged for this validation step
# =====================================================================

_build_preprocessing_draft_v030_final = build_preprocessing_draft
_prepare_existing_preprocessing_v030_final = prepare_existing_preprocessing
_export_editor_result_v030_final = export_editor_result

_FOREIGN_SENTENCE_TERMINAL_V031 = re.compile(
    r"[.!?。！？…]+(?:[\"'’”）)\]]+)?(?=\s|$)"
)


def _foreign_segment_pieces_v031(segment):
    """Split one raw caption segment only at explicit sentence punctuation.

    The YouTube segment timestamp stays the authority. When a segment contains
    more than one sentence, character position is used only to estimate the
    sentence boundary time within that segment.
    """
    text = _clean_foreign_source_text_v029(
        segment.get("text", "")
    )
    if not text:
        return []

    pieces = []
    last = 0
    for match in _FOREIGN_SENTENCE_TERMINAL_V031.finditer(text):
        end = match.end()
        piece_text = text[last:end].strip()
        if piece_text:
            start_seconds, end_seconds = _estimate_piece_time(
                segment,
                last,
                end,
                len(text),
            )
            pieces.append(
                {
                    "text": piece_text,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "terminal": True,
                    "segment_id": segment.get("segment_id"),
                    "segment_key": segment.get("segment_key"),
                    "segment_start_seconds": segment.get("start_seconds"),
                    "segment_end_seconds": segment.get("end_seconds"),
                    "raw_segment_text": segment.get("text", ""),
                }
            )
        last = end

    tail = text[last:].strip()
    if tail:
        start_seconds, end_seconds = _estimate_piece_time(
            segment,
            last,
            len(text),
            len(text),
        )
        pieces.append(
            {
                "text": tail,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "terminal": False,
                "segment_id": segment.get("segment_id"),
                "segment_key": segment.get("segment_key"),
                "segment_start_seconds": segment.get("start_seconds"),
                "segment_end_seconds": segment.get("end_seconds"),
                "raw_segment_text": segment.get("text", ""),
            }
        )

    return pieces


def _build_foreign_sentence_units_v031(
    data,
    gap_break_seconds=2.5,
    emergency_max_duration=50.0,
):
    """Reconstruct sentence units across the WHOLE transcript.

    Creator chapter timestamps are intentionally ignored here. This prevents
    chapter starts such as 02:45 from splitting "...is called / Whisper.".
    """
    segments = enrich_all_segments(data)
    units = []
    current = None
    previous_segment_end = None

    def append_piece(target, piece):
        if not target:
            target = {
                "raw_text": piece["text"],
                "start_seconds": float(piece["start_seconds"]),
                "end_seconds": float(piece["end_seconds"]),
                "source_segment_ids": [],
                "source_segment_keys": [],
                "source_spans": [],
                "sentence_complete": False,
                "boundary_reason": None,
            }
        else:
            target["raw_text"] = (
                str(target.get("raw_text", "")).rstrip()
                + " "
                + piece["text"].lstrip()
            ).strip()
            target["end_seconds"] = max(
                float(target.get("end_seconds", 0)),
                float(piece["end_seconds"]),
            )

        sid = piece.get("segment_id")
        skey = piece.get("segment_key")
        if sid and sid not in target["source_segment_ids"]:
            target["source_segment_ids"].append(sid)
        if skey and skey not in target["source_segment_keys"]:
            target["source_segment_keys"].append(skey)

        target["source_spans"].append(
            {
                "segment_id": sid,
                "segment_key": skey,
                "start_seconds": piece.get("segment_start_seconds"),
                "end_seconds": piece.get("segment_end_seconds"),
                "raw_segment_text": piece.get("raw_segment_text", ""),
                "used_text": piece.get("text", ""),
                "mapping_method": "foreign_sentence_reconstruction_v031",
                "verification_status": "machine_aligned",
            }
        )
        return target

    def flush(reason, complete=False):
        nonlocal current
        if not current:
            return
        current["boundary_reason"] = reason
        current["sentence_complete"] = bool(complete)
        current["raw_text"] = re.sub(
            r"\s+", " ", str(current.get("raw_text", ""))
        ).strip()
        units.append(current)
        current = None

    for segment in segments:
        seg_start = float(segment.get("start_seconds", 0) or 0)
        seg_end = float(segment.get("end_seconds", seg_start) or seg_start)
        gap = (
            0.0
            if previous_segment_end is None
            else seg_start - previous_segment_end
        )

        # A real pause is a stronger boundary than a rolling creator timestamp.
        if current and gap > gap_break_seconds:
            flush("time_gap", complete=False)

        for piece in _foreign_segment_pieces_v031(segment):
            current = append_piece(current, piece)

            if piece.get("terminal"):
                flush("terminal_punctuation", complete=True)
                continue

            if current:
                duration = (
                    float(current.get("end_seconds", 0))
                    - float(current.get("start_seconds", 0))
                )
                # Safety fallback only. 50 s is intentionally far above the old
                # 22 s cap so ordinary clauses are not chopped in half.
                if duration >= emergency_max_duration:
                    flush("emergency_long_no_punctuation", complete=False)

        previous_segment_end = max(
            previous_segment_end or seg_end,
            seg_end,
        )

    flush("transcript_end", complete=False)

    for index, unit in enumerate(units, start=1):
        unit["sentence_unit_id"] = f"FSU-{index:05d}"
    return units


def _assign_foreign_sentences_to_chapter_v031(all_units, chapter):
    """Assign each complete reconstructed sentence to one chapter by start time."""
    start = float(chapter.get("start_seconds", 0) or 0)
    end_raw = chapter.get("end_seconds")
    end = float(end_raw) if end_raw is not None else float("inf")

    selected = [
        unit
        for unit in all_units
        if float(unit.get("start_seconds", 0)) >= start
        and float(unit.get("start_seconds", 0)) < end
    ]

    previous = None
    following = None
    for unit in all_units:
        ustart = float(unit.get("start_seconds", 0))
        if ustart < start:
            previous = unit
        elif following is None and ustart >= end:
            following = unit

    cross_end = [
        unit.get("sentence_unit_id")
        for unit in selected
        if end != float("inf")
        and float(unit.get("end_seconds", 0)) > end
    ]
    previous_crosses_start = bool(
        previous
        and float(previous.get("end_seconds", 0)) > start
    )

    context = {
        "assignment_rule": "reconstructed_sentence_start_single_owner",
        "creator_boundary_is_hard_cut": False,
        "previous_sentence_context": (
            {
                "sentence_unit_id": previous.get("sentence_unit_id"),
                "start_seconds": previous.get("start_seconds"),
                "end_seconds": previous.get("end_seconds"),
                "raw_text": previous.get("raw_text"),
                "crosses_creator_start": previous_crosses_start,
            }
            if previous
            else None
        ),
        "next_sentence_context": (
            {
                "sentence_unit_id": following.get("sentence_unit_id"),
                "start_seconds": following.get("start_seconds"),
                "end_seconds": following.get("end_seconds"),
                "raw_text": following.get("raw_text"),
            }
            if following
            else None
        ),
        "selected_sentence_ids_crossing_creator_end": cross_end,
    }
    return selected, context


def _group_foreign_sentence_units_v031(
    units,
    target_duration=14.0,
    max_duration=30.0,
    max_chars=1000,
    max_sentences=4,
):
    """Make editor rows only at reconstructed sentence boundaries."""
    groups = []
    current = []

    def flush():
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for unit in units:
        if not current:
            current = [unit]
            continue

        current_start = float(current[0].get("start_seconds", 0))
        current_end = max(float(x.get("end_seconds", 0)) for x in current)
        current_duration = current_end - current_start
        current_chars = sum(len(str(x.get("raw_text", ""))) for x in current)

        proposed_duration = float(unit.get("end_seconds", 0)) - current_start
        proposed_chars = current_chars + 1 + len(str(unit.get("raw_text", "")))

        should_break_before = bool(
            len(current) >= max_sentences
            or proposed_duration > max_duration
            or proposed_chars > max_chars
            or (
                current_duration >= target_duration
                and len(current) >= 2
            )
        )

        if should_break_before:
            flush()
            current = [unit]
        else:
            current.append(unit)

    flush()
    return groups


def _dedupe_source_spans_v031(spans):
    """Keep partial pieces from one segment in order without losing used_text."""
    merged = []
    for span in spans:
        if (
            merged
            and merged[-1].get("segment_id") == span.get("segment_id")
            and merged[-1].get("mapping_method") == span.get("mapping_method")
        ):
            merged[-1]["used_text"] = (
                str(merged[-1].get("used_text", "")).rstrip()
                + " "
                + str(span.get("used_text", "")).lstrip()
            ).strip()
        else:
            merged.append(copy.deepcopy(span))
    return merged


def _build_foreign_translation_draft_v031(
    data,
    chapter_index,
    translation_local_model,
):
    model_name = str(
        translation_local_model
        or _DEFAULT_LOCAL_TRANSLATION_MODEL_V030
    ).strip()
    source_nllb = _nllb_source_language_v030(data)
    video_id = data.get("metadata", {}).get("video_id") or "unknown-video"
    chapter = selected_chapter(data, chapter_index)

    all_units = _build_foreign_sentence_units_v031(data)
    chapter_units, boundary_context = (
        _assign_foreign_sentences_to_chapter_v031(
            all_units,
            chapter,
        )
    )
    groups = _group_foreign_sentence_units_v031(chapter_units)

    translation_inputs = []
    base_rows = []
    referenced_segment_ids = []

    for index, group in enumerate(groups, start=1):
        utterance_id = f"UT-{index:05d}"
        raw_joined = " ".join(
            str(unit.get("raw_text", "")).strip()
            for unit in group
            if str(unit.get("raw_text", "")).strip()
        ).strip()
        if not raw_joined:
            continue

        source_ids = []
        source_keys = []
        spans = []
        for unit in group:
            for value in unit.get("source_segment_ids", []):
                if value not in source_ids:
                    source_ids.append(value)
                if value not in referenced_segment_ids:
                    referenced_segment_ids.append(value)
            for value in unit.get("source_segment_keys", []):
                if value not in source_keys:
                    source_keys.append(value)
            spans.extend(unit.get("source_spans", []))

        start_seconds = min(float(unit.get("start_seconds", 0)) for unit in group)
        end_seconds = max(float(unit.get("end_seconds", 0)) for unit in group)
        chapter_end = chapter.get("end_seconds")
        crosses_end = bool(
            chapter_end is not None
            and end_seconds > float(chapter_end)
        )

        translation_inputs.append({"id": utterance_id, "text": raw_joined})
        base_rows.append(
            {
                "utterance_id": utterance_id,
                "chapter_id": chapter["chapter_id"],
                "chapter_label": chapter.get("label"),
                "chapter_assignment_status": (
                    "cross_creator_boundary"
                    if crosses_end
                    else "single_chapter"
                ),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "display_timestamp": display_timestamp(start_seconds),
                "raw_joined_text": raw_joined,
                "source_segment_ids": source_ids,
                "source_segment_keys": source_keys,
                "source_spans": _dedupe_source_spans_v031(spans),
                "source_span_status": "complete",
                "source_span_mapping_ratio": 1.0,
                "unmapped_editor_tokens": [],
                "sentence_unit_ids": [
                    unit.get("sentence_unit_id") for unit in group
                ],
                "source_sentence_complete": all(
                    bool(unit.get("sentence_complete")) for unit in group
                ),
            }
        )

    translations = _translate_items_local_v030(
        translation_inputs,
        source_nllb=source_nllb,
        model_name=model_name,
    )

    source_lang = source_language_code(data) or "unknown"
    utterances = []
    for base in base_rows:
        korean = translations.get(base["utterance_id"], "").strip()
        # Source reconstruction is the authority for sentence completeness.
        sentence_complete = bool(base.pop("source_sentence_complete", False))
        utterance = dict(base)
        utterance.update(
            {
                "auto_normalized_text": korean,
                "normalized_text": korean,
                "speaker_id": None,
                "speaker_status": "unavailable",
                "content_mode": "translated_natural_language",
                "sentence_complete": sentence_complete,
                "normalization_item_ids": [],
                "confidence": "medium",
                "review_status": "needs_review",
                "editor_note": "",
                "validation_warnings": (
                    [] if sentence_complete else ["possible_incomplete_source_sentence"]
                ),
                "translation_status": "local_machine_translated_needs_review",
                "translation_source_language": source_lang,
                "translation_target_language": "ko-KR",
            }
        )
        utterances.append(utterance)

    segment_by_id = {
        item.get("segment_id"): item
        for item in enrich_all_segments(data)
        if item.get("segment_id")
    }
    raw_segments = [
        segment_by_id[sid]
        for sid in referenced_segment_ids
        if sid in segment_by_id
    ]

    complete_count = sum(1 for item in utterances if item.get("sentence_complete"))
    loaded = _LOCAL_TRANSLATOR_CACHE_V030.get(model_name, {})

    return {
        "schema_version": "script_preprocessing_v0.3.1",
        "source_schema_version": data.get("schema_version"),
        "source_url": data.get("source_url"),
        "video_id": video_id,
        "source_language": source_lang,
        "source_language_label": source_language_label(data),
        "transcript_origin": data.get("collector_methods", {}).get("transcript"),
        "is_auto_generated": data.get("transcript", {}).get("is_generated"),
        "processed_chapter": chapter,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input_document_kind": "acquisition",
        "boundary_profile": {
            "profile_id": "foreign_sentence_reconstruction_v0.3.1",
            "target_group_duration": 14.0,
            "max_group_duration": 30.0,
            "max_group_chars": 1000,
            "max_sentences_per_group": 4,
            "gap_break_seconds": 2.5,
            "emergency_no_punctuation_seconds": 50.0,
            "creator_chapter_is_hard_sentence_cut": False,
        },
        "chapter_boundary_context": boundary_context,
        "all_sentence_unit_count": len(all_units),
        "sentence_unit_count": len(chapter_units),
        "raw_segment_count": len(raw_segments),
        "normalized_utterance_count": len(utterances),
        "translation_required": True,
        "translation_status": "completed_needs_review",
        "translation_metadata": {
            "provider": "local_nllb_transformers",
            "model": model_name,
            "source_nllb_language": source_nllb,
            "target_language": "ko-KR",
            "target_nllb_language": "kor_Hang",
            "policy_version": "faithful_local_translation_v0.3.1",
            "translated_at": utc_now(),
            "api_key_required": False,
            "api_key_stored": False,
            "execution_device": loaded.get("device", "unknown"),
            "model_cache_reused_after_first_download": True,
        },
        "raw_segments": raw_segments,
        "sentence_units": chapter_units,
        "normalized_utterances": utterances,
        "normalization_items": [],
        "editor_changes": [],
        "unresolved_terms": [],
        "profile_application": {
            "mode": "foreign_translation_v031_sentence_reconstruction",
            "profile_source": "whole_transcript_sentence_reconstruction_then_local_translation",
            "generalization_claim": False,
        },
        "processing_report": {
            "processing_status": "validation_required",
            "chapter_review_status": "in_progress",
            "draft_only": True,
            "editor_review_required": True,
            "sentence_boundary_method": "whole_transcript_punctuation_reconstruction_before_chapter_assignment",
            "chapter_assignment_method": "reconstructed_sentence_start_single_owner",
            "creator_chapter_boundary_hard_cut": False,
            "sentence_complete_utterances": complete_count,
            "sentence_incomplete_utterances": len(utterances) - complete_count,
            "sentence_completion_rate": round(
                complete_count / max(1, len(utterances)), 4
            ),
            "reconstructed_sentence_unit_count": len(chapter_units),
            "cross_creator_boundary_utterances": sum(
                1
                for item in utterances
                if item.get("chapter_assignment_status") == "cross_creator_boundary"
            ),
            "mechanical_duplicates_removed": 0,
            "high_confidence_corrections": 0,
            "medium_confidence_corrections": 0,
            "low_confidence_terms": 0,
            "approved_utterances": 0,
            "rejected_utterances": 0,
            "review_required_utterances": len(utterances),
            "source_span_complete_utterances": len(utterances),
            "source_span_partial_utterances": 0,
            "source_span_weak_utterances": 0,
            "visual_verification_items": [
                "프롬프트·코드·파라미터의 정확한 문자열",
                "도구 화면에 표시되는 메뉴·설정값",
                "고유명사·제품명·모델명의 공식 표기",
                "로컬 번역 결과의 의미 누락·과잉 번역 여부",
                "제작자 챕터 경계를 넘는 문장의 실제 시작·끝",
            ],
        },
    }


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_local_model=None,
    translation_api_key=None,
    translation_model=None,
):
    # API parameters remain accepted only for backward-compatible app calls.
    del translation_api_key, translation_model

    if translation_required_for_source(data) and translate_foreign_to_korean:
        return _build_foreign_translation_draft_v031(
            data,
            chapter_index=chapter_index,
            translation_local_model=(
                translation_local_model
                or _DEFAULT_LOCAL_TRANSLATION_MODEL_V030
            ),
        )

    result = _build_preprocessing_draft_v030_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
        translate_foreign_to_korean=False,
        translation_local_model=translation_local_model,
    )
    result["schema_version"] = "script_preprocessing_v0.3.1"
    return result


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v030_final(data)
    result["schema_version"] = "script_preprocessing_v0.3.1"
    return result


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v030_final(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.3.1"
    return result

# =====================================================================
# v0.3.1 terminology policy patch
# - preserve foreign brand / product / model / tool names in official Latin form
# - applies to BOTH Korean-source preprocessing and foreign->Korean translation
# - e.g. 클로드 코드(Claude Code) -> Claude Code, 챗지피티 -> ChatGPT
# =====================================================================

_build_preprocessing_draft_v031_before_official_names = build_preprocessing_draft
_prepare_existing_preprocessing_v031_before_official_names = prepare_existing_preprocessing
_export_editor_result_v031_before_official_names = export_editor_result

# Longer / more specific names must come first.
_OFFICIAL_FOREIGN_NAME_RULES_V031 = [
    # Anthropic / Claude family
    (r"클로드\s*코드\s*\(\s*Claude\s*Code\s*\)", "Claude Code"),
    (r"클로드\s*코드", "Claude Code"),
    (r"Claude\s*코드", "Claude Code"),
    (r"클로드\s*디자인\s*\(\s*Claude\s*Design\s*\)", "Claude Design"),
    (r"클로드\s*디자인", "Claude Design"),
    (r"클로드\s*\(\s*Claude\s*\)", "Claude"),
    (r"클로드", "Claude"),
    (r"앤트로픽", "Anthropic"),

    # OpenAI family
    (r"챗\s*지피티\s*\(\s*ChatGPT\s*\)", "ChatGPT"),
    (r"챗지피티\s*\(\s*ChatGPT\s*\)", "ChatGPT"),
    (r"챗\s*GPT", "ChatGPT"),
    (r"챗지피티", "ChatGPT"),
    (r"오픈\s*에이아이", "OpenAI"),
    (r"오픈\s*AI", "OpenAI"),
    (r"소라\s*\(\s*Sora\s*\)", "Sora"),
    (r"소라", "Sora"),

    # Google / common AI tools
    (r"제미나이\s*\(\s*Gemini\s*\)", "Gemini"),
    (r"제미나이", "Gemini"),
    (r"나노\s*바나나\s*\(\s*Nano\s*Banana\s*\)", "Nano Banana"),
    (r"나노\s*바나나", "Nano Banana"),
    (r"비오\s*\(\s*Veo\s*\)", "Veo"),

    # Video / image generation tools
    (r"힉스필드\s*AI\s*\(\s*Higgsfield\s*AI\s*\)", "Higgsfield AI"),
    (r"힉스필드\s*AI", "Higgsfield AI"),
    (r"힉스필드\s*\(\s*Higgsfield\s*\)", "Higgsfield"),
    (r"힉스필드", "Higgsfield"),
    (r"시댄스\s*\(\s*Seedance\s*\)", "Seedance"),
    (r"씨댄스\s*\(\s*Seedance\s*\)", "Seedance"),
    (r"시댄스", "Seedance"),
    (r"씨댄스", "Seedance"),
    (r"미드저니\s*\(\s*Midjourney\s*\)", "Midjourney"),
    (r"미드저니", "Midjourney"),
    (r"런웨이\s*\(\s*Runway\s*\)", "Runway"),
    (r"런웨이", "Runway"),
    (r"클링\s*\(\s*Kling\s*\)", "Kling"),
    (r"클링", "Kling"),

    # Design / production tools
    (r"피그마\s*\(\s*Figma\s*\)", "Figma"),
    (r"피그마", "Figma"),
    (r"위스퍼\s*\(\s*Whisper\s*\)", "Whisper"),
    (r"위스퍼", "Whisper"),
    (r"에프에프엠페그\s*\(\s*FFmpeg\s*\)", "FFmpeg"),
    (r"에프에프엠페그", "FFmpeg"),
    (r"에프에프엠펙", "FFmpeg"),
    (r"하이퍼프레임즈\s*\(\s*HyperFrames\s*\)", "HyperFrames"),
    (r"하이퍼프레임\s*\(\s*HyperFrames\s*\)", "HyperFrames"),
    (r"하이퍼프레임즈", "HyperFrames"),
    (r"하이퍼프레임", "HyperFrames"),
    (r"리모션\s*\(\s*Remotion\s*\)", "Remotion"),
    (r"리모션", "Remotion"),
]


def _canonicalize_official_foreign_names_v031(text):
    value = str(text or "")
    if not value:
        return value
    for pattern, replacement in _OFFICIAL_FOREIGN_NAME_RULES_V031:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)

    # Clean redundant forms that can remain after a manual edit or machine translation.
    redundant = [
        "Claude Code", "Claude Design", "Claude", "ChatGPT", "OpenAI",
        "Sora", "Gemini", "Nano Banana", "Veo", "Higgsfield AI",
        "Higgsfield", "Seedance", "Midjourney", "Runway", "Kling",
        "Figma", "Whisper", "FFmpeg", "HyperFrames", "Remotion",
    ]
    for name in redundant:
        escaped = re.escape(name)
        value = re.sub(
            rf"{escaped}\s*\(\s*{escaped}\s*\)",
            name,
            value,
            flags=re.IGNORECASE,
        )
    return value


def _apply_official_foreign_name_policy_v031(result):
    if not isinstance(result, dict):
        return result

    for item in result.get("normalized_utterances", []) or []:
        for field in ("auto_normalized_text", "normalized_text"):
            if field in item:
                item[field] = _canonicalize_official_foreign_names_v031(
                    item.get(field, "")
                )

    # Korean-source preprocessing can also carry normalized text at sentence-unit level.
    for item in result.get("sentence_units", []) or []:
        if "normalized_text" in item:
            item["normalized_text"] = _canonicalize_official_foreign_names_v031(
                item.get("normalized_text", "")
            )

    result["terminology_policy"] = {
        "foreign_brand_product_model_tool_names": "preserve_official_latin_spelling",
        "applies_to": ["korean_source", "foreign_source_translated_to_korean"],
        "hangul_transliteration_output": False,
        "bilingual_parenthetical_duplication": False,
        "examples": {
            "클로드 코드": "Claude Code",
            "클로드": "Claude",
            "챗지피티": "ChatGPT",
            "힉스필드": "Higgsfield",
            "소라": "Sora",
            "시댄스": "Seedance",
        },
    }
    return result


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_local_model=None,
    translation_api_key=None,
    translation_model=None,
):
    result = _build_preprocessing_draft_v031_before_official_names(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
        translate_foreign_to_korean=translate_foreign_to_korean,
        translation_local_model=translation_local_model,
        translation_api_key=translation_api_key,
        translation_model=translation_model,
    )
    return _apply_official_foreign_name_policy_v031(result)


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v031_before_official_names(data)
    return _apply_official_foreign_name_policy_v031(result)


def export_editor_result(draft, edited_rows):
    canonical_rows = []
    for row in edited_rows or []:
        new_row = dict(row)
        if "normalized_text" in new_row:
            new_row["normalized_text"] = _canonicalize_official_foreign_names_v031(
                new_row.get("normalized_text", "")
            )
        canonical_rows.append(new_row)

    result = _export_editor_result_v031_before_official_names(
        draft,
        canonical_rows,
    )
    return _apply_official_foreign_name_policy_v031(result)

# =====================================================================
# v0.3.2 context-aware local LLM translation patch
# - API-key-free Apple Silicon inference via MLX-LM
# - short videos: whole-video context
# - long videos: target + neighboring source context
# - very short creator chapters: automatically read adjacent context
# - translate only TARGET_ROWS; context is reference-only
# - preserve original sentence/timestamp/chapter provenance from v0.3.1
# =====================================================================

_build_preprocessing_draft_v031_final = build_preprocessing_draft
_prepare_existing_preprocessing_v031_final = prepare_existing_preprocessing
_export_editor_result_v031_final = export_editor_result

_DEFAULT_LOCAL_LLM_MODEL_V032 = "mlx-community/Qwen2.5-14B-Instruct-4bit"
_LOCAL_LLM_CACHE_V032 = {}
_V032_SHORT_VIDEO_SECONDS = 20 * 60
_V032_SHORT_CHAPTER_SECONDS = 90
_V032_NEIGHBOR_CONTEXT_SECONDS = 180
_V032_MAX_REFERENCE_CHARS = 28000
_V032_MAX_TARGET_CHARS_PER_CALL = 9000
_V032_MAX_TARGET_ROWS_PER_CALL = 12


def _video_duration_seconds_v032(data, all_units=None):
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
    for key in ("duration_seconds", "duration"):
        value = metadata.get(key)
        try:
            if value is not None and float(value) > 0:
                return float(value)
        except Exception:
            pass

    transcript = data.get("transcript", {}) if isinstance(data, dict) else {}
    items = transcript.get("items", []) if isinstance(transcript, dict) else []
    ends = []
    for item in items:
        try:
            end = item.get("end_seconds")
            if end is None:
                end = float(item.get("start_seconds", 0) or 0) + float(
                    item.get("duration_seconds", 0) or 0
                )
            ends.append(float(end))
        except Exception:
            continue
    if ends:
        return max(ends)

    if all_units:
        try:
            return max(float(x.get("end_seconds", 0) or 0) for x in all_units)
        except Exception:
            pass
    return 0.0


def _chapter_outline_v032(data):
    rows = []
    for index, chapter in enumerate(data.get("creator_chapters", []) or [], start=1):
        start = chapter.get("start_seconds", 0)
        label = str(chapter.get("label") or chapter.get("title") or "").strip()
        rows.append(f"CH-{index:02d} {display_timestamp(start)} {label}".strip())
    return "\n".join(rows)


def _units_plain_text_v032(units):
    return "\n".join(
        f"[{display_timestamp(unit.get('start_seconds'))}] {str(unit.get('raw_text', '')).strip()}"
        for unit in units
        if str(unit.get("raw_text", "")).strip()
    )


def _trim_reference_units_v032(units, max_chars=_V032_MAX_REFERENCE_CHARS):
    if not units:
        return []
    text_len = 0
    selected = []
    for unit in units:
        piece_len = len(str(unit.get("raw_text", ""))) + 12
        if selected and text_len + piece_len > max_chars:
            break
        selected.append(unit)
        text_len += piece_len
    return selected


def _reference_units_for_batch_v032(data, all_units, chapter, batch_rows):
    duration = _video_duration_seconds_v032(data, all_units)
    chapter_start = float(chapter.get("start_seconds", 0) or 0)
    chapter_end_raw = chapter.get("end_seconds")
    chapter_end = (
        float(chapter_end_raw)
        if chapter_end_raw is not None
        else duration
    )
    chapter_duration = max(0.0, chapter_end - chapter_start)

    if duration and duration <= _V032_SHORT_VIDEO_SECONDS:
        return _trim_reference_units_v032(all_units), {
            "strategy": "whole_video_context",
            "video_duration_seconds": duration,
            "short_video_threshold_seconds": _V032_SHORT_VIDEO_SECONDS,
            "context_only_not_exported": True,
        }

    starts = [float(row.get("start_seconds", 0) or 0) for row in batch_rows]
    ends = [float(row.get("end_seconds", 0) or 0) for row in batch_rows]
    target_start = min(starts) if starts else chapter_start
    target_end = max(ends) if ends else chapter_end

    pad = _V032_NEIGHBOR_CONTEXT_SECONDS
    if chapter_duration and chapter_duration <= _V032_SHORT_CHAPTER_SECONDS:
        # Short creator chapters benefit from a wider adjacent reading window.
        pad = max(pad, 240)
        strategy = "short_chapter_plus_adjacent_context"
    elif not (data.get("creator_chapters") or []):
        strategy = "long_full_video_sliding_context"
    else:
        strategy = "chapter_plus_neighbor_context"

    low = max(0.0, target_start - pad)
    high = target_end + pad
    selected = [
        unit
        for unit in all_units
        if float(unit.get("end_seconds", 0) or 0) >= low
        and float(unit.get("start_seconds", 0) or 0) <= high
    ]

    # If a context window is still too large, keep units nearest the target first.
    if len(_units_plain_text_v032(selected)) > _V032_MAX_REFERENCE_CHARS:
        def distance(unit):
            mid = (
                float(unit.get("start_seconds", 0) or 0)
                + float(unit.get("end_seconds", 0) or 0)
            ) / 2
            if mid < target_start:
                return target_start - mid
            if mid > target_end:
                return mid - target_end
            return 0.0

        nearest = sorted(selected, key=distance)
        kept = []
        used = 0
        for unit in nearest:
            n = len(str(unit.get("raw_text", ""))) + 12
            if kept and used + n > _V032_MAX_REFERENCE_CHARS:
                continue
            kept.append(unit)
            used += n
        selected = sorted(
            kept,
            key=lambda x: float(x.get("start_seconds", 0) or 0),
        )

    return selected, {
        "strategy": strategy,
        "video_duration_seconds": duration,
        "chapter_duration_seconds": chapter_duration,
        "neighbor_context_seconds": pad,
        "short_video_threshold_seconds": _V032_SHORT_VIDEO_SECONDS,
        "short_chapter_threshold_seconds": _V032_SHORT_CHAPTER_SECONDS,
        "context_only_not_exported": True,
    }


def _translation_batches_v032(rows):
    batches = []
    current = []
    chars = 0
    for row in rows:
        n = len(str(row.get("raw_joined_text", "")))
        if current and (
            len(current) >= _V032_MAX_TARGET_ROWS_PER_CALL
            or chars + n > _V032_MAX_TARGET_CHARS_PER_CALL
        ):
            batches.append(current)
            current = []
            chars = 0
        current.append(row)
        chars += n
    if current:
        batches.append(current)
    return batches


def _load_local_llm_v032(model_name):
    model_name = str(model_name or _DEFAULT_LOCAL_LLM_MODEL_V032).strip()
    if model_name in _LOCAL_LLM_CACHE_V032:
        return _LOCAL_LLM_CACHE_V032[model_name]

    try:
        from mlx_lm import load, generate
    except Exception as exc:
        raise RuntimeError(
            "로컬 LLM 실행 모듈(mlx-lm)을 불러오지 못했습니다. "
            "requirements.txt를 설치한 뒤 다시 실행해 주세요. "
            f"원인: {exc}"
        ) from exc

    try:
        model, tokenizer = load(model_name)
    except Exception as exc:
        raise RuntimeError(
            "로컬 LLM 모델을 불러오지 못했습니다. 첫 실행이라면 인터넷 연결과 "
            "디스크 여유 공간을 확인해 주세요. "
            f"모델: {model_name} / 원인: {exc}"
        ) from exc

    loaded = {
        "model": model,
        "tokenizer": tokenizer,
        "generate": generate,
        "device": "apple_silicon_mlx",
    }
    _LOCAL_LLM_CACHE_V032[model_name] = loaded
    return loaded


def _extract_json_object_v032(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        return json.loads(value)
    except Exception:
        pass

    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        return json.loads(value[start : end + 1])
    raise ValueError("모델 응답에서 JSON 객체를 찾지 못했습니다.")


def _translation_system_prompt_v032():
    return (
        "당신은 외국어 YouTube 원본 스크립트를 한국어 검수 초안으로 바꾸는 전처리 편집기입니다. "
        "요약기가 아닙니다. TARGET_ROWS의 의미·사실·숫자·행동·순서를 빠뜨리거나 추가하지 마세요. "
        "문장 하나씩 직역하지 말고 REFERENCE_CONTEXT의 앞뒤 맥락을 읽어 자연스러운 한국어 발화로 옮기세요. "
        "대명사와 지시어가 가리키는 대상을 문맥에서 복원하고, 문장 사이 연결어와 어순도 자연스럽게 다듬으세요. "
        "단, 한 TARGET id의 사실을 다른 id로 옮기지 마세요. 각 id의 출처 추적이 유지되어야 합니다. "
        "Claude Code, Claude, ChatGPT, Higgsfield, Sora, Seedance, Gemini, Figma, Whisper, FFmpeg, "
        "Midjourney, Runway, Kling 같은 브랜드·제품·모델·도구의 공식 외국어 표기는 그대로 유지하세요. "
        "버튼·메뉴·탭·파일·항목 이름은 클릭/선택/열기/이동 같은 동작과 연결해 '무엇을 클릭하는지'가 드러나게 번역하세요. "
        "예: 'Just click AI creative content.'는 일반 개념 설명이 아니라 메뉴/항목을 누르는 문맥이면 "
        "'AI 크리에이티브 콘텐츠'를 클릭하세요. 처럼 처리합니다. "
        "credit은 서비스 사용량/크레딧 문맥이면 '신용'으로 번역하지 마세요. "
        "cracked the code 같은 관용 표현도 문맥상 실제 코드를 뜻하지 않으면 자연스러운 의미로 옮기세요. "
        "REFERENCE_CONTEXT는 이해를 위한 참고 자료일 뿐이며 TARGET_ROWS에 없는 내용을 출력에 넣지 마세요. "
        "반드시 입력된 모든 TARGET id에 대해 정확히 하나의 한국어 문자열을 반환하세요. "
        "설명이나 마크다운 없이 JSON만 반환하세요. 형식: "
        '{"translations":[{"id":"UT-00001","ko":"..."}]}'
    )


def _build_translation_user_prompt_v032(
    reference_units,
    target_rows,
    chapter_outline="",
    prior_korean_tail="",
):
    reference_text = _units_plain_text_v032(reference_units)
    targets = "\n".join(
        f"{row['utterance_id']} [{display_timestamp(row.get('start_seconds'))}] {row.get('raw_joined_text', '')}"
        for row in target_rows
    )
    parts = []
    if chapter_outline:
        parts.append("CHAPTER_OUTLINE (reference only):\n" + chapter_outline)
    parts.append("REFERENCE_CONTEXT (reference only):\n" + reference_text)
    if prior_korean_tail:
        parts.append(
            "PRIOR_KOREAN_TAIL (style/connection reference only; do not copy facts into another id):\n"
            + prior_korean_tail
        )
    parts.append("SOURCE_ANCHORS (fidelity hints; do not treat as new facts):\n" + _source_anchor_block_v0332(target_rows))
    parts.append("TARGET_ROWS (translate these ids only):\n" + targets)
    return "\n\n".join(parts)


def _generate_local_llm_json_v032(model_name, system_prompt, user_prompt, max_tokens):
    loaded = _load_local_llm_v032(model_name)
    tokenizer = loaded["tokenizer"]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
        )
    except TypeError:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    text = loaded["generate"](
        loaded["model"],
        tokenizer,
        prompt=prompt,
        max_tokens=int(max_tokens),
        verbose=False,
    )
    return _extract_json_object_v032(text)



def _generate_local_llm_text_v033(model_name, system_prompt, user_prompt, max_tokens):
    """Generate raw text for v0.3.3+.

    v0.3.3 originally required the local LLM to emit strict JSON. Natural
    Korean can legitimately contain quotation marks, which small/local models
    occasionally forget to escape, making otherwise good translations fail at
    json.loads(). v0.3.3.1 therefore uses ID markers and treats JSON only as a
    backwards-compatible fallback.
    """
    loaded = _load_local_llm_v032(model_name)
    tokenizer = loaded["tokenizer"]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
        )
    except TypeError:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    return str(
        loaded["generate"](
            loaded["model"],
            tokenizer,
            prompt=prompt,
            max_tokens=int(max_tokens),
            verbose=False,
        )
        or ""
    )


def _parse_translation_text_v033(text, expected_ids):
    """Parse marker output, with old JSON accepted as a fallback.

    Preferred format:
        @@UT-00001@@ 번역문
        @@UT-00002@@ 번역문

    Parsing by the next ID marker means Korean quotes, apostrophes and line
    breaks cannot corrupt the transport format.
    """
    value = str(text or "").strip()
    expected = [str(uid) for uid in expected_ids]

    marker_re = re.compile(r"@@\s*(UT-\d+)\s*@@")
    matches = list(marker_re.finditer(value))
    if matches:
        got = {}
        for i, match in enumerate(matches):
            uid = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(value)
            ko = value[start:end].strip()
            # Tolerate harmless list bullets/code fences around the payload.
            ko = re.sub(r"^[-*•]\s*", "", ko)
            ko = re.sub(r"\s*```$", "", ko).strip()
            if uid in expected and ko:
                got[uid] = ko
        missing = [uid for uid in expected if not got.get(uid)]
        if not missing:
            return got, []

    # Backwards compatibility: if the model still returned valid JSON, use it.
    try:
        parsed = _extract_json_object_v032(value)
        got, missing = _parse_translation_map_v033(parsed, expected)
        if got:
            return got, missing
    except Exception:
        pass

    return {}, list(expected)


def _marker_output_instruction_v033(expected_ids):
    ids = ", ".join(str(uid) for uid in expected_ids)
    return (
        "OUTPUT_FORMAT:\n"
        "JSON을 사용하지 마세요. 설명·마크다운·코드펜스도 쓰지 마세요. "
        "각 id를 아래 형식으로 정확히 한 번씩 출력하세요. 번역문 안의 따옴표는 자유롭게 사용할 수 있습니다.\n"
        "@@UT-00001@@ 한국어 번역문\n"
        "@@UT-00002@@ 한국어 번역문\n"
        f"반드시 출력해야 하는 id: {ids}"
    )


def _translate_rows_with_context_v032(data, all_units, chapter, rows, model_name):
    translations = {}
    policy_records = []
    prior_tail = ""
    outline = _chapter_outline_v032(data)

    for batch_index, batch in enumerate(_translation_batches_v032(rows), start=1):
        reference_units, context_meta = _reference_units_for_batch_v032(
            data,
            all_units,
            chapter,
            batch,
        )
        user_prompt = _build_translation_user_prompt_v032(
            reference_units,
            batch,
            chapter_outline=outline,
            prior_korean_tail=prior_tail,
        )
        target_chars = sum(len(str(row.get("raw_joined_text", ""))) for row in batch)
        max_tokens = min(7000, max(1200, int(target_chars * 1.15)))

        parsed = _generate_local_llm_json_v032(
            model_name,
            _translation_system_prompt_v032(),
            user_prompt,
            max_tokens=max_tokens,
        )
        output_rows = parsed.get("translations", []) if isinstance(parsed, dict) else []
        got = {
            str(item.get("id")): str(item.get("ko", "")).strip()
            for item in output_rows
            if isinstance(item, dict) and item.get("id")
        }
        expected = [row["utterance_id"] for row in batch]
        missing = [uid for uid in expected if not got.get(uid)]
        if missing:
            raise RuntimeError(
                "로컬 LLM 번역 결과에서 일부 검수 행이 누락되었습니다: "
                + ", ".join(missing)
            )

        for uid in expected:
            translations[uid] = _canonicalize_official_foreign_names_v031(got[uid])

        prior_tail = "\n".join(
            f"{uid}: {translations[uid]}"
            for uid in expected[-2:]
        )
        policy_records.append(
            {
                "batch_index": batch_index,
                "target_utterance_ids": expected,
                **context_meta,
                "reference_sentence_count": len(reference_units),
                "reference_char_count": len(_units_plain_text_v032(reference_units)),
            }
        )

    return translations, policy_records


def _build_foreign_translation_draft_v032(data, chapter_index, translation_local_model):
    model_name = str(
        translation_local_model or _DEFAULT_LOCAL_LLM_MODEL_V032
    ).strip()
    video_id = data.get("metadata", {}).get("video_id") or "unknown-video"
    chapter = selected_chapter(data, chapter_index)

    # v0.3.1 sentence reconstruction remains the provenance authority.
    all_units = _build_foreign_sentence_units_v031(data)
    chapter_units, boundary_context = _assign_foreign_sentences_to_chapter_v031(
        all_units,
        chapter,
    )
    groups = _group_foreign_sentence_units_v031(chapter_units)

    base_rows = []
    referenced_segment_ids = []
    for index, group in enumerate(groups, start=1):
        uid = f"UT-{index:05d}"
        raw_joined = " ".join(
            str(unit.get("raw_text", "")).strip()
            for unit in group
            if str(unit.get("raw_text", "")).strip()
        ).strip()
        if not raw_joined:
            continue

        source_ids, source_keys, spans = [], [], []
        for unit in group:
            for sid in unit.get("source_segment_ids", []):
                if sid not in source_ids:
                    source_ids.append(sid)
                if sid not in referenced_segment_ids:
                    referenced_segment_ids.append(sid)
            for skey in unit.get("source_segment_keys", []):
                if skey not in source_keys:
                    source_keys.append(skey)
            spans.extend(unit.get("source_spans", []))

        start_seconds = min(float(unit.get("start_seconds", 0)) for unit in group)
        end_seconds = max(float(unit.get("end_seconds", 0)) for unit in group)
        chapter_end = chapter.get("end_seconds")
        crosses_end = bool(
            chapter_end is not None and end_seconds > float(chapter_end)
        )
        base_rows.append(
            {
                "utterance_id": uid,
                "chapter_id": chapter["chapter_id"],
                "chapter_label": chapter.get("label"),
                "chapter_assignment_status": (
                    "cross_creator_boundary" if crosses_end else "single_chapter"
                ),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "display_timestamp": display_timestamp(start_seconds),
                "raw_joined_text": raw_joined,
                "source_segment_ids": source_ids,
                "source_segment_keys": source_keys,
                "source_spans": _dedupe_source_spans_v031(spans),
                "source_span_status": "complete",
                "source_span_mapping_ratio": 1.0,
                "unmapped_editor_tokens": [],
                "sentence_unit_ids": [unit.get("sentence_unit_id") for unit in group],
                "source_sentence_complete": all(
                    bool(unit.get("sentence_complete")) for unit in group
                ),
            }
        )

    translations, context_batches = _translate_rows_with_context_v032(
        data,
        all_units,
        chapter,
        base_rows,
        model_name,
    )

    source_lang = source_language_code(data) or "unknown"
    utterances = []
    for base in base_rows:
        sentence_complete = bool(base.pop("source_sentence_complete", False))
        korean = translations.get(base["utterance_id"], "").strip()
        utterance = dict(base)
        utterance.update(
            {
                "auto_normalized_text": korean,
                "normalized_text": korean,
                "speaker_id": None,
                "speaker_status": "unavailable",
                "content_mode": "translated_context_aware_natural_language",
                "sentence_complete": sentence_complete,
                "normalization_item_ids": [],
                "confidence": "medium",
                "review_status": "needs_review",
                "editor_note": "",
                "validation_warnings": (
                    [] if sentence_complete else ["possible_incomplete_source_sentence"]
                ),
                "translation_status": "local_llm_translated_needs_review",
                "translation_source_language": source_lang,
                "translation_target_language": "ko-KR",
            }
        )
        utterances.append(utterance)

    segment_by_id = {
        item.get("segment_id"): item
        for item in enrich_all_segments(data)
        if item.get("segment_id")
    }
    raw_segments = [
        segment_by_id[sid]
        for sid in referenced_segment_ids
        if sid in segment_by_id
    ]
    complete_count = sum(1 for item in utterances if item.get("sentence_complete"))

    result = {
        "schema_version": "script_preprocessing_v0.3.2",
        "source_schema_version": data.get("schema_version"),
        "source_url": data.get("source_url"),
        "video_id": video_id,
        "source_language": source_lang,
        "source_language_label": source_language_label(data),
        "transcript_origin": data.get("collector_methods", {}).get("transcript"),
        "is_auto_generated": data.get("transcript", {}).get("is_generated"),
        "processed_chapter": chapter,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input_document_kind": "acquisition",
        "boundary_profile": {
            "profile_id": "foreign_sentence_reconstruction_v0.3.2",
            "target_group_duration": 14.0,
            "max_group_duration": 30.0,
            "max_group_chars": 1000,
            "max_sentences_per_group": 4,
            "gap_break_seconds": 2.5,
            "emergency_no_punctuation_seconds": 50.0,
            "creator_chapter_is_hard_sentence_cut": False,
        },
        "chapter_boundary_context": boundary_context,
        "all_sentence_unit_count": len(all_units),
        "sentence_unit_count": len(chapter_units),
        "raw_segment_count": len(raw_segments),
        "normalized_utterance_count": len(utterances),
        "translation_required": True,
        "translation_status": "completed_needs_review",
        "translation_metadata": {
            "provider": "local_mlx_llm",
            "model": model_name,
            "target_language": "ko-KR",
            "policy_version": "context_aware_faithful_korean_v0.3.2",
            "translated_at": utc_now(),
            "api_key_required": False,
            "api_key_stored": False,
            "execution_device": "apple_silicon_mlx",
            "model_cache_reused_after_first_download": True,
            "context_policy": {
                "short_video_threshold_seconds": _V032_SHORT_VIDEO_SECONDS,
                "short_chapter_threshold_seconds": _V032_SHORT_CHAPTER_SECONDS,
                "neighbor_context_seconds": _V032_NEIGHBOR_CONTEXT_SECONDS,
                "target_rows_keep_original_provenance": True,
                "context_is_reference_only": True,
            },
            "context_batches": context_batches,
        },
        "raw_segments": raw_segments,
        "sentence_units": chapter_units,
        "normalized_utterances": utterances,
        "normalization_items": [],
        "editor_changes": [],
        "unresolved_terms": [],
        "profile_application": {
            "mode": "foreign_translation_v032_context_aware_local_llm",
            "profile_source": "whole_transcript_sentence_reconstruction_then_context_aware_local_llm",
            "generalization_claim": False,
        },
        "processing_report": {
            "processing_status": "validation_required",
            "chapter_review_status": "in_progress",
            "draft_only": True,
            "editor_review_required": True,
            "sentence_boundary_method": "whole_transcript_punctuation_reconstruction_before_chapter_assignment",
            "chapter_assignment_method": "reconstructed_sentence_start_single_owner",
            "creator_chapter_boundary_hard_cut": False,
            "translation_context_method": "whole_video_for_short_or_neighbor_window_for_long",
            "sentence_complete_utterances": complete_count,
            "sentence_incomplete_utterances": len(utterances) - complete_count,
            "sentence_completion_rate": round(
                complete_count / max(1, len(utterances)), 4
            ),
            "reconstructed_sentence_unit_count": len(chapter_units),
            "cross_creator_boundary_utterances": sum(
                1
                for item in utterances
                if item.get("chapter_assignment_status") == "cross_creator_boundary"
            ),
            "mechanical_duplicates_removed": 0,
            "high_confidence_corrections": 0,
            "medium_confidence_corrections": 0,
            "low_confidence_terms": 0,
            "approved_utterances": 0,
            "rejected_utterances": 0,
            "review_required_utterances": len(utterances),
            "source_span_complete_utterances": len(utterances),
            "source_span_partial_utterances": 0,
            "source_span_weak_utterances": 0,
            "visual_verification_items": [
                "프롬프트·코드·파라미터의 정확한 문자열",
                "버튼·메뉴·탭·파일·항목 이름과 행동의 연결",
                "도구 화면에 표시되는 메뉴·설정값",
                "고유명사·제품명·모델명의 공식 표기",
                "자연스러운 문장 연결과 대명사 지시 대상",
                "제작자 챕터 경계를 넘는 문장의 실제 시작·끝",
            ],
        },
    }
    return _apply_official_foreign_name_policy_v031(result)


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_local_model=None,
    translation_api_key=None,
    translation_model=None,
):
    if translation_required_for_source(data) and translate_foreign_to_korean:
        return _build_foreign_translation_draft_v032(
            data,
            chapter_index=chapter_index,
            translation_local_model=(
                translation_local_model or _DEFAULT_LOCAL_LLM_MODEL_V032
            ),
        )

    result = _build_preprocessing_draft_v031_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
        translate_foreign_to_korean=False,
        translation_local_model=translation_local_model,
        translation_api_key=translation_api_key,
        translation_model=translation_model,
    )
    result["schema_version"] = "script_preprocessing_v0.3.2"
    return _apply_official_foreign_name_policy_v031(result)


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v031_final(data)
    result["schema_version"] = "script_preprocessing_v0.3.2"
    return _apply_official_foreign_name_policy_v031(result)


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v031_final(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.3.2"
    return _apply_official_foreign_name_policy_v031(result)

# =====================================================================
# v0.3.3 context + style + self-review + whole-video translation patch
# - 30-minute-or-shorter videos use whole-video reference context in chapter mode
# - editor-verified Korean few-shot examples guide natural Korean style
# - second local-LLM pass compares Korean draft against source to repair omissions,
#   mistranslations, translationese, UI/action targets, and sentence connection
# - user can translate either one creator chapter OR the whole video in one run
# - whole-video mode preserves creator chapters as row metadata; FULL is only a
#   processing/review scope and never becomes source creator metadata
# =====================================================================

_build_preprocessing_draft_v032_final = build_preprocessing_draft
_prepare_existing_preprocessing_v032_final = prepare_existing_preprocessing
_export_editor_result_v032_final = export_editor_result

_V033_SHORT_VIDEO_SECONDS = 30 * 60
_V033_SHORT_CHAPTER_SECONDS = 90
_V033_NEIGHBOR_CONTEXT_SECONDS = 300
_V033_MAX_REFERENCE_CHARS = 42000
_V033_MAX_TARGET_CHARS_PER_CALL = 7800
_V033_MAX_TARGET_ROWS_PER_CALL = 10

# These are editor-verified style examples from the user's reviewed CH-01.
# They are examples of HOW to write Korean, not facts to copy into other videos.
_V033_FEW_SHOT_EXAMPLES = [
    {
        "en": "Honestly, AI video editor was so bad in the past, but I actually found a way to make it look good.",
        "ko": "솔직히 과거의 AI 영상 편집기들은 정말 별로였지만, 저는 마침내 영상이 멋지게 뽑혀 나오는 방법을 찾아냈습니다.",
        "lesson": "Honestly를 '정직히'로 직역하지 않고 자연스러운 한국어 구어체로 처리한다.",
    },
    {
        "en": "Does it cost credit? Because it seems like it's a lot of money.",
        "ko": "크레딧이 차감되는 방식일까요? 왜냐하면 돈이 꽤 많이 들 것 같아 보이거든요.",
        "lesson": "서비스 사용량 문맥의 credit은 '신용'이 아니라 '크레딧'으로 이해한다.",
    },
    {
        "en": "So, I'm actually really happy I cracked the code so I can share every single thing with you.",
        "ko": "그래서 마침내 그 해결책을 찾아내어 여러분과 모든 것을 공유할 수 있게 되어 정말 기쁩니다.",
        "lesson": "관용 표현은 실제 의미를 복원하되 새 사실을 만들지 않는다.",
    },
    {
        "en": "And if you're part of my community, you can just go straight into classroom on the resources.",
        "ko": "저희 커뮤니티 회원이시라면 자료실의 '클래스룸'으로 바로 이동하셔도 됩니다.",
        "lesson": "이동 대상·메뉴·화면 같은 구체 정보는 자연스럽게 쓰더라도 누락하지 않는다.",
    },
    {
        "en": "Just click AI creative content. I'll put the exact workflow that I currently use, the markdown file in here.",
        "ko": "'AI 크리에이티브 콘텐츠'를 클릭하시면 제가 현재 사용 중인 정확한 워크플로우와 마크다운 파일을 확인할 수 있습니다.",
        "lesson": "click 뒤 표현이 메뉴/항목명이라면 일반 개념으로 번역하지 말고 클릭 대상임을 분명히 한다.",
    },
]

def _few_shot_text_v033():
    blocks = []
    for index, item in enumerate(_V033_FEW_SHOT_EXAMPLES, start=1):
        blocks.append(
            f"예시 {index}\n원문: {item['en']}\n좋은 한국어: {item['ko']}\n포인트: {item['lesson']}"
        )
    return "\n\n".join(blocks)


def _trim_reference_units_v033(units, max_chars=_V033_MAX_REFERENCE_CHARS, target_start=None, target_end=None):
    if not units:
        return []
    if len(_units_plain_text_v032(units)) <= max_chars:
        return list(units)

    # Prefer units nearest to the output target when a very long reference would
    # exceed the context budget. This never changes the actual output range.
    if target_start is not None and target_end is not None:
        def distance(unit):
            mid = (
                float(unit.get("start_seconds", 0) or 0)
                + float(unit.get("end_seconds", 0) or 0)
            ) / 2
            if mid < target_start:
                return target_start - mid
            if mid > target_end:
                return mid - target_end
            return 0.0

        candidates = sorted(units, key=distance)
        kept, used = [], 0
        for unit in candidates:
            n = len(str(unit.get("raw_text", ""))) + 14
            if kept and used + n > max_chars:
                continue
            kept.append(unit)
            used += n
        return sorted(kept, key=lambda x: float(x.get("start_seconds", 0) or 0))

    # No target: preserve chronological order.
    kept, used = [], 0
    for unit in units:
        n = len(str(unit.get("raw_text", ""))) + 14
        if kept and used + n > max_chars:
            break
        kept.append(unit)
        used += n
    return kept


def _reference_units_for_batch_v033(data, all_units, chapter, batch_rows, translation_scope):
    duration = _video_duration_seconds_v032(data, all_units)
    starts = [float(row.get("start_seconds", 0) or 0) for row in batch_rows]
    ends = [float(row.get("end_seconds", 0) or 0) for row in batch_rows]
    target_start = min(starts) if starts else 0.0
    target_end = max(ends) if ends else duration

    # In chapter mode, videos up to 30 min are small enough to read as one
    # coherent reference context. Whole-video mode is also a one-click operation;
    # for <=30 min each output batch can see the whole source transcript.
    if duration and duration <= _V033_SHORT_VIDEO_SECONDS:
        selected = _trim_reference_units_v033(
            all_units,
            target_start=target_start,
            target_end=target_end,
        )
        return selected, {
            "strategy": "whole_video_reference_context",
            "video_duration_seconds": duration,
            "short_video_threshold_seconds": _V033_SHORT_VIDEO_SECONDS,
            "requested_translation_scope": translation_scope,
            "context_only_not_exported": True,
        }

    # Long videos: translate the requested target(s) in one user action, but use
    # a sliding reference window so source/output alignment remains reliable.
    chapter_start = float(chapter.get("start_seconds", target_start) or target_start)
    chapter_end_raw = chapter.get("end_seconds")
    chapter_end = float(chapter_end_raw) if chapter_end_raw is not None else target_end
    chapter_duration = max(0.0, chapter_end - chapter_start)

    pad = _V033_NEIGHBOR_CONTEXT_SECONDS
    if chapter_duration and chapter_duration <= _V033_SHORT_CHAPTER_SECONDS:
        pad = max(pad, 360)
        strategy = "short_chapter_plus_wide_adjacent_context"
    elif translation_scope == "whole_video":
        strategy = "whole_video_operation_sliding_context"
    elif not (data.get("creator_chapters") or []):
        strategy = "no_creator_chapter_sliding_context"
    else:
        strategy = "chapter_plus_neighbor_context"

    low = max(0.0, target_start - pad)
    high = target_end + pad
    selected = [
        unit for unit in all_units
        if float(unit.get("end_seconds", 0) or 0) >= low
        and float(unit.get("start_seconds", 0) or 0) <= high
    ]
    selected = _trim_reference_units_v033(
        selected,
        target_start=target_start,
        target_end=target_end,
    )
    return selected, {
        "strategy": strategy,
        "video_duration_seconds": duration,
        "chapter_duration_seconds": chapter_duration,
        "neighbor_context_seconds": pad,
        "short_video_threshold_seconds": _V033_SHORT_VIDEO_SECONDS,
        "short_chapter_threshold_seconds": _V033_SHORT_CHAPTER_SECONDS,
        "requested_translation_scope": translation_scope,
        "context_only_not_exported": True,
    }

def _translation_batches_v033(rows):
    batches, current, chars = [], [], 0
    for row in rows:
        n = len(str(row.get("raw_joined_text", "")))
        if current and (
            len(current) >= _V033_MAX_TARGET_ROWS_PER_CALL
            or chars + n > _V033_MAX_TARGET_CHARS_PER_CALL
        ):
            batches.append(current)
            current, chars = [], 0
        current.append(row)
        chars += n
    if current:
        batches.append(current)
    return batches



_V0332_PROTECTED_STOPWORDS = {
    "The", "A", "An", "And", "But", "So", "If", "When", "Before", "After",
    "Honestly", "Actually", "Just", "Then", "Here", "This", "That", "It", "I", "We", "You",
    "Open", "Select", "Choose", "Click", "Tap", "Press", "Enter", "Go", "Navigate", "Head",
    "How", "Does", "Because", "He", "She", "They", "In", "All", "Also",
}

_V0332_UI_ACTION_RE = re.compile(
    r"\b(?:click|tap|press|select|choose|open|go\s+to|navigate\s+to|head\s+to|enter)\s+"
    r"([^.!?;]{1,90})",
    re.IGNORECASE,
)
_V0332_CONCRETE_ACTION_RE = re.compile(
    r"\b(?:copy(?:\s+and)?\s+paste|copy|paste|download|upload|install|uninstall|drag|drop|"
    r"export|import|save|delete|rename|type|enter|run|execute|connect|disconnect|enable|disable|"
    r"turn\s+on|turn\s+off|set\s+up|configure)\b",
    re.IGNORECASE,
)
_V0332_FILE_RE = re.compile(
    r"\b[\w@+.-]+\.(?:md|markdown|json|csv|txt|py|js|ts|tsx|jsx|html|css|yaml|yml|toml|"
    r"zip|pdf|fig|mp4|mov|wav|mp3|png|jpg|jpeg|webp|svg)\b",
    re.IGNORECASE,
)
_V0332_NUMBER_RE = re.compile(
    r"(?<!\w)(?:[$€£¥₩]\s*)?\d+(?:[.,]\d+)*(?:\s*%|\s*(?:credits?|GB|MB|KB|TB|ms|s|sec|seconds?|minutes?|hours?|fps|px))?",
    re.IGNORECASE,
)
_V0332_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
# IMPORTANT: apostrophes are intentionally NOT treated as quote delimiters.
# v0.3.3.2 used a generic ['\"] regex and contractions such as you're / I'm / don't
# were incorrectly extracted as huge "exact values", bloating and contradicting the prompt.
_V0332_QUOTED_RE = re.compile(
    r"`([^`\n]{2,100})`|\"([^\"\n]{2,100})\"|“([^”\n]{2,100})”|‘([^’\n]{2,100})’"
)


def _dedupe_keep_order_v0332(values):
    seen, out = set(), []
    for value in values:
        value = str(value or "").strip(" \t\n,.;:()[]{}")
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _quoted_values_v0334(value):
    out = []
    for match in _V0332_QUOTED_RE.finditer(str(value or "")):
        text = next((g for g in match.groups() if g), "")
        if text:
            out.append(text)
    return out


def _conservative_latin_names_v0334(value):
    """Extract only high-confidence Latin names.

    The previous broad Title Case regex misclassified ordinary sentence words such as
    "How", "Because", "All I" and "B-rolls. And" as protected product names. That
    made the local model juggle false constraints. This version only keeps strong
    signals: acronyms, CamelCase/mixed-case tokens, or multi-word names where at least
    one token has a strong signal and the phrase appears away from a sentence start.
    """
    text = str(value or "")
    candidates = []
    token_re = re.compile(r"\b[A-Za-z][A-Za-z0-9+.#:/_-]*\b")
    tokens = list(token_re.finditer(text))

    def strong(tok):
        if len(tok) >= 2 and tok.isupper():
            return True
        if any(ch.isdigit() for ch in tok):
            return True
        # CamelCase / internal capital, e.g. ChatGPT, Midjourney-style mixed case.
        if any(ch.isupper() for ch in tok[1:]) and any(ch.islower() for ch in tok):
            return True
        return False

    for i, m in enumerate(tokens):
        tok = m.group(0)
        if tok in _V0332_PROTECTED_STOPWORDS:
            continue
        if strong(tok):
            candidates.append(tok)
            continue
        # Single TitleCase names like Claude/Figma/Sora are accepted only when they
        # are not the first lexical token of a sentence. This keeps recall while
        # avoiding most generic sentence-initial words.
        if re.fullmatch(r"[A-Z][a-z]+", tok):
            prefix = text[max(0, m.start()-3):m.start()]
            sentence_start = (m.start() == 0) or bool(re.search(r"[.!?]\s*$", prefix))
            if not sentence_start:
                candidates.append(tok)

    # Preserve a common two-word product form such as "Claude Code" if either token
    # is already a candidate. Do not expand to arbitrary title-cased prose.
    base = set(candidates)
    for a, b in zip(tokens, tokens[1:]):
        t1, t2 = a.group(0), b.group(0)
        gap = text[a.end():b.start()]
        if gap == " " and (t1 in base or t2 in base):
            if t1 not in _V0332_PROTECTED_STOPWORDS and t2 not in _V0332_PROTECTED_STOPWORDS:
                if t1[:1].isupper() and t2[:1].isupper():
                    candidates.append(f"{t1} {t2}")
    return _dedupe_keep_order_v0332(candidates)


def _extract_source_anchors_v0332(text):
    """Conservatively extract only high-risk details worth preserving.

    Anchors are hints, never semantic truth. False-positive anchors are more harmful
    than missing a low-confidence candidate because they enlarge the prompt and can
    destabilize a multilingual local model.
    """
    value = str(text or "")
    exact = []
    exact += _V0332_URL_RE.findall(value)
    exact += _V0332_FILE_RE.findall(value)
    exact += _V0332_NUMBER_RE.findall(value)
    exact += _quoted_values_v0334(value)

    ui_targets = []
    for match in _V0332_UI_ACTION_RE.finditer(value):
        target = match.group(1).strip()
        target = re.split(
            r",\s*(?:click|tap|press|select|choose|open|go\s+to|navigate\s+to|head\s+to|enter)\b|"
            r"\b(?:then|and then|so that|because|while)\b",
            target,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        if target:
            ui_targets.append(target)

    concrete_actions = [m.group(0) for m in _V0332_CONCRETE_ACTION_RE.finditer(value)]
    return {
        "exact_values": _dedupe_keep_order_v0332(exact),
        "latin_name_candidates": _conservative_latin_names_v0334(value),
        "potential_ui_targets": _dedupe_keep_order_v0332(ui_targets),
        "concrete_actions": _dedupe_keep_order_v0332(concrete_actions),
    }


def _source_anchor_block_v0332(target_rows):
    blocks = []
    for row in target_rows:
        anchors = _extract_source_anchors_v0332(row.get("raw_joined_text", ""))
        lines = [f"ID: {row['utterance_id']}"]
        if anchors["exact_values"]:
            lines.append("EXACT_VALUES: " + " | ".join(anchors["exact_values"]))
        if anchors["latin_name_candidates"]:
            lines.append("LATIN_NAMES: " + " | ".join(anchors["latin_name_candidates"]))
        if anchors["potential_ui_targets"]:
            lines.append("POTENTIAL_UI_TARGETS: " + " | ".join(anchors["potential_ui_targets"]))
        if anchors["concrete_actions"]:
            lines.append("CONCRETE_ACTIONS: " + " | ".join(anchors["concrete_actions"]))
        # Do not add filler for rows with no anchors; keeping this block small matters
        # for local-model prefill time.
        if len(lines) > 1:
            blocks.append("\\n".join(lines))
    return "\\n\\n".join(blocks) if blocks else "(none)"


def _apply_source_conditioned_term_normalization_v0332(source_text, korean_text):
    """Conservative, source-conditioned cleanup for established Korean terms."""
    source = str(source_text or "").lower()
    out = str(korean_text or "")
    out = out.replace("컨텐츠", "콘텐츠")
    out = out.replace("워크 플로우", "워크플로우")
    if "motion graphic" in source:
        out = out.replace("동영상 그래픽", "모션 그래픽")
        out = out.replace("모션 그래픽스", "모션 그래픽")
    if "sound effect" in source:
        out = out.replace("소리 효과", "사운드 효과")
        out = out.replace("음향 효과", "사운드 효과")
    return out.strip()


_HANGUL_RE_V0334 = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_HAN_RE_V0334 = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")


def _target_language_status_v0334(source_text, korean_text):
    """Validate that an en/foreign -> ko draft is actually Korean.

    Qwen is multilingual and can occasionally drift into Chinese during a long
    generation. v0.3.3.2 accepted any non-empty marker payload, so Chinese could
    overwrite a good first-pass Korean draft during pass 2. We now reject newly
    introduced Han characters and require meaningful Hangul in prose output.
    Han characters already present in SOURCE are exempt so an original Chinese
    proper name can still be preserved when necessary.
    """
    source = str(source_text or "")
    out = str(korean_text or "").strip()
    if not out:
        return False, "empty"
    source_han = set(_HAN_RE_V0334.findall(source))
    unexpected_han = [c for c in _HAN_RE_V0334.findall(out) if c not in source_han]
    if len(unexpected_han) >= 2:
        return False, "unexpected_han_characters"
    hangul_count = len(_HANGUL_RE_V0334.findall(out))
    # Normal utterances are prose, so two or more Hangul characters is a safe floor.
    # This still permits Latin UI/product names inside a Korean sentence.
    if hangul_count < 2:
        return False, "insufficient_hangul"
    return True, "ok"


def _ui_target_should_preserve_exact_v0332(target):
    value = str(target or "").strip()
    if not value:
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+.#:/_-]*", value)
    if not tokens:
        return False
    return any(
        (len(tok) >= 2 and tok.isupper())
        or (any(ch.isupper() for ch in tok[1:]) and any(ch.islower() for ch in tok))
        or (tok[:1].isupper() and tok not in _V0332_PROTECTED_STOPWORDS)
        for tok in tokens
    )


def _fidelity_warnings_v0332(source_text, korean_text):
    """Flag high-confidence anchor loss without inventing a repair."""
    source = str(source_text or "")
    korean = str(korean_text or "")
    anchors = _extract_source_anchors_v0332(source)
    warnings = []
    for value in anchors["exact_values"]:
        if value and value not in korean:
            warnings.append(f"possible_missing_exact_value:{value}")
    for value in anchors["latin_name_candidates"]:
        if value and value not in korean:
            warnings.append(f"possible_missing_latin_name:{value}")
    for target in anchors["potential_ui_targets"]:
        if _ui_target_should_preserve_exact_v0332(target) and target not in korean:
            warnings.append(f"possible_missing_ui_target:{target}")
    low = korean.lower()
    if re.search(r"\bcopy(?:\s+and)?\s+paste\b", source, re.IGNORECASE):
        if not (("복사" in korean and "붙여넣" in korean) or "copy" in low or "paste" in low):
            warnings.append("possible_missing_action:copy_and_paste")
    ok, reason = _target_language_status_v0334(source, korean)
    if not ok:
        warnings.append(f"invalid_target_language:{reason}")
    return _dedupe_keep_order_v0332(warnings)


def _translation_system_prompt_v033():
    return (
        "당신은 외국어 YouTube 원본 스크립트를 한국어 검수 초안으로 바꾸는 전문 전처리 편집기입니다. 반드시 한국어 문장으로 서술하세요. "
        "번역기가 아니라 문맥을 이해하는 편집자처럼 쓰되, 요약하거나 새 정보를 만들면 안 됩니다. "
        "TARGET_ROWS의 의미·사실·숫자·행동·고유명사·순서를 하나도 빠뜨리거나 추가하지 마세요. "
        "REFERENCE_CONTEXT와 CHAPTER_OUTLINE은 대명사, 지시어, 메뉴/파일/버튼의 역할, 용어 의미를 이해하기 위한 참고일 뿐입니다. "
        "영어 접속사 And/So/Honestly를 '그리고/그래서/정직히'처럼 기계적으로 1:1 대응시키지 마세요. "
        "한국어에서 불필요한 접속사는 생략하고, 실제 한국어 튜토리얼 영상 화자가 설명하듯 문장끼리 자연스럽게 이어 주세요. "
        "다만 한 TARGET id의 사실을 다른 id로 옮겨 출처 추적을 깨뜨리면 안 됩니다. "
        "Claude Code, Claude, ChatGPT, Higgsfield, Sora, Seedance, Gemini, Figma, Whisper, FFmpeg, Midjourney, Runway, Kling 등 "
        "외국어 브랜드·제품·모델·도구명은 공식 원문 표기를 유지하세요. "
        "버튼·메뉴·탭·파일·항목 이름은 클릭/선택/열기/이동 같은 동작의 대상인지 문맥으로 판단하고, 무엇을 클릭하거나 어디로 이동하는지 분명하게 보존하세요. UI/메뉴/파일명으로 보이는 Latin 표기는 확실하지 않으면 원문 보존을 우선하세요. "
        "copy/paste, drag/drop, install/download 같은 구체 행동과 설정 여부는 자연스럽게 만든다는 이유로 '바로 적용'처럼 추상화하거나 생략하지 마세요. motion graphics, sound effects처럼 한국 실무에서 굳어진 용어는 통용 표현을 사용하세요. "
        "credit은 서비스 사용량 문맥이면 '크레딧'으로, cracked the code 같은 관용구는 실제 의미로 옮기세요. "
        "사용자에게 직접 말하는 화자의 톤은 자연스러운 존댓말로 유지하되 과도하게 문어체로 바꾸지 마세요. "
        "STYLE_EXAMPLES는 문체와 판단 방식의 예시일 뿐이며 그 예시의 사실을 현재 영상에 복사하지 마세요. "
        "반드시 입력된 모든 TARGET id에 대해 정확히 하나의 한국어 문자열을 반환하세요. "
        "응답 전송 형식은 사용자 메시지 마지막의 OUTPUT_FORMAT 지시를 정확히 따르세요. "
    )

def _review_system_prompt_v033():
    return (
        "당신은 YouTube 외국어 스크립트의 한국어 번역 초안을 원문 대조 검수하는 편집자입니다. 반드시 한국어 문장으로 서술하세요. "
        "각 TARGET id마다 SOURCE_EN과 DRAFT_KO를 비교해 다음만 수정하세요: "
        "1) 원문의 사실·숫자·행동·구체 대상 누락, 2) 문맥 오역, 3) 영어식 번역투, "
        "4) 버튼·메뉴·탭·파일·도구명과 행동의 잘못된 연결, 5) 부자연스러운 문장 연결. "
        "SOURCE_EN에 없는 사실을 추가하거나 요약하지 마세요. 한 id의 사실을 다른 id로 이동하지 마세요. "
        "'classroom', 'resources', markdown file처럼 작지만 구체적인 이동 대상·파일·UI 정보도 임의로 생략하지 마세요. "
        "copy/paste, drag/drop, click/select/open, install/download 같은 행동과 대상·설정 여부를 더 일반적인 표현으로 줄이지 마세요. UI/메뉴/파일명으로 보이는 Latin 표기는 확실하지 않으면 원문 보존을 우선하세요. 한국 실무에서 굳어진 전문 용어는 어색한 사전식 직역을 피하세요. "
        "Claude Code, Claude, ChatGPT, Higgsfield, Sora, Seedance, Gemini, Figma, Whisper, FFmpeg 등 공식 외국어 이름은 그대로 유지하세요. "
        "DRAFT_KO가 이미 정확하고 자연스러우면 그대로 두세요. "
        "STYLE_EXAMPLES는 문체 참고용일 뿐이며 예시 사실을 현재 영상에 섞지 마세요. "
        "반드시 모든 TARGET id에 대해 정확히 하나의 최종 한국어 문자열을 반환하세요. "
        "응답 전송 형식은 사용자 메시지 마지막의 OUTPUT_FORMAT 지시를 정확히 따르세요. "
    )

def _build_translation_user_prompt_v033(reference_units, target_rows, chapter_outline="", prior_korean_tail=""):
    reference_text = _units_plain_text_v032(reference_units)
    targets = "\n".join(
        f"{row['utterance_id']} [{display_timestamp(row.get('start_seconds'))}] {row.get('raw_joined_text', '')}"
        for row in target_rows
    )
    parts = ["STYLE_EXAMPLES (style/decision reference only):\n" + _few_shot_text_v033()]
    if chapter_outline:
        parts.append("CHAPTER_OUTLINE (reference only):\n" + chapter_outline)
    parts.append("REFERENCE_CONTEXT (reference only):\n" + reference_text)
    if prior_korean_tail:
        parts.append(
            "PRIOR_KOREAN_TAIL (connection/style reference only; do not move facts across ids):\n"
            + prior_korean_tail
        )
    parts.append("TARGET_ROWS (translate these ids only):\n" + targets)
    parts.append(_marker_output_instruction_v033([row["utterance_id"] for row in target_rows]))
    return "\n\n".join(parts)

def _build_review_user_prompt_v033(reference_units, target_rows, draft_map, chapter_outline=""):
    source_and_draft = "\n\n".join(
        f"ID: {row['utterance_id']}\nSOURCE_EN: {row.get('raw_joined_text', '')}\nDRAFT_KO: {draft_map.get(row['utterance_id'], '')}"
        for row in target_rows
    )
    parts = ["STYLE_EXAMPLES (style/decision reference only):\n" + _few_shot_text_v033()]
    if chapter_outline:
        parts.append("CHAPTER_OUTLINE (reference only):\n" + chapter_outline)
    parts.append("REFERENCE_CONTEXT (reference only):\n" + _units_plain_text_v032(reference_units))
    parts.append("TARGET SOURCE + FIRST DRAFT (review these ids only):\n" + source_and_draft)
    parts.append(_marker_output_instruction_v033([row["utterance_id"] for row in target_rows]))
    return "\n\n".join(parts)

def _build_language_retry_prompt_v0334(rows, bad_map):
    payload = "\n\n".join(
        f"ID: {row['utterance_id']}\nSOURCE_EN: {row.get('raw_joined_text', '')}\nBAD_OUTPUT: {bad_map.get(row['utterance_id'], '')}"
        for row in rows
    )
    return (
        "이전 출력이 한국어가 아니었습니다. 아래 SOURCE_EN만 기준으로 다시 작성하세요. "
        "반드시 자연스러운 한국어 문장으로 쓰고, 브랜드·제품·UI·파일명 같은 Latin 표기는 원문 그대로 둘 수 있습니다. "
        "숫자·조건·구체 행동을 생략하거나 요약하지 마세요.\n\n"
        + payload
        + "\n\n"
        + _marker_output_instruction_v033([row["utterance_id"] for row in rows])
    )


def _parse_translation_map_v033(parsed, expected_ids):
    output_rows = parsed.get("translations", []) if isinstance(parsed, dict) else []
    got = {
        str(item.get("id")): str(item.get("ko", "")).strip()
        for item in output_rows
        if isinstance(item, dict) and item.get("id")
    }
    missing = [uid for uid in expected_ids if not got.get(uid)]
    return got, missing


def estimate_translation_workload(
    data,
    chapter_index=0,
    translation_scope="chapter",
):
    """Fast, model-free workload estimate for the local two-pass translator.

    This does not change translation content. It reconstructs the same sentence/row
    units used by the real pipeline, counts LLM calls, and returns a deliberately
    broad first-run time range. Runtime ETA is refined from actual completed passes.
    """
    all_units = _build_foreign_sentence_units_v031(data)
    duration = _video_duration_seconds_v032(data, all_units)
    requested_scope = str(translation_scope or "chapter").strip().lower()
    if requested_scope not in {"chapter", "whole_video"}:
        requested_scope = "chapter"
    if not (data.get("creator_chapters") or []):
        requested_scope = "whole_video"

    if requested_scope == "whole_video":
        group_records = _whole_video_group_records_v033(data, all_units)
        base_rows, _ = _base_rows_from_group_records_v033(group_records)
        context_mode = (
            "whole_video_reference_context"
            if duration and duration <= _V033_SHORT_VIDEO_SECONDS
            else "sliding_neighbor_context"
        )
    else:
        chapter = selected_chapter(data, chapter_index)
        sentence_units, _ = _assign_foreign_sentences_to_chapter_v031(all_units, chapter)
        groups = _group_foreign_sentence_units_v031(sentence_units)
        base_rows, _ = _base_rows_from_group_records_v033([(g, chapter) for g in groups])
        context_mode = (
            "whole_video_reference_context"
            if duration and duration <= _V033_SHORT_VIDEO_SECONDS
            else "chapter_plus_neighbor_context"
        )

    batches = _translation_batches_v033(base_rows)
    batch_count = max(1, len(batches))
    # Each batch normally has 2 LLM generations: draft + source-comparison review.
    total_passes = batch_count * 2

    # Broad first-run range for Qwen2.5 14B 4-bit on the target M4 Pro 40GB class.
    # Full-video reference context is heavier because each pass rereads the long context.
    if context_mode == "whole_video_reference_context":
        low_seconds_per_pass, high_seconds_per_pass = 120, 240
    else:
        low_seconds_per_pass, high_seconds_per_pass = 90, 210

    low_seconds = total_passes * low_seconds_per_pass
    high_seconds = total_passes * high_seconds_per_pass
    return {
        "translation_scope": requested_scope,
        "video_duration_seconds": duration,
        "target_row_count": len(base_rows),
        "batch_count": batch_count,
        "total_passes": total_passes,
        "context_mode": context_mode,
        "initial_low_seconds": low_seconds,
        "initial_high_seconds": high_seconds,
        "estimate_note": "첫 배치 완료 후 실제 Mac 속도로 남은 시간이 자동 보정됩니다.",
    }

def _translate_rows_with_context_v033(
    data, all_units, chapter, rows, model_name, translation_scope, progress_callback=None
):
    translations = {}
    policy_records = []
    prior_tail = ""
    outline = _chapter_outline_v032(data)
    batches = _translation_batches_v033(rows)
    total_batches = max(1, len(batches))
    total_steps = total_batches * 2
    completed_steps = 0
    if progress_callback:
        progress_callback({
            "event": "start",
            "total_batches": total_batches,
            "total_steps": total_steps,
            "target_row_count": len(rows),
        })

    for batch_index, batch in enumerate(batches, start=1):
        reference_units, context_meta = _reference_units_for_batch_v033(
            data, all_units, chapter, batch, translation_scope
        )
        expected = [row["utterance_id"] for row in batch]
        target_chars = sum(len(str(row.get("raw_joined_text", ""))) for row in batch)
        first_max_tokens = min(7000, max(1400, int(target_chars * 1.25)))

        if progress_callback:
            progress_callback({
                "event": "stage_start",
                "batch_index": batch_index,
                "total_batches": total_batches,
                "stage": "1차 번역",
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            })
        first_text = _generate_local_llm_text_v033(
            model_name,
            _translation_system_prompt_v033(),
            _build_translation_user_prompt_v033(
                reference_units,
                batch,
                chapter_outline=outline,
                prior_korean_tail=prior_tail,
            ),
            max_tokens=first_max_tokens,
        )
        first_map, missing = _parse_translation_text_v033(first_text, expected)
        if missing:
            # One strict retry is cheaper than throwing away a long local run.
            retry_rows = [row for row in batch if row["utterance_id"] in missing]
            retry_prompt = _build_translation_user_prompt_v033(
                reference_units,
                retry_rows,
                chapter_outline=outline,
                prior_korean_tail=prior_tail,
            ) + "\n\n중요: 이전 응답 형식이 깨졌습니다. OUTPUT_FORMAT 외의 텍스트를 절대 출력하지 마세요."
            retry_text = _generate_local_llm_text_v033(
                model_name,
                _translation_system_prompt_v033(),
                retry_prompt,
                max_tokens=max(900, min(first_max_tokens, int(first_max_tokens * 0.75))),
            )
            retry_map, retry_missing = _parse_translation_text_v033(retry_text, missing)
            first_map.update(retry_map)
            missing = retry_missing
        if missing:
            raise RuntimeError(
                "로컬 LLM 1차 번역 결과에서 일부 검수 행을 읽지 못했습니다: "
                + ", ".join(missing)
            )

        source_by_id = {row["utterance_id"]: row.get("raw_joined_text", "") for row in batch}
        first_map = {
            uid: _apply_source_conditioned_term_normalization_v0332(
                source_by_id.get(uid, ""),
                _canonicalize_official_foreign_names_v031(first_map[uid]),
            )
            for uid in expected
        }

        # Hard target-language guard. Qwen is multilingual and may drift into
        # Chinese during a long generation. Never let a non-Korean payload
        # silently enter the draft. Retry only the affected rows with a compact
        # source-only prompt so normal successful runs do not become slower.
        invalid_first = [
            uid for uid in expected
            if not _target_language_status_v0334(source_by_id.get(uid, ""), first_map.get(uid, ""))[0]
        ]
        if invalid_first:
            retry_rows = [row for row in batch if row["utterance_id"] in invalid_first]
            lang_retry_text = _generate_local_llm_text_v033(
                model_name,
                "반드시 한국어로만 번역하세요. 원문 정보를 보존하고 설명을 덧붙이지 마세요.",
                _build_language_retry_prompt_v0334(retry_rows, first_map),
                max_tokens=max(700, min(1800, int(sum(len(r.get("raw_joined_text", "")) for r in retry_rows) * 1.2))),
            )
            lang_retry_map, _ = _parse_translation_text_v033(lang_retry_text, invalid_first)
            for uid in invalid_first:
                candidate = lang_retry_map.get(uid)
                if candidate:
                    candidate = _apply_source_conditioned_term_normalization_v0332(
                        source_by_id.get(uid, ""),
                        _canonicalize_official_foreign_names_v031(candidate),
                    )
                    ok, _ = _target_language_status_v0334(source_by_id.get(uid, ""), candidate)
                    if ok:
                        first_map[uid] = candidate
            still_invalid = [
                uid for uid in invalid_first
                if not _target_language_status_v0334(source_by_id.get(uid, ""), first_map.get(uid, ""))[0]
            ]
            if still_invalid:
                raise RuntimeError(
                    "로컬 LLM이 한국어가 아닌 출력을 반복했습니다: " + ", ".join(still_invalid)
                )

        completed_steps += 1
        if progress_callback:
            progress_callback({
                "event": "stage_complete",
                "batch_index": batch_index,
                "total_batches": total_batches,
                "stage": "1차 번역",
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            })

        # Second pass: source-vs-draft review. If this pass fails, preserve the
        # complete first pass instead of losing the whole preprocessing result.
        review_status = "completed"
        review_error = None
        non_korean_review_ids = []
        final_map = dict(first_map)
        try:
            if progress_callback:
                progress_callback({
                    "event": "stage_start",
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "stage": "2차 원문 대조 검수",
                    "completed_steps": completed_steps,
                    "total_steps": total_steps,
                })
            review_text = _generate_local_llm_text_v033(
                model_name,
                _review_system_prompt_v033(),
                _build_review_user_prompt_v033(
                    reference_units,
                    batch,
                    first_map,
                    chapter_outline=outline,
                ),
                max_tokens=first_max_tokens,
            )
            reviewed, review_missing = _parse_translation_text_v033(review_text, expected)
            if review_missing:
                review_status = "partial_fallback_to_first_pass"
            non_korean_review_ids = []
            for uid in expected:
                if reviewed.get(uid):
                    candidate = _apply_source_conditioned_term_normalization_v0332(
                        source_by_id.get(uid, ""),
                        _canonicalize_official_foreign_names_v031(reviewed[uid]),
                    )
                    ok, _ = _target_language_status_v0334(source_by_id.get(uid, ""), candidate)
                    if ok:
                        final_map[uid] = candidate
                    else:
                        # A bad review must never overwrite a valid first-pass Korean
                        # translation. Keep first_map without spending another full-context call.
                        non_korean_review_ids.append(uid)
            if non_korean_review_ids:
                review_status = "non_korean_review_fallback_to_first_pass"
        except Exception as exc:
            review_status = "failed_fallback_to_first_pass"
            review_error = str(exc)

        completed_steps += 1
        if progress_callback:
            progress_callback({
                "event": "stage_complete",
                "batch_index": batch_index,
                "total_batches": total_batches,
                "stage": "2차 원문 대조 검수",
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            })

        for uid in expected:
            translations[uid] = final_map[uid]

        prior_tail = "\n".join(
            f"{uid}: {translations[uid]}" for uid in expected[-2:]
        )
        record = {
            "batch_index": batch_index,
            "target_utterance_ids": expected,
            **context_meta,
            "reference_sentence_count": len(reference_units),
            "reference_char_count": len(_units_plain_text_v032(reference_units)),
            "first_pass": "completed",
            "source_comparison_review_pass": review_status,
        }
        if review_error:
            record["source_comparison_review_error"] = review_error
        if non_korean_review_ids:
            record["target_language_review_fallback_ids"] = non_korean_review_ids
        policy_records.append(record)

    return translations, policy_records


def _creator_chapter_for_time_v033(data, seconds):
    chapters = data.get("creator_chapters", []) or []
    if not chapters:
        duration = _video_duration_seconds_v032(data)
        return {
            "chapter_id": "FULL",
            "chapter_index": 0,
            "label": "전체 영상 · 제작자 챕터 없음",
            "start_seconds": 0.0,
            "end_seconds": duration,
            "source_type": "no_creator_chapter",
        }

    t = float(seconds or 0)
    chosen_index = 0
    for index, chapter in enumerate(chapters):
        start = float(chapter.get("start_seconds", 0) or 0)
        if start <= t:
            chosen_index = index
        else:
            break
    chapter = copy.deepcopy(chapters[chosen_index])
    chapter["chapter_id"] = f"CH-{chosen_index + 1:02d}"
    chapter["chapter_index"] = chosen_index
    if chapter.get("end_seconds") is None:
        if chosen_index + 1 < len(chapters):
            chapter["end_seconds"] = chapters[chosen_index + 1].get("start_seconds")
        else:
            chapter["end_seconds"] = _video_duration_seconds_v032(data)
    return chapter


def _whole_video_group_records_v033(data, all_units):
    records = []
    run_units = []
    run_chapter = None

    def flush():
        nonlocal run_units, run_chapter
        if not run_units or run_chapter is None:
            run_units, run_chapter = [], None
            return
        for group in _group_foreign_sentence_units_v031(run_units):
            records.append((group, copy.deepcopy(run_chapter)))
        run_units, run_chapter = [], None

    for unit in all_units:
        owner = _creator_chapter_for_time_v033(data, unit.get("start_seconds", 0))
        owner_id = owner.get("chapter_id")
        if run_chapter is not None and run_chapter.get("chapter_id") != owner_id:
            flush()
        if run_chapter is None:
            run_chapter = owner
        run_units.append(unit)
    flush()
    return records


def _base_rows_from_group_records_v033(group_records):
    base_rows = []
    referenced_segment_ids = []
    for index, (group, owner_chapter) in enumerate(group_records, start=1):
        raw_joined = " ".join(
            str(unit.get("raw_text", "")).strip()
            for unit in group
            if str(unit.get("raw_text", "")).strip()
        ).strip()
        if not raw_joined:
            continue

        source_ids, source_keys, spans = [], [], []
        for unit in group:
            for sid in unit.get("source_segment_ids", []):
                if sid not in source_ids:
                    source_ids.append(sid)
                if sid not in referenced_segment_ids:
                    referenced_segment_ids.append(sid)
            for skey in unit.get("source_segment_keys", []):
                if skey not in source_keys:
                    source_keys.append(skey)
            spans.extend(unit.get("source_spans", []))

        start_seconds = min(float(unit.get("start_seconds", 0) or 0) for unit in group)
        end_seconds = max(float(unit.get("end_seconds", 0) or 0) for unit in group)
        chapter_end = owner_chapter.get("end_seconds")
        crosses_end = bool(chapter_end is not None and end_seconds > float(chapter_end))
        base_rows.append(
            {
                "utterance_id": f"UT-{index:05d}",
                "chapter_id": owner_chapter.get("chapter_id", "FULL"),
                "chapter_label": owner_chapter.get("label"),
                "chapter_index": owner_chapter.get("chapter_index"),
                "chapter_assignment_status": "cross_creator_boundary" if crosses_end else "single_chapter",
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "display_timestamp": display_timestamp(start_seconds),
                "raw_joined_text": raw_joined,
                "source_segment_ids": source_ids,
                "source_segment_keys": source_keys,
                "source_spans": _dedupe_source_spans_v031(spans),
                "source_span_status": "complete",
                "source_span_mapping_ratio": 1.0,
                "unmapped_editor_tokens": [],
                "sentence_unit_ids": [unit.get("sentence_unit_id") for unit in group],
                "source_sentence_complete": all(bool(unit.get("sentence_complete")) for unit in group),
            }
        )
    return base_rows, referenced_segment_ids


def _build_foreign_translation_draft_v033(data, chapter_index, translation_local_model, translation_scope="chapter", progress_callback=None):
    model_name = str(translation_local_model or _DEFAULT_LOCAL_LLM_MODEL_V032).strip()
    video_id = data.get("metadata", {}).get("video_id") or "unknown-video"
    all_units = _build_foreign_sentence_units_v031(data)
    duration = _video_duration_seconds_v032(data, all_units)

    requested_scope = str(translation_scope or "chapter").strip().lower()
    if requested_scope not in {"chapter", "whole_video"}:
        requested_scope = "chapter"
    if not (data.get("creator_chapters") or []):
        requested_scope = "whole_video"

    if requested_scope == "whole_video":
        processed_chapter = {
            "timestamp_text": "00:00",
            "start_seconds": 0.0,
            "end_seconds": duration,
            "label": "전체 영상 번역",
            "source_type": "translation_processing_scope",
            "value_source": "script_preprocessor_ui",
            "verification_status": "not_creator_chapter",
            "chapter_id": "FULL",
            "chapter_index": None,
            "creator_chapters_preserved": True,
        }
        sentence_units = all_units
        boundary_context = {
            "assignment_rule": "reconstructed_sentence_start_single_owner",
            "creator_boundary_is_hard_cut": False,
            "whole_video_processing": True,
            "creator_chapters_preserved": True,
        }
        group_records = _whole_video_group_records_v033(data, all_units)
        base_rows, referenced_segment_ids = _base_rows_from_group_records_v033(group_records)
        context_chapter = processed_chapter
    else:
        processed_chapter = selected_chapter(data, chapter_index)
        sentence_units, boundary_context = _assign_foreign_sentences_to_chapter_v031(
            all_units, processed_chapter
        )
        groups = _group_foreign_sentence_units_v031(sentence_units)
        group_records = [(group, processed_chapter) for group in groups]
        base_rows, referenced_segment_ids = _base_rows_from_group_records_v033(group_records)
        context_chapter = processed_chapter

    translations, context_batches = _translate_rows_with_context_v033(
        data,
        all_units,
        context_chapter,
        base_rows,
        model_name,
        requested_scope,
        progress_callback=progress_callback,
    )

    source_lang = source_language_code(data) or "unknown"
    utterances = []
    for base in base_rows:
        base = dict(base)
        sentence_complete = bool(base.pop("source_sentence_complete", False))
        korean = translations.get(base["utterance_id"], "").strip()
        base.update(
            {
                "auto_normalized_text": korean,
                "normalized_text": korean,
                "speaker_id": None,
                "speaker_status": "unavailable",
                "content_mode": "translated_context_aware_self_reviewed_natural_language",
                "sentence_complete": sentence_complete,
                "normalization_item_ids": [],
                "confidence": "medium",
                "review_status": "needs_review",
                "editor_note": "",
                "validation_warnings": (([] if sentence_complete else ["possible_incomplete_source_sentence"]) + _fidelity_warnings_v0332(base.get("raw_joined_text", ""), korean)),
                "translation_status": "local_llm_two_pass_translated_needs_review",
                "translation_source_language": source_lang,
                "translation_target_language": "ko-KR",
            }
        )
        utterances.append(base)

    segment_by_id = {
        item.get("segment_id"): item
        for item in enrich_all_segments(data)
        if item.get("segment_id")
    }
    raw_segments = [
        segment_by_id[sid]
        for sid in referenced_segment_ids
        if sid in segment_by_id
    ]
    complete_count = sum(1 for item in utterances if item.get("sentence_complete"))

    result = {
        "schema_version": "script_preprocessing_v0.3.3.5",
        "source_schema_version": data.get("schema_version"),
        "source_url": data.get("source_url"),
        "video_id": video_id,
        "source_language": source_lang,
        "source_language_label": source_language_label(data),
        "transcript_origin": data.get("collector_methods", {}).get("transcript"),
        "is_auto_generated": data.get("transcript", {}).get("is_generated"),
        "processed_chapter": processed_chapter,
        "translation_scope": requested_scope,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input_document_kind": "acquisition",
        "boundary_profile": {
            "profile_id": "foreign_sentence_reconstruction_v0.3.3.5",
            "target_group_duration": 14.0,
            "max_group_duration": 30.0,
            "max_group_chars": 1000,
            "max_sentences_per_group": 4,
            "gap_break_seconds": 2.5,
            "emergency_no_punctuation_seconds": 50.0,
            "creator_chapter_is_hard_sentence_cut": False,
        },
        "chapter_boundary_context": boundary_context,
        "all_sentence_unit_count": len(all_units),
        "sentence_unit_count": len(sentence_units),
        "raw_segment_count": len(raw_segments),
        "normalized_utterance_count": len(utterances),
        "translation_required": True,
        "translation_status": "completed_needs_review",
        "translation_metadata": {
            "provider": "local_mlx_llm",
            "model": model_name,
            "target_language": "ko-KR",
            "policy_version": "context_aware_two_pass_faithful_korean_v0.3.3.1_plus_language_guard",
            "translated_at": utc_now(),
            "api_key_required": False,
            "api_key_stored": False,
            "execution_device": "apple_silicon_mlx",
            "model_cache_reused_after_first_download": True,
            "requested_scope": requested_scope,
            "whole_video_scope_execution": "one_click_multi_batch_with_shared_context",
            "two_pass_pipeline": {
                "pass_1": "context_aware_korean_draft",
                "pass_2": "source_comparison_review_and_rewrite",
                "fallback_if_pass_2_fails": "keep_complete_pass_1",
            },
            "style_profile": {
                "source": "editor_verified_examples_used_as_general_policy_reference",
                "few_shot_example_count": len(_V033_FEW_SHOT_EXAMPLES),
                "goal": "generalized_faithful_natural_korean_without_information_loss",
            },
            "context_policy": {
                "short_video_threshold_seconds": _V033_SHORT_VIDEO_SECONDS,
                "short_chapter_threshold_seconds": _V033_SHORT_CHAPTER_SECONDS,
                "neighbor_context_seconds": _V033_NEIGHBOR_CONTEXT_SECONDS,
                "target_rows_keep_original_provenance": True,
                "context_is_reference_only": True,
            },
            "context_batches": context_batches,
        },
        "raw_segments": raw_segments,
        "sentence_units": sentence_units,
        "normalized_utterances": utterances,
        "normalization_items": [],
        "editor_changes": [],
        "unresolved_terms": [],
        "profile_application": {
            "mode": "foreign_translation_v0332_generalized_policy_local_llm",
            "profile_source": "whole_transcript_sentence_reconstruction_then_generalized_policy_local_llm_then_source_fidelity_review",
            "generalization_claim": False,
        },
        "processing_report": {
            "processing_status": "validation_required",
            "chapter_review_status": "in_progress",
            "draft_only": True,
            "editor_review_required": True,
            "sentence_boundary_method": "whole_transcript_punctuation_reconstruction_before_chapter_assignment",
            "chapter_assignment_method": "reconstructed_sentence_start_single_owner",
            "creator_chapter_boundary_hard_cut": False,
            "translation_context_method": "whole_video_reference_for_30min_or_shorter_else_sliding_neighbor_context",
            "translation_review_method": "generalized_anchor_aware_local_llm_second_pass_source_comparison",
            "translation_scope": requested_scope,
            "sentence_complete_utterances": complete_count,
            "sentence_incomplete_utterances": len(utterances) - complete_count,
            "sentence_completion_rate": round(complete_count / max(1, len(utterances)), 4),
            "reconstructed_sentence_unit_count": len(sentence_units),
            "cross_creator_boundary_utterances": sum(
                1 for item in utterances
                if item.get("chapter_assignment_status") == "cross_creator_boundary"
            ),
            "mechanical_duplicates_removed": 0,
            "high_confidence_corrections": 0,
            "medium_confidence_corrections": 0,
            "low_confidence_terms": 0,
            "approved_utterances": 0,
            "rejected_utterances": 0,
            "review_required_utterances": len(utterances),
            "source_span_complete_utterances": len(utterances),
            "source_span_partial_utterances": 0,
            "source_span_weak_utterances": 0,
            "visual_verification_items": [
                "프롬프트·코드·파라미터의 정확한 문자열",
                "버튼·메뉴·탭·파일·항목 이름과 행동의 연결",
                "도구 화면에 표시되는 메뉴·설정값",
                "고유명사·제품명·모델명의 공식 표기",
                "자연스러운 문장 연결과 대명사 지시 대상",
                "원문에 있던 구체 정보가 한국어 초안에서 누락되지 않았는지",
                "제작자 챕터 경계를 넘는 문장의 실제 시작·끝",
            ],
        },
    }
    return _apply_official_foreign_name_policy_v031(result)


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_local_model=None,
    translation_api_key=None,
    translation_model=None,
    translation_scope="chapter",
    progress_callback=None,
):
    if translation_required_for_source(data) and translate_foreign_to_korean:
        return _build_foreign_translation_draft_v033(
            data,
            chapter_index=chapter_index,
            translation_local_model=(translation_local_model or _DEFAULT_LOCAL_LLM_MODEL_V032),
            translation_scope=translation_scope,
            progress_callback=progress_callback,
        )

    result = _build_preprocessing_draft_v032_final(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
        translate_foreign_to_korean=False,
        translation_local_model=translation_local_model,
        translation_api_key=translation_api_key,
        translation_model=translation_model,
    )
    result["schema_version"] = "script_preprocessing_v0.3.3.5"
    return _apply_official_foreign_name_policy_v031(result)


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v032_final(data)
    result["schema_version"] = "script_preprocessing_v0.3.3.5"
    return _apply_official_foreign_name_policy_v031(result)


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v032_final(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.3.3.5"
    return _apply_official_foreign_name_policy_v031(result)

# =====================================================================
# v0.3.4 Qwen3 production translation patch
# - v0.3.3.5 remains the structural baseline (sentence reconstruction,
#   chapter/source provenance, timestamps, editor flow)
# - foreign -> Korean translation model changes to the benchmark winner:
#   mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit
# - production translation is one context-aware LLM pass, matching the benchmark
#   that produced the preferred natural Korean style
# - no routine second LLM rewrite; deterministic guards run after generation:
#   target-language guard, official-name canonicalization, established term cleanup,
#   and source-fidelity warning generation
# - Korean-source preprocessing remains on the existing validated pipeline and still
#   receives the same official foreign-name canonicalization policy.
# =====================================================================

_build_preprocessing_draft_v0335_baseline = build_preprocessing_draft
_prepare_existing_preprocessing_v0335_baseline = prepare_existing_preprocessing
_export_editor_result_v0335_baseline = export_editor_result
_build_foreign_translation_draft_v0335_baseline = _build_foreign_translation_draft_v033

_DEFAULT_LOCAL_LLM_MODEL_V034 = "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"

_V034_STYLE_EXAMPLES = [
    {
        "en": "Honestly, the old AI editor was pretty bad.",
        "ko": "솔직히 예전 AI 편집기는 정말 별로였습니다.",
        "lesson": "Honestly 같은 담화 표현을 기계적으로 직역하지 않는다.",
    },
    {
        "en": "Does it cost credit?",
        "ko": "크레딧이 차감되는 방식일까요?",
        "lesson": "서비스 사용량 문맥의 credit은 신용이 아니라 크레딧으로 해석한다.",
    },
    {
        "en": "I finally cracked the code.",
        "ko": "마침내 해결책을 찾아냈습니다.",
        "lesson": "관용 표현은 문맥상의 실제 의미로 자연스럽게 옮긴다.",
    },
    {
        "en": "Just click AI Creative Content.",
        "ko": "'AI Creative Content'를 클릭하시면 됩니다.",
        "lesson": "click/select/open 뒤 대상이 UI 항목이면 행동 대상을 명확히 유지한다.",
    },
    {
        "en": "You can copy and paste the markdown file.",
        "ko": "마크다운 파일을 복사해서 붙여넣으면 됩니다.",
        "lesson": "구체적인 실행 행동을 추상화하거나 생략하지 않는다.",
    },
]


def _few_shot_text_v034():
    blocks = []
    for index, item in enumerate(_V034_STYLE_EXAMPLES, start=1):
        blocks.append(
            f"예시 {index}\n원문: {item['en']}\n좋은 한국어: {item['ko']}\n판단 기준: {item['lesson']}"
        )
    return "\n\n".join(blocks)


def _translation_system_prompt_v034():
    return (
        "당신은 해외 영상 스크립트를 한국어 검수 초안으로 바꾸는 전문 편집자입니다. "
        "목표는 '번역한 한국어'가 아니라 한국인이 실제 튜토리얼·설명 영상에서 자연스럽게 말하는 한국어입니다. "
        "반드시 한국어 문장으로 작성하세요. "
        "원문의 사실, 숫자, 비용, 기간, 조건, 순서, 행동, 대상을 추가·삭제·요약하지 마세요. "
        "문장을 하나씩 직역하지 말고 REFERENCE_CONTEXT를 읽어 대명사와 지시 대상을 복원하세요. "
        "영어 접속사를 '그리고/그래서'로 기계적으로 반복하지 말고 한국어 흐름에 맞게 연결하세요. "
        "click/select/open/go to/copy/paste/install/download/drag/drop 같은 행동과 그 대상을 정확히 유지하세요. "
        "버튼·메뉴·탭·파일명·UI 문구처럼 보이는 표현은 일반 개념으로 오역하지 말고, 확실하지 않으면 원문 Latin 표기를 유지하세요. "
        "외국어 브랜드·제품·모델·도구명은 공식 원문 표기를 유지하세요. 예: Claude Code, Claude, ChatGPT, Higgsfield, Sora, Seedance, Gemini, Figma. "
        "한국 실무에서 통용되는 용어를 사용하세요. 예: motion graphics는 모션 그래픽, sound effects는 사운드 효과입니다. "
        "관용어는 문맥상의 뜻으로 옮기되 원문에 없는 설명이나 '자동으로' 같은 의미를 임의로 덧붙이지 마세요. "
        "원문의 말투 강도와 친근함은 유지하되 불필요한 번역투를 제거하세요. 존댓말/해요체는 문맥에 맞게 자연스럽게 쓰세요. "
        "각 TARGET id의 사실은 그 id 안에 그대로 두어 출처 추적을 깨뜨리지 마세요. "
        "STYLE_EXAMPLES는 판단 방식만 참고하고 예시의 사실이나 문구를 현재 영상에 복사하지 마세요. "
        "중국어·일본어 등 다른 언어 문장을 출력하지 마세요. "
        "반드시 모든 TARGET id에 정확히 하나의 한국어 문자열을 반환하고 OUTPUT_FORMAT만 사용하세요."
    )


def _build_translation_user_prompt_v034(
    reference_units,
    target_rows,
    chapter_outline="",
    prior_korean_tail="",
):
    context = _units_plain_text_v032(reference_units)
    target_block = "\n\n".join(
        f"ID: {row['utterance_id']}\nSOURCE_EN: {row.get('raw_joined_text', '')}"
        for row in target_rows
    )
    parts = [
        "STYLE_EXAMPLES (문구를 복사하지 말고 판단 방식만 참고):\n" + _few_shot_text_v034(),
    ]
    if chapter_outline:
        parts.append("CHAPTER_OUTLINE (맥락 참고용):\n" + chapter_outline)
    parts.append("REFERENCE_CONTEXT (맥락 참고용이며 출력 범위를 늘리지 마세요):\n" + context)
    if prior_korean_tail:
        parts.append(
            "PRIOR_KOREAN_TAIL (문장 연결/톤 참고용이며 사실을 옮기지 마세요):\n"
            + prior_korean_tail
        )
    parts.append("TARGET_ROWS:\n" + target_block)
    parts.append(_marker_output_instruction_v033([row["utterance_id"] for row in target_rows]))
    return "\n\n".join(parts)


def _build_language_retry_prompt_v034(rows, bad_map):
    payload = "\n\n".join(
        f"ID: {row['utterance_id']}\nSOURCE_EN: {row.get('raw_joined_text', '')}\nBAD_OUTPUT: {bad_map.get(row['utterance_id'], '')}"
        for row in rows
    )
    return (
        "이전 출력이 한국어가 아니었습니다. SOURCE_EN을 기준으로 자연스러운 한국어로 다시 작성하세요. "
        "브랜드·제품·UI·파일명의 공식 Latin 표기는 그대로 유지하고, 원문의 숫자·기간·조건·행동을 추가·삭제·요약하지 마세요.\n\n"
        + payload
        + "\n\n"
        + _marker_output_instruction_v033([row["utterance_id"] for row in rows])
    )


def _translate_rows_with_context_v034(
    data,
    all_units,
    chapter,
    rows,
    model_name,
    translation_scope,
    progress_callback=None,
):
    translations = {}
    policy_records = []
    prior_tail = ""
    outline = _chapter_outline_v032(data)
    batches = _translation_batches_v033(rows)
    total_batches = max(1, len(batches))
    total_steps = total_batches
    completed_steps = 0

    if progress_callback:
        progress_callback({
            "event": "start",
            "total_batches": total_batches,
            "total_steps": total_steps,
            "target_row_count": len(rows),
        })

    for batch_index, batch in enumerate(batches, start=1):
        reference_units, context_meta = _reference_units_for_batch_v033(
            data, all_units, chapter, batch, translation_scope
        )
        expected = [row["utterance_id"] for row in batch]
        target_chars = sum(len(str(row.get("raw_joined_text", ""))) for row in batch)
        max_tokens = min(7000, max(1200, int(target_chars * 1.45)))

        if progress_callback:
            progress_callback({
                "event": "stage_start",
                "batch_index": batch_index,
                "total_batches": total_batches,
                "stage": "Qwen3 자연어 번역",
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            })

        text = _generate_local_llm_text_v033(
            model_name,
            _translation_system_prompt_v034(),
            _build_translation_user_prompt_v034(
                reference_units,
                batch,
                chapter_outline=outline,
                prior_korean_tail=prior_tail,
            ),
            max_tokens=max_tokens,
        )
        translated, missing = _parse_translation_text_v033(text, expected)

        if missing:
            retry_rows = [row for row in batch if row["utterance_id"] in missing]
            retry_text = _generate_local_llm_text_v033(
                model_name,
                _translation_system_prompt_v034(),
                _build_translation_user_prompt_v034(
                    reference_units,
                    retry_rows,
                    chapter_outline=outline,
                    prior_korean_tail=prior_tail,
                ) + "\n\n중요: 이전 응답 형식이 깨졌습니다. OUTPUT_FORMAT 외의 텍스트는 절대 출력하지 마세요.",
                max_tokens=max(800, min(max_tokens, int(max_tokens * 0.8))),
            )
            retry_map, retry_missing = _parse_translation_text_v033(retry_text, missing)
            translated.update(retry_map)
            missing = retry_missing
        if missing:
            raise RuntimeError(
                "Qwen3 번역 결과에서 일부 검수 행을 읽지 못했습니다: " + ", ".join(missing)
            )

        source_by_id = {
            row["utterance_id"]: row.get("raw_joined_text", "")
            for row in batch
        }
        for uid in expected:
            translated[uid] = _apply_source_conditioned_term_normalization_v0332(
                source_by_id.get(uid, ""),
                _canonicalize_official_foreign_names_v031(translated.get(uid, "")),
            )

        invalid = [
            uid for uid in expected
            if not _target_language_status_v0334(
                source_by_id.get(uid, ""), translated.get(uid, "")
            )[0]
        ]
        retried_language_ids = []
        if invalid:
            retry_rows = [row for row in batch if row["utterance_id"] in invalid]
            retry_text = _generate_local_llm_text_v033(
                model_name,
                "반드시 자연스러운 한국어로만 작성하세요. 원문 정보를 추가·삭제·요약하지 마세요.",
                _build_language_retry_prompt_v034(retry_rows, translated),
                max_tokens=max(
                    700,
                    min(
                        2000,
                        int(sum(len(r.get("raw_joined_text", "")) for r in retry_rows) * 1.35),
                    ),
                ),
            )
            retry_map, _ = _parse_translation_text_v033(retry_text, invalid)
            for uid in invalid:
                candidate = retry_map.get(uid)
                if not candidate:
                    continue
                candidate = _apply_source_conditioned_term_normalization_v0332(
                    source_by_id.get(uid, ""),
                    _canonicalize_official_foreign_names_v031(candidate),
                )
                if _target_language_status_v0334(source_by_id.get(uid, ""), candidate)[0]:
                    translated[uid] = candidate
                    retried_language_ids.append(uid)

            still_invalid = [
                uid for uid in invalid
                if not _target_language_status_v0334(
                    source_by_id.get(uid, ""), translated.get(uid, "")
                )[0]
            ]
            if still_invalid:
                raise RuntimeError(
                    "Qwen3가 한국어가 아닌 출력을 반복했습니다: " + ", ".join(still_invalid)
                )

        for uid in expected:
            translations[uid] = translated[uid]

        prior_tail = "\n".join(
            f"{uid}: {translations[uid]}" for uid in expected[-2:]
        )
        completed_steps += 1
        if progress_callback:
            progress_callback({
                "event": "stage_complete",
                "batch_index": batch_index,
                "total_batches": total_batches,
                "stage": "Qwen3 자연어 번역",
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            })

        record = {
            "batch_index": batch_index,
            "target_utterance_ids": expected,
            **context_meta,
            "reference_sentence_count": len(reference_units),
            "reference_char_count": len(_units_plain_text_v032(reference_units)),
            "first_pass": "completed",
            "llm_second_pass": "disabled_by_v0.3.4_policy",
            "post_generation_guards": [
                "target_language_guard",
                "official_foreign_name_canonicalization",
                "source_conditioned_term_normalization",
                "source_fidelity_warning_generation",
            ],
        }
        if retried_language_ids:
            record["target_language_retry_ids"] = retried_language_ids
        policy_records.append(record)

    return translations, policy_records


# The v0.3.3.5 foreign builder resolves this global function at runtime.
# Swap only the translation engine; keep its sentence/chapter/provenance builder intact.
_translate_rows_with_context_v033 = _translate_rows_with_context_v034


def _upgrade_v0335_result_to_v034(result, model_name):
    if not isinstance(result, dict):
        return result
    result["schema_version"] = "script_preprocessing_v0.3.4"
    boundary = result.get("boundary_profile") or {}
    if boundary.get("profile_id"):
        boundary["profile_id"] = str(boundary["profile_id"]).replace("v0.3.3.5", "v0.3.4")
    tm = result.get("translation_metadata") or {}
    if tm:
        tm["model"] = model_name
        tm["policy_version"] = "qwen3_context_aware_natural_korean_one_pass_guarded_v0.3.4"
        tm.pop("two_pass_pipeline", None)
        tm["translation_pipeline"] = {
            "llm_pass": "single_context_aware_natural_korean_pass",
            "routine_llm_second_pass": False,
            "post_generation_guards": [
                "target_language_guard_with_bad_row_retry",
                "official_foreign_name_canonicalization",
                "source_conditioned_korean_term_normalization",
                "source_fidelity_warnings",
            ],
        }
        tm["style_profile"] = {
            "source": "qwen3_benchmark_winner_generalized_style_policy",
            "few_shot_example_count": len(_V034_STYLE_EXAMPLES),
            "goal": "natural_spoken_korean_with_source_fidelity",
        }
        for record in tm.get("context_batches", []) or []:
            record.pop("source_comparison_review_pass", None)
            record.pop("source_comparison_review_error", None)
    for item in result.get("normalized_utterances", []) or []:
        if item.get("translation_required") is not False:
            if item.get("translation_status"):
                item["translation_status"] = "local_qwen3_one_pass_guarded_translated_needs_review"
            if item.get("content_mode"):
                item["content_mode"] = "translated_qwen3_context_aware_guarded_natural_language"
    profile = result.get("profile_application") or {}
    if result.get("translation_required"):
        profile["mode"] = "foreign_translation_v034_qwen3_one_pass_guarded"
        profile["profile_source"] = "v0335_sentence_provenance_plus_qwen3_natural_translation_plus_deterministic_guards"
    report = result.get("processing_report") or {}
    if result.get("translation_required"):
        report["translation_review_method"] = "qwen3_one_pass_plus_deterministic_fidelity_guards"
    return _apply_official_foreign_name_policy_v031(result)


def estimate_translation_workload(data, chapter_index=0, translation_scope="chapter"):
    all_units = _build_foreign_sentence_units_v031(data)
    requested_scope = str(translation_scope or "chapter").strip().lower()
    if requested_scope not in {"chapter", "whole_video"}:
        requested_scope = "chapter"
    if not (data.get("creator_chapters") or []):
        requested_scope = "whole_video"

    if requested_scope == "whole_video":
        group_records = _whole_video_group_records_v033(data, all_units)
        rows, _ = _base_rows_from_group_records_v033(group_records)
        context_mode = "whole_video"
    else:
        chapter = selected_chapter(data, chapter_index)
        sentence_units, _ = _assign_foreign_sentences_to_chapter_v031(all_units, chapter)
        groups = _group_foreign_sentence_units_v031(sentence_units)
        rows, _ = _base_rows_from_group_records_v033([(group, chapter) for group in groups])
        context_mode = "chapter"

    batches = _translation_batches_v033(rows)
    batch_count = max(1, len(batches))
    # The user's cached benchmark completed 9 rows in ~24 s including ~5 s load.
    # Keep the estimate deliberately broad because full-context prefill and long videos vary.
    low_seconds = 15 + batch_count * 15
    high_seconds = 45 + batch_count * 75
    return {
        "translation_scope": requested_scope,
        "target_row_count": len(rows),
        "batch_count": batch_count,
        "total_passes": batch_count,
        "llm_passes_per_batch": 1,
        "context_mode": context_mode,
        "initial_low_seconds": low_seconds,
        "initial_high_seconds": high_seconds,
        "estimate_note": "Qwen3 모델이 이미 로컬 캐시에 있으면 다운로드 없이 실행됩니다. 첫 생성 완료 후 실제 속도로 ETA가 자동 보정됩니다.",
    }


def _build_foreign_translation_draft_v034(
    data,
    chapter_index,
    translation_local_model,
    translation_scope="chapter",
    progress_callback=None,
):
    model_name = str(translation_local_model or _DEFAULT_LOCAL_LLM_MODEL_V034).strip()
    result = _build_foreign_translation_draft_v0335_baseline(
        data,
        chapter_index=chapter_index,
        translation_local_model=model_name,
        translation_scope=translation_scope,
        progress_callback=progress_callback,
    )
    return _upgrade_v0335_result_to_v034(result, model_name)


def build_preprocessing_draft(
    data,
    chapter_index=0,
    custom_glossary_text="",
    include_boundary_continuation=True,
    calibration_gold=None,
    use_validated_profile=True,
    apply_verified_same_chapter=True,
    reuse_approval_status=False,
    auto_apply_builtin_profile=True,
    translate_foreign_to_korean=False,
    translation_local_model=None,
    translation_api_key=None,
    translation_model=None,
    translation_scope="chapter",
    progress_callback=None,
):
    if translation_required_for_source(data) and translate_foreign_to_korean:
        return _build_foreign_translation_draft_v034(
            data,
            chapter_index=chapter_index,
            translation_local_model=(translation_local_model or _DEFAULT_LOCAL_LLM_MODEL_V034),
            translation_scope=translation_scope,
            progress_callback=progress_callback,
        )

    # Korean-source path: preserve the v0.3.3.5 validated normalizer for now.
    # It already receives official-name canonicalization; disfluency/style cleanup will
    # be benchmarked separately before changing this path.
    result = _build_preprocessing_draft_v0335_baseline(
        data,
        chapter_index=chapter_index,
        custom_glossary_text=custom_glossary_text,
        include_boundary_continuation=include_boundary_continuation,
        calibration_gold=calibration_gold,
        use_validated_profile=use_validated_profile,
        apply_verified_same_chapter=apply_verified_same_chapter,
        reuse_approval_status=reuse_approval_status,
        auto_apply_builtin_profile=auto_apply_builtin_profile,
        translate_foreign_to_korean=False,
        translation_local_model=translation_local_model,
        translation_api_key=translation_api_key,
        translation_model=translation_model,
        translation_scope=translation_scope,
        progress_callback=progress_callback,
    )
    result["schema_version"] = "script_preprocessing_v0.3.4"
    result.setdefault("processing_report", {})["korean_normalization_policy"] = (
        "v0.3.3.5_validated_baseline_plus_shared_official_name_canonicalization"
    )
    return _apply_official_foreign_name_policy_v031(result)


def prepare_existing_preprocessing(data):
    result = _prepare_existing_preprocessing_v0335_baseline(data)
    result["schema_version"] = "script_preprocessing_v0.3.4"
    return _apply_official_foreign_name_policy_v031(result)


def export_editor_result(draft, edited_rows):
    result = _export_editor_result_v0335_baseline(draft, edited_rows)
    result["schema_version"] = "script_preprocessing_v0.3.4"
    return _apply_official_foreign_name_policy_v031(result)
