from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from korean_asr_editorial_review import (
    _adjacent_leakage,
    _canonicalize_entities,
    _next_normalization_number,
    _source_language,
    _strip_korean_particle,
    build_video_local_entity_map,
    load_canonical_registry,
)
from runtime_generation_metrics import generation_stage
from screenshot_candidates import resolve_source_locator
from screenshot_runtime import inspect_pinned_yt_dlp


AUDIO_REVIEW_VERSION = "korean_selective_audio_reasr_v0.2"
DEFAULT_ASR_ENGINE = "mlx-whisper"
DEFAULT_ASR_MODEL = "mlx-community/whisper-large-v3-turbo"
MODEL_PATH_ENV = "KOREAN_AUDIO_ASR_MODEL_PATH"
AUDIO_REVIEW_BUDGET_ENV = "KOREAN_AUDIO_REVIEW_BUDGET_SECONDS"
WINDOW_PADDING_SECONDS = 1.75
CLUSTER_MAX_GAP_SECONDS = 2.5
MAX_WINDOW_SECONDS = 28.0
DEFAULT_AUDIO_REVIEW_BUDGET_SECONDS = 180.0
ADAPTIVE_HIGH_SEVERITY_PRIORITY = 360.0
ADAPTIVE_AUDIO_REVIEW_CAP_SECONDS = 480.0
YTDLP_AUDIO_FORMAT = "bestaudio[abr<=160]/bestaudio"
YTDLP_VERSION_CHECK_TIMEOUT_SECONDS = 30.0

_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])\d+(?:[.,:]\d+)*(?:%|원|년|월|일|개|번|단계)?"
)
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./-]*")
_ACTOR_RE = re.compile(
    r"(?<![가-힣])(?:제가|저는|나는|내가|우리가|저희가|그가|그분이|사용자가|개발자가|디자이너가)(?![가-힣])"
)
_RELATION_ACTION_RE = re.compile(
    r"(?:연결|삭제|생성|수정|다운로드|업로드|선택|실행|저장|구현|복사|이동|변경)"
)
_NEGATION_RE = re.compile(r"(?:하지\s*않|하지\s*말|안\s+[가-힣]+|못\s+[가-힣]+|금지)")

_AUDIO_HIGH_SIGNALS = {
    "canonical_alias_near_match",
    "metadata_term_embedded_in_unknown_token",
    "unverified_official_name_candidate",
    "protected_korean_term_near_match",
    "broken_korean_compound",
    "unusual_korean_connective_sequence",
    "short_technical_modifier_needs_context_review",
    "contextually_unusual_action_verb",
    "past_demonstration_verb_needs_review",
    "singleton_unregistered_acronym",
    "video_local_person_identity_near_match",
    "official_entity_discourse_continuity",
    "acronym_discourse_inconsistency",
    "technical_domain_phrase_near_match",
    "malformed_script_boundary",
    "attached_token_boundary_candidate",
    "severe_video_local_lexical_outlier",
    "deterministic_fix_with_remaining_lexical_outlier",
    "deterministic_boundary_fix_with_remaining_audio_review",
}
_AUDIO_MEDIUM_SIGNALS = {
    "within_row_lexical_inconsistency",
    "loanword_semantic_duplication",
    "deterministic_fix_with_remaining_lexical_outlier",
}
_TEXT_ONLY_SIGNALS = {
    "malformed_korean_join",
    "video_local_lexical_outlier",
}


class AudioASRAdapter(Protocol):
    engine_name: str
    model_name: str

    def capability(self) -> dict[str, Any]: ...

    def transcribe(
        self,
        audio_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AudioWindow:
    window_id: str
    start_seconds: float
    end_seconds: float
    row_ids: tuple[str, ...]
    priority: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


def _finite_seconds(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _configured_audio_budget(value: float | None) -> float:
    if value is not None:
        return max(0.0, float(value))
    configured = str(os.environ.get(AUDIO_REVIEW_BUDGET_ENV) or "").strip()
    if configured:
        try:
            return max(0.0, float(configured))
        except ValueError:
            pass
    return DEFAULT_AUDIO_REVIEW_BUDGET_SECONDS


def _huggingface_cache_model_path(model_id: str) -> Path | None:
    explicit = str(os.environ.get(MODEL_PATH_ENV) or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_dir() else None
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    model_root = hub / ("models--" + model_id.replace("/", "--"))
    snapshots = model_root / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = sorted(
        (path for path in snapshots.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        if (candidate / "config.json").is_file() and any(
            candidate.glob("*.safetensors")
        ):
            return candidate
    return None


class KoreanAudioASRAdapter:
    """Local-only MLX Whisper adapter; it never passes a Hub ID to inference."""

    engine_name = DEFAULT_ASR_ENGINE

    def __init__(
        self,
        model_name: str = DEFAULT_ASR_MODEL,
        *,
        model_path: Path | str | None = None,
    ) -> None:
        self.model_name = str(model_name)
        self.model_path = (
            Path(model_path).expanduser()
            if model_path is not None
            else _huggingface_cache_model_path(self.model_name)
        )
        self.model_load_count = 0
        self.model_load_seconds = 0.0
        self.generation_seconds = 0.0
        self.call_count = 0
        self._module: Any | None = None

    def capability(self) -> dict[str, Any]:
        package_available = importlib.util.find_spec("mlx_whisper") is not None
        ffmpeg_path = next(
            (
                value
                for value in (
                    shutil.which("ffmpeg"),
                    "/opt/homebrew/bin/ffmpeg",
                    "/usr/local/bin/ffmpeg",
                )
                if value and Path(value).is_file()
            ),
            None,
        )
        model_available = bool(
            self.model_path
            and self.model_path.is_dir()
            and (self.model_path / "config.json").is_file()
        )
        if not package_available:
            reason = "mlx_whisper_package_unavailable"
        elif not model_available:
            reason = "local_whisper_model_unavailable"
        elif not ffmpeg_path:
            reason = "ffmpeg_unavailable"
        else:
            reason = None
        return {
            "available": bool(package_available and model_available and ffmpeg_path),
            "engine": self.engine_name,
            "model": self.model_name,
            "model_path": str(self.model_path) if model_available else None,
            "package_available": package_available,
            "model_available": model_available,
            "ffmpeg_path": ffmpeg_path,
            "reason": reason,
            "setup": (
                "Install mlx-whisper and place a fully downloaded MLX Whisper model "
                f"in the Hugging Face cache or set {MODEL_PATH_ENV}."
            ),
            "automatic_download": False,
        }

    def _load_module(self) -> Any:
        if self._module is not None:
            return self._module
        capability = self.capability()
        if not capability["available"]:
            raise RuntimeError(str(capability["reason"]))
        started = time.perf_counter()
        import mlx_whisper
        import mlx.core as mx
        from mlx_whisper.transcribe import ModelHolder

        ModelHolder.get_model(str(self.model_path), mx.float16)
        self._module = mlx_whisper
        self.model_load_count = 1
        self.model_load_seconds += time.perf_counter() - started
        return self._module

    def transcribe(
        self,
        audio_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> dict[str, Any]:
        module = self._load_module()
        started = time.perf_counter()
        self.call_count += 1
        try:
            output = module.transcribe(
                str(audio_path),
                path_or_hf_repo=str(self.model_path),
                language="ko",
                task="transcribe",
                word_timestamps=True,
                condition_on_previous_text=False,
                temperature=0.0,
                clip_timestamps=f"{start_seconds:.3f},{end_seconds:.3f}",
                verbose=False,
            )
        finally:
            self.generation_seconds += time.perf_counter() - started
        if not isinstance(output, dict):
            raise RuntimeError("mlx_whisper_returned_non_object")
        output = copy.deepcopy(output)
        output["time_base"] = "media"
        return output


def classify_suspicious_items(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    editorial = result.get("korean_editorial_review") or {}
    changed_ids = {
        str(item.get("utterance_id") or "")
        for item in editorial.get("changed_items") or []
        if isinstance(item, dict)
    }
    classified: list[dict[str, Any]] = []
    for item in editorial.get("suspicious_items") or []:
        if not isinstance(item, dict):
            continue
        record = copy.deepcopy(item)
        row_id = str(record.get("utterance_id") or "")
        signals = set(record.get("signals") or [])
        suspicion = float(record.get("suspicion_score") or 0.0)
        already_fixed_residual_signals = {
            "deterministic_fix_with_remaining_lexical_outlier",
            "video_local_lexical_outlier",
        }
        if row_id in changed_ids and signals.issubset(already_fixed_residual_signals):
            category = "entity_fixable"
            severity = "low"
            priority = 0.0
        elif signals & _AUDIO_HIGH_SIGNALS:
            category = "audio_evidence_needed"
            severity = "high"
            priority = 300.0 + suspicion
            if signals & {
                "metadata_term_embedded_in_unknown_token",
                "canonical_alias_near_match",
                "unverified_official_name_candidate",
                "video_local_person_identity_near_match",
                "official_entity_discourse_continuity",
                "acronym_discourse_inconsistency",
            }:
                priority += 100.0
            if signals & {
                "broken_korean_compound",
                "contextually_unusual_action_verb",
                "past_demonstration_verb_needs_review",
            }:
                priority += 80.0
            if signals & {
                "protected_korean_term_near_match",
                "short_technical_modifier_needs_context_review",
                "technical_domain_phrase_near_match",
            }:
                priority += 180.0
            if signals & {
                "attached_token_boundary_candidate",
                "malformed_script_boundary",
            }:
                priority += 240.0
            if "severe_video_local_lexical_outlier" in signals:
                priority += 120.0
            if (
                "deterministic_fix_with_remaining_lexical_outlier" in signals
                and signals & _AUDIO_MEDIUM_SIGNALS
            ):
                priority += 180.0
            if "deterministic_boundary_fix_with_remaining_audio_review" in signals:
                priority += 180.0
            if "singleton_unregistered_acronym" in signals:
                priority += 40.0
        elif signals & _AUDIO_MEDIUM_SIGNALS:
            category = "audio_evidence_needed"
            severity = "medium"
            priority = 200.0 + suspicion
        elif row_id in changed_ids:
            category = (
                "entity_fixable"
                if "canonical_alias_near_match" in signals
                else "deterministic_fixable"
            )
            severity = "low"
            priority = 0.0
        else:
            category = "ambiguous_needs_review"
            severity = "low"
            priority = 100.0 + suspicion if signals - _TEXT_ONLY_SIGNALS else suspicion
        record.update(
            {
                "classification": category,
                "audio_priority": severity,
                "priority_score": priority,
            }
        )
        classified.append(record)
    return classified


def _row_times(row: dict[str, Any]) -> tuple[float, float]:
    start = max(0.0, _finite_seconds(row.get("start_seconds")))
    end = max(start, _finite_seconds(row.get("end_seconds"), start))
    return start, end


def cluster_audio_windows(
    records: list[dict[str, Any]],
    rows_by_id: dict[str, dict[str, Any]],
    *,
    duration_seconds: float | None = None,
    padding_seconds: float = WINDOW_PADDING_SECONDS,
    max_gap_seconds: float = CLUSTER_MAX_GAP_SECONDS,
    max_window_seconds: float = MAX_WINDOW_SECONDS,
) -> list[AudioWindow]:
    targets: list[dict[str, Any]] = []
    ceiling = duration_seconds if duration_seconds and duration_seconds > 0 else None
    for record in records:
        row_id = str(record.get("utterance_id") or "")
        row = rows_by_id.get(row_id)
        if row is None:
            continue
        owned_start, owned_end = _row_times(row)
        window_start = max(0.0, owned_start - padding_seconds)
        window_end = owned_end + padding_seconds
        if ceiling is not None:
            window_end = min(window_end, ceiling)
        targets.append(
            {
                "row_id": row_id,
                "start": window_start,
                "end": max(window_start, window_end),
                "priority": float(record.get("priority_score") or 0),
            }
        )
    targets.sort(key=lambda item: (item["start"], item["end"], item["row_id"]))
    clusters: list[dict[str, Any]] = []
    for target in targets:
        if not clusters:
            clusters.append({**target, "row_ids": [target["row_id"]]})
            continue
        current = clusters[-1]
        merged_end = max(float(current["end"]), float(target["end"]))
        can_merge = (
            float(target["start"]) - float(current["end"]) <= max_gap_seconds
            and merged_end - float(current["start"]) <= max_window_seconds
        )
        if can_merge:
            current["end"] = merged_end
            current["row_ids"].append(target["row_id"])
            current["priority"] = max(current["priority"], target["priority"])
        else:
            clusters.append({**target, "row_ids": [target["row_id"]]})
    return [
        AudioWindow(
            window_id=f"ARW-{index:04d}",
            start_seconds=round(float(item["start"]), 6),
            end_seconds=round(float(item["end"]), 6),
            row_ids=tuple(item["row_ids"]),
            priority=float(item["priority"]),
        )
        for index, item in enumerate(clusters, 1)
    ]


def select_windows_by_duration_budget(
    windows: list[AudioWindow],
    budget_seconds: float,
) -> tuple[list[AudioWindow], list[AudioWindow]]:
    ordered = sorted(
        windows,
        key=lambda window: (-window.priority, window.start_seconds, window.window_id),
    )
    selected: list[AudioWindow] = []
    deferred: list[AudioWindow] = []
    if budget_seconds <= 0:
        return [], sorted(windows, key=lambda window: window.start_seconds)
    used = 0.0
    for window in ordered:
        duration = window.duration_seconds
        if used + duration <= budget_seconds:
            selected.append(window)
            used += duration
        else:
            deferred.append(window)
    selected.sort(key=lambda window: window.start_seconds)
    deferred.sort(key=lambda window: window.start_seconds)
    return selected, deferred


def select_windows_adaptive_high_severity(
    windows: list[AudioWindow],
    base_budget_seconds: float,
    *,
    high_severity_priority: float = ADAPTIVE_HIGH_SEVERITY_PRIORITY,
    hard_cap_seconds: float = ADAPTIVE_AUDIO_REVIEW_CAP_SECONDS,
) -> tuple[list[AudioWindow], list[AudioWindow], dict[str, Any]]:
    """Cover high-severity windows first, with a finite and auditable cap."""
    cap = max(0.0, max(base_budget_seconds, hard_cap_seconds))
    ordered = sorted(
        windows,
        key=lambda window: (-window.priority, window.start_seconds, window.window_id),
    )
    selected: list[AudioWindow] = []
    selected_ids: set[str] = set()
    used = 0.0
    high_windows = [window for window in ordered if window.priority >= high_severity_priority]
    for window in high_windows:
        if used + window.duration_seconds <= cap:
            selected.append(window)
            selected_ids.add(window.window_id)
            used += window.duration_seconds
    fill_target = max(base_budget_seconds, used)
    for window in ordered:
        if window.window_id in selected_ids:
            continue
        if used + window.duration_seconds <= fill_target:
            selected.append(window)
            selected_ids.add(window.window_id)
            used += window.duration_seconds
    deferred = [window for window in windows if window.window_id not in selected_ids]
    selected.sort(key=lambda window: window.start_seconds)
    deferred.sort(key=lambda window: window.start_seconds)
    return selected, deferred, {
        "mode": "adaptive_high_severity_first",
        "base_budget_seconds": base_budget_seconds,
        "hard_cap_seconds": cap,
        "high_severity_priority_threshold": high_severity_priority,
        "high_severity_window_count": len(high_windows),
        "selected_high_severity_window_count": sum(
            1 for window in selected if window.priority >= high_severity_priority
        ),
        "planned_seconds": round(used, 6),
    }


@lru_cache(maxsize=1)
def _resolve_ytdlp_status() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        pinned = inspect_pinned_yt_dlp(
            timeout_seconds=YTDLP_VERSION_CHECK_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        pinned = {
            "available": False,
            "reason": f"pinned_sidecar_check_failed:{type(exc).__name__}",
        }
    if pinned.get("available"):
        return {
            "executable": str(pinned["executable_path"]),
            "source": "pinned_nightly_sidecar",
            "version": pinned.get("version"),
            "pinned_status": pinned,
            "readiness_seconds": time.perf_counter() - started,
        }

    candidates = (
        shutil.which("yt-dlp"),
        str(Path.home() / ".local" / "bin" / "yt-dlp"),
        "/opt/homebrew/bin/yt-dlp",
        "/usr/local/bin/yt-dlp",
    )
    executable = next(
        (value for value in candidates if value and Path(value).is_file()),
        None,
    )
    return {
        "executable": executable,
        "source": "system_fallback" if executable else "unavailable",
        "version": None,
        "pinned_status": pinned,
        "readiness_seconds": time.perf_counter() - started,
    }


def _resolve_ytdlp() -> str | None:
    return _resolve_ytdlp_status().get("executable")


@contextmanager
def prepare_temporary_audio_source(
    source_url: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
    yt_dlp_executable: str | None = None,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    if yt_dlp_executable:
        executable = yt_dlp_executable
        resolver_status = {
            "source": "explicit",
            "version": None,
            "readiness_seconds": 0.0,
        }
    else:
        resolver_status = _resolve_ytdlp_status()
        executable = resolver_status.get("executable")
    if not executable:
        raise RuntimeError("yt_dlp_unavailable")
    with tempfile.TemporaryDirectory(prefix="v0316_korean_audio_") as name:
        root = Path(name)
        output_template = root / "audio_source.%(ext)s"
        command = [
            executable,
            "--no-playlist",
            "--no-part",
            "--no-progress",
            "--no-warnings",
            "-f",
            YTDLP_AUDIO_FORMAT,
            "-o",
            str(output_template),
            source_url,
        ]
        started = time.perf_counter()
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        elapsed = time.perf_counter() - started
        if int(getattr(completed, "returncode", 1)) != 0:
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            raise RuntimeError("audio_download_failed:" + stderr[-300:])
        files = [path for path in root.glob("audio_source.*") if path.is_file()]
        if len(files) != 1 or files[0].stat().st_size <= 0:
            raise RuntimeError("audio_download_output_missing")
        path = files[0]
        yield path, {
            "audio_download_count": 1,
            "audio_bytes": path.stat().st_size,
            "audio_source_prepare_seconds": elapsed,
            "yt_dlp_executable": executable,
            "yt_dlp_source": resolver_status.get("source"),
            "yt_dlp_version": resolver_status.get("version"),
            "yt_dlp_readiness_seconds": resolver_status.get("readiness_seconds", 0.0),
            "temporary": True,
        }


def _words_from_output(output: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(output.get("words"), list):
        return [item for item in output["words"] if isinstance(item, dict)]
    words: list[dict[str, Any]] = []
    for segment in output.get("segments") or []:
        if isinstance(segment, dict) and isinstance(segment.get("words"), list):
            words.extend(item for item in segment["words"] if isinstance(item, dict))
    return words


def _join_words(words: list[dict[str, Any]]) -> str:
    text = "".join(str(word.get("word") or "") for word in words).strip()
    if text and " " not in text and len(words) > 1:
        text = " ".join(str(word.get("word") or "").strip() for word in words)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def align_candidate_to_row(
    output: dict[str, Any],
    row: dict[str, Any],
    window: AudioWindow,
    *,
    owned_start_seconds: float | None = None,
    owned_end_seconds: float | None = None,
) -> dict[str, Any]:
    words = _words_from_output(output)
    if not words:
        return {
            "candidate_text": None,
            "word_timestamps": False,
            "confidence": None,
            "reason": "word_timestamps_unavailable",
            "full_window_text": str(output.get("text") or "").strip(),
        }
    row_start, row_end = _row_times(row)
    owned_start = row_start if owned_start_seconds is None else owned_start_seconds
    owned_end = row_end if owned_end_seconds is None else owned_end_seconds
    aligned: list[dict[str, Any]] = []
    probabilities: list[float] = []
    relative = str(output.get("time_base") or "media") == "window"
    for word in words:
        start = _finite_seconds(word.get("start"), -1.0)
        end = _finite_seconds(word.get("end"), start)
        if relative:
            start += window.start_seconds
            end += window.start_seconds
        midpoint = (start + end) / 2.0
        if owned_start <= midpoint <= owned_end:
            aligned.append(word)
            probability = word.get("probability")
            if isinstance(probability, (int, float)):
                probabilities.append(float(probability))
    candidate = _join_words(aligned)
    confidence = (
        sum(probabilities) / len(probabilities)
        if probabilities
        else output.get("confidence")
    )
    return {
        "candidate_text": candidate or None,
        "word_timestamps": True,
        "aligned_word_count": len(aligned),
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
        "reason": None if candidate else "no_words_owned_by_current_row",
        "full_window_text": str(output.get("text") or "").strip(),
    }


def _exclusive_owned_times(
    rows: list[dict[str, Any]],
    index: int,
) -> tuple[float, float]:
    start, end = _row_times(rows[index])
    if index > 0:
        _, previous_end = _row_times(rows[index - 1])
        if previous_end > start:
            start = min(end, (previous_end + start) / 2.0)
    if index + 1 < len(rows):
        next_start, _ = _row_times(rows[index + 1])
        if next_start < end:
            end = max(start, (end + next_start) / 2.0)
    return start, end


def _text_tokens(value: str) -> list[dict[str, Any]]:
    return [
        {"text": match.group(0), "start": match.start(), "end": match.end()}
        for match in re.finditer(r"\S+", value)
    ]


def _comparison_token(value: str) -> str:
    compact = re.sub(r"[^0-9A-Za-z가-힣+./%-]+", "", value)
    return compact.casefold()


def _lexical_content(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).casefold()


def _adjacent_phrase_leakage(
    before: str,
    candidate: str,
    previous: str,
    following: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    before_compact = re.sub(r"\s+", "", before).casefold()
    candidate_compact = re.sub(r"\s+", "", candidate).casefold()
    matches: list[dict[str, str]] = []
    for side, text in (("previous", previous), ("following", following)):
        words = [
            cleaned
            for token in re.findall(r"\S+", text)
            if (cleaned := _comparison_token(token))
        ]
        seen: set[str] = set()
        for size in range(min(4, len(words)), 1, -1):
            for index in range(len(words) - size + 1):
                phrase = "".join(words[index : index + size])
                if len(phrase) < 4 or phrase in seen:
                    continue
                seen.add(phrase)
                if phrase in candidate_compact and phrase not in before_compact:
                    matches.append(
                        {
                            "side": side,
                            "phrase": " ".join(words[index : index + size]),
                        }
                    )
                    break
            if matches and matches[-1]["side"] == side:
                break
    return {
        "detected": bool(matches),
        "matches": matches,
        "seconds": time.perf_counter() - started,
    }


def _anchor_from_equal_block(
    tokens: list[dict[str, Any]],
    start: int,
    end: int,
    *,
    left: bool,
) -> str:
    selected = tokens[max(start, end - 4) : end] if left else tokens[start : min(end, start + 4)]
    return " ".join(str(token["text"]) for token in selected).strip()


def _supported_official_entity_replacement(
    source_span: str,
    replacement: str,
    known_latin: set[str],
) -> bool:
    before_latin = {token.casefold() for token in _LATIN_TOKEN_RE.findall(source_span)}
    after_latin = {token.casefold() for token in _LATIN_TOKEN_RE.findall(replacement)}
    return bool(after_latin - before_latin) and all(
        token in known_latin for token in after_latin - before_latin
    )


def build_span_safe_patch(
    before: str,
    raw_youtube_row: str,
    audio_candidate: str,
    *,
    previous: str = "",
    following: str = "",
    protected_terms: tuple[str, ...] = (),
    known_latin: set[str] | None = None,
    speaker_transition: bool = False,
    audio_confidence: float | None = None,
    suspicion_signals: tuple[str, ...] = (),
    strict_runtime_evidence: bool = False,
) -> dict[str, Any]:
    """Patch only localized audio-supported spans onto the existing normalized row."""
    total_started = time.perf_counter()
    known_latin = known_latin or set()
    before_tokens = _text_tokens(before)
    candidate_tokens = _text_tokens(audio_candidate)
    leakage = _adjacent_phrase_leakage(before, audio_candidate, previous, following)
    diff_started = time.perf_counter()
    matcher = SequenceMatcher(
        None,
        [_comparison_token(str(token["text"])) for token in before_tokens],
        [_comparison_token(str(token["text"])) for token in candidate_tokens],
        autojunk=False,
    )
    opcodes = matcher.get_opcodes()
    expanded_opcodes: list[tuple[str, int, int, int, int]] = []
    for tag, before_start, before_end, cand_start, cand_end in opcodes:
        before_count = before_end - before_start
        candidate_count = cand_end - cand_start
        if (
            tag == "replace"
            and before_count > 1
            and candidate_count >= before_count
        ):
            expanded_opcodes.extend(
                ("replace", before_start + offset, before_start + offset + 1,
                 cand_start + offset,
                 cand_end if offset == before_count - 1 else cand_start + offset + 1)
                for offset in range(before_count)
            )
        else:
            expanded_opcodes.append((tag, before_start, before_end, cand_start, cand_end))
    opcodes = expanded_opcodes
    diff_seconds = time.perf_counter() - diff_started
    equal_blocks = [opcode for opcode in opcodes if opcode[0] == "equal" and opcode[2] > opcode[1]]
    first_equal_before = equal_blocks[0][1] if equal_blocks else len(before_tokens)
    last_equal_before = equal_blocks[-1][2] if equal_blocks else 0
    prefix_loss = first_equal_before > 0
    suffix_loss = last_equal_before < len(before_tokens)
    raw_compact = re.sub(r"\s+", "", raw_youtube_row).casefold()
    accepted_spans: list[dict[str, Any]] = []
    rejected_spans: list[dict[str, Any]] = []
    anchor_seconds = 0.0

    for position, (tag, before_start, before_end, cand_start, cand_end) in enumerate(opcodes):
        if tag != "replace" or before_start == before_end or cand_start == cand_end:
            continue
        anchor_started = time.perf_counter()
        left_block = next(
            (
                opcode
                for opcode in reversed(opcodes[:position])
                if opcode[0] == "equal" and opcode[2] > opcode[1]
            ),
            None,
        )
        right_block = next(
            (
                opcode
                for opcode in opcodes[position + 1 :]
                if opcode[0] == "equal" and opcode[2] > opcode[1]
            ),
            None,
        )
        left_anchor = (
            _anchor_from_equal_block(
                before_tokens, left_block[1], left_block[2], left=True
            )
            if left_block
            else ""
        )
        right_anchor = (
            _anchor_from_equal_block(
                before_tokens, right_block[1], right_block[2], left=False
            )
            if right_block
            else ""
        )
        anchor_preserved = bool(
            len(_comparison_token(left_anchor)) >= 2
            and len(_comparison_token(right_anchor)) >= 2
        )
        anchor_seconds += time.perf_counter() - anchor_started
        source_start = int(before_tokens[before_start]["start"])
        source_end = int(before_tokens[before_end - 1]["end"])
        candidate_start = int(candidate_tokens[cand_start]["start"])
        candidate_end = int(candidate_tokens[cand_end - 1]["end"])
        source_span = before[source_start:source_end]
        replacement = audio_candidate[candidate_start:candidate_end]
        source_compact = re.sub(r"\s+", "", source_span).casefold()
        source_token_count = before_end - before_start
        replacement_token_count = cand_end - cand_start
        source_comparison = _comparison_token(source_span)
        replacement_comparison = _comparison_token(replacement)
        lexical_ratio = SequenceMatcher(
            None,
            source_comparison,
            replacement_comparison,
            autojunk=False,
        ).ratio()
        span = {
            "span_from": source_span,
            "span_to": replacement,
            "replacement": replacement,
            "source_start": source_start,
            "source_end": source_end,
            "left_anchor": left_anchor,
            "right_anchor": right_anchor,
            "anchor_preserved": anchor_preserved,
            "lexical_similarity": round(lexical_ratio, 6),
        }
        if not anchor_preserved:
            span["reason"] = "anchor_not_preserved"
            rejected_spans.append(span)
            continue
        normalized_entity_lineage = bool(
            any(
                token.casefold() in known_latin
                for token in _LATIN_TOKEN_RE.findall(source_span)
            )
            and any(
                len(token) >= 2 and token in raw_compact
                for token in re.findall(r"[가-힣]{2,}", source_span)
            )
        )
        if not source_compact or (
            source_compact not in raw_compact and not normalized_entity_lineage
        ):
            span["reason"] = "source_span_not_in_raw_youtube_row"
            rejected_spans.append(span)
            continue
        if _lexical_content(source_span) == _lexical_content(replacement):
            span["reason"] = "formatting_only_audio_difference"
            rejected_spans.append(span)
            continue
        source_chars = len(_comparison_token(source_span))
        official_entity_replacement = _supported_official_entity_replacement(
            source_span,
            replacement,
            known_latin,
        )
        domain_phrase_replacement = bool(
            isinstance(audio_confidence, (int, float))
            and float(audio_confidence) >= 0.86
            and source_token_count <= 5
            and replacement_token_count <= 5
            and (
                source_token_count == replacement_token_count
                or source_token_count == 1
            )
            and sum(1 for term in protected_terms if term in audio_candidate) >= 1
            and any(
                _strip_korean_particle(token) == re.sub(r"\s+", "", term)
                for token in re.findall(r"[가-힣]{2,}", replacement)
                for term in protected_terms
            )
            and lexical_ratio >= 0.40
        )
        attached_prefixes = re.findall(
            r"([가-힣]+(?:데|게|고|지만|는데))이(?:\s|$)", source_span
        )
        attached_boundary_preserved = bool(
            attached_prefixes
            and all(
                f"{prefix}이" in re.sub(r"\s+", "", replacement)
                for prefix in attached_prefixes
            )
        )
        one_token_structural_source = bool(
            source_token_count == 1
            and (
                re.search(r"(?:은은|는는|을을|를를|에서에서|으로로)", source_span)
                or re.search(r"(?<!\d)\d+[가-힣]{2,}", source_span)
                or re.search(r"[A-Za-z][A-Za-z0-9+./-]*[가-힣]{2,}", source_span)
            )
        )
        structural_source = bool(
            one_token_structural_source
            or attached_boundary_preserved
        )
        source_hangul = "".join(re.findall(r"[가-힣]", source_span))
        replacement_hangul = "".join(re.findall(r"[가-힣]", replacement))
        particle_only_difference = bool(
            source_hangul
            and replacement_hangul
            and (
                source_hangul.startswith(replacement_hangul)
                or replacement_hangul.startswith(source_hangul)
            )
            and abs(len(source_hangul) - len(replacement_hangul)) <= 2
        )
        high_confidence_local_replacement = bool(
            (audio_confidence is None or float(audio_confidence) >= 0.55)
            and source_token_count == replacement_token_count == 1
            and lexical_ratio >= 0.72
            and source_hangul[:1] == replacement_hangul[:1]
            and (
                len(source_hangul) == len(replacement_hangul)
                or (
                    abs(len(source_hangul) - len(replacement_hangul)) == 1
                    and lexical_ratio >= 0.87
                )
            )
            and not particle_only_difference
            and (
                lexical_ratio >= 0.83
                or "within_row_lexical_inconsistency" in suspicion_signals
            )
        )
        direct_span_evidence = bool(
            official_entity_replacement
            or domain_phrase_replacement
            or structural_source
            or (high_confidence_local_replacement and not strict_runtime_evidence)
            or (
                high_confidence_local_replacement
                and re.search(r"(?:던|었던)", source_span)
                and lexical_ratio >= 0.87
            )
            or (
                "past_demonstration_verb_needs_review" in suspicion_signals
                and re.search(r"(?:던|었던)", source_span)
                and lexical_ratio >= 0.78
            )
        )
        if (
            source_token_count > 2
            and not domain_phrase_replacement
        ) or source_chars > max(40 if domain_phrase_replacement else 24, int(len(before) * 0.35)):
            span["reason"] = "changed_span_too_large"
            rejected_spans.append(span)
            continue
        if (
            source_token_count == 1
            and replacement_token_count > 1
            and not official_entity_replacement
            and not domain_phrase_replacement
        ):
            span["reason"] = "single_token_expanded_without_official_entity_evidence"
            rejected_spans.append(span)
            continue
        if (
            (
                lexical_ratio < 0.78
                or (source_chars <= 5 and lexical_ratio < 0.83)
            )
            and not official_entity_replacement
            and not domain_phrase_replacement
            and not high_confidence_local_replacement
            and not structural_source
        ):
            span["reason"] = "localized_audio_evidence_too_dissimilar"
            rejected_spans.append(span)
            continue
        if not direct_span_evidence:
            span["reason"] = "span_lacks_direct_suspicion_evidence"
            rejected_spans.append(span)
            continue
        accepted_spans.append(span)

    patched = before
    for span in sorted(accepted_spans, key=lambda item: item["source_start"], reverse=True):
        patched = (
            patched[: span["source_start"]]
            + span["replacement"]
            + patched[span["source_end"] :]
        )
    passed = bool(accepted_spans and patched != before)
    failure_reason = None
    if not passed:
        if not audio_candidate or audio_candidate == before:
            failure_reason = "empty_or_unchanged_audio_candidate"
        elif rejected_spans:
            failure_reason = str(rejected_spans[0].get("reason") or "span_alignment_failed")
        elif leakage["detected"]:
            failure_reason = "adjacent_leakage_detected"
        else:
            failure_reason = "no_safe_changed_span"
    residual_current_span_count = len(rejected_spans) + sum(
        1
        for tag, before_start, before_end, _cand_start, _cand_end in opcodes
        if tag == "delete" and before_end > before_start
    )
    return {
        "passed": passed,
        "patched_text": patched,
        "span_patch_attempted": bool(audio_candidate and audio_candidate != before),
        "span_patches": accepted_spans,
        "rejected_spans": rejected_spans,
        "span_from": accepted_spans[0]["span_from"] if len(accepted_spans) == 1 else None,
        "span_to": accepted_spans[0]["span_to"] if len(accepted_spans) == 1 else None,
        "replacement": accepted_spans[0]["replacement"] if len(accepted_spans) == 1 else None,
        "left_anchor": accepted_spans[0]["left_anchor"] if len(accepted_spans) == 1 else None,
        "right_anchor": accepted_spans[0]["right_anchor"] if len(accepted_spans) == 1 else None,
        "anchor_preserved": bool(accepted_spans) and all(
            bool(span["anchor_preserved"]) for span in accepted_spans
        ),
        "prefix_loss_detected": prefix_loss,
        "suffix_loss_detected": suffix_loss,
        "adjacent_leakage_detected": bool(leakage["detected"]),
        "adjacent_leakage_matches": leakage["matches"],
        "speaker_transition": speaker_transition,
        "boundary_integrity": (
            "passed"
            if passed and not prefix_loss and not suffix_loss and not leakage["detected"]
            else "safe_span_only"
            if passed
            else "failed"
        ),
        "residual_current_span_count": residual_current_span_count,
        "failure_reason": failure_reason,
        "timing": {
            "span_diff_seconds": diff_seconds,
            "anchor_guard_seconds": anchor_seconds,
            "leakage_guard_seconds": leakage["seconds"],
            "total_seconds": time.perf_counter() - total_started,
        },
    }


def _candidate_guard(
    before: str,
    candidate: str,
    *,
    adjacent: list[str],
    protected_terms: tuple[str, ...],
    known_latin: set[str],
) -> tuple[bool, str]:
    if not candidate or candidate == before:
        return False, "empty_or_unchanged_audio_candidate"
    if _NUMBER_RE.findall(before) != _NUMBER_RE.findall(candidate):
        return False, "numbers_dates_or_amounts_changed"
    if _ACTOR_RE.findall(before) != _ACTOR_RE.findall(candidate):
        return False, "actor_relationship_changed"
    if set(_RELATION_ACTION_RE.findall(before)) != set(
        _RELATION_ACTION_RE.findall(candidate)
    ):
        return False, "action_or_target_relationship_changed"
    if bool(_NEGATION_RE.search(before)) != bool(_NEGATION_RE.search(candidate)):
        return False, "action_polarity_changed"
    if len(candidate) < max(1, int(len(before) * 0.45)):
        return False, "audio_candidate_too_short"
    if len(candidate) > int(len(before) * 1.8) + 20:
        return False, "audio_candidate_too_long"
    if _adjacent_leakage(before, candidate, adjacent):
        return False, "adjacent_row_content_leakage"
    before_latin = {token.casefold() for token in _LATIN_TOKEN_RE.findall(before)}
    after_latin = {token.casefold() for token in _LATIN_TOKEN_RE.findall(candidate)}
    if before_latin - after_latin:
        return False, "existing_latin_entity_or_acronym_removed"
    if any(token not in known_latin for token in after_latin - before_latin):
        return False, "unsupported_new_latin_entity"
    for term in protected_terms:
        if term in before and term not in candidate:
            return False, "protected_korean_concept_removed"
    return True, "passed"


def _independently_guard_span_patches(
    before: str,
    spans: list[dict[str, Any]],
    *,
    adjacent: list[str],
    protected_terms: tuple[str, ...],
    known_latin: set[str],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Reject one unsafe span without discarding independent safe repairs."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for span in sorted(spans, key=lambda item: int(item["source_start"])):
        start, end = int(span["source_start"]), int(span["source_end"])
        if any(start < other_end and end > other_start for other_start, other_end in occupied):
            rejected.append({**copy.deepcopy(span), "reason": "overlapping_span_patch"})
            continue
        one_patch = before[:start] + str(span["replacement"]) + before[end:]
        passed, reason = _candidate_guard(
            before,
            one_patch,
            adjacent=adjacent,
            protected_terms=protected_terms,
            known_latin=known_latin,
        )
        if not passed:
            rejected.append({**copy.deepcopy(span), "reason": reason})
            continue
        accepted.append(span)
        occupied.append((start, end))
    patched = before
    for span in sorted(accepted, key=lambda item: int(item["source_start"]), reverse=True):
        patched = (
            patched[: int(span["source_start"])]
            + str(span["replacement"])
            + patched[int(span["source_end"]):]
        )
    return patched, accepted, rejected


def _build_verifier_prompt(
    row: dict[str, Any],
    candidate: str,
    *,
    previous: str,
    following: str,
    source: dict[str, Any],
    local_map: dict[str, Any],
) -> str:
    metadata = source.get("metadata") or {}
    payload = {
        "role": "Korean ASR evidence verifier",
        "constraints": [
            "Do not rewrite or invent lexical content.",
            "accept_reasr corrected_text must exactly equal SPAN_PATCHED_RESULT.",
            "Previous and next are context-only.",
            "If evidence is insufficient, choose unresolved.",
        ],
        "current_youtube_asr": str(row.get("raw_joined_text") or ""),
        "current_normalized": str(row.get("normalized_text") or ""),
        "span_patched_result": candidate,
        "previous_context": previous,
        "next_context": following,
        "video_title": str(metadata.get("title") or ""),
        "creator_chapter": str(row.get("chapter_label") or ""),
        "canonical_entities": [
            item
            for item in local_map.get("entities") or []
            if item.get("evidence_score", 0) > 0
        ],
        "output_schema": {
            "decision": "accept_reasr | keep_existing | unresolved",
            "confidence": "high | medium | low",
            "reason": "short evidence reason",
            "corrected_text": "exact candidate or existing text",
            "evidence": [],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _verify_with_qwen(
    core: Any,
    model_name: str,
    prompt: str,
    candidate: str,
    generator: Callable[[str, str, str, int], str] | None,
) -> tuple[bool, dict[str, Any]]:
    system = (
        "You verify whether a timestamp-aligned local audio ASR candidate is sufficient "
        "evidence for the current Korean utterance. Never create a third wording. "
        "Return one JSON object only."
    )
    active = generator
    if active is None:
        active = lambda name, system_text, user_text, tokens: getattr(
            core, "_generate_local_llm_text_v033"
        )(name, system_text, user_text, tokens)
    with generation_stage("korean_audio_reasr_verifier"):
        response = active(model_name, system, prompt, 700)
    extractor = getattr(core, "_extract_json_object_v032", None)
    parsed = extractor(response) if callable(extractor) else json.loads(response)
    if not isinstance(parsed, dict):
        raise ValueError("audio_verifier_response_not_object")
    accepted = (
        str(parsed.get("decision") or "") == "accept_reasr"
        and str(parsed.get("confidence") or "") == "high"
        and str(parsed.get("corrected_text") or "") == candidate
    )
    return accepted, parsed


def _remove_old_unresolved(result: dict[str, Any], row_id: str) -> None:
    result["unresolved_terms"] = [
        item
        for item in result.get("unresolved_terms") or []
        if not (
            isinstance(item, dict)
            and str(item.get("utterance_id") or "") == row_id
            and item.get("stage") == "korean_asr_editorial_review"
        )
    ]


def _mark_audio_unresolved(
    result: dict[str, Any],
    row: dict[str, Any],
    reason: str,
    status: str,
    *,
    preserve_state: bool = False,
) -> None:
    row_id = str(row.get("utterance_id") or "")
    if not preserve_state:
        row["korean_editorial_state"] = status
    row["review_status"] = "needs_review"
    warning = f"korean_audio_reasr:{reason}"
    warnings = row.setdefault("validation_warnings", [])
    if warning not in warnings:
        warnings.append(warning)
    unresolved = result.setdefault("unresolved_terms", [])
    if not any(
        isinstance(item, dict)
        and item.get("stage") == "korean_audio_reasr"
        and str(item.get("utterance_id") or "") == row_id
        for item in unresolved
    ):
        unresolved.append(
            {
                "utterance_id": row_id,
                "text": row.get("normalized_text"),
                "reason": reason,
                "review_status": "needs_review",
                "stage": "korean_audio_reasr",
            }
        )


def apply_selective_audio_reasr(
    result: dict[str, Any],
    source: dict[str, Any],
    *,
    core: Any,
    adapter: AudioASRAdapter | None = None,
    audio_preparer: Callable[..., Any] | None = None,
    verifier_generator: Callable[[str, str, str, int], str] | None = None,
    qwen_model_name: str | None = None,
    audio_review_budget_seconds: float | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not isinstance(result, dict) or not isinstance(source, dict):
        return result
    if not _source_language(result, source).startswith("ko"):
        return result
    if result.get("translation_required") is True:
        return result

    rows = [row for row in result.get("normalized_utterances") or [] if isinstance(row, dict)]
    rows_by_id = {str(row.get("utterance_id") or ""): row for row in rows}
    row_index_by_id = {
        str(row.get("utterance_id") or ""): index for index, row in enumerate(rows)
    }
    classified = classify_suspicious_items(result)
    classified_by_id = {
        str(item.get("utterance_id") or ""): item for item in classified
    }
    configured_budget = _configured_audio_budget(audio_review_budget_seconds)
    audio_records = [
        item for item in classified if item["classification"] == "audio_evidence_needed"
    ]
    duration = _finite_seconds((source.get("metadata") or {}).get("duration_seconds"), 0.0)
    windows = cluster_audio_windows(
        audio_records,
        rows_by_id,
        duration_seconds=duration or None,
    )
    adaptive_budget_enabled = (
        audio_review_budget_seconds is None
        and not str(os.environ.get(AUDIO_REVIEW_BUDGET_ENV) or "").strip()
    )
    if adaptive_budget_enabled:
        selected_windows, deferred_windows, budget_policy = (
            select_windows_adaptive_high_severity(windows, configured_budget)
        )
    else:
        selected_windows, deferred_windows = select_windows_by_duration_budget(
            windows, configured_budget
        )
        budget_policy = {
            "mode": "explicit_fixed_budget",
            "base_budget_seconds": configured_budget,
            "hard_cap_seconds": configured_budget,
            "planned_seconds": round(
                sum(window.duration_seconds for window in selected_windows), 6
            ),
        }
    deferred_ids = {row_id for window in deferred_windows for row_id in window.row_ids}
    selected_ids = {row_id for window in selected_windows for row_id in window.row_ids}

    for item in classified:
        row = rows_by_id.get(str(item.get("utterance_id") or ""))
        if row is None:
            continue
        category = item["classification"]
        if category == "audio_evidence_needed":
            row["korean_editorial_state"] = (
                "review_pending" if item["utterance_id"] in deferred_ids else "audio_review_needed"
            )
        elif category == "ambiguous_needs_review":
            _mark_audio_unresolved(
                result,
                row,
                "ambiguous_without_sufficient_audio_priority",
                "review_pending",
            )
        elif category == "entity_fixable":
            row["korean_editorial_state"] = "entity_fixed"
            _remove_old_unresolved(result, str(item.get("utterance_id") or ""))
            warnings = row.setdefault("validation_warnings", [])
            warnings[:] = [
                warning
                for warning in warnings
                if warning != "korean_asr_editorial_review:review_budget_deferred"
            ]
        elif category == "deterministic_fixable":
            row["korean_editorial_state"] = "deterministic_fixed"
            _remove_old_unresolved(result, str(item.get("utterance_id") or ""))

    active_adapter = adapter or KoreanAudioASRAdapter()
    capability: dict[str, Any] = {
        "available": False,
        "engine": getattr(active_adapter, "engine_name", "unknown"),
        "model": getattr(active_adapter, "model_name", "unknown"),
        "reason": "not_needed",
        "automatic_download": False,
    }
    audio_source_prepare_seconds = 0.0
    audio_download_count = 0
    audio_bytes = 0
    yt_dlp_executable: str | None = None
    yt_dlp_source: str | None = None
    yt_dlp_version: str | None = None
    yt_dlp_readiness_seconds = 0.0
    asr_calls = 0
    asr_generation_seconds = 0.0
    qwen_calls = 0
    qwen_seconds = 0.0
    span_diff_seconds = 0.0
    anchor_guard_seconds = 0.0
    leakage_guard_seconds = 0.0
    reviewed_ids: set[str] = set()
    repaired_ids: set[str] = set()
    unresolved_ids: set[str] = set()
    failed_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []
    registry: dict[str, Any] | None = None
    local_map: dict[str, Any] | None = None
    known_latin: set[str] = set()
    next_number = _next_normalization_number(result.setdefault("normalization_items", []))
    changed_items = result.setdefault("korean_editorial_review", {}).setdefault("changed_items", [])

    if selected_windows:
        try:
            capability = active_adapter.capability()
        except Exception as exc:
            capability = {
                "available": False,
                "engine": getattr(active_adapter, "engine_name", "unknown"),
                "model": getattr(active_adapter, "model_name", "unknown"),
                "reason": f"capability_check_failed:{type(exc).__name__}",
                "automatic_download": False,
            }
    if selected_windows and not capability.get("available"):
        for row_id in selected_ids:
            row = rows_by_id.get(row_id)
            if row is not None:
                _mark_audio_unresolved(
                    result,
                    row,
                    str(capability.get("reason") or "asr_capability_unavailable"),
                    "review_pending",
                )
    elif selected_windows:
        registry = load_canonical_registry()
        local_map = build_video_local_entity_map(result, source, registry)
        known_latin = {
            token.casefold()
            for entity in registry["entities"]
            for token in _LATIN_TOKEN_RE.findall(entity.canonical_name)
        } | {entity.canonical_name.casefold() for entity in registry["entities"]}
        locator = resolve_source_locator(result)
        if locator is None:
            metadata = source.get("metadata") or {}
            locator = resolve_source_locator(
                {
                    "source_url": metadata.get("source_url") or source.get("source_url"),
                    "video_id": metadata.get("video_id") or source.get("video_id"),
                }
            )
        if locator is None:
            for row_id in selected_ids:
                row = rows_by_id.get(row_id)
                if row is not None:
                    failed_ids.add(row_id)
                    _mark_audio_unresolved(result, row, "source_locator_missing", "review_failed")
        else:
            preparer = audio_preparer or prepare_temporary_audio_source
            try:
                with preparer(str(locator["source_url"])) as prepared:
                    audio_path, source_metrics = prepared
                    audio_source_prepare_seconds = float(
                        source_metrics.get("audio_source_prepare_seconds") or 0.0
                    )
                    audio_download_count = int(source_metrics.get("audio_download_count") or 0)
                    audio_bytes = int(source_metrics.get("audio_bytes") or 0)
                    yt_dlp_executable = str(source_metrics.get("yt_dlp_executable") or "") or None
                    yt_dlp_source = str(source_metrics.get("yt_dlp_source") or "") or None
                    yt_dlp_version = str(source_metrics.get("yt_dlp_version") or "") or None
                    yt_dlp_readiness_seconds = float(
                        source_metrics.get("yt_dlp_readiness_seconds") or 0.0
                    )
                    for window in selected_windows:
                        generation_started = time.perf_counter()
                        try:
                            asr_calls += 1
                            output = active_adapter.transcribe(
                                Path(audio_path), window.start_seconds, window.end_seconds
                            )
                        except Exception as exc:
                            asr_generation_seconds += time.perf_counter() - generation_started
                            for row_id in window.row_ids:
                                row = rows_by_id.get(row_id)
                                if row is not None:
                                    failed_ids.add(row_id)
                                    _mark_audio_unresolved(
                                        result,
                                        row,
                                        f"asr_inference_failed:{type(exc).__name__}",
                                        "review_failed",
                                    )
                            continue
                        asr_generation_seconds += time.perf_counter() - generation_started
                        for row_id in window.row_ids:
                            row = rows_by_id.get(row_id)
                            if row is None:
                                continue
                            reviewed_ids.add(row_id)
                            index = row_index_by_id[row_id]
                            owned_start, owned_end = _exclusive_owned_times(rows, index)
                            aligned = align_candidate_to_row(
                                output,
                                row,
                                window,
                                owned_start_seconds=owned_start,
                                owned_end_seconds=owned_end,
                            )
                            candidate = str(aligned.get("candidate_text") or "")
                            full_window_candidate = str(aligned.get("full_window_text") or "")
                            candidate_record = {
                                "utterance_id": row_id,
                                "window_id": window.window_id,
                                "audio_candidate": candidate or None,
                                "candidate_text": candidate or None,
                                "word_timestamps": bool(aligned.get("word_timestamps")),
                                "candidate_confidence": aligned.get("confidence"),
                                "confidence": aligned.get("confidence"),
                                "span_patch_attempted": False,
                                "anchor_preserved": False,
                                "prefix_loss_detected": False,
                                "suffix_loss_detected": False,
                                "adjacent_leakage_detected": False,
                                "boundary_integrity": "failed",
                                "final_decision": "unresolved",
                                "failure_reason": aligned.get("reason"),
                                "status": "unresolved",
                                "reason": aligned.get("reason"),
                            }
                            if not candidate:
                                unresolved_ids.add(row_id)
                                _mark_audio_unresolved(
                                    result,
                                    row,
                                    str(aligned.get("reason") or "audio_candidate_missing"),
                                    "audio_reviewed_unresolved",
                                )
                                candidates.append(candidate_record)
                                continue
                            context = "\n".join(
                                str(rows[position].get("normalized_text") or "")
                                for position in range(max(0, index - 1), min(len(rows), index + 2))
                            )
                            canonical_candidate, _, _ = _canonicalize_entities(
                                candidate, context, registry, local_map
                            )
                            canonical_full_candidate, _, _ = _canonicalize_entities(
                                full_window_candidate, context, registry, local_map
                            )
                            before = str(row.get("normalized_text") or "")
                            previous = (
                                str(rows[index - 1].get("normalized_text") or "")
                                if index > 0
                                else ""
                            )
                            following = (
                                str(rows[index + 1].get("normalized_text") or "")
                                if index + 1 < len(rows)
                                else ""
                            )
                            adjacent = [text for text in (previous, following) if text]
                            speaker_transition = bool(
                                row.get("speaker_change_before")
                                or (
                                    index + 1 < len(rows)
                                    and rows[index + 1].get("speaker_change_before")
                                )
                            )
                            plans: list[dict[str, Any]] = []
                            for evidence_source, evidence_text in (
                                ("owned_words", canonical_candidate),
                                ("full_window", canonical_full_candidate),
                            ):
                                if not evidence_text or any(
                                    plan.get("audio_evidence") == evidence_text
                                    for plan in plans
                                ):
                                    continue
                                plan = build_span_safe_patch(
                                    before,
                                    str(row.get("raw_joined_text") or before),
                                    evidence_text,
                                    previous=previous,
                                    following=following,
                                    protected_terms=registry["protected_korean_concepts"],
                                    known_latin=known_latin,
                                    speaker_transition=speaker_transition,
                                    audio_confidence=aligned.get("confidence"),
                                    suspicion_signals=tuple(
                                        classified_by_id.get(row_id, {}).get("signals") or []
                                    ),
                                    strict_runtime_evidence=True,
                                )
                                plan["audio_evidence_source"] = evidence_source
                                plan["audio_evidence"] = evidence_text
                                plans.append(plan)
                                span_diff_seconds += float(
                                    plan["timing"].get("span_diff_seconds") or 0.0
                                )
                                anchor_guard_seconds += float(
                                    plan["timing"].get("anchor_guard_seconds") or 0.0
                                )
                                leakage_guard_seconds += float(
                                    plan["timing"].get("leakage_guard_seconds") or 0.0
                                )
                            plan = max(
                                plans,
                                key=lambda item: (
                                    bool(item.get("passed")),
                                    len(item.get("span_patches") or []),
                                    -int(item.get("residual_current_span_count") or 0),
                                    item.get("boundary_integrity") == "passed",
                                ),
                                default={
                                    "passed": False,
                                    "patched_text": before,
                                    "failure_reason": "span_alignment_failed",
                                    "span_patches": [],
                                    "rejected_spans": [],
                                    "span_patch_attempted": False,
                                    "anchor_preserved": False,
                                    "prefix_loss_detected": False,
                                    "suffix_loss_detected": False,
                                    "adjacent_leakage_detected": False,
                                    "boundary_integrity": "failed",
                                    "residual_current_span_count": 0,
                                },
                            )
                            patched_candidate = str(plan.get("patched_text") or before)
                            patched_candidate, independently_accepted, independently_rejected = (
                                _independently_guard_span_patches(
                                    before,
                                    list(plan.get("span_patches") or []),
                                    adjacent=adjacent,
                                    protected_terms=registry["protected_korean_concepts"],
                                    known_latin=known_latin,
                                )
                            )
                            plan["span_patches"] = independently_accepted
                            plan["rejected_spans"] = list(plan.get("rejected_spans") or []) + independently_rejected
                            plan["patched_text"] = patched_candidate
                            plan["passed"] = bool(independently_accepted and patched_candidate != before)
                            plan["residual_current_span_count"] = int(
                                plan.get("residual_current_span_count") or 0
                            ) + len(independently_rejected)
                            candidate_record.update(
                                {
                                    key: copy.deepcopy(plan.get(key))
                                    for key in (
                                        "span_patch_attempted",
                                        "span_from",
                                        "span_to",
                                        "replacement",
                                        "span_patches",
                                        "rejected_spans",
                                        "left_anchor",
                                        "right_anchor",
                                        "anchor_preserved",
                                        "prefix_loss_detected",
                                        "suffix_loss_detected",
                                        "adjacent_leakage_detected",
                                        "adjacent_leakage_matches",
                                        "boundary_integrity",
                                        "residual_current_span_count",
                                        "audio_evidence_source",
                                    )
                                }
                            )
                            passed, guard_reason = _candidate_guard(
                                before,
                                patched_candidate,
                                adjacent=adjacent,
                                protected_terms=registry["protected_korean_concepts"],
                                known_latin=known_latin,
                            )
                            if not plan.get("passed"):
                                passed = False
                                guard_reason = str(
                                    plan.get("failure_reason") or "span_alignment_failed"
                                )
                            confidence = aligned.get("confidence")
                            accepted = bool(
                                passed
                                and isinstance(confidence, (int, float))
                                and float(confidence) >= 0.78
                            )
                            verification: dict[str, Any] | None = None
                            if passed and not accepted and isinstance(confidence, (int, float)) and float(confidence) >= 0.55:
                                prompt = _build_verifier_prompt(
                                    row,
                                    patched_candidate,
                                    previous=previous,
                                    following=following,
                                    source=source,
                                    local_map=local_map,
                                )
                                verifier_started = time.perf_counter()
                                try:
                                    qwen_calls += 1
                                    accepted, verification = _verify_with_qwen(
                                        core,
                                        qwen_model_name
                                        or getattr(core, "_DEFAULT_LOCAL_LLM_MODEL_V034", "")
                                        or "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit",
                                        prompt,
                                        patched_candidate,
                                        verifier_generator,
                                    )
                                except Exception as exc:
                                    verification = {"error": f"{type(exc).__name__}:{exc}"}
                                    accepted = False
                                qwen_seconds += time.perf_counter() - verifier_started
                            if not accepted:
                                reason = guard_reason if not passed else "audio_candidate_not_high_confidence"
                                unresolved_ids.add(row_id)
                                _mark_audio_unresolved(
                                    result, row, reason, "audio_reviewed_unresolved"
                                )
                                candidate_record.update(
                                    {
                                        "reason": reason,
                                        "failure_reason": reason,
                                        "final_decision": "unresolved",
                                        "verification": verification,
                                    }
                                )
                                candidates.append(candidate_record)
                                continue

                            row["normalized_text"] = patched_candidate
                            row["auto_normalized_text"] = patched_candidate
                            row["korean_editorial_state"] = "audio_span_repaired"
                            residual_uncertainty = bool(
                                plan.get("residual_current_span_count")
                            )
                            row["review_status"] = (
                                "needs_review" if residual_uncertainty else "auto_approved"
                            )
                            warnings = row.setdefault("validation_warnings", [])
                            warnings[:] = [
                                warning
                                for warning in warnings
                                if warning != "korean_asr_editorial_review:review_budget_deferred"
                            ]
                            if not residual_uncertainty:
                                _remove_old_unresolved(result, row_id)
                            normalization_id = f"NM-{next_number:05d}"
                            next_number += 1
                            row.setdefault("normalization_item_ids", []).append(normalization_id)
                            result["normalization_items"].append(
                                {
                                    "normalization_id": normalization_id,
                                    "raw_text": before,
                                    "normalized_text": patched_candidate,
                                    "normalization_type": "korean_audio_reasr_span_repair_v0316",
                                    "confidence": "high",
                                    "evidence_sources": [
                                        "timestamp_aligned_local_audio_reasr",
                                        "word_timestamp_ownership",
                                        "stable_left_and_right_context_anchors",
                                    ],
                                    "affected_segment_ids": copy.deepcopy(
                                        row.get("source_segment_ids") or []
                                    ),
                                    "review_status": (
                                        "needs_review"
                                        if residual_uncertainty
                                        else "auto_approved"
                                    ),
                                    "audio_span_patches": copy.deepcopy(
                                        plan.get("span_patches") or []
                                    ),
                                }
                            )
                            changed_items.append(
                                {
                                    "utterance_id": row_id,
                                    "before": before,
                                    "after": patched_candidate,
                                    "reason": "span_safe_timestamp_aligned_local_audio_reasr",
                                    "confidence": "high",
                                    "evidence_type": "local_audio_reasr",
                                }
                            )
                            repaired_ids.add(row_id)
                            if residual_uncertainty:
                                unresolved_ids.add(row_id)
                                _mark_audio_unresolved(
                                    result,
                                    row,
                                    "partial_audio_span_repair_remaining_uncertainty",
                                    "audio_reviewed_unresolved",
                                    preserve_state=True,
                                )
                            candidate_record.update(
                                {
                                    "candidate_text": canonical_candidate,
                                    "patched_text": patched_candidate,
                                    "status": (
                                        "partial_repair"
                                        if residual_uncertainty
                                        else "accepted"
                                    ),
                                    "reason": "span_safe_timestamp_aligned_audio",
                                    "failure_reason": (
                                        "partial_audio_span_repair_remaining_uncertainty"
                                        if residual_uncertainty
                                        else None
                                    ),
                                    "final_decision": (
                                        "partial_repair_unresolved"
                                        if residual_uncertainty
                                        else "audio_span_repaired"
                                    ),
                                    "verification": verification,
                                }
                            )
                            candidates.append(candidate_record)
            except Exception as exc:
                for row_id in selected_ids - reviewed_ids:
                    row = rows_by_id.get(row_id)
                    if row is not None:
                        failed_ids.add(row_id)
                        _mark_audio_unresolved(
                            result,
                            row,
                            f"audio_source_prepare_failed:{type(exc).__name__}",
                            "review_failed",
                        )

    for row_id in deferred_ids:
        row = rows_by_id.get(row_id)
        if row is not None:
            _mark_audio_unresolved(
                result, row, "audio_review_duration_budget_deferred", "review_pending"
            )
    ambiguous_ids = {
        str(item.get("utterance_id") or "")
        for item in classified
        if item["classification"] == "ambiguous_needs_review"
    }
    pending_ids = deferred_ids | ambiguous_ids
    if selected_windows and not capability.get("available"):
        pending_ids |= selected_ids

    adapter_load_count = int(getattr(active_adapter, "model_load_count", 0) or 0)
    adapter_load_seconds = float(getattr(active_adapter, "model_load_seconds", 0.0) or 0.0)
    adapter_generation_seconds = float(
        getattr(active_adapter, "generation_seconds", asr_generation_seconds)
        or asr_generation_seconds
    )
    total_seconds = time.perf_counter() - started
    result["korean_audio_review"] = {
        "enabled": True,
        "stage": "korean_audio_reasr",
        "version": AUDIO_REVIEW_VERSION,
        "detected_suspicious_count": len(classified),
        "audio_needed_count": len(audio_records),
        "audio_reviewed_count": len(reviewed_ids),
        "audio_repaired_count": len(repaired_ids),
        "audio_unresolved_count": len(unresolved_ids),
        "review_pending_count": len(pending_ids),
        "review_failed_count": len(failed_ids),
        "classification_counts": {
            name: sum(1 for item in classified if item["classification"] == name)
            for name in (
                "deterministic_fixable",
                "entity_fixable",
                "audio_evidence_needed",
                "ambiguous_needs_review",
            )
        },
        "classified_items": classified,
        "audio_windows": [
            {
                "window_id": window.window_id,
                "start_seconds": window.start_seconds,
                "end_seconds": window.end_seconds,
                "duration_seconds": round(window.duration_seconds, 6),
                "utterance_ids": list(window.row_ids),
                "selected": window in selected_windows,
            }
            for window in windows
        ],
        "candidates": candidates,
        "capability": capability,
        "runtime_metrics": {
            "audio_source_prepare_seconds": round(audio_source_prepare_seconds, 6),
            "audio_download_count": audio_download_count,
            "audio_bytes": audio_bytes,
            "yt_dlp_executable": yt_dlp_executable,
            "yt_dlp_source": yt_dlp_source,
            "yt_dlp_version": yt_dlp_version,
            "yt_dlp_readiness_seconds": round(yt_dlp_readiness_seconds, 6),
            "system_ytdlp_media_attempt_count": int(
                audio_download_count > 0 and yt_dlp_source == "system_fallback"
            ),
            "audio_window_count": len(selected_windows) if capability.get("available") else 0,
            "audio_review_total_seconds": round(
                sum(window.duration_seconds for window in selected_windows)
                if capability.get("available")
                else 0.0,
                6,
            ),
            "planned_audio_review_seconds": round(
                sum(window.duration_seconds for window in selected_windows), 6
            ),
            "asr_engine": capability.get("engine"),
            "asr_model": capability.get("model"),
            "asr_model_load_count": adapter_load_count,
            "asr_model_load_seconds": round(adapter_load_seconds, 6),
            "asr_generation_seconds": round(adapter_generation_seconds, 6),
            "asr_call_count": asr_calls,
            "reasr_candidate_count": len(candidates),
            "reasr_accepted_count": len(repaired_ids),
            "reasr_rejected_count": len(unresolved_ids),
            "qwen_verifier_calls": qwen_calls,
            "qwen_verifier_seconds": round(qwen_seconds, 6),
            "span_diff_seconds": round(span_diff_seconds, 6),
            "anchor_guard_seconds": round(anchor_guard_seconds, 6),
            "adjacent_leakage_guard_seconds": round(leakage_guard_seconds, 6),
            "total_korean_audio_review_seconds": round(total_seconds, 6),
        },
        "policy": {
            "padding_seconds": WINDOW_PADDING_SECONDS,
            "cluster_max_gap_seconds": CLUSTER_MAX_GAP_SECONDS,
            "max_window_seconds": MAX_WINDOW_SECONDS,
            "audio_review_budget_seconds": configured_budget,
            "audio_review_budget_policy": budget_policy,
            "audio_review_budget_environment_variable": AUDIO_REVIEW_BUDGET_ENV,
            "word_timestamp_required_for_auto_apply": True,
            "full_row_replacement_allowed": False,
            "stable_left_and_right_anchors_required": True,
            "adjacent_row_leakage_allowed_in_patched_result": False,
            "automatic_model_download": False,
            "audio_download_max_per_run": 1,
        },
    }
    editorial = result.get("korean_editorial_review") or {}
    editorial["text_only_model_review_disabled_in_runtime"] = True
    editorial["audio_repaired_count"] = len(repaired_ids)
    editorial["repaired_count"] = int(editorial.get("repaired_count") or 0) + len(repaired_ids)
    editorial["unresolved_count"] = len(
        {
            str(item.get("utterance_id") or "")
            for item in result.get("unresolved_terms") or []
            if isinstance(item, dict)
            and item.get("stage") in {"korean_asr_editorial_review", "korean_audio_reasr"}
        }
    )
    editorial["states"] = Counter(
        str(row.get("korean_editorial_state") or "clean") for row in rows
    )
    report = result.setdefault("processing_report", {})
    report["korean_audio_review_enabled"] = True
    report["korean_audio_needed_count"] = len(audio_records)
    report["korean_audio_repaired_count"] = len(repaired_ids)
    return result
