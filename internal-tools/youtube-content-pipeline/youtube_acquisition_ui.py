from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from youtube_acquisition_runtime import (
    AcquisitionRuntimeError,
    acquisition_fingerprint,
    collect_from_youtube,
    preprocessing_eligible,
    save_collection_backup,
    validate_collection_result,
)


ACQUISITION_RESULT_KEY = "v0316_acquisition_result"
WORKFLOW_FINGERPRINT_KEY = "v0316_workflow_source_fingerprint"
WORKFLOW_VIDEO_ID_KEY = "v0316_workflow_video_id"
WORKFLOW_STAGE_KEY = "v0316_workflow_stage"
_DOWNSTREAM_STATE_KEYS = (
    "preprocessing_draft",
    "editor_df",
    "last_saved_path",
    "last_saved_at",
    "source_chapter_index",
    "translation_workload_estimate",
)
_DOWNSTREAM_KEY_PREFIXES = (
    "whole_chapter_editor_",
    "v0316_preprocessing_scope_",
    "v0316_screenshot_choice_",
    "v0316_save_screenshot_",
    "v0316_regenerate_screenshot_",
)
_PROGRESS = {
    "video_info": (0.2, "영상 정보 확인 중"),
    "creator_chapters": (0.45, "챕터 확인 중"),
    "transcript": (0.7, "자막 가져오는 중"),
    "complete": (1.0, "원본 수집 완료"),
}


def _format_duration(value: Any) -> str:
    if value is None:
        return "확인 불가"
    try:
        return str(timedelta(seconds=max(0, int(float(value)))))
    except (TypeError, ValueError):
        return "확인 불가"


def _clear_downstream_state(session_state: Any) -> None:
    for key in _DOWNSTREAM_STATE_KEYS:
        session_state.pop(key, None)
    for key in list(session_state.keys()):
        if any(str(key).startswith(prefix) for prefix in _DOWNSTREAM_KEY_PREFIXES):
            session_state.pop(key, None)


def begin_acquisition_workflow(
    session_state: Any,
    result: dict[str, Any],
) -> bool:
    errors = validate_collection_result(result)
    if errors:
        raise AcquisitionRuntimeError(
            "collection JSON 형식이 올바르지 않습니다: " + ", ".join(errors)
        )
    fingerprint = acquisition_fingerprint(result)
    previous = session_state.get(WORKFLOW_FINGERPRINT_KEY)
    existing_source = session_state.get("source_data")
    if previous is None and isinstance(existing_source, dict):
        if not validate_collection_result(existing_source):
            previous = acquisition_fingerprint(existing_source)
    changed = bool(previous and previous != fingerprint)
    if changed:
        _clear_downstream_state(session_state)
    metadata = result.get("metadata") or {}
    session_state["source_data"] = result
    session_state[ACQUISITION_RESULT_KEY] = result
    session_state[WORKFLOW_FINGERPRINT_KEY] = fingerprint
    session_state[WORKFLOW_VIDEO_ID_KEY] = metadata.get("video_id")
    session_state[WORKFLOW_STAGE_KEY] = "acquisition_ready"
    return changed


def clear_workflow_for_new_video(session_state: Any) -> None:
    _clear_downstream_state(session_state)
    for key in (
        "source_data",
        ACQUISITION_RESULT_KEY,
        WORKFLOW_FINGERPRINT_KEY,
        WORKFLOW_VIDEO_ID_KEY,
        WORKFLOW_STAGE_KEY,
    ):
        session_state.pop(key, None)


def _read_uploaded_collection(uploaded: Any) -> dict[str, Any]:
    try:
        uploaded.seek(0)
        value = json.load(uploaded)
    except Exception as exc:
        raise AcquisitionRuntimeError(f"collection JSON을 읽지 못했습니다: {exc}") from exc
    if not isinstance(value, dict):
        raise AcquisitionRuntimeError("collection JSON 최상위 값은 object여야 합니다.")
    return value


def _api_key_from_environment_or_secrets(st: Any) -> str:
    value = str(os.environ.get("YOUTUBE_DATA_API_KEY") or "").strip()
    if value:
        return value
    try:
        return str(st.secrets.get("YOUTUBE_DATA_API_KEY") or "").strip()
    except Exception:
        return ""


def _render_collection_summary(st: Any, result: dict[str, Any]) -> None:
    metadata = result.get("metadata") or {}
    transcript = result.get("transcript") or {}
    chapters = result.get("creator_chapters") or []
    st.success("YouTube 원본 수집 완료")
    st.markdown(f"### {metadata.get('title') or '제목 없음'}")
    first, second, third, fourth = st.columns(4)
    first.metric("영상 길이", _format_duration(metadata.get("duration_seconds")))
    second.metric(
        "언어",
        transcript.get("language_code")
        or metadata.get("default_audio_language")
        or "확인 불가",
    )
    third.metric("제작자 챕터", "있음" if chapters else "없음")
    fourth.metric("챕터 수", len(chapters))
    st.caption(
        f"video_id: {metadata.get('video_id') or 'unknown'} · "
        f"자막 segment: {len(transcript.get('items') or [])}"
    )


def _render_primary_acquisition(
    st: Any,
    session_state: Any,
    app_directory: Path,
) -> None:
    st.title("YouTube 스크립트 통합 전처리 v0.3.16")
    st.caption("YouTube URL에서 원본 수집부터 전처리·검수·대표 이미지 선택까지 이어집니다.")
    video_url = st.text_input(
        "YouTube URL",
        placeholder="https://www.youtube.com/watch?v=...",
        key="v0316_youtube_url",
    )
    configured_api_key = _api_key_from_environment_or_secrets(st)
    api_key = st.text_input(
        "YouTube Data API 키",
        type="password",
        help=(
            "기존 원본 수집기가 영상 metadata를 확인할 때 사용합니다. "
            "YOUTUBE_DATA_API_KEY 환경변수 또는 Streamlit secrets로도 설정할 수 있습니다."
        ),
        key="v0316_youtube_api_key",
    )
    if configured_api_key and not api_key:
        st.caption("환경 설정에 저장된 YouTube Data API 키를 사용합니다.")
    with st.expander("수집 옵션", expanded=False):
        languages = st.multiselect(
            "자막 우선 언어",
            options=["ko", "en", "ja", "zh-Hans", "zh-Hant"],
            default=["ko", "en"],
            key="v0316_acquisition_languages",
        )

    if st.button(
        "영상 불러오기",
        type="primary",
        width="stretch",
        key="v0316_load_youtube_video",
    ):
        resolved_key = str(api_key or configured_api_key).strip()
        if not str(video_url or "").strip():
            st.error("YouTube URL을 입력해 주세요.")
        elif not resolved_key:
            st.error("YouTube Data API 키를 입력하거나 환경 설정에 등록해 주세요.")
        else:
            progress = st.progress(0.0)
            status = st.empty()

            def update_progress(event: dict[str, Any]) -> None:
                stage = str(event.get("stage") or "")
                value, label = _PROGRESS.get(stage, (0.0, stage))
                progress.progress(value)
                status.write(label)

            try:
                result = collect_from_youtube(
                    video_url,
                    resolved_key,
                    preferred_languages=languages or ["ko", "en"],
                    project_directory=app_directory,
                    progress_callback=update_progress,
                )
                save_collection_backup(result, app_directory / "output")
                begin_acquisition_workflow(session_state, result)
            except AcquisitionRuntimeError as exc:
                st.error(f"YouTube 원본 수집 실패 · {exc}")
            except Exception as exc:
                st.error(f"YouTube 원본 수집 실패 · {type(exc).__name__}: {exc}")
            else:
                progress.progress(1.0)
                status.success("원본 수집 완료")
                st.rerun()

    with st.expander("고급: 기존 collection JSON 직접 사용", expanded=False):
        uploaded = st.file_uploader(
            "youtube_acquisition_validation_v0.1 collection JSON",
            type=["json", "txt"],
            key="v0316_collection_json_upload",
        )
        if uploaded is not None and st.button(
            "이 collection JSON 사용",
            key="v0316_use_collection_json",
        ):
            try:
                result = _read_uploaded_collection(uploaded)
                begin_acquisition_workflow(session_state, result)
            except AcquisitionRuntimeError as exc:
                st.error(str(exc))
            else:
                st.success("collection JSON을 불러왔습니다.")
                st.rerun()


def render_integrated_entry(
    st: Any,
    session_state: Any,
    render_preprocessing_setup: Callable[[], None],
    app_directory: Path | str,
) -> None:
    app_root = Path(app_directory)
    source = session_state.get("source_data")
    if not isinstance(source, dict):
        _render_primary_acquisition(st, session_state, app_root)
        return

    if validate_collection_result(source):
        st.error("현재 source_data가 지원하는 collection schema가 아닙니다.")
        if st.button("YouTube URL 입력으로 돌아가기"):
            clear_workflow_for_new_video(session_state)
            st.rerun()
        return

    if ACQUISITION_RESULT_KEY not in session_state:
        begin_acquisition_workflow(session_state, source)
    _render_collection_summary(st, source)
    if st.button(
        "다른 YouTube URL 입력",
        key="v0316_change_youtube_video",
    ):
        clear_workflow_for_new_video(session_state)
        st.rerun()
    if not preprocessing_eligible(source):
        transcript = source.get("transcript") or {}
        st.error(
            "자막을 확보하지 못해 전처리를 시작할 수 없습니다. "
            f"status={transcript.get('status') or 'unknown'}"
        )
        return

    st.divider()
    st.subheader("전처리 설정")
    render_preprocessing_setup()
