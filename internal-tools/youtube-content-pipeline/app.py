
from __future__ import annotations

from pathlib import Path
import json
import time
from datetime import datetime, timedelta
import streamlit as st

from preprocessor import (
    build_preprocessing_draft,
    compare_with_gold,
    detect_document_kind,
    estimate_translation_workload,
    get_builtin_verified_profile_info,
    prepare_existing_preprocessing,
    source_language_code,
    source_language_label,
    translation_required_for_source,
)
from review_store import (
    atomic_autosave,
    current_result,
    dataframe_from_draft,
    load_autosave,
)


APP_DIR = Path(__file__).resolve().parent
AUTOSAVE_DIR = APP_DIR / "autosave"


def _format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"
    if minutes:
        return f"{minutes}분 {secs}초" if secs else f"{minutes}분"
    return f"{secs}초"


def _format_clock_after(seconds):
    target = datetime.now() + timedelta(seconds=max(0, float(seconds or 0)))
    return target.strftime("%H:%M")

st.set_page_config(
    page_title="스크립트 전처리 v0.3.4",
    page_icon="📝",
    layout="wide",
)


def parse_uploaded_json(uploaded):
    try:
        uploaded.seek(0)
        return json.load(uploaded)
    except Exception as exc:
        st.error(
            f"JSON을 읽지 못했습니다: {exc}"
        )
        return None


def begin_review(
    draft,
    source=None,
    chapter_index=None,
):
    st.session_state[
        "preprocessing_draft"
    ] = draft
    review_df = dataframe_from_draft(draft)
    if (
        draft.get("processed_chapter", {}).get("chapter_id") == "FULL"
        and draft.get("translation_scope") == "whole_video"
        and len(review_df) == len(draft.get("normalized_utterances", []))
    ):
        chapter_values = []
        for item in draft.get("normalized_utterances", []):
            chapter_id = item.get("chapter_id", "")
            chapter_label = item.get("chapter_label", "") or ""
            chapter_values.append(
                f"{chapter_id} · {chapter_label}".strip(" ·")
            )
        review_df.insert(3, "chapter", chapter_values)
    st.session_state[
        "editor_df"
    ] = review_df

    if source is not None:
        st.session_state[
            "source_data"
        ] = source

    if chapter_index is not None:
        st.session_state[
            "source_chapter_index"
        ] = chapter_index

    st.session_state[
        "last_saved_path"
    ] = None
    st.session_state[
        "last_saved_at"
    ] = None


def leave_review():
    st.session_state.pop(
        "preprocessing_draft",
        None,
    )
    st.session_state.pop(
        "editor_df",
        None,
    )


def render_setup():
    st.title(
        "YouTube 스크립트 전처리 도구 v0.3.4"
    )
    st.caption(
        "한 챕터 전체를 한 화면에서 "
        "위→아래로 계속 들으며 수정합니다. "
        "제작자 챕터가 없으면 전체 영상을 한 번에 검수합니다."
    )

    source = st.session_state.get(
        "source_data"
    )

    if source is None:
        uploaded = st.file_uploader(
            "원본 수집 JSON 또는 기존 검수 JSON 업로드",
            type=["json", "txt"],
        )
        if uploaded is None:
            return

        parsed = parse_uploaded_json(
            uploaded
        )
        if parsed is None:
            return

        kind = detect_document_kind(
            parsed
        )

        if kind == "acquisition":
            st.session_state[
                "source_data"
            ] = parsed
            st.rerun()

        elif kind == "preprocessing":
            if st.button(
                "기존 검수본 불러오기",
                type="primary",
            ):
                begin_review(
                    prepare_existing_preprocessing(
                        parsed
                    )
                )
                st.rerun()
        else:
            st.error(
                "지원하는 JSON 형식이 아닙니다."
            )
        return

    if detect_document_kind(
        source
    ) != "acquisition":
        st.error(
            "원본 수집 JSON이 아닙니다."
        )
        if st.button(
            "원본 초기화"
        ):
            st.session_state.pop(
                "source_data",
                None,
            )
            st.rerun()
        return

    metadata = source.get(
        "metadata",
        {},
    )
    st.success(
        "원본 유지 중 · "
        + str(
            metadata.get(
                "title",
                metadata.get(
                    "video_id",
                    "",
                ),
            )
        )
    )

    chapters = source.get(
        "creator_chapters",
        [],
    )

    if chapters:
        labels = [
            (
                f"{chapter.get('timestamp_text', '')}"
                f" · "
                f"{chapter.get('label', f'챕터 {index + 1}')}"
            )
            for index, chapter in enumerate(
                chapters
            )
        ]
        default_index = min(
            st.session_state.get(
                "source_chapter_index",
                0,
            ),
            len(labels) - 1,
        )
        chapter_index = st.selectbox(
            "챕터 선택",
            options=list(
                range(len(labels))
            ),
            index=default_index,
            format_func=lambda index: labels[
                index
            ],
        )
        creator_id = (
            f"CH-{chapter_index + 1:02d}"
        )
        processing_scope_label = "챕터 전체"
    else:
        chapter_index = 0
        creator_id = "FULL"
        duration = metadata.get(
            "duration_seconds"
        )
        duration_text = ""
        if duration is not None:
            total = max(0, int(float(duration)))
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            duration_text = (
                f" · {hours:02d}:{minutes:02d}:{seconds:02d}"
                if hours
                else f" · {minutes:02d}:{seconds:02d}"
            )
        st.info(
            "제작자 챕터 없음 · 전체 영상으로 검수합니다"
            + duration_text
        )
        processing_scope_label = "전체 영상"

    video_id = metadata.get(
        "video_id",
        "",
    )

    builtin = (
        get_builtin_verified_profile_info(
            video_id,
            creator_id,
        )
        if creator_id != "FULL"
        else None
    )

    target_id = (
        builtin.get("chapter_id")
        if builtin
        else creator_id
    )

    if builtin:
        st.success(
            "내장 승인 기준본 · "
            f"{builtin.get('gold_revision')} · "
            f"{builtin.get('utterance_count')}개 발화"
        )
    else:
        st.info(
            "새 영상/새 검수 구간입니다. "
            "검증한 고유명사·붙여쓰기·더듬기 규칙을 "
            "범용 초안에 적용합니다."
        )

    needs_translation = translation_required_for_source(
        source
    )
    source_lang = source_language_code(source)
    source_lang_label = source_language_label(source)

    translate_foreign = False
    translation_scope = "chapter"
    local_translation_model = "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"

    if needs_translation:
        st.warning(
            "외국어 자막 감지 · "
            f"{source_lang_label} ({source_lang or 'unknown'})"
        )
        with st.expander(
            "외국어 → 한국어 문맥형 로컬 LLM 전처리",
            expanded=True,
        ):
            translate_foreign = st.checkbox(
                "자연스러운 한국어 번역 초안 생성",
                value=True,
            )
            if chapters:
                scope_label = st.radio(
                    "번역 범위",
                    options=["선택한 챕터만", "전체 영상"],
                    index=0,
                    horizontal=True,
                    help=(
                        "전체 영상은 한 번 클릭으로 영상 전체를 번역·전처리합니다. "
                        "누락 방지를 위해 내부적으로 여러 배치로 처리할 수 있지만 "
                        "전체/인접 문맥을 공유하고 하나의 FULL 검수본으로 만듭니다."
                    ),
                )
                translation_scope = (
                    "whole_video" if scope_label == "전체 영상" else "chapter"
                )
            else:
                translation_scope = "whole_video"
                st.info("제작자 챕터가 없어 전체 영상 번역으로 처리합니다.")

            st.checkbox(
                "번역 후 자동 안전 검사",
                value=True,
                disabled=True,
                help=(
                    "Qwen3 1-pass 번역 뒤 중국어 혼입, 공식명 표기, 실무 용어, "
                    "숫자·UI 대상·copy/paste 같은 구체 정보 누락 가능성을 기계적으로 검사합니다. "
                    "매번 2차 LLM 재작성은 하지 않습니다."
                ),
            )
            st.text_input(
                "로컬 번역 모델",
                value=local_translation_model,
                disabled=True,
                help=(
                    "API Key 없이 Mac의 Apple Silicon에서 직접 실행합니다. "
                    "첫 실행 때 약 8GB 규모의 4-bit 모델을 한 번 내려받습니다."
                ),
            )
            st.caption(
                "API Key가 필요 없습니다. 30분 이하 영상은 선택한 챕터만 번역해도 전체 영상 문맥을 참고합니다. "
                "전체 영상 번역도 같은 문맥 원칙을 사용하되 결과 범위만 전체 영상으로 확장합니다. "
                "Qwen3가 한 번에 자연스러운 한국어 초안을 만든 뒤 언어·공식명·실무 용어·정보 보존 안전 검사를 적용합니다. "
                "제작자 챕터와 원문·타임스탬프는 그대로 보존합니다."
            )
            st.caption(
                "기본 모델은 Qwen3 30B-A3B Instruct 2507 4-bit(MLX)입니다. "
                "A/B 비교에서 선택한 B 모델이며, 이미 같은 Mac에서 모델을 내려받았다면 Hugging Face 로컬 캐시를 재사용하므로 다시 17GB를 받을 필요가 없습니다. "
                "앱을 새로 실행할 때 메모리 로딩 시간은 조금 필요할 수 있습니다."
            )
            try:
                workload = estimate_translation_workload(
                    source,
                    chapter_index=chapter_index,
                    translation_scope=translation_scope,
                )
                st.session_state["translation_workload_estimate"] = workload
                low_text = _format_duration(workload.get("initial_low_seconds"))
                high_text = _format_duration(workload.get("initial_high_seconds"))
                st.info(
                    f"초기 예상 소요 시간: 약 {low_text} ~ {high_text} · "
                    f"{workload.get('batch_count', 1)}개 배치 × 1회 Qwen3 번역 "
                    f"({workload.get('total_passes', 1)}회 로컬 LLM 처리). "
                    "첫 배치가 끝나면 이 Mac의 실제 처리 속도로 남은 시간을 자동 보정합니다."
                )
            except Exception:
                st.session_state.pop("translation_workload_estimate", None)

    autosave_target_id = (
        "FULL"
        if needs_translation and translate_foreign and translation_scope == "whole_video"
        else target_id
    )
    autosave = (
        AUTOSAVE_DIR
        / f"{video_id}_{autosave_target_id}_autosave.json"
    )

    if autosave.exists():
        st.warning(
            "이 검수 구간의 저장본이 있습니다."
        )
        if st.button(
            "저장본 이어서 검수",
            type="primary",
        ):
            saved = load_autosave(
                autosave
            )
            begin_review(
                prepare_existing_preprocessing(
                    saved
                ),
                source=source,
                chapter_index=chapter_index,
            )
            st.session_state[
                "last_saved_path"
            ] = str(autosave)
            st.rerun()

    with st.expander(
        "고급 옵션",
        expanded=False,
    ):
        use_profile = st.checkbox(
            "검증 기반 롱폼 분리 프로필",
            value=True,
        )
        apply_same = st.checkbox(
            "동일 구간 승인 프로필 적용",
            value=True,
        )
        auto_builtin = st.checkbox(
            "내장 승인 프로필 자동 적용",
            value=True,
        )
        reuse_status = st.checkbox(
            "승인 상태까지 재사용",
            value=False,
        )
        glossary = st.text_area(
            "추가 용어 사전",
            value="",
            placeholder=(
                "이 영상에만 새로 등장한 "
                "확실한 고유명사가 있을 때만 입력"
            ),
        )

    button_label = (
        (
            "전체 영상 한국어 번역 + 전처리 초안 만들기"
            if translation_scope == "whole_video"
            else "선택한 챕터 한국어 번역 + 전처리 초안 만들기"
        )
        if needs_translation and translate_foreign
        else f"{processing_scope_label} 전처리"
    )

    if st.button(
        button_label,
        type="primary",
        use_container_width=True,
    ):
        try:
            spinner_text = (
                "문맥을 읽어 Qwen3로 자연스러운 한국어 초안을 만드는 중입니다..."
                if needs_translation and translate_foreign
                else "전처리 초안을 만드는 중입니다..."
            )
            progress_bar = None
            progress_status = None
            eta_status = None
            run_started = time.perf_counter()

            def translation_progress(event):
                nonlocal progress_bar, progress_status, eta_status
                if progress_bar is None:
                    progress_bar = st.progress(0.0)
                    progress_status = st.empty()
                    eta_status = st.empty()

                total_steps = max(1, int(event.get("total_steps", 1)))
                completed = max(0, int(event.get("completed_steps", 0)))
                batch_index_now = int(event.get("batch_index", 1))
                total_batches_now = int(event.get("total_batches", 1))
                stage = event.get("stage", "준비")
                progress_bar.progress(min(1.0, completed / total_steps))
                progress_status.write(
                    f"배치 {batch_index_now}/{total_batches_now} · {stage} "
                    f"· 전체 {completed}/{total_steps}단계 완료"
                )

                elapsed = time.perf_counter() - run_started
                if completed > 0:
                    seconds_per_step = elapsed / completed
                    remaining = seconds_per_step * max(0, total_steps - completed)
                    eta_status.info(
                        f"경과 {_format_duration(elapsed)} · "
                        f"예상 남은 시간 약 {_format_duration(remaining)} · "
                        f"예상 완료 {_format_clock_after(remaining)} 전후"
                    )
                else:
                    estimate = st.session_state.get("translation_workload_estimate", {})
                    low = estimate.get("initial_low_seconds")
                    high = estimate.get("initial_high_seconds")
                    if low and high:
                        eta_status.info(
                            f"초기 예상 {_format_duration(low)} ~ {_format_duration(high)}. "
                            "첫 1차 번역이 끝나면 실제 속도로 ETA를 다시 계산합니다."
                        )

            with st.spinner(spinner_text):
                draft = build_preprocessing_draft(
                    source,
                    chapter_index=chapter_index,
                    custom_glossary_text=glossary,
                    use_validated_profile=use_profile,
                    apply_verified_same_chapter=apply_same,
                    reuse_approval_status=reuse_status,
                    auto_apply_builtin_profile=auto_builtin,
                    translate_foreign_to_korean=(
                        needs_translation
                        and translate_foreign
                    ),
                    translation_local_model=local_translation_model,
                    translation_scope=translation_scope,
                    progress_callback=(
                        translation_progress
                        if needs_translation and translate_foreign
                        else None
                    ),
                )
            if progress_bar is not None:
                progress_bar.progress(1.0)
                total_elapsed = time.perf_counter() - run_started
                progress_status.success(
                    f"Qwen3 번역·안전 검사 완료 · 총 {_format_duration(total_elapsed)}"
                )
                eta_status.empty()
        except Exception as exc:
            st.error(
                "전처리 초안을 만들지 못했습니다: "
                f"{exc}"
            )
            return

        begin_review(
            draft,
            source=source,
            chapter_index=chapter_index,
        )
        st.rerun()

    if st.button(
        "다른 원본 파일 사용"
    ):
        st.session_state.pop(
            "source_data",
            None,
        )
        st.rerun()

def commit_review(
    edited_df,
    approve_all=False,
):
    saved_df = edited_df.copy()

    if approve_all:
        saved_df[
            "review_status"
        ] = "approved"

    st.session_state[
        "editor_df"
    ] = saved_df

    result = current_result(
        st.session_state[
            "preprocessing_draft"
        ],
        saved_df,
    )

    path, result = atomic_autosave(
        AUTOSAVE_DIR,
        result,
    )

    st.session_state[
        "last_saved_path"
    ] = str(path)
    st.session_state[
        "last_saved_at"
    ] = result.get(
        "local_autosave",
        {},
    ).get("saved_at")

    return result


def render_review():
    draft = st.session_state[
        "preprocessing_draft"
    ]
    editor_df = st.session_state[
        "editor_df"
    ]
    chapter = draft.get(
        "processed_chapter",
        {},
    )

    is_full_video = chapter.get("chapter_id") == "FULL"
    is_translation = bool(draft.get("translation_required"))

    st.title(
        "전체 영상 검수"
        if is_full_video
        else "챕터 전체 검수"
    )

    top_left, top_right = st.columns(
        [5, 1]
    )

    with top_left:
        st.caption(
            f"{chapter.get('chapter_id', '')}"
            f" · "
            f"{chapter.get('label', '')}"
        )

    with top_right:
        if st.button(
            "챕터 다시 선택",
            use_container_width=True,
            help=(
                "현재 수정 내용을 저장하지 않았다면 "
                "먼저 아래 저장 버튼을 눌러 주세요."
            ),
        ):
            leave_review()
            st.rerun()

    total = len(editor_df)
    approved = int(
        (
            editor_df[
                "review_status"
            ]
            == "approved"
        ).sum()
    )
    remaining = total - approved

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "전체 발화",
        total,
    )
    m2.metric(
        "승인",
        approved,
    )
    m3.metric(
        "미승인",
        remaining,
    )

    if is_translation:
        st.info(
            "왼쪽 raw는 원문 그대로 유지됩니다. "
            "오른쪽 normalized_text의 한국어 번역 초안만 "
            "위에서 아래까지 검수·수정하세요. "
            "Qwen3 문맥 번역 후 언어·공식명·정보 보존 안전 검사를 거친 초안입니다. "
            "최종 사용 전 사람 검수는 필요합니다."
        )
    else:
        st.info(
            "normalized_text를 위에서 아래까지 "
            "계속 수정하세요. "
            "셀을 바꾸거나 스크롤하는 동안 "
            "전체 앱은 다시 실행되지 않습니다. "
            "검수가 끝났을 때 한 번만 저장하면 됩니다."
        )

    # Tall editor: browser/page scroll rather than 10-row pagination.
    editor_height = min(
        max(
            700,
            36 * total + 120,
        ),
        4200,
    )

    with st.form(
        f"whole_chapter_review_"
        f"{chapter.get('chapter_id', 'CH')}",
        clear_on_submit=False,
        border=True,
    ):
        disabled_columns = [
            "no",
            "utterance_id",
            "timestamp",
            "raw_joined_text",
            "confidence",
        ]
        if "chapter" in editor_df.columns:
            disabled_columns.append("chapter")

        column_config = {
                "no": st.column_config.NumberColumn(
                    "#",
                    width="small",
                ),
                "timestamp": st.column_config.TextColumn(
                    "시간",
                    width="small",
                ),
                "raw_joined_text": st.column_config.TextColumn(
                    "원문" if is_translation else "raw",
                    width="large",
                ),
                "normalized_text": st.column_config.TextColumn(
                    "한국어 초안" if is_translation else "normalized_text",
                    width="large",
                ),
                "review_status": st.column_config.SelectboxColumn(
                    "검수 상태",
                    options=[
                        "needs_review",
                        "approved",
                        "rejected",
                    ],
                    width="small",
                ),
                "editor_note": st.column_config.TextColumn(
                    "메모",
                    width="medium",
                ),
            }
        if "chapter" in editor_df.columns:
            column_config["chapter"] = st.column_config.TextColumn(
                "챕터",
                width="medium",
            )

        edited = st.data_editor(
            editor_df,
            use_container_width=True,
            hide_index=True,
            height=editor_height,
            disabled=disabled_columns,
            column_config=column_config,
            key=(
                "whole_chapter_editor_"
                + str(
                    chapter.get(
                        "chapter_id",
                        "CH",
                    )
                )
            ),
        )

        c1, c2 = st.columns(2)
        with c1:
            save_button = (
                st.form_submit_button(
                    "전체 영상 저장" if is_full_video else "현재 챕터 저장",
                    use_container_width=True,
                )
            )
        with c2:
            approve_button = (
                st.form_submit_button(
                    "전체 승인 + 저장",
                    type="primary",
                    use_container_width=True,
                )
            )

    committed = None

    if save_button:
        committed = commit_review(
            edited,
            approve_all=False,
        )
        st.success(
            "전체 영상 수정 내용을 저장했습니다." if is_full_video else "현재 챕터 수정 내용을 저장했습니다."
        )

    elif approve_button:
        committed = commit_review(
            edited,
            approve_all=True,
        )
        st.success(
            "전체 영상을 승인하고 저장했습니다." if is_full_video else "현재 챕터 전체를 승인하고 저장했습니다."
        )

    current_df = st.session_state[
        "editor_df"
    ]
    current = (
        committed
        if committed is not None
        else current_result(
            draft,
            current_df,
        )
    )

    if st.session_state.get(
        "last_saved_at"
    ):
        st.caption(
            "마지막 저장 · "
            + str(
                st.session_state[
                    "last_saved_at"
                ]
            )
        )

    st.download_button(
        "현재 저장 상태 JSON 다운로드",
        data=json.dumps(
            current,
            ensure_ascii=False,
            indent=2,
        ),
        file_name=(
            f"{current.get('video_id', 'video')}_"
            f"{chapter.get('chapter_id', 'CH')}_"
            "preprocessed_v0_3_4.json"
        ),
        mime="application/json",
        use_container_width=True,
        help=(
            "폼 안에서 아직 저장 버튼을 누르지 않은 "
            "수정은 다운로드에 포함되지 않습니다."
        ),
    )

    report = current.get(
        "processing_report",
        {},
    )
    st.caption(
        f"승인 "
        f"{report.get('approved_utterances', 0)}"
        f" / "
        f"{len(current.get('normalized_utterances', []))}"
        f" · "
        f"미승인 "
        f"{report.get('review_required_utterances', 0)}"
    )

    with st.expander(
        "승인 기준본과 비교",
        expanded=False,
    ):
        gold_file = st.file_uploader(
            "승인 기준 JSON",
            type=["json"],
            key="gold_compare",
        )
        if gold_file:
            gold = parse_uploaded_json(
                gold_file
            )
            if gold:
                st.json(
                    compare_with_gold(
                        current,
                        gold,
                    )
                )


if st.session_state.get(
    "preprocessing_draft"
) is None:
    render_setup()
else:
    render_review()
