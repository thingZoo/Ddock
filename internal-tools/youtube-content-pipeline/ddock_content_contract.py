from __future__ import annotations

from typing import Final


SCHEMA_VERSION: Final = "ddock_content_v0.1"
OUTPUT_FILENAME: Final = "ddock_content_v0_1.json"
CURATION_GENERATION_SCHEMA_VERSION: Final = "ddock_content_curation_generation_v0.2"
PART_PLANNING_CONTRACT_VERSION: Final = "ddock_part_planning_v0.2"
STEP_GENERATION_CONTRACT_VERSION: Final = "ddock_step_generation_v0.2"
VIDEO_DETAIL_CONTRACT_VERSION: Final = "ddock_video_detail_v0.2"

RICH_SEGMENT_TYPES: Final = frozenset(
    {"text", "command", "ui_label", "filename", "path"}
)

TOP_LEVEL_FIELDS: Final = frozenset(
    {
        "schema_version",
        "source",
        "video_detail",
        "script_chapters",
        "catchup_parts",
        "script",
        "curation_generation",
    }
)

SOURCE_FIELDS: Final = frozenset(
    {
        "video_id",
        "source_url",
        "title",
        "channel_name",
        "published_at",
        "duration_seconds",
        "source_language",
        "preprocessing_schema_version",
        "content_chapter_schema_version",
        "view_count",
        "like_count",
    }
)

VIDEO_DETAIL_FIELDS: Final = frozenset(
    {"recommendation", "tools", "tags", "part_preview"}
)

SCRIPT_CHAPTER_FIELDS: Final = frozenset(
    {
        "chapter_id",
        "order",
        "title",
        "start_seconds",
        "end_seconds",
        "utterance_ids",
    }
)

SCRIPT_ROW_FIELDS: Final = frozenset(
    {
        "utterance_id",
        "start_seconds",
        "end_seconds",
        "timestamp",
        "text",
        "script_chapter_id",
        "catchup_part_ids",
    }
)

PART_FIELDS: Final = frozenset(
    {
        "part_id",
        "order",
        "title",
        "summary",
        "action_objective",
        "source_utterance_ids",
        "action_utterance_ids",
        "source_script_chapter_ids",
        "start_seconds",
        "end_seconds",
        "start_timestamp",
        "end_timestamp",
        "evidence",
        "thumbnail",
        "steps",
        "needs_review",
        "generation_warnings",
        "excluded_actions",
    }
)

STEP_FIELDS: Final = frozenset(
    {
        "step_id",
        "parent_part_id",
        "order",
        "action_title",
        "action_lines",
        "source_utterance_ids",
        "evidence",
        "playback_start_seconds",
        "playback_end_seconds",
        "prompt",
        "warning",
        "learn_more",
        "needs_review",
    }
)

ACTION_LINE_FIELDS: Final = frozenset(
    {"text", "segments", "source_utterance_ids"}
)
EXCLUDED_ACTION_FIELDS: Final = frozenset({"utterance_id", "reason"})
SEGMENT_FIELDS: Final = frozenset({"type", "text"})
EVIDENCE_FIELDS: Final = frozenset(
    {"utterance_id", "start_seconds", "end_seconds"}
)
PROMPT_FIELDS: Final = frozenset({"text", "source_kind", "evidence"})
WARNING_FIELDS: Final = frozenset({"title", "body", "evidence"})
LEARN_MORE_FIELDS: Final = frozenset(
    {"question", "body", "evidence", "source_timestamp"}
)
THUMBNAIL_FIELDS: Final = frozenset(
    {
        "content_chapter_id",
        "relative_path",
        "overlap_utterance_count",
        "overlap_ratio",
        "mapping_method",
    }
)
RECOMMENDATION_FIELDS: Final = frozenset(
    {"eyebrow", "title", "body", "claims", "evidence"}
)
RECOMMENDATION_CLAIM_FIELDS: Final = frozenset({"text", "evidence"})
TOOL_FIELDS: Final = frozenset(
    {"name", "canonical_name", "url", "description", "evidence"}
)
PART_PREVIEW_FIELDS: Final = frozenset(
    {"part_id", "title", "start_seconds", "end_seconds", "thumbnail"}
)

GENERATION_FIELDS: Final = frozenset(
    {
        "schema_version",
        "status",
        "model",
        "pass_architecture",
        "part_planning_calls",
        "step_generation_calls",
        "step_generation_initial_calls",
        "step_generation_retry_calls",
        "video_detail_calls",
        "total_model_calls",
        "model_generation_seconds",
        "total_runtime_seconds",
        "created_at",
        "warnings",
        "needs_review_count",
        "review_reasons",
        "omitted_part_candidates",
        "high_action_coverage_warnings",
        "deterministic_generation",
        "source_preprocessed_sha256",
    }
)

FORBIDDEN_MVP_FIELDS: Final = frozenset(
    {
        "logbook",
        "comments",
        "comment",
        "likes",
        "user_uploads",
        "user_results",
        "community_feed",
        "related_videos",
        "progress",
        "completed",
        "is_completed",
    }
)
