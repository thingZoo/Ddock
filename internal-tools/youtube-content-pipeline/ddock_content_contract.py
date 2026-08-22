from __future__ import annotations

from typing import Final


SCHEMA_VERSION: Final = "ddock_content_v0.1"
OUTPUT_FILENAME: Final = "ddock_content_v0_1.json"
REVIEW_SCHEMA_VERSION: Final = "ddock_content_review_v0.1"
REVIEW_OUTPUT_FILENAME: Final = "ddock_content_review_v0_1.json"
CURATION_GENERATION_SCHEMA_VERSION: Final = "ddock_content_curation_generation_v0.2"
PART_PLANNING_CONTRACT_VERSION: Final = "ddock_part_planning_v0.2"
ACTION_PHASE_DISCOVERY_CONTRACT_VERSION: Final = "ddock_action_phase_discovery_v0.1"
PART_COMPOSITION_CONTRACT_VERSION: Final = "ddock_part_composition_v0.1"
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

REVIEW_TOP_LEVEL_FIELDS: Final = frozenset(
    {
        "schema_version",
        "source",
        "video_detail",
        "script_chapters",
        "script",
        "draft_parts",
        "action_phases",
        "unassigned_phases",
        "review_queue",
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
REVIEW_PART_FIELDS: Final = PART_FIELDS.union({"review_reasons"})

ACTION_PHASE_FIELDS: Final = frozenset(
    {
        "phase_id",
        "order",
        "phase_label",
        "operation",
        "tool_or_surface",
        "expected_result",
        "action_utterance_ids",
        "context_utterance_ids",
        "assigned_part_id",
        "needs_review",
        "review_reasons",
    }
)
UNASSIGNED_PHASE_FIELDS: Final = ACTION_PHASE_FIELDS.union({"excluded_reason"})
REVIEW_QUEUE_FIELDS: Final = frozenset(
    {
        "review_id",
        "type",
        "severity",
        "part_id",
        "phase_id",
        "step_id",
        "utterance_ids",
        "message",
    }
)
REVIEW_QUEUE_TYPES: Final = frozenset(
    {
        "unassigned_phase",
        "phase_context_too_broad",
        "part_needs_review",
        "step_needs_review",
        "excluded_action",
        "unattached_context",
        "unsupported_claim_removed",
        "script_not_human_verified",
    }
)
REVIEW_SEVERITIES: Final = frozenset({"warning", "blocking"})

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
EXCLUDED_ACTION_FIELDS: Final = frozenset(
    {"utterance_id", "reason", "reason_category"}
)
EXCLUSION_REASON_CATEGORIES: Final = frozenset(
    {
        "duplicate",
        "not_reproducible",
        "context_only",
        "superseded_by_adjacent_action",
        "filtered_by_grounding",
        "ambiguous_source",
        "unassigned",
    }
)
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
        "action_phase_discovery_calls",
        "part_composition_calls",
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
        "phase_accounting",
        "posthoc_chapter_copy_audit",
        "recommendation_accounting",
        "script_review_status",
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
