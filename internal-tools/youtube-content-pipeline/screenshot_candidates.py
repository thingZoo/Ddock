from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from representative_moment import (
    RepresentativeMomentError,
    rank_representative_moments,
    select_representative_moment,
)


CONTENT_CHAPTER_ASSET_SCHEMA_VERSION = "content_chapter_assets_v0.1"
SCREENSHOT_PLAN_METHOD = "semantic_screenshot_candidates_v0.2"
DEFAULT_CANDIDATE_OFFSETS_SECONDS = (-2.0, 0.0, 2.0)
MIN_DISTINCT_CANDIDATE_SPACING_SECONDS = 0.25
MAX_SEMANTIC_SCREENSHOT_CANDIDATES = 3
SEMANTIC_RELEVANCE_WEIGHT = 0.75
TEMPORAL_DIVERSITY_WEIGHT = 0.25
YTDLP_VIDEO_FORMAT = (
    "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]"
)
_SAFE_PATH_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _safe_component(value: Any, fallback: str) -> str:
    component = _SAFE_PATH_COMPONENT_RE.sub("_", str(value or "").strip())
    component = component.strip("._")
    return component or fallback


def chapter_fingerprint(content_chapter: dict[str, Any]) -> str:
    payload = {
        "content_chapter_id": content_chapter.get("content_chapter_id"),
        "start_utterance_id": content_chapter.get("start_utterance_id"),
        "end_utterance_id": content_chapter.get("end_utterance_id"),
        "start_seconds": content_chapter.get("start_seconds"),
        "end_seconds": content_chapter.get("end_seconds"),
        "source_utterance_ids": list(
            content_chapter.get("source_utterance_ids") or []
        ),
        "title": content_chapter.get("title"),
        "summary": content_chapter.get("summary"),
        "boundary_reason": content_chapter.get("boundary_reason"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_source_locator(result: dict[str, Any]) -> dict[str, Any] | None:
    source_url = str(result.get("source_url") or "").strip()
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    video_id = str(result.get("video_id") or metadata.get("video_id") or "").strip()
    if source_url:
        return {
            "source_url": source_url,
            "video_id": video_id or None,
            "method": "preserved_source_url",
        }
    if video_id:
        return {
            "source_url": (
                "https://www.youtube.com/watch?v=" + quote(video_id, safe="")
            ),
            "video_id": video_id,
            "method": "canonical_youtube_url_from_video_id",
        }
    return None


def _local_frame_variant_times(
    target_seconds: float,
    chapter_start: float,
    chapter_end: float,
) -> tuple[list[float], list[str]]:
    """Reserve nearby timestamps for later blur/transition frame selection."""
    if chapter_end < chapter_start:
        raise ValueError("chapter_end_precedes_start")
    target = min(max(target_seconds, chapter_start), chapter_end)

    def clamp(value: float) -> float:
        return min(max(value, chapter_start), chapter_end)

    requested = [
        clamp(target + offset)
        for offset in DEFAULT_CANDIDATE_OFFSETS_SECONDS
    ]
    supplemental = [
        clamp(target - 1.0),
        clamp(target + 1.0),
        chapter_start,
        chapter_end,
        (chapter_start + chapter_end) / 2,
    ]
    selected = [target]

    def add(value: float) -> None:
        if len(selected) >= 3:
            return
        if all(
            abs(value - existing)
            >= MIN_DISTINCT_CANDIDATE_SPACING_SECONDS - 1e-9
            for existing in selected
        ):
            selected.append(value)

    for value in (requested[0], requested[2], *supplemental):
        add(value)
    selected = sorted(round(value, 6) for value in selected)
    warnings: list[str] = []
    if len(selected) < 3:
        warnings.append(
            "screenshot_candidate_count_reduced_for_short_chapter:"
            f"planned={len(selected)}"
        )
    return selected, warnings


def _semantic_candidate_moments(
    primary: dict[str, Any],
    ranked: list[dict[str, Any]],
    chapter_start: float,
    chapter_end: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    primary_id = str(primary["representative_utterance_id"])
    primary_target = float(primary["target_seconds"])
    selected = [
        {
            "source_utterance_id": primary_id,
            "target_seconds": primary_target,
            "target_timestamp": primary["target_timestamp"],
            "semantic_score": float(primary["selection_score"]),
            "selection_role": "primary_anchor",
        }
    ]
    remaining: list[dict[str, Any]] = []
    seen_targets = {primary_target}
    for candidate in ranked:
        if candidate["source_utterance_id"] == primary_id:
            continue
        target = float(candidate["target_seconds"])
        if not candidate.get("has_semantic_signal") or target in seen_targets:
            continue
        seen_targets.add(target)
        remaining.append(candidate)

    semantic_ceiling = max(
        [float(item["semantic_score"]) for item in ranked]
        + [float(primary["selection_score"]), 0.0]
    )
    chapter_duration = max(0.0, chapter_end - chapter_start)
    while remaining and len(selected) < MAX_SEMANTIC_SCREENSHOT_CANDIDATES:
        scored: list[tuple[tuple[float, ...], dict[str, Any]]] = []
        for candidate in remaining:
            semantic_score = float(candidate["semantic_score"])
            semantic_relevance = (
                semantic_score / semantic_ceiling if semantic_ceiling > 0 else 0.0
            )
            minimum_distance = min(
                abs(float(candidate["target_seconds"]) - item["target_seconds"])
                for item in selected
            )
            temporal_diversity = (
                minimum_distance / chapter_duration if chapter_duration > 0 else 0.0
            )
            combined = (
                SEMANTIC_RELEVANCE_WEIGHT * semantic_relevance
                + TEMPORAL_DIVERSITY_WEIGHT * temporal_diversity
            )
            key = (
                combined,
                semantic_relevance,
                temporal_diversity,
                float(candidate["centrality_score"]),
                float(candidate["metadata_relevance_score"]),
                -int(candidate["source_order"]),
            )
            scored.append((key, candidate))
        _, chosen = max(scored, key=lambda item: item[0])
        selected.append(
            {
                "source_utterance_id": chosen["source_utterance_id"],
                "target_seconds": float(chosen["target_seconds"]),
                "target_timestamp": chosen["target_timestamp"],
                "semantic_score": float(chosen["semantic_score"]),
                "selection_role": "semantic_alternative",
            }
        )
        remaining.remove(chosen)

    warnings: list[str] = []
    if len(selected) < MAX_SEMANTIC_SCREENSHOT_CANDIDATES:
        warnings.append(
            "insufficient_distinct_semantic_screenshot_candidates:"
            f"planned={len(selected)}"
        )
    return selected, warnings


def build_screenshot_plan(result: dict[str, Any]) -> dict[str, Any]:
    """Build a detached asset layer without mutating preprocessing output."""
    if not isinstance(result, dict):
        raise TypeError("preprocessing result must be a dictionary")
    chapters = result.get("content_chapters")
    chapters = chapters if isinstance(chapters, list) else []
    utterances = result.get("normalized_utterances")
    utterances = utterances if isinstance(utterances, list) else []
    generation = result.get("content_chapter_generation")
    generation = generation if isinstance(generation, dict) else {}
    generation_warnings = [str(item) for item in generation.get("warnings") or []]
    locator = resolve_source_locator(result)
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    video_id = str(result.get("video_id") or metadata.get("video_id") or "").strip()
    warnings: list[str] = []
    if locator is None:
        warnings.append("screenshot_source_locator_unavailable")
    if not chapters:
        warnings.append("screenshot_plan_has_no_content_chapters")

    items: list[dict[str, Any]] = []
    for chapter_index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            warnings.append(
                f"content_chapter[{chapter_index}]_screenshot_plan_skipped:not_an_object"
            )
            continue
        chapter_id = str(
            chapter.get("content_chapter_id") or f"CCH-{chapter_index + 1:02d}"
        )
        item_warnings: list[str] = []
        try:
            moment = select_representative_moment(
                chapter,
                utterances,
                generation_warnings=generation_warnings,
            )
            chapter_start = _seconds(chapter.get("start_seconds"))
            chapter_end = _seconds(chapter.get("end_seconds"))
            if chapter_start is None or chapter_end is None:
                raise RepresentativeMomentError(
                    "chapter_has_invalid_timestamp_range"
                )
            ranked = rank_representative_moments(
                chapter,
                utterances,
                generation_warnings=generation_warnings,
            )
            semantic_moments, candidate_warnings = _semantic_candidate_moments(
                moment,
                ranked,
                chapter_start,
                chapter_end,
            )
            item_warnings.extend(candidate_warnings)
        except (RepresentativeMomentError, ValueError) as exc:
            message = (
                f"content_chapter[{chapter_index}]_screenshot_plan_skipped:"
                f"{str(exc)}"
            )
            warnings.append(message)
            items.append(
                {
                    "content_chapter_id": chapter_id,
                    "chapter_fingerprint": chapter_fingerprint(chapter),
                    "status": "skipped",
                    "failure_stage": "candidate_planning",
                    "failure_reason": str(exc),
                    "representative_moment": None,
                    "screenshot_candidates": [],
                    "warnings": [message],
                }
            )
            continue

        safe_chapter_id = _safe_component(
            chapter_id, f"CCH-{chapter_index + 1:02d}"
        )
        candidate_status = "planned" if locator is not None else "skipped"
        screenshot_candidates = [
            {
                "candidate_index": index,
                "offset_seconds": round(
                    candidate["target_seconds"]
                    - float(moment["target_seconds"]),
                    6,
                ),
                "source_utterance_id": candidate["source_utterance_id"],
                "target_seconds": candidate["target_seconds"],
                "target_timestamp": candidate["target_timestamp"],
                "semantic_score": candidate["semantic_score"],
                "selection_role": candidate["selection_role"],
                "relative_path": (
                    f"screenshots/{safe_chapter_id}/candidate_{index:02d}.jpg"
                ),
                "status": candidate_status,
            }
            for index, candidate in enumerate(semantic_moments, 1)
        ]
        if locator is None:
            item_warnings.append("screenshot_source_locator_unavailable")
        warnings.extend(
            f"content_chapter[{chapter_index}]:{warning}"
            for warning in item_warnings
        )
        items.append(
            {
                "content_chapter_id": chapter_id,
                "chapter_fingerprint": chapter_fingerprint(chapter),
                "status": "planned" if locator is not None else "skipped",
                "failure_stage": None if locator is not None else "source_locator",
                "failure_reason": (
                    None if locator is not None else "screenshot_source_locator_unavailable"
                ),
                "representative_moment": moment,
                "screenshot_candidates": screenshot_candidates,
                "warnings": item_warnings,
            }
        )

    status = "planned"
    if locator is None or not items:
        status = "skipped"
    elif any(item["status"] == "skipped" for item in items):
        status = "planned_with_warnings"
    return {
        "schema_version": CONTENT_CHAPTER_ASSET_SCHEMA_VERSION,
        "status": status,
        "method": SCREENSHOT_PLAN_METHOD,
        "video_id": video_id or None,
        "source_url": locator["source_url"] if locator else None,
        "source_locator": copy.deepcopy(locator),
        "items": items,
        "warnings": list(dict.fromkeys(warnings)),
    }


def attach_screenshot_plan(result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with a detached asset layer; never alter semantic fields."""
    if not isinstance(result, dict):
        raise TypeError("preprocessing result must be a dictionary")
    output = copy.deepcopy(result)
    try:
        output["content_chapter_assets"] = build_screenshot_plan(result)
    except Exception as exc:
        output["content_chapter_assets"] = {
            "schema_version": CONTENT_CHAPTER_ASSET_SCHEMA_VERSION,
            "status": "failed",
            "method": SCREENSHOT_PLAN_METHOD,
            "video_id": result.get("video_id"),
            "source_url": result.get("source_url"),
            "source_locator": None,
            "items": [],
            "warnings": [
                f"screenshot_plan_failed_nonfatally:{type(exc).__name__}"
            ],
        }
    return output


def build_yt_dlp_command(
    yt_dlp_executable: str,
    source_url: str,
    output_template: Path,
) -> list[str]:
    return [
        yt_dlp_executable,
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "--format",
        YTDLP_VIDEO_FORMAT,
        "--output",
        str(output_template),
        source_url,
    ]


def build_ffmpeg_command(
    ffmpeg_executable: str,
    video_path: Path,
    target_seconds: float,
    output_path: Path,
) -> list[str]:
    return [
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{float(target_seconds):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(output_path),
    ]


def _mark_candidates(
    assets: dict[str, Any], status: str, error: str | None = None
) -> None:
    for item in assets.get("items") or []:
        if not isinstance(item, dict):
            continue
        item["status"] = status
        if error:
            item["failure_stage"] = (
                "video_preparation"
                if error.startswith("video_download_failed")
                else "tool_check"
                if error.startswith("screenshot_tools_unavailable")
                else "candidate_extraction"
            )
            item["failure_reason"] = error
        for candidate in item.get("screenshot_candidates") or []:
            if isinstance(candidate, dict):
                candidate["status"] = status
                if error:
                    candidate["error"] = error


def extract_screenshot_candidates(
    asset_plan: dict[str, Any],
    output_directory: Path | str,
    *,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    tempdir_factory: Callable[..., Any] = tempfile.TemporaryDirectory,
) -> dict[str, Any]:
    """Execute a plan nonfatally; production callers retain their JSON result."""
    assets = copy.deepcopy(asset_plan)
    if assets.get("status") == "skipped" or not assets.get("source_url"):
        assets["status"] = "skipped"
        assets.setdefault("warnings", []).append(
            "screenshot_extraction_skipped_without_source_locator"
        )
        _mark_candidates(assets, "skipped")
        return assets

    yt_dlp = which("yt-dlp")
    ffmpeg = which("ffmpeg")
    missing = [name for name, path in (("yt-dlp", yt_dlp), ("ffmpeg", ffmpeg)) if not path]
    if missing:
        error = "screenshot_tools_unavailable:" + ",".join(missing)
        assets["status"] = "skipped"
        assets.setdefault("warnings", []).append(error)
        _mark_candidates(assets, "skipped", error)
        return assets

    output_root = Path(output_directory)
    completed = 0
    failed = 0
    try:
        with tempdir_factory(prefix="v0316_screenshot_") as temp_name:
            temp_root = Path(temp_name)
            output_template = temp_root / "source.%(ext)s"
            download_command = build_yt_dlp_command(
                str(yt_dlp), assets["source_url"], output_template
            )
            try:
                runner(
                    download_command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                error = f"video_download_failed:{type(exc).__name__}"
                assets["status"] = "failed"
                assets.setdefault("warnings", []).append(error)
                _mark_candidates(assets, "failed", error)
                return assets

            videos = sorted(
                path
                for path in temp_root.glob("source.*")
                if path.is_file()
            )
            if not videos:
                error = "video_download_failed:downloaded_video_not_found"
                assets["status"] = "failed"
                assets.setdefault("warnings", []).append(error)
                _mark_candidates(assets, "failed", error)
                return assets
            video_path = videos[0]

            for item in assets.get("items") or []:
                if not isinstance(item, dict) or item.get("status") == "skipped":
                    continue
                item_completed = 0
                item_failed = 0
                for candidate in item.get("screenshot_candidates") or []:
                    relative = Path(str(candidate.get("relative_path") or ""))
                    if relative.is_absolute() or ".." in relative.parts:
                        candidate["status"] = "failed"
                        candidate["error"] = "unsafe_screenshot_relative_path"
                        failed += 1
                        item_failed += 1
                        continue
                    output_path = output_root / relative
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    command = build_ffmpeg_command(
                        str(ffmpeg),
                        video_path,
                        float(candidate["target_seconds"]),
                        output_path,
                    )
                    try:
                        runner(
                            command,
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                        candidate["status"] = "completed"
                        completed += 1
                        item_completed += 1
                    except Exception as exc:
                        candidate["status"] = "failed"
                        candidate["error"] = (
                            f"screenshot_extraction_failed:{type(exc).__name__}"
                        )
                        failed += 1
                        item_failed += 1
                if item_failed and item_completed:
                    item["status"] = "partial"
                elif item_failed:
                    item["status"] = "failed"
                elif item_completed:
                    item["status"] = "completed"
                if item_failed:
                    errors = [
                        str(candidate.get("error"))
                        for candidate in item.get("screenshot_candidates") or []
                        if isinstance(candidate, dict) and candidate.get("error")
                    ]
                    item["failure_stage"] = "candidate_extraction"
                    item["failure_reason"] = (
                        errors[0] if errors else "candidate_extraction_failed"
                    )
                elif item_completed:
                    item["failure_stage"] = None
                    item["failure_reason"] = None
    except Exception as exc:
        error = f"screenshot_extraction_wrapper_failed:{type(exc).__name__}"
        assets.setdefault("warnings", []).append(error)
        _mark_candidates(assets, "failed", error)
        assets["status"] = "failed"
        return assets

    if failed and completed:
        assets["status"] = "partial"
    elif failed:
        assets["status"] = "failed"
    elif completed:
        assets["status"] = "completed"
    else:
        assets["status"] = "skipped"
        assets.setdefault("warnings", []).append(
            "screenshot_extraction_had_no_planned_candidates"
        )
    return assets
