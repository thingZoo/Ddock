from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from screenshot_runtime import (
    ScreenshotRuntimeError,
    chapter_asset_is_stale,
    generate_screenshot_candidates,
    inspect_screenshot_tools,
    persist_screenshot_assets,
    persist_selected_screenshot_packages,
    prepare_pinned_yt_dlp,
)
from screenshot_output import (
    ScreenshotOutputError,
    legacy_screenshot_directory,
    result_with_source_title,
    resolve_candidate_path,
    resolve_selected_path,
)


_ROLE_LABELS = {
    "primary_anchor": "주요 의미 지점",
    "semantic_alternative": "의미 대안",
}
_PROGRESS_LABELS = {
    "tools_check": "스크린샷 도구 확인 중",
    "video_preparation": "영상 준비 중",
    "extracting": "후보 프레임 추출 중",
    "complete": "스크린샷 후보 생성 완료",
}
_TOOL_STATUS_SESSION_KEY = "v0316_screenshot_tool_status"


def _screenshot_tool_status(session_state: Any) -> dict[str, Any]:
    cached = session_state.get(_TOOL_STATUS_SESSION_KEY)
    if isinstance(cached, dict) and cached.get("ready"):
        return copy.deepcopy(cached)
    tools = inspect_screenshot_tools()
    if tools.get("ready"):
        session_state[_TOOL_STATUS_SESSION_KEY] = copy.deepcopy(tools)
    else:
        session_state.pop(_TOOL_STATUS_SESSION_KEY, None)
    return tools


def _yt_dlp_status_message(status: dict[str, Any]) -> str:
    reason = str(status.get("reason") or "unknown")
    if reason == "sidecar_version_check_timeout":
        seconds = status.get("timeout_seconds")
        return f"yt-dlp 버전 확인이 {seconds:g}초 안에 끝나지 않았습니다."
    if reason.startswith("sidecar_version_check_failed"):
        return "yt-dlp 실행 확인에 실패했습니다: " + reason
    return "yt-dlp 확인 실패 · " + reason


def _candidate_failure_message(stage: Any, reason: Any) -> str:
    stage_value = str(stage or "unknown")
    reason_value = str(reason or "unknown")
    if "utterance_outside_chapter_range" in reason_value or (
        "utterance_does_not_overlap_chapter_range" in reason_value
    ):
        detail = "chapter와 발화 timestamp 범위가 맞지 않아 planning이 중단됐습니다."
    elif reason_value.startswith("chapter_missing_source_utterance_ids"):
        detail = "대표 시점을 계산할 source utterance가 없습니다."
    elif reason_value.startswith("chapter_source_utterances_missing"):
        detail = "content chapter가 참조한 utterance를 현재 결과에서 찾지 못했습니다."
    elif reason_value.startswith("screenshot_source_locator_unavailable"):
        detail = "원본 YouTube URL 또는 video ID를 찾지 못했습니다."
    elif reason_value.startswith("video_download_failed"):
        detail = "스크린샷용 임시 영상을 준비하지 못했습니다."
    elif reason_value.startswith("screenshot_extraction_failed"):
        detail = "ffmpeg frame 추출에 실패했습니다."
    elif reason_value in {"candidate_cache_file_missing", "staged_screenshot_missing"}:
        detail = "생성 기록은 있지만 candidate cache 파일을 찾지 못했습니다."
    else:
        detail = reason_value
    return f"{stage_value} · {detail} ({reason_value})"


def build_screenshot_workflow_view(
    result: dict[str, Any],
    candidate_cache_directory: Path | str,
    output_directory: Path | str | None = None,
) -> dict[str, Any]:
    chapters = [
        chapter
        for chapter in result.get("content_chapters") or []
        if isinstance(chapter, dict)
    ]
    if not chapters:
        return {"visible": False, "items": [], "status": "hidden"}

    assets = result.get("content_chapter_assets")
    assets = assets if isinstance(assets, dict) else {}
    assets_by_id = {
        str(item.get("content_chapter_id") or ""): item
        for item in assets.get("items") or []
        if isinstance(item, dict)
    }
    candidate_cache_root = Path(candidate_cache_directory)
    output_root = Path(
        output_directory
        if output_directory is not None
        else candidate_cache_directory
    )
    items: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_id = str(chapter.get("content_chapter_id") or "")
        asset_item = assets_by_id.get(chapter_id)
        stale = bool(asset_item and chapter_asset_is_stale(result, asset_item))
        retained_selected = (
            asset_item.get("selected_screenshot") if asset_item else None
        )
        selected = retained_selected if not stale else None
        selected_path: Path | None = None
        if isinstance(retained_selected, dict):
            try:
                selected_path = resolve_selected_path(
                    output_root,
                    result,
                    retained_selected,
                )
            except ScreenshotOutputError:
                selected_path = None
        selected_image_available = bool(
            selected_path is not None
            and selected_path.is_file()
            and selected_path.stat().st_size > 0
        )
        final_selection_authoritative = bool(
            not stale
            and isinstance(selected, dict)
            and selected.get("storage_kind") == "final_output"
            and selected_image_available
        )
        candidates: list[dict[str, Any]] = []
        for candidate in (asset_item or {}).get("screenshot_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            relative_path = str(candidate.get("relative_path") or "")
            try:
                path = resolve_candidate_path(
                    candidate_cache_root,
                    output_root,
                    relative_path,
                )
            except ScreenshotOutputError:
                path = candidate_cache_root / "invalid_candidate_path"
            completed = candidate.get("status") == "completed"
            image_available = bool(
                completed and path.is_file() and path.stat().st_size > 0
            )
            display_reason = candidate.get("error")
            if (
                completed
                and not image_available
                and not display_reason
                and not final_selection_authoritative
            ):
                display_reason = "candidate_cache_file_missing"
            candidates.append(
                {
                    "candidate_index": candidate.get("candidate_index"),
                    "source_utterance_id": candidate.get("source_utterance_id"),
                    "target_seconds": candidate.get("target_seconds"),
                    "target_timestamp": candidate.get("target_timestamp"),
                    "selection_role": candidate.get("selection_role"),
                    "role_label": _ROLE_LABELS.get(
                        str(candidate.get("selection_role") or ""),
                        "후보",
                    ),
                    "relative_path": relative_path,
                    "absolute_path": str(path),
                    "status": candidate.get("status"),
                    "error": candidate.get("error"),
                    "display_reason": display_reason,
                    "image_available": image_available,
                }
            )
        candidate_cache_retired = bool(
            final_selection_authoritative
            and candidates
            and not any(candidate["image_available"] for candidate in candidates)
        )
        if candidate_cache_retired:
            candidates = []
        item_warnings = list((asset_item or {}).get("warnings") or [])
        failure_reason = (asset_item or {}).get("failure_reason")
        failure_stage = (asset_item or {}).get("failure_stage")
        if not failure_reason and not candidates and item_warnings:
            failure_reason = item_warnings[0]
            if "screenshot_plan_skipped" in str(failure_reason):
                failure_stage = "candidate_planning"
        items.append(
            {
                "content_chapter_id": chapter_id,
                "title": str(chapter.get("title") or chapter_id),
                "asset_status": (asset_item or {}).get("status", "not_generated"),
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
                "chapter_fingerprint": (asset_item or {}).get(
                    "chapter_fingerprint"
                ),
                "stale": stale,
                "selected_screenshot": copy.deepcopy(selected),
                "retained_selected_screenshot": copy.deepcopy(
                    retained_selected
                ),
                "selected_image_path": (
                    str(selected_path) if selected_path is not None else None
                ),
                "selected_image_available": selected_image_available,
                "final_selection_authoritative": final_selection_authoritative,
                "candidate_cache_retired": candidate_cache_retired,
                "candidates": candidates,
                "warnings": item_warnings,
            }
        )
    return {
        "visible": True,
        "status": assets.get("status", "not_generated"),
        "items": items,
        "warnings": list(assets.get("warnings") or []),
    }


def _update_session_after_save(
    session_state: Any,
    saved: dict[str, Any],
    path: Path,
) -> None:
    draft = session_state.get("preprocessing_draft")
    if isinstance(draft, dict):
        draft["content_chapter_assets"] = copy.deepcopy(
            saved.get("content_chapter_assets")
        )
        if "local_autosave" in saved:
            draft["local_autosave"] = copy.deepcopy(saved["local_autosave"])
        if saved.get("source_title"):
            draft["source_title"] = str(saved["source_title"])
    session_state["last_saved_path"] = str(path)
    session_state["last_saved_at"] = (
        saved.get("local_autosave", {}).get("saved_at")
    )


def _first_runtime_error(assets: dict[str, Any]) -> str:
    warnings = [str(value) for value in assets.get("warnings") or []]
    if not warnings:
        return "원인을 확인할 수 없습니다."
    value = warnings[0]
    if value.startswith("video_download_failed"):
        return "YouTube 영상에 접근하거나 임시 영상을 준비하지 못했습니다."
    if value.startswith("screenshot_tools_unavailable"):
        return "yt-dlp 또는 ffmpeg 도구를 사용할 수 없습니다."
    if value.startswith("screenshot_output_promotion_failed"):
        return "생성한 JPEG를 output 폴더에 저장하지 못했습니다."
    return value


def _generate_and_persist(
    st: Any,
    current_result: dict[str, Any],
    session_state: Any,
    output_directory: Path,
    candidate_cache_directory: Path,
    autosave_directory: Path | str,
    *,
    chapter_ids: list[str] | None = None,
    tools: dict[str, Any] | None = None,
) -> None:
    progress = st.progress(0.0)
    progress_text = st.empty()

    def update_progress(event: dict[str, Any]) -> None:
        total = max(1, int(event.get("total") or 1))
        current = max(0, int(event.get("current") or 0))
        stage = str(event.get("stage") or "")
        progress.progress(min(1.0, current / total))
        label = _PROGRESS_LABELS.get(stage, stage)
        if stage == "extracting":
            progress_text.write(f"{label} · {current}/{total}")
        else:
            progress_text.write(label)

    ready_tools = tools if isinstance(tools, dict) and tools.get("ready") else {}
    yt_dlp = ready_tools.get("yt_dlp") or {}
    ffmpeg = ready_tools.get("ffmpeg") or {}
    assets = generate_screenshot_candidates(
        current_result,
        output_directory,
        candidate_cache_directory=candidate_cache_directory,
        progress_callback=update_progress,
        chapter_ids=chapter_ids,
        yt_dlp_executable=yt_dlp.get("executable_path"),
        ffmpeg_executable=ffmpeg.get("path"),
    )
    if assets.get("status") in {"completed", "partial"}:
        try:
            path, saved = persist_screenshot_assets(
                current_result,
                assets,
                autosave_directory,
            )
            _update_session_after_save(session_state, saved, path)
        except Exception as exc:
            st.error(f"스크린샷 결과 저장 실패 · {exc}")
        else:
            progress.progress(1.0)
            st.success("대표 스크린샷 후보 생성을 완료했습니다.")
            st.rerun()
    else:
        st.error("스크린샷 생성 실패 · " + _first_runtime_error(assets))


def render_screenshot_workflow(
    st: Any,
    current_result: dict[str, Any],
    session_state: Any,
    app_directory: Path | str,
    autosave_directory: Path | str,
) -> None:
    current_result = result_with_source_title(
        current_result,
        session_state.get("source_data"),
    )
    output_directory = Path(app_directory) / "output"
    candidate_cache_directory = (
        Path(autosave_directory) / "screenshot_candidates"
    )
    view = build_screenshot_workflow_view(
        current_result,
        candidate_cache_directory,
        output_directory,
    )
    if not view["visible"]:
        return

    st.divider()
    st.subheader("대표 스크린샷")
    st.caption(
        "최종 content chapter마다 의미가 다른 후보를 최대 3장 생성합니다. "
        "최종 대표 이미지는 직접 선택해 저장합니다."
    )
    saved_notice = session_state.pop(
        "v0316_screenshot_saved_notice",
        None,
    )
    if isinstance(saved_notice, dict):
        st.success(
            "대표 이미지 저장 완료: "
            f"{saved_notice.get('success_count', 0)} / "
            f"{saved_notice.get('requested_count', 0)}"
        )
        if saved_notice.get("relative_path"):
            st.caption("최종 저장 위치 · " + str(saved_notice["relative_path"]))
        for failure in saved_notice.get("failures") or []:
            st.error(
                f"{failure.get('content_chapter_id')} · "
                f"{failure.get('reason')}"
            )
        for failure in saved_notice.get("cleanup_failures") or []:
            st.warning(
                f"{failure.get('content_chapter_id')} candidate cache 정리 보류 · "
                f"{failure.get('reason')}"
            )

    legacy_directory = legacy_screenshot_directory(output_directory)
    if legacy_directory is not None:
        st.caption(
            "기존 방식의 screenshot 후보가 감지되었습니다. "
            "기존 파일은 유지하며 새 저장부터 video/chapter별 결과 폴더를 사용합니다."
        )

    tools = _screenshot_tool_status(session_state)
    sidecar = tools["yt_dlp"]
    ffmpeg = tools["ffmpeg"]
    if not sidecar["available"]:
        reason = str(sidecar.get("reason") or "")
        can_prepare = reason in {
            "sidecar_not_installed",
            "sidecar_metadata_unavailable",
            "sidecar_metadata_invalid",
            "sidecar_metadata_version_mismatch",
            "sidecar_executable_version_mismatch",
        }
        if can_prepare:
            st.warning("최초 1회 스크린샷 도구 준비가 필요합니다.")
            if st.button(
                "스크린샷 도구 준비",
                key="v0316_prepare_screenshot_tools",
            ):
                try:
                    with st.spinner("공식 yt-dlp 고정 버전을 준비하는 중입니다..."):
                        prepare_pinned_yt_dlp()
                except Exception as exc:
                    st.error(f"스크린샷 도구 준비 실패 · {exc}")
                else:
                    session_state.pop(_TOOL_STATUS_SESSION_KEY, None)
                    st.success("스크린샷 도구 준비를 완료했습니다.")
                    st.rerun()
        else:
            st.error(_yt_dlp_status_message(sidecar))
    else:
        st.caption(
            "yt-dlp " + str(sidecar.get("version") or "") + " · 자동 업데이트 안 함"
        )

    if not ffmpeg["available"]:
        st.error(
            "ffmpeg가 필요합니다. Homebrew의 ffmpeg를 설치한 뒤 앱을 다시 확인해 주세요."
        )

    generate_disabled = not tools["ready"]
    if st.button(
        "대표 스크린샷 후보 생성",
        type="primary",
        width="stretch",
        disabled=generate_disabled,
        key="v0316_generate_screenshot_candidates",
    ):
        _generate_and_persist(
            st,
            current_result,
            session_state,
            output_directory,
            candidate_cache_directory,
            autosave_directory,
            tools=tools,
        )

    pending_selections: dict[str, int] = {}
    selected_count = 0
    selection_target_count = sum(
        1 for item in view["items"] if not item["stale"]
    )
    for item in view["items"]:
        with st.container(border=True):
            st.markdown(
                f"#### {item['content_chapter_id']} · {item['title']}"
            )
            if item["stale"]:
                st.warning(
                    "STALE · content chapter가 변경되어 기존 후보와 선택을 신뢰할 수 없습니다. "
                    "후보를 다시 생성해 주세요."
                )
            if item["selected_image_available"]:
                if item["stale"]:
                    st.info(
                        "기존 저장 이미지는 보존되어 있지만 현재 chapter의 "
                        "선택으로 신뢰하지 않습니다. 후보를 다시 생성해 주세요."
                    )
                else:
                    st.success("대표 이미지 저장됨")
                st.image(item["selected_image_path"], width="stretch")
                try:
                    display_path = Path(item["selected_image_path"]).relative_to(
                        Path(app_directory)
                    )
                except ValueError:
                    display_path = Path(item["selected_image_path"])
                st.caption("최종 경로 · " + str(display_path))
            candidates = item["candidates"]
            if not candidates:
                if item["final_selection_authoritative"]:
                    selected_count += 1
                    st.caption(
                        "선택 저장이 완료되어 이 chapter의 candidate cache를 정리했습니다."
                    )
                elif item["asset_status"] == "not_generated":
                    st.info("아직 이 chapter의 스크린샷 후보를 생성하지 않았습니다.")
                elif item.get("failure_reason"):
                    st.error(
                        "스크린샷 후보 없음 · "
                        + _candidate_failure_message(
                            item.get("failure_stage"),
                            item.get("failure_reason"),
                        )
                    )
                else:
                    st.warning(
                        "스크린샷 후보가 생성되지 않았지만 저장된 실패 이유가 없습니다. "
                        f"status={item['asset_status']}"
                    )
            else:
                columns = st.columns(max(1, len(candidates)))
                selectable: list[int] = []
                for column, candidate in zip(columns, candidates):
                    with column:
                        st.caption(
                            f"후보 {candidate['candidate_index']} · "
                            f"{candidate['role_label']} · "
                            f"{candidate['target_timestamp']}"
                        )
                        if candidate["image_available"]:
                            st.image(
                                candidate["absolute_path"],
                                width="stretch",
                            )
                            selectable.append(int(candidate["candidate_index"]))
                        elif candidate["status"] == "failed":
                            st.error(
                                "이 후보 추출에 실패했습니다. · "
                                + _candidate_failure_message(
                                    "candidate_extraction",
                                    candidate.get("display_reason"),
                                )
                            )
                        elif candidate.get("display_reason"):
                            st.error(
                                _candidate_failure_message(
                                    "cache_load",
                                    candidate.get("display_reason"),
                                )
                            )
                        elif candidate["status"] == "skipped":
                            st.warning("이 후보는 이전 오류 때문에 건너뛰었습니다.")
                        else:
                            st.info(
                                "후보는 계획됐지만 아직 frame extraction을 실행하지 않았습니다."
                            )
                if not selectable:
                    st.info(
                        "선택 가능한 후보가 없습니다. 다른 chapter는 계속 사용할 수 있습니다."
                    )
                else:
                    selected = item.get("selected_screenshot") or {}
                    selected_index = selected.get(
                        "source_candidate_index",
                        selected.get("candidate_index"),
                    )
                    default_index = (
                        selectable.index(selected_index)
                        if selected_index in selectable and not item["stale"]
                        else 0
                    )
                    choice_key = (
                        "v0316_screenshot_choice_"
                        + item["content_chapter_id"]
                        + "_"
                        + str(item.get("chapter_fingerprint") or "none")[:12]
                    )
                    choice = st.radio(
                        "대표 이미지 선택",
                        options=selectable,
                        index=default_index,
                        format_func=lambda value: f"후보 {value}",
                        horizontal=True,
                        key=choice_key,
                        disabled=item["stale"],
                    )
                    if not item["stale"]:
                        pending_selections[item["content_chapter_id"]] = int(choice)
                        selected_count += 1
            if st.button(
                "이 chapter 후보 다시 생성",
                key="v0316_regenerate_screenshot_" + item["content_chapter_id"],
                disabled=generate_disabled,
            ):
                _generate_and_persist(
                    st,
                    current_result,
                    session_state,
                    output_directory,
                    candidate_cache_directory,
                    autosave_directory,
                    chapter_ids=[item["content_chapter_id"]],
                    tools=tools,
                )

    st.markdown(
        f"대표 이미지 선택 **{selected_count} / {selection_target_count}**"
    )
    if st.button(
        "선택한 대표 이미지 모두 저장",
        type="primary",
        width="stretch",
        disabled=not pending_selections,
        key="v0316_save_all_screenshots",
    ):
        try:
            package = persist_selected_screenshot_packages(
                current_result,
                pending_selections,
                candidate_cache_directory,
                output_directory,
                autosave_directory,
            )
            if package["success_count"]:
                saved = package["saved_result"]
                _update_session_after_save(
                    session_state,
                    saved,
                    package["autosave_path"],
                )
                output_path = package["json_path"].parent
                try:
                    relative_output = output_path.relative_to(Path(app_directory))
                except ValueError:
                    relative_output = output_path
                session_state["v0316_screenshot_saved_notice"] = {
                    "success_count": package["success_count"],
                    "requested_count": package["requested_count"],
                    "relative_path": str(relative_output),
                    "failures": copy.deepcopy(package["failures"]),
                    "cleanup_failures": copy.deepcopy(
                        package["cleanup_failures"]
                    ),
                }
        except ScreenshotRuntimeError as exc:
            st.error(f"대표 이미지 일괄 저장 실패 · {exc}")
        except Exception as exc:
            st.error(
                "대표 이미지 일괄 저장 실패 · "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            if package["success_count"]:
                st.rerun()
            else:
                st.error(
                    "대표 이미지를 저장하지 못했습니다. preflight 결과를 확인해 주세요."
                )
                for failure in package["failures"]:
                    st.error(
                        f"{failure.get('content_chapter_id')} · "
                        f"{failure.get('reason')}"
                    )
