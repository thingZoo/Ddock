from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


CHAPTER_SCOPE = "chapter"
WHOLE_VIDEO_SCOPE = "whole_video"
CHAPTER_SCOPE_LABEL = "챕터별 전처리"
WHOLE_VIDEO_SCOPE_LABEL = "전체 영상 전처리"


_CHAPTERS_ANCHOR = '''    chapters = source.get(
        "creator_chapters",
        [],
    )

    if chapters:
'''

_CHAPTERS_REPLACEMENT = '''    chapters = source.get(
        "creator_chapters",
        [],
    )
    source_creator_chapters = list(chapters)
    needs_translation = translation_required_for_source(source)
    processing_scope = render_korean_processing_scope(
        st,
        source,
        source_creator_chapters,
        needs_translation=needs_translation,
    )
    if processing_scope == "whole_video" and not needs_translation:
        # UI-only view: the runtime adapter still receives the untouched source,
        # including creator chapters for semantic ownership/provenance.
        chapters = []

    if chapters:
'''

_IMPORT_ANCHOR = '''from review_store import (
    atomic_autosave,
    current_result,
    dataframe_from_draft,
    load_autosave,
)
'''

_IMPORT_REPLACEMENT = _IMPORT_ANCHOR + '''from korean_full_scope import (
    preprocessing_autosave_target_id,
    render_korean_processing_scope,
)
'''

_AUTOSAVE_ANCHOR = '''    autosave_target_id = (
        "FULL"
        if needs_translation and translate_foreign and translation_scope == "whole_video"
        else target_id
    )
'''

_AUTOSAVE_REPLACEMENT = '''    autosave_target_id = preprocessing_autosave_target_id(
        target_id=target_id,
        needs_translation=needs_translation,
        translate_foreign=translate_foreign,
        processing_scope=processing_scope,
        translation_scope=translation_scope,
    )
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"한국어 FULL UI patch anchor가 일치하지 않습니다: {label} ({count})"
        )
    return source.replace(old, new, 1)


def install_korean_full_scope_ui(source: str) -> str:
    """Install the v0.3.16 UI adapter without modifying the stable app.py file."""
    output = _replace_once(source, _IMPORT_ANCHOR, _IMPORT_REPLACEMENT, "import")
    output = _replace_once(output, _CHAPTERS_ANCHOR, _CHAPTERS_REPLACEMENT, "chapters")
    output = _replace_once(
        output,
        '    translation_scope = "chapter"\n',
        '    translation_scope = processing_scope\n',
        "initial_scope",
    )
    output = _replace_once(
        output,
        '        processing_scope_label = "챕터 전체"\n',
        '        processing_scope_label = "선택 챕터"\n',
        "chapter_button_label",
    )
    output = _replace_once(
        output,
        '            "제작자 챕터 없음 · 전체 영상으로 검수합니다"\n',
        '            (\n'
        '                "전체 영상 범위 · 전체 transcript로 검수합니다"\n'
        '                if source_creator_chapters\n'
        '                else "제작자 챕터 없음 · 전체 영상으로 검수합니다"\n'
        '            )\n',
        "full_scope_info",
    )
    return _replace_once(
        output,
        _AUTOSAVE_ANCHOR,
        _AUTOSAVE_REPLACEMENT,
        "autosave_scope",
    )


def _source_identity(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") or {}
    stable_parts = {
        "video_id": metadata.get("video_id") or source.get("video_id"),
        "source_url": metadata.get("source_url") or source.get("source_url"),
        "title": metadata.get("title"),
    }
    encoded = json.dumps(
        stable_parts,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def scope_session_key(source: dict[str, Any]) -> str:
    return f"v0316_preprocessing_scope_{_source_identity(source)}"


def preprocessing_autosave_target_id(
    *,
    target_id: str,
    needs_translation: bool,
    translate_foreign: bool,
    processing_scope: str,
    translation_scope: str,
) -> str:
    korean_full = (
        not needs_translation
        and processing_scope == WHOLE_VIDEO_SCOPE
    )
    foreign_full = (
        needs_translation
        and translate_foreign
        and translation_scope == WHOLE_VIDEO_SCOPE
    )
    return "FULL" if korean_full or foreign_full else target_id


def render_korean_processing_scope(
    st: Any,
    source: dict[str, Any],
    creator_chapters: list[dict[str, Any]],
    *,
    needs_translation: bool,
) -> str:
    """Render only the Korean scope choice; foreign scope remains in its existing UI."""
    if not creator_chapters:
        return WHOLE_VIDEO_SCOPE
    if needs_translation:
        return CHAPTER_SCOPE
    selected = st.radio(
        "처리 범위",
        options=[CHAPTER_SCOPE_LABEL, WHOLE_VIDEO_SCOPE_LABEL],
        index=0,
        horizontal=True,
        key=scope_session_key(source),
        help=(
            "챕터별 전처리는 선택한 제작자 챕터만 처리합니다. "
            "전체 영상 전처리는 전체 transcript를 하나의 FULL 범위로 처리합니다."
        ),
    )
    return (
        WHOLE_VIDEO_SCOPE
        if selected == WHOLE_VIDEO_SCOPE_LABEL
        else CHAPTER_SCOPE
    )


def is_korean_full_request(
    core: Any,
    source: Any,
    *,
    translation_scope: Any,
    translate_foreign_to_korean: Any,
) -> bool:
    if not isinstance(source, dict):
        return False
    if str(translation_scope or CHAPTER_SCOPE).strip().lower() != WHOLE_VIDEO_SCOPE:
        return False
    if not (source.get("creator_chapters") or []):
        return False
    if bool(translate_foreign_to_korean):
        return False
    return not bool(core.translation_required_for_source(source))


def source_for_korean_full(source: dict[str, Any]) -> dict[str, Any]:
    """Expose the established chapterless FULL path to the baseline builder."""
    adapted = dict(source)
    adapted["creator_chapters"] = []
    return adapted


def _duration_seconds(source: dict[str, Any]) -> Any:
    metadata = source.get("metadata") or {}
    duration = metadata.get("duration_seconds")
    if duration is not None:
        return duration
    transcript = source.get("transcript") or {}
    ends: list[float] = []
    for item in transcript.get("items") or []:
        try:
            end = item.get("end_seconds")
            if end is None:
                end = float(item.get("start_seconds", 0) or 0) + float(
                    item.get("duration_seconds", 0) or 0
                )
            ends.append(float(end))
        except (TypeError, ValueError):
            continue
    return max(ends) if ends else None


def finalize_korean_full_result(
    result: dict[str, Any],
    source: dict[str, Any],
    *,
    core: Any,
) -> dict[str, Any]:
    """Restore creator provenance and express the existing FULL schema accurately."""
    owner_for_time = getattr(core, "_creator_chapter_for_time_v033", None)
    if not callable(owner_for_time):
        raise RuntimeError(
            "기존 whole-video creator ownership helper를 찾을 수 없습니다."
        )
    for row in result.get("normalized_utterances") or []:
        if not isinstance(row, dict):
            continue
        owner = owner_for_time(source, row.get("start_seconds", 0))
        owner_end = owner.get("end_seconds")
        try:
            crosses_end = bool(
                owner_end is not None
                and float(row.get("end_seconds", 0) or 0) > float(owner_end)
            )
        except (TypeError, ValueError):
            crosses_end = False
        row["chapter_id"] = owner.get("chapter_id")
        row["chapter_index"] = owner.get("chapter_index")
        row["chapter_label"] = owner.get("label")
        row["chapter_assignment_status"] = (
            "cross_creator_boundary" if crosses_end else "single_chapter"
        )
        if "creator_chapter_id" in row:
            row["creator_chapter_id"] = None

    processed = dict(result.get("processed_chapter") or {})
    processed.update(
        {
            "chapter_id": "FULL",
            "chapter_index": 0,
            "creator_chapter_id": None,
            "label": "전체 영상",
            "start_seconds": 0,
            "end_seconds": _duration_seconds(source),
            "source_type": "full_video_processing",
            "boundary_source": "processing_scope_whole_video",
            "verification_status": "source_structure_verified",
            "creator_chapters_preserved": True,
        }
    )
    result["processed_chapter"] = processed
    result["creator_chapters"] = copy.deepcopy(
        source.get("creator_chapters") or []
    )
    result["translation_required"] = False
    result["translation_status"] = "not_required"
    result["preprocessing_scope"] = WHOLE_VIDEO_SCOPE
    return result
