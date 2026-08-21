from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MAX_SAFE_TITLE_BYTES = 180


class ScreenshotOutputError(RuntimeError):
    pass


def safe_component(value: Any, fallback: str) -> str:
    component = _SAFE_COMPONENT.sub("_", str(value or "").strip())
    component = component.strip("._")
    return component or fallback


def _title_value(result: dict[str, Any]) -> str:
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    source_metadata = result.get("source_metadata")
    source_metadata = source_metadata if isinstance(source_metadata, dict) else {}
    for value in (
        result.get("source_title"),
        metadata.get("title"),
        source_metadata.get("title"),
        result.get("video_title"),
        result.get("title"),
    ):
        title = str(value or "").strip()
        if title:
            return title
    return ""


def safe_video_title(value: Any, max_bytes: int = _MAX_SAFE_TITLE_BYTES) -> str:
    """Keep a readable Unicode title while making one safe path component."""
    title = str(value or "").replace("/", "／").replace("\\", "／")
    title = _CONTROL_CHARACTERS.sub(" ", title)
    title = " ".join(title.split()).strip(" .")
    if title in {"", ".", ".."}:
        return ""
    encoded = title.encode("utf-8")
    if len(encoded) > max_bytes:
        title = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .")
    return title


def result_with_source_title(
    result: dict[str, Any],
    source_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add current acquisition title metadata without mutating either input."""
    output = copy.deepcopy(result)
    source = source_data if isinstance(source_data, dict) else {}
    title = _title_value(source) or _title_value(output)
    if title:
        output["source_title"] = title
    return output


def screenshot_scope(result: dict[str, Any]) -> dict[str, str]:
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    chapter = result.get("processed_chapter")
    chapter = chapter if isinstance(chapter, dict) else {}
    return {
        "video_id": safe_component(
            result.get("video_id") or metadata.get("video_id"),
            "unknown-video",
        ),
        "source_chapter_id": safe_component(
            chapter.get("chapter_id"),
            "FULL",
        ),
    }


def final_video_directory_name(result: dict[str, Any]) -> str:
    scope = screenshot_scope(result)
    title = safe_video_title(_title_value(result))
    if not title:
        return scope["video_id"]
    return f"{title} [{scope['video_id']}]"


def scoped_candidate_relative_path(
    result: dict[str, Any],
    content_chapter_id: str,
    candidate_index: int,
) -> Path:
    scope = screenshot_scope(result)
    chapter_id = safe_component(content_chapter_id, "CCH")
    return (
        Path(scope["video_id"])
        / scope["source_chapter_id"]
        / chapter_id
        / f"candidate_{int(candidate_index):02d}.jpg"
    )


def scope_candidate_assets(
    result: dict[str, Any],
    assets: dict[str, Any],
) -> dict[str, Any]:
    output = copy.deepcopy(assets)
    scope = screenshot_scope(result)
    output["candidate_storage"] = {
        "kind": "internal_cache",
        "scope": copy.deepcopy(scope),
    }
    for item in output.get("items") or []:
        if not isinstance(item, dict):
            continue
        content_chapter_id = str(item.get("content_chapter_id") or "CCH")
        item["asset_scope"] = {
            **scope,
            "content_chapter_id": safe_component(
                content_chapter_id,
                "CCH",
            ),
        }
        for candidate in item.get("screenshot_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            candidate["relative_path"] = str(
                scoped_candidate_relative_path(
                    result,
                    content_chapter_id,
                    int(candidate.get("candidate_index") or 0),
                )
            )
            candidate["storage_kind"] = "internal_cache"
    return output


def safe_child(root: Path | str, relative_value: Any) -> Path:
    base = Path(root).resolve()
    relative = Path(str(relative_value or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ScreenshotOutputError("unsafe_relative_path")
    destination = (base / relative).resolve()
    try:
        destination.relative_to(base)
    except ValueError as exc:
        raise ScreenshotOutputError("path_outside_storage_root") from exc
    return destination


def final_chapter_directory(
    output_root: Path | str,
    result: dict[str, Any],
) -> Path:
    scope = screenshot_scope(result)
    return safe_child(
        output_root,
        Path(final_video_directory_name(result)) / scope["source_chapter_id"],
    )


def legacy_final_chapter_directory(
    output_root: Path | str,
    result: dict[str, Any],
) -> Path:
    scope = screenshot_scope(result)
    return safe_child(
        output_root,
        Path(scope["video_id"]) / scope["source_chapter_id"],
    )


def final_json_path(
    output_root: Path | str,
    result: dict[str, Any],
) -> Path:
    scope = screenshot_scope(result)
    return final_chapter_directory(output_root, result) / (
        scope["source_chapter_id"] + "_preprocessed.json"
    )


def final_image_path(
    output_root: Path | str,
    result: dict[str, Any],
    content_chapter_id: str,
) -> Path:
    return final_chapter_directory(output_root, result) / (
        safe_component(content_chapter_id, "CCH") + ".jpg"
    )


def resolve_candidate_path(
    candidate_cache_root: Path | str,
    output_root: Path | str,
    relative_value: Any,
) -> Path:
    relative = Path(str(relative_value or ""))
    primary = safe_child(candidate_cache_root, relative)
    if primary.is_file() and primary.stat().st_size > 0:
        return primary
    if relative.parts and relative.parts[0] == "screenshots":
        legacy = safe_child(output_root, relative)
        if legacy.is_file() and legacy.stat().st_size > 0:
            return legacy
    return primary


def resolve_selected_path(
    output_root: Path | str,
    result: dict[str, Any],
    selected: dict[str, Any],
) -> Path:
    relative = Path(str(selected.get("relative_path") or ""))
    if relative.parts and relative.parts[0] == "screenshots":
        return safe_child(output_root, relative)
    stored_directory = selected.get("output_scope_relative_path")
    if stored_directory:
        stored = safe_child(
            output_root,
            Path(str(stored_directory)) / relative,
        )
        if stored.is_file() and stored.stat().st_size > 0:
            return stored
    primary = safe_child(final_chapter_directory(output_root, result), relative)
    if primary.is_file() and primary.stat().st_size > 0:
        return primary
    legacy = safe_child(legacy_final_chapter_directory(output_root, result), relative)
    if legacy != primary and legacy.is_file() and legacy.stat().st_size > 0:
        return legacy
    return primary


def atomic_copy(source: Path, destination: Path) -> None:
    if not source.is_file() or source.stat().st_size <= 0:
        raise ScreenshotOutputError("selected_candidate_file_missing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        shutil.copyfile(source, temporary)
        if temporary.stat().st_size <= 0:
            raise ScreenshotOutputError("selected_candidate_copy_is_empty")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_candidate_scope(
    candidate_cache_root: Path | str,
    result: dict[str, Any],
    content_chapter_id: str,
) -> None:
    relative = scoped_candidate_relative_path(
        result,
        content_chapter_id,
        1,
    ).parent
    directory = safe_child(candidate_cache_root, relative)
    if directory.is_dir():
        shutil.rmtree(directory)


def legacy_screenshot_directory(output_root: Path | str) -> Path | None:
    directory = Path(output_root) / "screenshots"
    if directory.is_dir() and any(directory.rglob("candidate_*.jpg")):
        return directory
    return None
