from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from screenshot_candidates import (
    build_screenshot_plan,
    extract_screenshot_candidates,
)
from screenshot_output import (
    ScreenshotOutputError,
    atomic_copy,
    atomic_write_json,
    cleanup_candidate_scope,
    final_image_path,
    final_json_path,
    resolve_candidate_path,
    scope_candidate_assets,
)


PINNED_YTDLP_CHANNEL = "nightly"
PINNED_YTDLP_VERSION = "2026.08.18.122307"
PINNED_YTDLP_DOWNLOAD_URL = (
    "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/download/"
    f"{PINNED_YTDLP_VERSION}/yt-dlp_macos"
)
PINNED_YTDLP_SHA256 = (
    "46d572488acb4b57f2b34ef05645ae56d0071b00e1f0d33a756502b62ae08822"
)
SIDECAR_EXECUTABLE_NAME = "yt-dlp_macos"
SIDECAR_METADATA_NAME = "metadata.json"
FFMPEG_OVERRIDE_ENV = "YSP_FFMPEG_EXECUTABLE"
TOOL_CACHE_OVERRIDE_ENV = "YSP_SCREENSHOT_TOOL_CACHE"
TOOL_VERSION_CHECK_TIMEOUT_SECONDS = 15.0


class ScreenshotRuntimeError(RuntimeError):
    pass


class StaleScreenshotSelectionError(ScreenshotRuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_tool_cache_directory() -> Path:
    override = str(os.environ.get(TOOL_CACHE_OVERRIDE_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return (
        Path.home()
        / "Library"
        / "Caches"
        / "youtube_script_preprocessor"
        / "tools"
        / "yt-dlp"
    )


def _sidecar_paths(cache_directory: Path | str | None = None) -> tuple[Path, Path]:
    root = Path(cache_directory or default_tool_cache_directory()).expanduser()
    return root / SIDECAR_EXECUTABLE_NAME, root / SIDECAR_METADATA_NAME


def _completed_stdout(completed: Any) -> str:
    lines = str(getattr(completed, "stdout", "") or "").strip().splitlines()
    return lines[0] if lines else ""


def inspect_pinned_yt_dlp(
    cache_directory: Path | str | None = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = TOOL_VERSION_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    executable, metadata_path = _sidecar_paths(cache_directory)
    status: dict[str, Any] = {
        "available": False,
        "channel": PINNED_YTDLP_CHANNEL,
        "expected_version": PINNED_YTDLP_VERSION,
        "version": None,
        "executable_path": str(executable),
        "metadata_path": str(metadata_path),
        "reason": "sidecar_not_installed",
    }
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return status
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        status["reason"] = "sidecar_metadata_unavailable"
        return status
    if not isinstance(metadata, dict):
        status["reason"] = "sidecar_metadata_invalid"
        return status
    if (
        metadata.get("channel") != PINNED_YTDLP_CHANNEL
        or str(metadata.get("version") or "") != PINNED_YTDLP_VERSION
        or str(metadata.get("sha256") or "") != PINNED_YTDLP_SHA256
    ):
        status["reason"] = "sidecar_metadata_version_mismatch"
        return status
    try:
        completed = runner(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        version = _completed_stdout(completed)
    except subprocess.TimeoutExpired:
        status["reason"] = "sidecar_version_check_timeout"
        status["timeout_seconds"] = timeout_seconds
        return status
    except Exception as exc:
        status["reason"] = f"sidecar_version_check_failed:{type(exc).__name__}"
        return status
    status["version"] = version
    if version != PINNED_YTDLP_VERSION:
        status["reason"] = "sidecar_executable_version_mismatch"
        return status
    status.update(
        {
            "available": True,
            "reason": None,
            "installed_at": metadata.get("installed_at"),
            "build": metadata.get("build"),
        }
    )
    return status


def _download_to_path(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "youtube-script-preprocessor-v0.3.16"})
    with urlopen(request, timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def prepare_pinned_yt_dlp(
    cache_directory: Path | str | None = None,
    *,
    downloader: Callable[[str, Path], None] = _download_to_path,
    runner: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = TOOL_VERSION_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Install the pinned official macOS sidecar only after an explicit UI action."""
    existing = inspect_pinned_yt_dlp(
        cache_directory,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    if existing["available"]:
        output = dict(existing)
        output["reused"] = True
        return output
    if platform.system() != "Darwin":
        raise ScreenshotRuntimeError("yt-dlp sidecar는 현재 macOS에서만 준비할 수 있습니다.")

    executable, metadata_path = _sidecar_paths(cache_directory)
    executable.parent.mkdir(parents=True, exist_ok=True)
    temporary_binary: Path | None = None
    temporary_metadata = metadata_path.with_suffix(".tmp")
    try:
        with tempfile.NamedTemporaryFile(
            prefix="yt-dlp_macos_",
            suffix=".download",
            dir=str(executable.parent),
            delete=False,
        ) as handle:
            temporary_binary = Path(handle.name)
        downloader(PINNED_YTDLP_DOWNLOAD_URL, temporary_binary)
        digest = hashlib.sha256(temporary_binary.read_bytes()).hexdigest()
        if digest != PINNED_YTDLP_SHA256:
            raise ScreenshotRuntimeError("다운로드한 yt-dlp의 SHA-256이 일치하지 않습니다.")
        temporary_binary.chmod(0o755)
        completed = runner(
            [str(temporary_binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        version = _completed_stdout(completed)
        if version != PINNED_YTDLP_VERSION:
            raise ScreenshotRuntimeError(
                "다운로드한 yt-dlp 버전이 고정 버전과 일치하지 않습니다."
            )
        os.replace(temporary_binary, executable)
        temporary_binary = None
        metadata = {
            "channel": PINNED_YTDLP_CHANNEL,
            "version": PINNED_YTDLP_VERSION,
            "build": "official_macos_standalone",
            "download_url": PINNED_YTDLP_DOWNLOAD_URL,
            "sha256": PINNED_YTDLP_SHA256,
            "executable_path": str(executable.resolve()),
            "installed_at": _utc_now(),
            "auto_update": False,
        }
        temporary_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_metadata, metadata_path)
    except ScreenshotRuntimeError:
        raise
    except Exception as exc:
        raise ScreenshotRuntimeError(
            f"yt-dlp 도구 준비 실패: {type(exc).__name__}"
        ) from exc
    finally:
        if temporary_binary is not None:
            temporary_binary.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)

    installed = inspect_pinned_yt_dlp(
        cache_directory,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    if not installed["available"]:
        raise ScreenshotRuntimeError(
            "yt-dlp를 준비했지만 실행 확인에 실패했습니다: "
            + str(installed.get("reason") or "unknown")
        )
    installed["reused"] = False
    return installed


def resolve_ffmpeg(
    *,
    environ: dict[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    candidates: list[tuple[str, str | None]] = [
        ("environment_override", environment.get(FFMPEG_OVERRIDE_ENV)),
        ("path", which("ffmpeg")),
        ("homebrew_apple_silicon", "/opt/homebrew/bin/ffmpeg"),
        ("homebrew_intel", "/usr/local/bin/ffmpeg"),
    ]
    seen: set[str] = set()
    for method, value in candidates:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        path = Path(normalized).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return {
                "available": True,
                "path": str(path),
                "method": method,
                "reason": None,
            }
    return {
        "available": False,
        "path": None,
        "method": None,
        "reason": "ffmpeg_unavailable",
    }


def inspect_screenshot_tools(
    cache_directory: Path | str | None = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
    environ: dict[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    timeout_seconds: float = TOOL_VERSION_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    yt_dlp = inspect_pinned_yt_dlp(
        cache_directory,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    ffmpeg = resolve_ffmpeg(environ=environ, which=which)
    return {
        "ready": bool(yt_dlp["available"] and ffmpeg["available"]),
        "yt_dlp": yt_dlp,
        "ffmpeg": ffmpeg,
    }


def _emit(progress_callback: Callable[[dict[str, Any]], None] | None, **event: Any) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(event)
    except Exception:
        pass


def _mark_failed(plan: dict[str, Any], warning: str) -> dict[str, Any]:
    output = copy.deepcopy(plan)
    output["status"] = "failed"
    output.setdefault("warnings", []).append(warning)
    for item in output.get("items") or []:
        if not isinstance(item, dict):
            continue
        item["status"] = "failed"
        item["failure_stage"] = (
            "cache_promotion"
            if warning.startswith("screenshot_output_promotion_failed")
            else "candidate_generation"
        )
        item["failure_reason"] = warning
        for candidate in item.get("screenshot_candidates") or []:
            if isinstance(candidate, dict):
                candidate["status"] = "failed"
                candidate["error"] = warning
    return output


def _refresh_asset_item_statuses(assets: dict[str, Any]) -> None:
    for item in assets.get("items") or []:
        if not isinstance(item, dict):
            continue
        candidates = [
            candidate
            for candidate in item.get("screenshot_candidates") or []
            if isinstance(candidate, dict)
        ]
        if not candidates:
            continue
        completed = sum(candidate.get("status") == "completed" for candidate in candidates)
        failed = sum(candidate.get("status") == "failed" for candidate in candidates)
        if completed and failed:
            item["status"] = "partial"
        elif failed:
            item["status"] = "failed"
        elif completed == len(candidates):
            item["status"] = "completed"
        if failed:
            errors = [
                str(candidate.get("error"))
                for candidate in candidates
                if candidate.get("error")
            ]
            item["failure_stage"] = (
                "cache_promotion"
                if any(error == "staged_screenshot_missing" for error in errors)
                else "candidate_extraction"
            )
            item["failure_reason"] = errors[0] if errors else "candidate_failed"
    statuses = [
        str(item.get("status") or "")
        for item in assets.get("items") or []
        if isinstance(item, dict)
    ]
    completed_items = sum(status == "completed" for status in statuses)
    problem_items = sum(
        status in {"partial", "failed", "skipped"} for status in statuses
    )
    if completed_items and problem_items:
        assets["status"] = "partial"
    elif statuses and completed_items == len(statuses):
        assets["status"] = "completed"
    elif any(status == "partial" for status in statuses):
        assets["status"] = "partial"
    elif any(status == "failed" for status in statuses):
        assets["status"] = "failed"
    elif statuses and all(status == "skipped" for status in statuses):
        assets["status"] = "skipped"


def _safe_destination(output_root: Path, relative_value: Any) -> Path:
    relative = Path(str(relative_value or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ScreenshotRuntimeError("unsafe_screenshot_relative_path")
    destination = (output_root / relative).resolve()
    try:
        destination.relative_to(output_root.resolve())
    except ValueError as exc:
        raise ScreenshotRuntimeError("screenshot_path_outside_output_root") from exc
    return destination


def _promote_staged_candidates(
    assets: dict[str, Any],
    staging_root: Path,
    output_root: Path,
) -> None:
    for item in assets.get("items") or []:
        if not isinstance(item, dict):
            continue
        prepared: list[tuple[Path, Path]] = []
        for candidate in item.get("screenshot_candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("status") != "completed":
                continue
            relative = candidate.get("relative_path")
            staged = _safe_destination(staging_root, relative)
            destination = _safe_destination(output_root, relative)
            if not staged.is_file() or staged.stat().st_size <= 0:
                candidate["status"] = "failed"
                candidate["error"] = "staged_screenshot_missing"
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copyfile(staged, temporary)
            prepared.append((temporary, destination))
        if not prepared:
            continue
        chapter_directory = prepared[0][1].parent
        for old_path in chapter_directory.glob("candidate_[0-9][0-9].jpg"):
            old_path.unlink()
        for temporary, destination in prepared:
            os.replace(temporary, destination)


def _preserve_valid_selections(
    previous_assets: dict[str, Any] | None,
    new_assets: dict[str, Any],
) -> None:
    if not isinstance(previous_assets, dict):
        return
    old_items = {
        str(item.get("content_chapter_id") or ""): item
        for item in previous_assets.get("items") or []
        if isinstance(item, dict)
    }
    for item in new_assets.get("items") or []:
        if not isinstance(item, dict):
            continue
        old = old_items.get(str(item.get("content_chapter_id") or ""))
        if not old or old.get("chapter_fingerprint") != item.get("chapter_fingerprint"):
            continue
        selected = old.get("selected_screenshot")
        if not isinstance(selected, dict):
            continue
        item["selected_screenshot"] = copy.deepcopy(selected)


def _merge_targeted_assets(
    previous_assets: dict[str, Any] | None,
    generated_assets: dict[str, Any],
    target_chapter_ids: set[str] | None,
) -> dict[str, Any]:
    if target_chapter_ids is None or not isinstance(previous_assets, dict):
        return generated_assets
    generated_by_id = {
        str(item.get("content_chapter_id") or ""): item
        for item in generated_assets.get("items") or []
        if isinstance(item, dict)
    }
    output = copy.deepcopy(previous_assets)
    merged_items: list[dict[str, Any]] = []
    retained_ids: set[str] = set()
    for old_item in output.get("items") or []:
        if not isinstance(old_item, dict):
            continue
        chapter_id = str(old_item.get("content_chapter_id") or "")
        if chapter_id in target_chapter_ids and chapter_id in generated_by_id:
            merged_items.append(copy.deepcopy(generated_by_id[chapter_id]))
        else:
            merged_items.append(old_item)
        retained_ids.add(chapter_id)
    for chapter_id, item in generated_by_id.items():
        if chapter_id not in retained_ids:
            merged_items.append(copy.deepcopy(item))
    output["items"] = merged_items
    for field in (
        "schema_version",
        "method",
        "video_id",
        "source_url",
        "source_locator",
        "candidate_storage",
        "runtime",
    ):
        if field in generated_assets:
            output[field] = copy.deepcopy(generated_assets[field])
    output["status"] = generated_assets.get("status", "failed")
    output["warnings"] = list(
        dict.fromkeys(
            [str(value) for value in output.get("warnings") or []]
            + [str(value) for value in generated_assets.get("warnings") or []]
        )
    )
    return output


def generate_screenshot_candidates(
    result: dict[str, Any],
    output_directory: Path | str,
    *,
    candidate_cache_directory: Path | str | None = None,
    cache_directory: Path | str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    environ: dict[str, str] | None = None,
    yt_dlp_executable: Path | str | None = None,
    ffmpeg_executable: Path | str | None = None,
    chapter_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    """Generate final chapter candidates with one temporary video download."""
    operation_started = time.perf_counter()
    started_at = _utc_now()
    planning_started = time.perf_counter()
    full_plan = build_screenshot_plan(result)
    planning_duration = time.perf_counter() - planning_started
    previous_assets = (
        result.get("content_chapter_assets")
        if isinstance(result.get("content_chapter_assets"), dict)
        else None
    )
    target_chapter_ids = (
        {str(value) for value in chapter_ids}
        if chapter_ids is not None
        else None
    )
    plan = copy.deepcopy(full_plan)
    if candidate_cache_directory is not None:
        plan = scope_candidate_assets(result, plan)
    if target_chapter_ids is not None:
        plan["items"] = [
            item
            for item in plan.get("items") or []
            if isinstance(item, dict)
            and str(item.get("content_chapter_id") or "") in target_chapter_ids
        ]
        if not plan["items"]:
            failed = _mark_failed(plan, "screenshot_target_chapter_not_found")
            failed["runtime"] = {
                "started_at": _utc_now(),
                "completed_at": _utc_now(),
                "video_download_count": 0,
                "qwen_generation_calls": 0,
                "planning_duration_seconds": round(planning_duration, 6),
                "tool_check_duration_seconds": 0.0,
                "video_preparation_duration_seconds": 0.0,
                "candidate_extraction_duration_seconds": 0.0,
                "total_duration_seconds": round(
                    time.perf_counter() - operation_started,
                    6,
                ),
            }
            return _merge_targeted_assets(
                previous_assets, failed, target_chapter_ids
            )
    total = sum(
        len(item.get("screenshot_candidates") or [])
        for item in plan.get("items") or []
        if isinstance(item, dict)
    )
    _emit(progress_callback, stage="tools_check", current=0, total=total)

    if total == 0:
        failed = _mark_failed(plan, "screenshot_plan_has_no_candidates")
        failed["runtime"] = {
            "started_at": started_at,
            "completed_at": _utc_now(),
            "video_download_count": 0,
            "candidate_extraction_attempts": 0,
            "qwen_generation_calls": 0,
            "planning_duration_seconds": round(planning_duration, 6),
            "tool_check_duration_seconds": 0.0,
            "video_preparation_duration_seconds": 0.0,
            "candidate_extraction_duration_seconds": 0.0,
            "total_duration_seconds": round(
                time.perf_counter() - operation_started,
                6,
            ),
        }
        return _merge_targeted_assets(
            previous_assets, failed, target_chapter_ids
        )

    tool_check_started = time.perf_counter()
    if yt_dlp_executable is None:
        sidecar = inspect_pinned_yt_dlp(cache_directory, runner=runner)
        yt_dlp = sidecar.get("executable_path") if sidecar.get("available") else None
    else:
        yt_dlp = str(yt_dlp_executable)
        sidecar = {
            "available": True,
            "channel": PINNED_YTDLP_CHANNEL,
            "version": PINNED_YTDLP_VERSION,
            "executable_path": yt_dlp,
            "reason": None,
        }
    if ffmpeg_executable is None:
        ffmpeg_status = resolve_ffmpeg(environ=environ, which=which)
        ffmpeg = ffmpeg_status.get("path") if ffmpeg_status.get("available") else None
    else:
        ffmpeg = str(ffmpeg_executable)
        ffmpeg_status = {
            "available": True,
            "path": ffmpeg,
            "method": "explicit_runtime_path",
            "reason": None,
        }
    tool_check_duration = time.perf_counter() - tool_check_started

    if not yt_dlp or not ffmpeg:
        missing = []
        if not yt_dlp:
            missing.append("yt-dlp")
        if not ffmpeg:
            missing.append("ffmpeg")
        warning = "screenshot_tools_unavailable:" + ",".join(missing)
        failed = _mark_failed(plan, warning)
        failed["runtime"] = {
            "started_at": started_at,
            "completed_at": _utc_now(),
            "video_download_count": 0,
            "yt_dlp": sidecar,
            "ffmpeg": ffmpeg_status,
            "qwen_generation_calls": 0,
            "planning_duration_seconds": round(planning_duration, 6),
            "tool_check_duration_seconds": round(tool_check_duration, 6),
            "video_preparation_duration_seconds": 0.0,
            "candidate_extraction_duration_seconds": 0.0,
            "total_duration_seconds": round(
                time.perf_counter() - operation_started,
                6,
            ),
        }
        return _merge_targeted_assets(
            previous_assets, failed, target_chapter_ids
        )

    output_root = Path(candidate_cache_directory or output_directory)
    counts = {"video_download": 0, "extracted": 0}
    stage_durations = {"video_preparation": 0.0, "candidate_extraction": 0.0}

    def monitored_runner(command: list[str], **kwargs: Any) -> Any:
        executable = str(command[0]) if command else ""
        if executable == str(yt_dlp):
            counts["video_download"] += 1
            _emit(
                progress_callback,
                stage="video_preparation",
                current=0,
                total=total,
            )
            started = time.perf_counter()
            try:
                return runner(command, **kwargs)
            finally:
                stage_durations["video_preparation"] += (
                    time.perf_counter() - started
                )
        if executable == str(ffmpeg):
            started = time.perf_counter()
            try:
                return runner(command, **kwargs)
            finally:
                stage_durations["candidate_extraction"] += (
                    time.perf_counter() - started
                )
                counts["extracted"] += 1
                _emit(
                    progress_callback,
                    stage="extracting",
                    current=counts["extracted"],
                    total=total,
                )
        return runner(command, **kwargs)

    with tempfile.TemporaryDirectory(prefix="v0316_screenshot_stage_") as stage_name:
        staging_root = Path(stage_name)
        extracted = extract_screenshot_candidates(
            plan,
            staging_root,
            runner=monitored_runner,
            which=lambda name: (
                str(yt_dlp)
                if name == "yt-dlp"
                else str(ffmpeg) if name == "ffmpeg" else None
            ),
        )
        try:
            _promote_staged_candidates(extracted, staging_root, output_root)
        except Exception as exc:
            extracted = _mark_failed(
                extracted,
                f"screenshot_output_promotion_failed:{type(exc).__name__}",
            )
        _refresh_asset_item_statuses(extracted)

    _preserve_valid_selections(
        previous_assets,
        extracted,
    )
    extracted["runtime"] = {
        "started_at": started_at,
        "completed_at": _utc_now(),
        "video_download_count": counts["video_download"],
        "candidate_extraction_attempts": counts["extracted"],
        "yt_dlp": sidecar,
        "ffmpeg": ffmpeg_status,
        "qwen_generation_calls": 0,
        "planning_duration_seconds": round(planning_duration, 6),
        "tool_check_duration_seconds": round(tool_check_duration, 6),
        "video_preparation_duration_seconds": round(
            stage_durations["video_preparation"],
            6,
        ),
        "candidate_extraction_duration_seconds": round(
            stage_durations["candidate_extraction"],
            6,
        ),
        "total_duration_seconds": round(
            time.perf_counter() - operation_started,
            6,
        ),
    }
    _emit(
        progress_callback,
        stage="complete",
        current=counts["extracted"],
        total=total,
        status=extracted.get("status"),
    )
    return _merge_targeted_assets(
        previous_assets, extracted, target_chapter_ids
    )


def chapter_asset_is_stale(result: dict[str, Any], item: dict[str, Any]) -> bool:
    chapter_id = str(item.get("content_chapter_id") or "")
    current = next(
        (
            chapter
            for chapter in result.get("content_chapters") or []
            if isinstance(chapter, dict)
            and str(chapter.get("content_chapter_id") or "") == chapter_id
        ),
        None,
    )
    if current is None:
        return True
    from screenshot_candidates import chapter_fingerprint

    return chapter_fingerprint(current) != item.get("chapter_fingerprint")


def select_screenshot_candidate(
    result: dict[str, Any],
    content_chapter_id: str,
    candidate_index: int,
    *,
    selected_at: str | None = None,
) -> dict[str, Any]:
    output = copy.deepcopy(result)
    assets = output.get("content_chapter_assets")
    if not isinstance(assets, dict):
        raise ScreenshotRuntimeError("content_chapter_assets가 없습니다.")
    item = next(
        (
            value
            for value in assets.get("items") or []
            if isinstance(value, dict)
            and str(value.get("content_chapter_id") or "")
            == str(content_chapter_id)
        ),
        None,
    )
    if item is None:
        raise ScreenshotRuntimeError("선택할 content chapter asset이 없습니다.")
    if chapter_asset_is_stale(output, item):
        raise StaleScreenshotSelectionError(
            "content chapter가 변경되어 기존 후보를 다시 생성해야 합니다."
        )
    candidate = next(
        (
            value
            for value in item.get("screenshot_candidates") or []
            if isinstance(value, dict)
            and value.get("candidate_index") == int(candidate_index)
        ),
        None,
    )
    if candidate is None or candidate.get("status") != "completed":
        raise ScreenshotRuntimeError("완료된 screenshot 후보만 선택할 수 있습니다.")
    item["selected_screenshot"] = {
        "candidate_index": int(candidate["candidate_index"]),
        "relative_path": str(candidate["relative_path"]),
        "selected_at": selected_at or _utc_now(),
    }
    return output


def persist_screenshot_assets(
    result: dict[str, Any],
    assets: dict[str, Any],
    autosave_directory: Path | str,
) -> tuple[Path, dict[str, Any]]:
    """Atomically persist only the detached asset layer alongside the result."""
    from review_store import atomic_autosave

    output = copy.deepcopy(result)
    output["content_chapter_assets"] = copy.deepcopy(assets)
    return atomic_autosave(autosave_directory, output)


def persist_selected_screenshot_package(
    result: dict[str, Any],
    content_chapter_id: str,
    candidate_index: int,
    candidate_cache_directory: Path | str,
    output_directory: Path | str,
    autosave_directory: Path | str,
    *,
    selected_at: str | None = None,
    cleanup_candidates: bool = True,
) -> dict[str, Any]:
    """Backward-compatible one-chapter wrapper around the bulk transaction."""
    package = persist_selected_screenshot_packages(
        result,
        {str(content_chapter_id): int(candidate_index)},
        candidate_cache_directory,
        output_directory,
        autosave_directory,
        selected_at=selected_at,
        cleanup_candidates=cleanup_candidates,
    )
    if not package["successful_chapter_ids"]:
        failure = package["failures"][0] if package["failures"] else {}
        raise ScreenshotRuntimeError(
            str(failure.get("reason") or "selected_screenshot_save_failed")
        )
    chapter_id = str(content_chapter_id)
    return {
        "autosave_path": package["autosave_path"],
        "json_path": package["json_path"],
        "image_path": package["image_paths"][chapter_id],
        "saved_result": package["saved_result"],
    }


def _selection_preflight(
    result: dict[str, Any],
    content_chapter_id: str,
    candidate_index: int,
    candidate_cache_directory: Path | str,
    output_directory: Path | str,
) -> dict[str, Any]:
    assets = result.get("content_chapter_assets")
    if not isinstance(assets, dict):
        raise ScreenshotRuntimeError("content_chapter_assets_missing")
    item = next(
        (
            value
            for value in assets.get("items") or []
            if isinstance(value, dict)
            and str(value.get("content_chapter_id") or "")
            == content_chapter_id
        ),
        None,
    )
    if item is None:
        raise ScreenshotRuntimeError("content_chapter_asset_missing")
    if chapter_asset_is_stale(result, item):
        raise StaleScreenshotSelectionError("content_chapter_fingerprint_stale")
    candidate = next(
        (
            value
            for value in item.get("screenshot_candidates") or []
            if isinstance(value, dict)
            and value.get("candidate_index") == candidate_index
        ),
        None,
    )
    if candidate is None:
        raise ScreenshotRuntimeError("selected_candidate_index_missing")
    if candidate.get("status") != "completed":
        raise ScreenshotRuntimeError("selected_candidate_not_completed")
    try:
        source = resolve_candidate_path(
            candidate_cache_directory,
            output_directory,
            candidate.get("relative_path"),
        )
        if not source.is_file() or source.stat().st_size <= 0:
            raise ScreenshotOutputError("selected_candidate_file_missing")
        image_path = final_image_path(
            output_directory,
            result,
            content_chapter_id,
        )
    except ScreenshotOutputError as exc:
        raise ScreenshotRuntimeError(str(exc)) from exc
    return {
        "item": item,
        "candidate": candidate,
        "source": source,
        "image_path": image_path,
    }


def persist_selected_screenshot_packages(
    result: dict[str, Any],
    selections: dict[str, int],
    candidate_cache_directory: Path | str,
    output_directory: Path | str,
    autosave_directory: Path | str,
    *,
    selected_at: str | None = None,
    cleanup_candidates: bool = True,
) -> dict[str, Any]:
    """Preflight all selections, save valid images, then write JSON once."""
    from review_store import atomic_autosave

    working = copy.deepcopy(result)
    prepared: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for chapter_value, candidate_value in selections.items():
        chapter_id = str(chapter_value or "").strip()
        try:
            candidate_index = int(candidate_value)
            prepared_item = _selection_preflight(
                working,
                chapter_id,
                candidate_index,
                candidate_cache_directory,
                output_directory,
            )
        except Exception as exc:
            failures.append(
                {
                    "content_chapter_id": chapter_id or "unknown",
                    "stage": "preflight",
                    "reason": str(exc) or type(exc).__name__,
                }
            )
            continue
        prepared_item["content_chapter_id"] = chapter_id
        prepared_item["candidate_index"] = candidate_index
        prepared.append(prepared_item)

    timestamp = selected_at or _utc_now()
    successful_chapter_ids: list[str] = []
    image_paths: dict[str, Path] = {}
    for prepared_item in prepared:
        chapter_id = prepared_item["content_chapter_id"]
        try:
            atomic_copy(
                prepared_item["source"],
                prepared_item["image_path"],
            )
        except Exception as exc:
            failures.append(
                {
                    "content_chapter_id": chapter_id,
                    "stage": "image_save",
                    "reason": str(exc) or type(exc).__name__,
                }
            )
            continue
        candidate_index = int(prepared_item["candidate_index"])
        output_scope_relative_path = str(
            prepared_item["image_path"].parent.relative_to(
                Path(output_directory).resolve()
            )
        )
        prepared_item["item"]["selected_screenshot"] = {
            "candidate_index": candidate_index,
            "source_candidate_index": candidate_index,
            "relative_path": prepared_item["image_path"].name,
            "selected_at": timestamp,
            "storage_kind": "final_output",
            "output_scope_relative_path": output_scope_relative_path,
        }
        successful_chapter_ids.append(chapter_id)
        image_paths[chapter_id] = prepared_item["image_path"]

    autosave_path: Path | None = None
    package_json_path: Path | None = None
    saved = working
    if successful_chapter_ids:
        autosave_path, saved = atomic_autosave(autosave_directory, working)
        package_json_path = final_json_path(output_directory, saved)
        atomic_write_json(package_json_path, saved)

    cleanup_failures: list[dict[str, str]] = []
    if cleanup_candidates and successful_chapter_ids:
        for chapter_id in successful_chapter_ids:
            try:
                cleanup_candidate_scope(
                    candidate_cache_directory,
                    saved,
                    chapter_id,
                )
            except Exception as exc:
                cleanup_failures.append(
                    {
                        "content_chapter_id": chapter_id,
                        "stage": "candidate_cache_cleanup",
                        "reason": str(exc) or type(exc).__name__,
                    }
                )
    return {
        "requested_count": len(selections),
        "success_count": len(successful_chapter_ids),
        "failure_count": len(failures),
        "successful_chapter_ids": successful_chapter_ids,
        "failures": failures,
        "cleanup_failures": cleanup_failures,
        "autosave_path": autosave_path,
        "json_path": package_json_path,
        "image_paths": image_paths,
        "saved_result": saved,
    }
