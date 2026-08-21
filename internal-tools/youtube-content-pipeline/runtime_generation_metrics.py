from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


INSTRUMENTATION_VERSION = "v0.3.16-generation-metrics-v0.1"

GENERATION_STAGES = (
    "baseline_unclassified",
    "translation_first_pass",
    "editorial_review",
    "video_entity_audit",
    "semantic_audit",
    "semantic_repair",
    "language_rescue",
    "korean_asr_editorial_review",
    "korean_audio_reasr_verifier",
    "content_chapter_segmentation",
    "content_chapter_role_audit",
)

_CONTENT_CHAPTER_STAGES = {
    "content_chapter_segmentation",
    "content_chapter_role_audit",
}
_ACTIVE_METRICS: ContextVar[dict[str, Any] | None] = ContextVar(
    "v0316_active_generation_metrics",
    default=None,
)
_ACTIVE_STAGE: ContextVar[tuple[str, str | None] | None] = ContextVar(
    "v0316_active_generation_stage",
    default=None,
)


def new_runtime_generation_metrics() -> dict[str, Any]:
    return {
        "total_generation_calls": 0,
        "translation_generation_calls": 0,
        "content_chapter_generation_calls": 0,
        "content_chapter_segmentation_calls": 0,
        "content_chapter_role_audit_calls": 0,
        "korean_asr_editorial_review_generation_calls": 0,
        "korean_audio_reasr_verifier_generation_calls": 0,
        "calls_by_stage": {stage: 0 for stage in GENERATION_STAGES},
        # Existing v0.3.15.1 internals do not expose reliable retry/stage hooks.
        # These fields count only explicitly labelled future calls.
        "retry_calls": 0,
        "retry_reasons": [],
        "retry_classification_complete": False,
        "model_load_attempts": 0,
        "model_load_successes": 0,
        "model_cache_hits": 0,
        "stage_classification_complete": False,
        "stage_classification_note": (
            "Existing v0.3.15.1 generation calls are counted as "
            "baseline_unclassified without inferring a stage or retry reason; "
            "retry_calls includes only explicitly labelled future retries."
        ),
        "instrumentation_version": INSTRUMENTATION_VERSION,
    }


@contextmanager
def capture_runtime_generation_metrics() -> Iterator[dict[str, Any]]:
    metrics = new_runtime_generation_metrics()
    token = _ACTIVE_METRICS.set(metrics)
    try:
        yield metrics
    finally:
        _ACTIVE_METRICS.reset(token)


@contextmanager
def generation_stage(
    stage: str,
    *,
    retry_reason: str | None = None,
) -> Iterator[None]:
    if stage not in GENERATION_STAGES or stage == "baseline_unclassified":
        raise ValueError(f"unsupported explicit generation stage: {stage}")
    reason = str(retry_reason).strip() if retry_reason is not None else None
    token = _ACTIVE_STAGE.set((stage, reason or None))
    try:
        yield
    finally:
        _ACTIVE_STAGE.reset(token)


def record_generation_call() -> None:
    metrics = _ACTIVE_METRICS.get()
    if metrics is None:
        return

    explicit = _ACTIVE_STAGE.get()
    stage, retry_reason = explicit or ("baseline_unclassified", None)
    metrics["total_generation_calls"] += 1
    metrics["calls_by_stage"][stage] += 1
    if stage in _CONTENT_CHAPTER_STAGES:
        metrics["content_chapter_generation_calls"] += 1
        if stage == "content_chapter_segmentation":
            metrics["content_chapter_segmentation_calls"] += 1
        elif stage == "content_chapter_role_audit":
            metrics["content_chapter_role_audit_calls"] += 1
    elif stage == "korean_asr_editorial_review":
        metrics["korean_asr_editorial_review_generation_calls"] += 1
    elif stage == "korean_audio_reasr_verifier":
        metrics["korean_audio_reasr_verifier_generation_calls"] += 1
    else:
        metrics["translation_generation_calls"] += 1

    if retry_reason:
        metrics["retry_calls"] += 1
        metrics["retry_reasons"].append(retry_reason)


def record_model_lookup(*, cache_hit: bool) -> None:
    metrics = _ACTIVE_METRICS.get()
    if metrics is None:
        return
    if cache_hit:
        metrics["model_cache_hits"] += 1
    else:
        metrics["model_load_attempts"] += 1


def record_model_load_success() -> None:
    metrics = _ACTIVE_METRICS.get()
    if metrics is not None:
        metrics["model_load_successes"] += 1


def snapshot_runtime_generation_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(metrics)


def ensure_runtime_generation_metrics(
    result: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        return result
    if "runtime_generation_metrics" in result:
        return result
    try:
        output = dict(result)
        output["runtime_generation_metrics"] = snapshot_runtime_generation_metrics(
            metrics or new_runtime_generation_metrics()
        )
        return output
    except Exception:
        # Diagnostics must never turn a valid preprocessing result into a failure.
        return result
