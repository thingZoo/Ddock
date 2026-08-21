from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from review_store import atomic_autosave, autosave_path
from screenshot_output import (
    atomic_write_json,
    final_json_path,
    result_with_source_title,
)


MANUAL_REVIEW_SCHEMA_VERSION = "manual_script_review_v0.1"
MANUAL_REVIEW_SOURCE = "manual_review_ui"
HIGH_SEVERITY_PRIORITY = 360.0

_REVIEW_STATES = {
    "suspicious",
    "unresolved",
    "review_pending",
    "review_failed",
    "audio_review_needed",
    "audio_reviewed_unresolved",
}
_COMPLETED_HUMAN_STATES = {"corrected", "confirmed"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_LABELS = {
    "high": "높은 우선순위",
    "medium": "중간 우선순위",
    "low": "용어 확인",
}
_REASON_LABELS = {
    "audio_review_needed": "음성 확인 필요",
    "audio_review_duration_budget_deferred": "음성 검토 대기",
    "audio_reviewed_unresolved": "음성을 확인했지만 판단 보류",
    "ambiguous_without_sufficient_audio_priority": "용어 확인 필요",
    "ambiguous_needs_review": "용어 확인 필요",
    "boundary_integrity_failed": "자막 인식이 불확실함",
    "anchor_not_preserved": "문장 경계 확인 필요",
    "span_alignment_failed": "자막과 음성 정렬 확인 필요",
    "adjacent_row_content_leakage": "인접 문장 혼입 가능성",
    "review_budget_deferred": "검토 우선순위 대기",
    "source_locator_missing": "원본 영상 위치 확인 필요",
    "technical_domain_phrase_near_match": "전문용어 확인 필요",
    "video_local_person_identity_near_match": "인명 확인 필요",
    "official_entity_discourse_continuity": "공식명 확인 필요",
    "acronym_discourse_inconsistency": "약어 확인 필요",
    "severe_video_local_lexical_outlier": "심한 자막 인식 오류 가능성",
    "malformed_script_boundary": "붙어 있는 자막 확인 필요",
    "attached_token_boundary_candidate": "띄어쓰기 경계 확인 필요",
    "singleton_unregistered_acronym": "약어 의미 확인 필요",
}


def _seconds(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _timestamp(seconds: Any) -> str:
    total = int(_seconds(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def review_result_fingerprint(result: Mapping[str, Any]) -> str:
    """Identify one processing run without depending on editable normalized text."""
    chapter = result.get("processed_chapter")
    chapter = chapter if isinstance(chapter, Mapping) else {}
    rows = [
        {
            "utterance_id": row.get("utterance_id"),
            "start_seconds": row.get("start_seconds"),
            "end_seconds": row.get("end_seconds"),
            "source_segment_ids": list(row.get("source_segment_ids") or []),
        }
        for row in result.get("normalized_utterances") or []
        if isinstance(row, Mapping)
    ]
    payload = {
        "video_id": result.get("video_id"),
        "scope": chapter.get("chapter_id"),
        "created_at": result.get("created_at"),
        "raw_segment_count": len(result.get("raw_segments") or []),
        "rows": rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_session_key(result: Mapping[str, Any], utterance_id: str) -> str:
    return "script_review_edit_" + review_result_fingerprint(result)[:16] + "_" + str(
        utterance_id
    )


def _friendly_reason(values: list[str]) -> str:
    for value in values:
        clean = str(value or "").split(":")[-1]
        if clean in _REASON_LABELS:
            return _REASON_LABELS[clean]
    return "자막 문맥 확인 필요"


def _severity(record: Mapping[str, Any], reasons: list[str]) -> str:
    priority = _seconds(record.get("priority_score"))
    signals = {str(value) for value in record.get("signals") or []}
    if priority >= HIGH_SEVERITY_PRIORITY or signals & {
        "severe_video_local_lexical_outlier",
        "malformed_script_boundary",
        "video_local_person_identity_near_match",
        "official_entity_discourse_continuity",
    }:
        return "high"
    if str(record.get("audio_priority") or "") == "medium" or str(
        record.get("classification") or ""
    ) == "audio_evidence_needed":
        return "medium"
    if any("high" in value or "severe" in value for value in reasons):
        return "high"
    return "low"


def collect_review_items(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Collect reviewable rows only from metadata already produced by the pipeline."""
    unresolved_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in result.get("unresolved_terms") or []:
        if not isinstance(item, Mapping):
            continue
        unresolved_by_id.setdefault(str(item.get("utterance_id") or ""), []).append(
            dict(item)
        )

    audio_review = result.get("korean_audio_review")
    audio_review = audio_review if isinstance(audio_review, Mapping) else {}
    classified_by_id = {
        str(item.get("utterance_id") or ""): dict(item)
        for item in audio_review.get("classified_items") or []
        if isinstance(item, Mapping)
    }
    candidates_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in audio_review.get("candidates") or []:
        if isinstance(item, Mapping):
            candidates_by_id.setdefault(
                str(item.get("utterance_id") or ""), []
            ).append(dict(item))

    editorial = result.get("korean_editorial_review")
    editorial = editorial if isinstance(editorial, Mapping) else {}
    changes_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in editorial.get("changed_items") or []:
        if isinstance(item, Mapping):
            changes_by_id.setdefault(str(item.get("utterance_id") or ""), []).append(
                dict(item)
            )

    has_pipeline_metadata = bool(editorial or audio_review or unresolved_by_id)
    items: list[dict[str, Any]] = []
    for row in result.get("normalized_utterances") or []:
        if not isinstance(row, Mapping):
            continue
        utterance_id = str(row.get("utterance_id") or "")
        if not utterance_id:
            continue
        human_review = row.get("human_review")
        human_review = human_review if isinstance(human_review, Mapping) else {}
        human_status = str(human_review.get("status") or "")
        completed = human_status in _COMPLETED_HUMAN_STATES
        state = str(row.get("korean_editorial_state") or "")
        classification = classified_by_id.get(utterance_id, {})
        category = str(classification.get("classification") or "")
        warnings = [str(value) for value in row.get("validation_warnings") or []]
        unresolved = unresolved_by_id.get(utterance_id, [])
        reasons = [str(value.get("reason") or "") for value in unresolved]
        reasons.extend(str(value) for value in classification.get("signals") or [])
        reasons.extend(warnings)
        needs_review = not completed and (
            bool(unresolved)
            or state in _REVIEW_STATES
            or category in {"audio_evidence_needed", "ambiguous_needs_review"}
            or (
                not has_pipeline_metadata
                and str(row.get("review_status") or "") == "needs_review"
            )
        )
        if not needs_review and not completed:
            continue
        severity = _severity(classification, reasons)
        items.append(
            {
                "utterance_id": utterance_id,
                "start_seconds": _seconds(row.get("start_seconds")),
                "end_seconds": _seconds(row.get("end_seconds")),
                "timestamp": str(row.get("display_timestamp") or "")
                or _timestamp(row.get("start_seconds")),
                "normalized_text": str(row.get("normalized_text") or ""),
                "raw_text": str(row.get("raw_joined_text") or ""),
                "review_status": "completed" if completed else "needs_review",
                "human_review": copy.deepcopy(human_review),
                "severity": severity,
                "severity_label": _SEVERITY_LABELS[severity],
                "priority_score": classification.get("priority_score"),
                "reason": _friendly_reason(reasons),
                "reason_codes": list(dict.fromkeys(value for value in reasons if value)),
                "whisper_candidates": copy.deepcopy(
                    candidates_by_id.get(utterance_id, [])
                ),
                "automatic_changes": copy.deepcopy(
                    changes_by_id.get(utterance_id, [])
                ),
            }
        )
    items.sort(
        key=lambda item: (
            _SEVERITY_ORDER[item["severity"]],
            item["start_seconds"],
            item["utterance_id"],
        )
    )
    return items


def build_timestamp_url(result: Mapping[str, Any], seconds: Any) -> str | None:
    source_url = str(result.get("source_url") or "").strip()
    video_id = str(result.get("video_id") or "").strip()
    if not source_url and video_id:
        source_url = "https://www.youtube.com/watch?v=" + video_id
    if not source_url:
        return None
    parsed = urlparse(source_url)
    if "youtu" not in parsed.netloc.casefold():
        return None
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["t"] = f"{int(max(0.0, _seconds(seconds) - 1.5))}s"
    return urlunparse(parsed._replace(query=urlencode(query)))


def initialize_review_session(
    session_state: MutableMapping[str, Any],
    result: Mapping[str, Any],
    items: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    review_items = collect_review_items(result) if items is None else [dict(x) for x in items]
    for item in review_items:
        session_state.setdefault(
            review_session_key(result, str(item["utterance_id"])),
            str(item.get("normalized_text") or ""),
        )
    return review_items


def pending_session_edits(
    session_state: Mapping[str, Any],
    result: Mapping[str, Any],
    items: list[Mapping[str, Any]],
) -> dict[str, str]:
    edits: dict[str, str] = {}
    for item in items:
        utterance_id = str(item["utterance_id"])
        key = review_session_key(result, utterance_id)
        current = str(session_state.get(key, item.get("normalized_text") or ""))
        if current != str(item.get("normalized_text") or ""):
            edits[utterance_id] = current
    return edits


def apply_manual_review_edits(
    result: Mapping[str, Any],
    edits: Mapping[str, str],
    *,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Apply only normalized-layer edits and attach auditable human provenance."""
    output = copy.deepcopy(dict(result))
    timestamp = reviewed_at or datetime.now(timezone.utc).isoformat()
    items = {item["utterance_id"]: item for item in collect_review_items(output)}
    rows = {
        str(row.get("utterance_id") or ""): row
        for row in output.get("normalized_utterances") or []
        if isinstance(row, dict)
    }
    history = output.setdefault("manual_review", {})
    history.setdefault("schema_version", MANUAL_REVIEW_SCHEMA_VERSION)
    entries = history.setdefault("entries", [])
    applied = 0
    for utterance_id, value in edits.items():
        row = rows.get(str(utterance_id))
        if row is None:
            raise ValueError(f"unknown_manual_review_utterance:{utterance_id}")
        before = str(row.get("normalized_text") or "")
        after = str(value)
        if not after.strip():
            raise ValueError(f"empty_manual_review_text:{utterance_id}")
        if after == before:
            continue
        item = items.get(str(utterance_id), {})
        provenance = {
            "status": "corrected",
            "reviewed_at": timestamp,
            "before": before,
            "after": after,
            "source": MANUAL_REVIEW_SOURCE,
            "video_id": output.get("video_id"),
            "utterance_id": str(utterance_id),
            "timestamp_seconds": row.get("start_seconds"),
            "review_reason": item.get("reason"),
            "review_reason_codes": copy.deepcopy(item.get("reason_codes") or []),
            "severity": item.get("severity"),
            "human_confirmed": True,
        }
        row["normalized_text"] = after
        if "final_normalized_text" in row:
            row["final_normalized_text"] = after
        row["review_status"] = "approved"
        row["human_review"] = copy.deepcopy(provenance)
        entries.append(copy.deepcopy(provenance))
        for unresolved in output.get("unresolved_terms") or []:
            if isinstance(unresolved, dict) and str(
                unresolved.get("utterance_id") or ""
            ) == str(utterance_id):
                unresolved["human_review_status"] = "corrected"
                unresolved["human_reviewed_at"] = timestamp
        applied += 1
    history["updated_at"] = timestamp
    history["source"] = MANUAL_REVIEW_SOURCE
    history["last_saved_edit_count"] = applied
    history["global_correction_memory_updated"] = False
    output["updated_at"] = timestamp
    report = output.setdefault("processing_report", {})
    report["human_review_corrected_utterances"] = sum(
        1
        for row in rows.values()
        if isinstance(row.get("human_review"), Mapping)
        and row["human_review"].get("status") == "corrected"
    )
    report["manual_review_remaining_utterances"] = sum(
        item["review_status"] == "needs_review" for item in collect_review_items(output)
    )
    report["review_required_utterances"] = report[
        "manual_review_remaining_utterances"
    ]
    return output


def _snapshot(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, value: bytes | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".review-rollback")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_manual_review_edits(
    result: Mapping[str, Any],
    edits: Mapping[str, str],
    autosave_directory: Path | str,
    output_directory: Path | str,
    *,
    source_data: Mapping[str, Any] | None = None,
    reviewed_at: str | None = None,
    final_writer: Callable[[Path, dict[str, Any]], None] = atomic_write_json,
) -> dict[str, Any]:
    prepared = apply_manual_review_edits(result, edits, reviewed_at=reviewed_at)
    prepared = result_with_source_title(
        prepared,
        dict(source_data) if isinstance(source_data, Mapping) else None,
    )
    autosave_target = autosave_path(autosave_directory, prepared)
    output_target = final_json_path(output_directory, prepared)
    autosave_before = _snapshot(autosave_target)
    output_before = _snapshot(output_target)
    try:
        saved_path, saved = atomic_autosave(autosave_directory, prepared)
        final_writer(output_target, saved)
    except Exception:
        _restore(autosave_target, autosave_before)
        _restore(output_target, output_before)
        raise
    return {
        "autosave_path": saved_path,
        "json_path": output_target,
        "saved_result": saved,
        "edit_count": int(saved.get("manual_review", {}).get("last_saved_edit_count") or 0),
    }


def _is_korean_review_result(result: Mapping[str, Any]) -> bool:
    language = str(result.get("source_language") or "").casefold()
    return language.startswith("ko") and result.get("translation_required") is not True


def review_workflow_applicable(result: Mapping[str, Any]) -> bool:
    return _is_korean_review_result(result)


def result_without_reexport_when_unchanged(
    draft: Mapping[str, Any],
    editor_df: Any,
    exporter: Callable[[Any, Any], dict[str, Any]],
) -> dict[str, Any]:
    """Avoid provenance realignment when the legacy editor has no pending edits."""
    if editor_df is None or not hasattr(editor_df, "to_dict"):
        return copy.deepcopy(dict(draft))
    editor_rows = {
        str(row.get("utterance_id") or ""): row
        for row in editor_df.to_dict(orient="records")
        if isinstance(row, Mapping)
    }
    draft_rows = [
        row
        for row in draft.get("normalized_utterances") or []
        if isinstance(row, Mapping)
    ]
    unchanged = len(editor_rows) == len(draft_rows) and all(
        str(
            editor_rows.get(str(row.get("utterance_id") or ""), {}).get(
                "normalized_text"
            )
            or ""
        )
        == str(row.get("normalized_text") or "")
        and str(
            editor_rows.get(str(row.get("utterance_id") or ""), {}).get(
                "review_status"
            )
            or ""
        )
        == str(row.get("review_status") or "")
        for row in draft_rows
    )
    if unchanged:
        return copy.deepcopy(dict(draft))
    return exporter(draft, editor_df)


def _update_editor_dataframe(session_state: MutableMapping[str, Any], saved: Mapping[str, Any]) -> None:
    frame = session_state.get("editor_df")
    if frame is None or not hasattr(frame, "loc") or "utterance_id" not in frame.columns:
        return
    for row in saved.get("normalized_utterances") or []:
        if not isinstance(row, Mapping):
            continue
        mask = frame["utterance_id"] == row.get("utterance_id")
        frame.loc[mask, "normalized_text"] = row.get("normalized_text")
        frame.loc[mask, "review_status"] = row.get("review_status", "approved")
    session_state["editor_df"] = frame


def render_optional_script_review(
    st: Any,
    current_result: dict[str, Any],
    session_state: MutableMapping[str, Any],
    app_directory: Path | str,
    autosave_directory: Path | str,
) -> bool:
    """Render Korean optional review. Return False to use the legacy full editor."""
    if not _is_korean_review_result(current_result):
        return False
    items = initialize_review_session(session_state, current_result)
    pending = pending_session_edits(session_state, current_result, items)
    open_items = [item for item in items if item["review_status"] == "needs_review"]
    high_count = sum(item["severity"] == "high" for item in open_items)
    completed_ids = {
        item["utterance_id"] for item in items if item["review_status"] == "completed"
    }
    modified_count = len(completed_ids | set(pending))

    st.title("전처리 완료")
    st.success("자동으로 정리된 스크립트를 바로 사용할 수 있습니다.")
    st.caption(
        f"검토 필요 {len(open_items)}개 · 높은 우선순위 {high_count}개 · "
        f"사용자 수정 {modified_count}개 · "
        f"남은 검토 {max(0, len(open_items) - len(pending))}개"
    )

    with st.expander("결과 보기", expanded=False):
        st.dataframe(
            [
                {
                    "시간": str(row.get("display_timestamp") or _timestamp(row.get("start_seconds"))),
                    "normalized_text": row.get("normalized_text"),
                }
                for row in current_result.get("normalized_utterances") or []
                if isinstance(row, Mapping)
            ],
            use_container_width=True,
            hide_index=True,
        )
        chapter = current_result.get("processed_chapter") or {}
        st.download_button(
            "현재 저장 상태 JSON 다운로드",
            data=json.dumps(current_result, ensure_ascii=False, indent=2),
            file_name=(
                f"{current_result.get('video_id', 'video')}_"
                f"{chapter.get('chapter_id', 'CH')}_preprocessed_v0_3_16.json"
            ),
            mime="application/json",
            use_container_width=True,
            help="아직 전체 저장을 누르지 않은 수정은 포함되지 않습니다.",
        )

    with st.expander("검토 필요 문장 보기", expanded=False):
        filter_label = st.selectbox(
            "표시 항목",
            ("높은 우선순위", "전체", "수정 안 됨", "수정 완료"),
            key="script_review_filter_" + review_result_fingerprint(current_result)[:16],
        )
        visible: list[dict[str, Any]] = []
        for item in items:
            key = review_session_key(current_result, item["utterance_id"])
            modified = str(session_state.get(key, "")) != item["normalized_text"]
            if filter_label == "높은 우선순위" and not (
                item["severity"] == "high" and item["review_status"] == "needs_review"
            ):
                continue
            if filter_label == "수정 안 됨" and (
                modified or item["review_status"] == "completed"
            ):
                continue
            if filter_label == "수정 완료" and not (
                modified or item["review_status"] == "completed"
            ):
                continue
            visible.append(item)
        if not visible:
            st.info("이 조건에 표시할 검토 문장이 없습니다.")
        for item in visible:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                with left:
                    status = " · 수정됨" if item["utterance_id"] in pending else ""
                    st.caption(
                        f"{item['timestamp']} · {item['severity_label']} · "
                        f"{item['reason']}{status}"
                    )
                with right:
                    seek_url = build_timestamp_url(current_result, item["start_seconds"])
                    if seek_url:
                        st.link_button(
                            "이 구간 듣기",
                            seek_url,
                            use_container_width=True,
                        )
                st.text_area(
                    "현재 문장",
                    key=review_session_key(current_result, item["utterance_id"]),
                    height=100,
                    label_visibility="collapsed",
                )
                with st.expander("자세히 보기", expanded=False):
                    st.caption("원본 YouTube 자막")
                    st.write(item["raw_text"] or "원본 자막 없음")
                    st.caption("Whisper 후보")
                    candidates = [
                        str(candidate.get("candidate_text") or candidate.get("audio_candidate") or "")
                        for candidate in item["whisper_candidates"]
                    ]
                    st.write("\n\n".join(value for value in candidates if value) or "후보 없음")
                    st.caption("자동 수정 기록")
                    st.json(item["automatic_changes"] or [])
                    st.caption("검토 사유")
                    st.write(", ".join(item["reason_codes"]) or item["reason"])

        pending = pending_session_edits(session_state, current_result, items)
        if st.button(
            "수정 내용 모두 저장",
            type="primary",
            use_container_width=True,
            disabled=not pending,
            key="script_review_global_save_" + review_result_fingerprint(current_result)[:16],
        ):
            try:
                package = persist_manual_review_edits(
                    current_result,
                    pending,
                    autosave_directory,
                    Path(app_directory) / "output",
                    source_data=session_state.get("source_data"),
                )
            except Exception as exc:
                st.error("수정 내용을 저장하지 못했습니다. 입력값은 유지됩니다: " + str(exc))
            else:
                saved = package["saved_result"]
                session_state["preprocessing_draft"] = copy.deepcopy(saved)
                _update_editor_dataframe(session_state, saved)
                session_state["last_saved_path"] = str(package["autosave_path"])
                session_state["last_saved_at"] = saved.get("local_autosave", {}).get(
                    "saved_at"
                )
                session_state["script_review_saved_notice"] = {
                    "edit_count": package["edit_count"],
                    "json_path": str(package["json_path"]),
                }
                st.rerun()

    notice = session_state.pop("script_review_saved_notice", None)
    if isinstance(notice, Mapping):
        st.success(f"사용자 수정 {notice.get('edit_count', 0)}개를 한 번에 저장했습니다.")
        st.caption("최종 JSON · " + str(notice.get("json_path") or ""))
    use_legacy = st.checkbox(
        "고급: 전체 결과 편집기 열기",
        value=False,
        key="script_review_legacy_editor_" + review_result_fingerprint(current_result)[:16],
        help="기존 전체 표 편집기가 필요할 때만 엽니다.",
    )
    return not use_legacy
