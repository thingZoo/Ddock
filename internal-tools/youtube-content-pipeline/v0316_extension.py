from __future__ import annotations

import sys
import warnings
from functools import wraps
from typing import Any

from content_chapters import add_content_chapter_foundation
from content_chapter_segmentation import apply_content_chapter_policy
from korean_full_scope import (
    finalize_korean_full_result,
    is_korean_full_request,
    source_for_korean_full,
)
from runtime_generation_metrics import (
    capture_runtime_generation_metrics,
    ensure_runtime_generation_metrics,
    record_generation_call,
    record_model_load_success,
    record_model_lookup,
)


EXTENSION_VERSION = "v0.3.16-semantic-content-chapters"
BASELINE_PATCH_VERSION = "v0.3.15.1"


def _install_generation_instrumentation(core: Any) -> None:
    if getattr(core, "_V0316_GENERATION_INSTRUMENTATION_APPLIED", False):
        return

    original_generate = getattr(core, "_generate_local_llm_text_v033", None)
    original_loader = getattr(core, "_load_local_llm_v032", None)

    if callable(original_loader):
        @wraps(original_loader)
        def wrapped_loader(model_name: Any) -> Any:
            normalized_name = str(
                model_name
                or getattr(core, "_DEFAULT_LOCAL_LLM_MODEL_V032", "")
            ).strip()
            cache = getattr(core, "_LOCAL_LLM_CACHE_V032", {})
            cache_hit = isinstance(cache, dict) and normalized_name in cache
            try:
                record_model_lookup(cache_hit=cache_hit)
            except Exception:
                pass
            loaded = original_loader(model_name)
            if not cache_hit:
                try:
                    record_model_load_success()
                except Exception:
                    pass
            return loaded

        wrapped_loader._v0316_model_load_instrumentation = True
        core._load_local_llm_v032 = wrapped_loader

    if callable(original_generate):
        @wraps(original_generate)
        def wrapped_generate(*args: Any, **kwargs: Any) -> Any:
            try:
                record_generation_call()
            except Exception:
                pass
            return original_generate(*args, **kwargs)

        wrapped_generate._v0316_generation_instrumentation = True
        core._generate_local_llm_text_v033 = wrapped_generate

    core._V0316_GENERATION_INSTRUMENTATION_APPLIED = True


def extend_result_safely(
    result: dict[str, Any],
    source_data: dict[str, Any] | None = None,
    *,
    core: Any | None = None,
    model_name: str | None = None,
    allow_semantic_generation: bool = False,
) -> dict[str, Any]:
    try:
        if core is not None:
            return apply_content_chapter_policy(
                core,
                result,
                source_data,
                model_name=model_name,
                allow_semantic_generation=allow_semantic_generation,
            )
        return add_content_chapter_foundation(result, source_data)
    except Exception as exc:
        warnings.warn(
            "v0.3.16 content_chapters extension을 적용하지 못해 "
            f"기존 v0.3.15.1 결과를 유지합니다: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return result


def normalize_korean_result_safely(
    result: dict[str, Any],
    source_data: dict[str, Any] | None,
    *,
    core: Any,
) -> dict[str, Any]:
    if not isinstance(source_data, dict):
        return result
    try:
        from korean_evidence_normalization import (
            apply_korean_evidence_normalization,
        )

        return apply_korean_evidence_normalization(
            result,
            source_data,
            canonicalize=getattr(
                core,
                "_canonicalize_official_foreign_names_v031",
                None,
            ),
        )
    except Exception as exc:
        warnings.warn(
            "v0.3.16 한국어 evidence normalization을 적용하지 못해 "
            f"기존 전처리 결과를 유지합니다: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return result


def review_korean_asr_safely(
    result: dict[str, Any],
    source_data: dict[str, Any] | None,
    *,
    core: Any,
    model_name: str | None = None,
) -> dict[str, Any]:
    if not isinstance(source_data, dict):
        return result
    try:
        from korean_asr_editorial_review import (
            apply_korean_asr_editorial_review,
        )

        return apply_korean_asr_editorial_review(
            result,
            source_data,
            core=core,
            model_name=model_name,
            allow_model_review=False,
        )
    except Exception as exc:
        warnings.warn(
            "v0.3.16 한국어 ASR editorial review를 적용하지 못해 "
            f"기존 deterministic 결과를 유지합니다: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return result


def review_korean_audio_safely(
    result: dict[str, Any],
    source_data: dict[str, Any] | None,
    *,
    core: Any,
    model_name: str | None = None,
) -> dict[str, Any]:
    if not isinstance(source_data, dict):
        return result
    try:
        from korean_audio_reasr import apply_selective_audio_reasr

        return apply_selective_audio_reasr(
            result,
            source_data,
            core=core,
            qwen_model_name=model_name,
        )
    except Exception as exc:
        warnings.warn(
            "v0.3.16 선택적 Korean audio re-ASR를 적용하지 못해 "
            f"기존 normalized 결과를 유지합니다: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return result


def apply(core: Any) -> Any:
    if not getattr(core, "_V03151_PATCH_APPLIED", False):
        raise RuntimeError("v0316 extension보다 v0315_1_patch.apply()가 먼저 실행되어야 합니다.")
    if getattr(core, "_V03151_PATCH_VERSION", None) != BASELINE_PATCH_VERSION:
        raise RuntimeError("v0316 extension의 안정 기반 patch 버전이 일치하지 않습니다.")
    try:
        _install_generation_instrumentation(core)
    except Exception as exc:
        warnings.warn(
            f"v0.3.16 generation 계측을 설치하지 못해 계측 없이 계속합니다: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
    if getattr(core, "_V0316_CONTENT_CHAPTER_EXTENSION_APPLIED", False):
        return core

    original_build = core.build_preprocessing_draft
    original_prepare = core.prepare_existing_preprocessing
    original_export = core.export_editor_result

    @wraps(original_build)
    def wrapped_build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        source_data = args[0] if args else kwargs.get("data")
        build_args = args
        build_kwargs = kwargs
        korean_full = is_korean_full_request(
            core,
            source_data,
            translation_scope=kwargs.get("translation_scope"),
            translate_foreign_to_korean=kwargs.get(
                "translate_foreign_to_korean",
                False,
            ),
        )
        if korean_full:
            build_source = source_for_korean_full(source_data)
            if args:
                build_args = (build_source, *args[1:])
            else:
                build_kwargs = dict(kwargs)
                build_kwargs["data"] = build_source
        with capture_runtime_generation_metrics() as metrics:
            result = original_build(*build_args, **build_kwargs)
            if korean_full:
                result = finalize_korean_full_result(
                    result,
                    source_data,
                    core=core,
                )
            result = normalize_korean_result_safely(
                result,
                source_data if isinstance(source_data, dict) else None,
                core=core,
            )
            result = review_korean_asr_safely(
                result,
                source_data if isinstance(source_data, dict) else None,
                core=core,
                model_name=kwargs.get("translation_local_model"),
            )
            result = review_korean_audio_safely(
                result,
                source_data if isinstance(source_data, dict) else None,
                core=core,
                model_name=kwargs.get("translation_local_model"),
            )
            extended = extend_result_safely(
                result,
                source_data if isinstance(source_data, dict) else None,
                core=core,
                model_name=kwargs.get("translation_local_model"),
                allow_semantic_generation=True,
            )
        if extended is result:
            return result
        return ensure_runtime_generation_metrics(
            extended,
            metrics,
        )

    @wraps(original_prepare)
    def wrapped_prepare(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_prepare(*args, **kwargs)
        source_data = args[0] if args else kwargs.get("data")
        extended = extend_result_safely(
            result,
            source_data if isinstance(source_data, dict) else None,
            core=core,
            allow_semantic_generation=False,
        )
        if extended is result:
            return result
        return ensure_runtime_generation_metrics(extended)

    @wraps(original_export)
    def wrapped_export(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_export(*args, **kwargs)
        draft = args[0] if args else kwargs.get("draft")
        extended = extend_result_safely(
            result,
            draft if isinstance(draft, dict) else None,
            core=core,
            allow_semantic_generation=False,
        )
        if extended is result:
            return result
        return ensure_runtime_generation_metrics(extended)

    wrapped_build._v0316_content_chapter_wrapper = True
    wrapped_prepare._v0316_content_chapter_wrapper = True
    wrapped_export._v0316_content_chapter_wrapper = True

    core.build_preprocessing_draft = wrapped_build
    core.prepare_existing_preprocessing = wrapped_prepare
    core.export_editor_result = wrapped_export

    loaded_review_store = sys.modules.get("review_store")
    if (
        loaded_review_store is not None
        and getattr(loaded_review_store, "export_editor_result", None) is original_export
    ):
        loaded_review_store.export_editor_result = wrapped_export

    core._V0316_CONTENT_CHAPTER_EXTENSION_APPLIED = True
    core._V0316_CONTENT_CHAPTER_EXTENSION_VERSION = EXTENSION_VERSION
    return core
