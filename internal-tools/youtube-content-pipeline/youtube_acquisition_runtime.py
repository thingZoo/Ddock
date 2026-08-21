from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from youtube_acquisition import collector as bundled_collector


COLLECTION_SCHEMA_VERSION = "youtube_acquisition_validation_v0.1"
_SAFE_FILE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class AcquisitionRuntimeError(RuntimeError):
    pass


def bundled_collector_info(
    project_directory: Path | str | None = None,
) -> dict[str, Any]:
    project = Path(project_directory or Path(__file__).resolve().parent).resolve()
    collector_path = project / "youtube_acquisition" / "collector.py"
    if not collector_path.is_file():
        raise AcquisitionRuntimeError(
            "통합 도구 내부 YouTube collector를 찾지 못했습니다: "
            f"{collector_path}"
        )
    return {
        "directory": str(collector_path.parent),
        "logic_file": str(collector_path),
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "bundled": True,
    }


def load_bundled_collector(
    project_directory: Path | str | None = None,
) -> Any:
    bundled_collector_info(project_directory)
    if not callable(getattr(bundled_collector, "collect", None)):
        raise AcquisitionRuntimeError("내부 collector.py에 collect()가 없습니다.")
    if not callable(getattr(bundled_collector, "extract_video_id", None)):
        raise AcquisitionRuntimeError("내부 collector.py에 extract_video_id()가 없습니다.")
    return bundled_collector


def extract_video_id(
    video_url: str,
    *,
    project_directory: Path | str | None = None,
) -> str:
    module = load_bundled_collector(project_directory)
    try:
        return str(module.extract_video_id(video_url))
    except Exception as exc:
        raise AcquisitionRuntimeError(str(exc)) from exc


def _emit(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    stage: str,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback({"stage": stage})
    except Exception:
        pass


def validate_collection_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(result, dict):
        return ["collection_result_must_be_an_object"]
    if result.get("schema_version") != COLLECTION_SCHEMA_VERSION:
        errors.append("collection_schema_version_mismatch")
    if not str(result.get("source_url") or "").strip():
        errors.append("collection_source_url_missing")
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("collection_metadata_missing")
    elif not str(metadata.get("video_id") or "").strip():
        errors.append("collection_video_id_missing")
    if not isinstance(result.get("creator_chapters"), list):
        errors.append("collection_creator_chapters_must_be_a_list")
    transcript = result.get("transcript")
    if not isinstance(transcript, dict):
        errors.append("collection_transcript_missing")
    elif not isinstance(transcript.get("items"), list):
        errors.append("collection_transcript_items_must_be_a_list")
    return errors


def preprocessing_eligible(result: dict[str, Any]) -> bool:
    if validate_collection_result(result):
        return False
    transcript = result.get("transcript") or {}
    return bool(
        transcript.get("status") == "collected"
        and isinstance(transcript.get("items"), list)
        and transcript["items"]
    )


def collect_from_youtube(
    video_url: str,
    api_key: str,
    *,
    preferred_languages: list[str] | None = None,
    project_directory: Path | str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Call the bundled collector's unchanged collect() path."""
    module = load_bundled_collector(project_directory)
    originals: dict[str, Any] = {}
    stage_by_function = {
        "youtube_metadata": "video_info",
        "parse_creator_chapters": "creator_chapters",
        "fetch_transcript": "transcript",
    }
    for function_name, stage in stage_by_function.items():
        original = getattr(module, function_name, None)
        if not callable(original):
            continue
        originals[function_name] = original

        def wrapped(
            *args: Any,
            _original: Any = original,
            _stage: str = stage,
            **kwargs: Any,
        ) -> Any:
            _emit(progress_callback, _stage)
            return _original(*args, **kwargs)

        setattr(module, function_name, wrapped)
    try:
        result = module.collect(
            video_url,
            api_key,
            preferred_languages=preferred_languages or ["ko", "en"],
        )
    except Exception as exc:
        raise AcquisitionRuntimeError(str(exc)) from exc
    finally:
        for function_name, original in originals.items():
            setattr(module, function_name, original)
    errors = validate_collection_result(result)
    if errors:
        raise AcquisitionRuntimeError(
            "내부 collector 결과 schema가 올바르지 않습니다: "
            + ", ".join(errors)
        )
    _emit(progress_callback, "complete")
    return result


def acquisition_fingerprint(result: dict[str, Any]) -> str:
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    payload = {
        "schema_version": result.get("schema_version"),
        "video_id": metadata.get("video_id"),
        "source_url": result.get("source_url"),
        "published_at": metadata.get("published_at"),
        "duration_seconds": metadata.get("duration_seconds"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_collection_backup(
    result: dict[str, Any],
    output_directory: Path | str,
) -> Path:
    errors = validate_collection_result(result)
    if errors:
        raise AcquisitionRuntimeError(
            "저장할 collection 결과가 올바르지 않습니다: " + ", ".join(errors)
        )
    metadata = result.get("metadata") or {}
    video_id = _SAFE_FILE_COMPONENT.sub(
        "_", str(metadata.get("video_id") or "youtube")
    )
    root = Path(output_directory) / "collections"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{video_id}_collection.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target
