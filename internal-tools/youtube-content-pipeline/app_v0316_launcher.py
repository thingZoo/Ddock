from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from v0315_1_patch import apply
from korean_full_scope import install_korean_full_scope_ui


BASELINE_PATCH_VERSION = "v0.3.15.1"
APP_VERSION = "v0.3.16"


BASE_APP_DISPATCH = '''if st.session_state.get(
    "preprocessing_draft"
) is None:
    render_setup()
else:
    render_review()
'''


INTEGRATED_APP_DISPATCH = '''if st.session_state.get(
    "preprocessing_draft"
) is None:
    try:
        from youtube_acquisition_ui import render_integrated_entry

        render_integrated_entry(
            st,
            st.session_state,
            render_setup,
            APP_DIR,
        )
    except Exception as _v0316_acquisition_ui_exc:
        st.error(
            "YouTube 원본 수집 화면을 표시하지 못했습니다. "
            "기존 JSON 입력 화면으로 계속합니다: "
            + str(_v0316_acquisition_ui_exc)
        )
        render_setup()
else:
    st.session_state["v0316_workflow_stage"] = "preprocessing_review"
    render_review()
'''


SCREENSHOT_UI_HOOK = r'''

# v0.3.16-only UI extension. The stable app.py remains unchanged.
if st.session_state.get("preprocessing_draft") is not None:
    try:
        from screenshot_ui import render_screenshot_workflow
        from script_review_ui import result_without_reexport_when_unchanged

        _v0316_screenshot_current = result_without_reexport_when_unchanged(
            st.session_state["preprocessing_draft"],
            st.session_state["editor_df"],
            current_result,
        )
        if _v0316_screenshot_current.get("content_chapters"):
            st.session_state["v0316_workflow_stage"] = "screenshot_eligible"
        render_screenshot_workflow(
            st,
            _v0316_screenshot_current,
            st.session_state,
            APP_DIR,
            AUTOSAVE_DIR,
        )
    except Exception as _v0316_screenshot_exc:
        st.error(
            "스크린샷 기능을 표시하지 못했습니다. "
            "기존 전처리 결과는 그대로 유지됩니다: "
            + str(_v0316_screenshot_exc)
        )
'''


OPTIONAL_REVIEW_MARKER = '''    editor_df = st.session_state[
        "editor_df"
    ]
'''


OPTIONAL_REVIEW_HOOK = '''    editor_df = st.session_state[
        "editor_df"
    ]
    try:
        from script_review_ui import (
            render_optional_script_review,
            result_without_reexport_when_unchanged,
        )

        _v0316_review_current = result_without_reexport_when_unchanged(
            draft,
            editor_df,
            current_result,
        )
        if render_optional_script_review(
            st,
            _v0316_review_current,
            st.session_state,
            APP_DIR,
            AUTOSAVE_DIR,
        ):
            return
    except Exception as _v0316_review_ui_exc:
        st.error(
            "선택적 문장 검토 화면을 표시하지 못했습니다. "
            "기존 전체 편집기로 계속합니다: "
            + str(_v0316_review_ui_exc)
        )
'''


def apply_baseline_patch() -> Any:
    core = apply()
    if not getattr(core, "_V03151_PATCH_APPLIED", False):
        raise RuntimeError("v0.3.15.1 안정 패치가 적용되지 않았습니다.")
    if getattr(core, "_V03151_PATCH_VERSION", None) != BASELINE_PATCH_VERSION:
        raise RuntimeError(
            "예상한 안정 패치 버전과 다릅니다: "
            f"{getattr(core, '_V03151_PATCH_VERSION', 'unknown')}"
        )
    return core


def apply_v0316_extension(core: Any) -> Any:
    try:
        from v0316_extension import apply as apply_extension

        extended_core = apply_extension(core)
        if not getattr(
            extended_core,
            "_V0316_CONTENT_CHAPTER_EXTENSION_APPLIED",
            False,
        ):
            raise RuntimeError("content_chapters extension 적용 marker가 없습니다.")
        return extended_core
    except Exception as exc:
        warnings.warn(
            "v0.3.16 extension을 적용하지 못해 v0.3.15.1 baseline으로 실행합니다: "
            f"{exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return core


def versioned_app_source() -> tuple[Path, str]:
    app_path = Path(__file__).resolve().parent / "app.py"
    if not app_path.is_file():
        raise RuntimeError("현재 폴더에 안정 기반 app.py가 없습니다.")

    source = app_path.read_text(encoding="utf-8")
    source = source.replace("v0.3.4", APP_VERSION)
    source = source.replace("v0_3_4", "v0_3_16")
    source = install_korean_full_scope_ui(source)
    if OPTIONAL_REVIEW_MARKER not in source:
        warnings.warn(
            "v0.3.16 선택적 script review UI를 설치하지 못해 기존 전체 편집기를 사용합니다.",
            RuntimeWarning,
            stacklevel=2,
        )
    else:
        source = source.replace(
            OPTIONAL_REVIEW_MARKER,
            OPTIONAL_REVIEW_HOOK,
            1,
        )
    if BASE_APP_DISPATCH not in source:
        warnings.warn(
            "v0.3.16 통합 화면 dispatch를 설치하지 못해 기존 app 화면으로 실행합니다.",
            RuntimeWarning,
            stacklevel=2,
        )
    else:
        source = source.replace(
            BASE_APP_DISPATCH,
            INTEGRATED_APP_DISPATCH,
            1,
        )
    source += SCREENSHOT_UI_HOOK
    return app_path, source


def main() -> None:
    core = apply_baseline_patch()
    apply_v0316_extension(core)
    app_path, source = versioned_app_source()
    exec(
        compile(source, str(app_path), "exec"),
        {"__name__": "__main__", "__file__": str(app_path)},
    )


if __name__ == "__main__":
    main()
