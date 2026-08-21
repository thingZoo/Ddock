from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import isodate
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

YOUTUBE_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"


class CollectorError(RuntimeError):
    pass


def extract_video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[\w-]{11}", value):
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.")
    candidate = ""

    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) > 1 else ""

    if not re.fullmatch(r"[\w-]{11}", candidate or ""):
        raise CollectorError("유효한 YouTube URL 또는 영상 ID를 입력해 주세요.")
    return candidate


def youtube_metadata(video_id: str, api_key: str) -> dict[str, Any]:
    params = {
        "part": "snippet,contentDetails,statistics,status",
        "id": video_id,
        "key": api_key.strip(),
    }
    response = requests.get(YOUTUBE_VIDEOS_API, params=params, timeout=30)
    try:
        payload = response.json()
    except ValueError as exc:
        raise CollectorError(f"YouTube API 응답을 읽지 못했습니다. HTTP {response.status_code}") from exc

    if response.status_code != 200:
        message = payload.get("error", {}).get("message", "알 수 없는 YouTube API 오류")
        raise CollectorError(f"YouTube API 오류: {message}")

    items = payload.get("items", [])
    if not items:
        raise CollectorError("영상 정보를 찾지 못했습니다. 비공개·삭제·지역 제한 여부를 확인해 주세요.")

    item = items[0]
    snippet = item.get("snippet", {})
    details = item.get("contentDetails", {})
    statistics = item.get("statistics", {})
    status = item.get("status", {})

    iso_duration = details.get("duration")
    duration_seconds = int(isodate.parse_duration(iso_duration).total_seconds()) if iso_duration else None

    return {
        "video_id": video_id,
        "title": snippet.get("title"),
        "channel_title": snippet.get("channelTitle"),
        "channel_id": snippet.get("channelId"),
        "published_at": snippet.get("publishedAt"),
        "description_raw": snippet.get("description", ""),
        "default_language": snippet.get("defaultLanguage"),
        "default_audio_language": snippet.get("defaultAudioLanguage"),
        "thumbnails": snippet.get("thumbnails", {}),
        "tags": snippet.get("tags", []),
        "duration_iso8601": iso_duration,
        "duration_seconds": duration_seconds,
        "caption_availability": details.get("caption"),
        "view_count": statistics.get("viewCount"),
        "like_count": statistics.get("likeCount"),
        "comment_count": statistics.get("commentCount"),
        "privacy_status": status.get("privacyStatus"),
        "embeddable": status.get("embeddable"),
        "value_source": "youtube_data_api_v3",
        "verification_status": "directly_verified",
    }


TIME_PATTERN = re.compile(
    r"(?m)^\s*(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—|:：]?\s*(?P<label>.+?)\s*$"
)


def timestamp_to_seconds(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(value)


def parse_creator_chapters(description: str, duration_seconds: int | None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for match in TIME_PATTERN.finditer(description or ""):
        timestamp_text = match.group("time")
        start_seconds = timestamp_to_seconds(timestamp_text)
        label = match.group("label").strip(" -–—|:：")
        if duration_seconds is None or start_seconds <= duration_seconds:
            found.append({
                "timestamp_text": timestamp_text,
                "start_seconds": start_seconds,
                "label": label,
                "source_type": "creator_timestamp",
                "value_source": "youtube_description",
                "verification_status": "directly_verified",
            })

    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in sorted(found, key=lambda x: x["start_seconds"]):
        key = (item["start_seconds"], item["label"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    for index, item in enumerate(deduped):
        item["end_seconds"] = (
            deduped[index + 1]["start_seconds"] if index + 1 < len(deduped) else duration_seconds
        )
    return deduped


@dataclass
class TranscriptResult:
    status: str
    language: str | None
    language_code: str | None
    is_generated: bool | None
    is_translatable: bool | None
    items: list[dict[str, Any]]
    error_type: str | None = None
    error_message: str | None = None


def fetch_transcript(video_id: str, preferred_languages: list[str] | None = None) -> TranscriptResult:
    preferred_languages = preferred_languages or ["ko", "en"]
    api = YouTubeTranscriptApi()

    try:
        transcripts = list(api.list(video_id))
        if not transcripts:
            return TranscriptResult("not_available", None, None, None, None, [], "NoTranscriptFound", "사용 가능한 스크립트가 없습니다.")

        selected = None
        for generated in (False, True):
            for language in preferred_languages:
                for transcript in transcripts:
                    if transcript.language_code.startswith(language) and transcript.is_generated == generated:
                        selected = transcript
                        break
                if selected:
                    break
            if selected:
                break
        selected = selected or transcripts[0]

        fetched = selected.fetch()
        items = []
        for index, item in enumerate(fetched.to_raw_data()):
            start = float(item.get("start", 0))
            duration = float(item.get("duration", 0))
            items.append({
                "segment_id": f"TR-{index + 1:05d}",
                "text": item.get("text", ""),
                "start_seconds": start,
                "duration_seconds": duration,
                "end_seconds": start + duration,
                "source_type": "youtube_transcript",
            })

        return TranscriptResult(
            "collected",
            selected.language,
            selected.language_code,
            selected.is_generated,
            selected.is_translatable,
            items,
        )
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        return TranscriptResult("not_available", None, None, None, None, [], type(exc).__name__, str(exc))
    except VideoUnavailable as exc:
        return TranscriptResult("access_blocked", None, None, None, None, [], type(exc).__name__, str(exc))
    except CouldNotRetrieveTranscript as exc:
        return TranscriptResult("failed", None, None, None, None, [], type(exc).__name__, str(exc))
    except Exception as exc:
        return TranscriptResult("failed", None, None, None, None, [], type(exc).__name__, str(exc))


def determine_completeness(metadata: dict[str, Any], transcript: TranscriptResult, chapters: list[dict[str, Any]]) -> dict[str, Any]:
    description_ok = bool((metadata.get("description_raw") or "").strip())
    transcript_ok = transcript.status == "collected" and bool(transcript.items)

    if transcript_ok:
        completeness = "text_complete"
        can_run_metadata = True
        limitations = [
            "영상 주요 프레임·화면 텍스트는 아직 수집하지 않았습니다.",
            "고정 댓글·작성자 댓글·외부 자료 접근 상태는 아직 검증하지 않았습니다.",
        ]
    elif description_ok:
        completeness = "transcript_missing"
        can_run_metadata = False
        limitations = [
            "영상 전체 자막을 확보하지 못해 전체 가치 단위 판정을 금지합니다.",
            "더보기란에 직접 적힌 범위만 제한적으로 확인할 수 있습니다.",
        ]
    else:
        completeness = "metadata_only"
        can_run_metadata = False
        limitations = ["더보기란과 스크립트를 확보하지 못해 콘텐츠 분석을 금지합니다."]

    return {
        "source_completeness": completeness,
        "can_run_content_metadata": can_run_metadata,
        "can_split_value_units": can_run_metadata,
        "can_generate_3A": can_run_metadata,
        "can_generate_3B": can_run_metadata,
        "metadata_limitations": limitations,
        "creator_chapter_status": "collected" if chapters else "not_provided_or_unparsed",
    }


def collect(video_url: str, api_key: str, preferred_languages: list[str] | None = None) -> dict[str, Any]:
    video_id = extract_video_id(video_url)
    metadata = youtube_metadata(video_id, api_key)
    chapters = parse_creator_chapters(metadata.get("description_raw", ""), metadata.get("duration_seconds"))
    transcript = fetch_transcript(video_id, preferred_languages)
    gate = determine_completeness(metadata, transcript, chapters)

    return {
        "schema_version": "youtube_acquisition_validation_v0.1",
        "source_url": video_url,
        "platform": "youtube",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collector_methods": {
            "metadata": "youtube_data_api_v3",
            "description": "youtube_data_api_v3",
            "creator_chapters": "description_timestamp_parser",
            "transcript": "youtube-transcript-api_unofficial",
        },
        "metadata": metadata,
        "creator_chapters": chapters,
        "transcript": {
            "status": transcript.status,
            "language": transcript.language,
            "language_code": transcript.language_code,
            "is_generated": transcript.is_generated,
            "is_translatable": transcript.is_translatable,
            "segment_count": len(transcript.items),
            "items": transcript.items,
            "error_type": transcript.error_type,
            "error_message": transcript.error_message,
            "value_source": "youtube_web_client_undocumented",
            "verification_status": "directly_collected" if transcript.status == "collected" else "collection_failed_or_unavailable",
        },
        "quality_gate": gate,
        "not_collected_in_v0_1": [
            "video_frames",
            "ocr_text",
            "creator_comments",
            "pinned_comment",
            "external_asset_access_validation",
            "youtube_platform_generated_key_concepts",
        ],
    }
