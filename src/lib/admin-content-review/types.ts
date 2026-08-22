export const REVIEW_SCHEMA_VERSION = "ddock_content_review_v0.1" as const;
export const PUBLISHED_SCHEMA_VERSION = "ddock_content_v0.1" as const;

export type ReviewSeverity = "warning" | "blocking";
export type RichSegmentType =
  | "text"
  | "command"
  | "ui_label"
  | "filename"
  | "path";

export interface Evidence {
  utterance_id: string;
  start_seconds: number;
  end_seconds: number;
}

export interface RichSegment {
  type: RichSegmentType;
  text: string;
}

export interface ActionLine {
  text: string;
  segments: RichSegment[];
  source_utterance_ids: string[];
}

export interface PromptBlock {
  text: string;
  source_kind: "verbatim";
  evidence: Evidence[];
}

export interface WarningBlock {
  title: string;
  body: string;
  evidence: Evidence[];
}

export interface LearnMoreBlock {
  question: string;
  body: string;
  evidence: Evidence[];
  source_timestamp: string;
}

export interface DraftStep {
  step_id: string;
  parent_part_id: string;
  order: number;
  action_title: string;
  action_lines: ActionLine[];
  source_utterance_ids: string[];
  evidence: Evidence[];
  playback_start_seconds: number;
  playback_end_seconds: number;
  prompt: PromptBlock | null;
  warning: WarningBlock | null;
  learn_more: LearnMoreBlock[];
  needs_review: boolean;
}

export interface ThumbnailData {
  content_chapter_id: string;
  relative_path: string;
  overlap_utterance_count: number;
  overlap_ratio: number;
  mapping_method: string;
}

export interface ExcludedAction {
  utterance_id: string;
  reason: string;
  reason_category?: string;
}

export interface DraftPart {
  part_id: string;
  order: number;
  title: string;
  summary: string | null;
  action_objective: string;
  source_utterance_ids: string[];
  action_utterance_ids: string[];
  source_script_chapter_ids: string[];
  start_seconds: number;
  end_seconds: number;
  start_timestamp: string;
  end_timestamp: string;
  evidence: Evidence[];
  thumbnail: ThumbnailData | null;
  steps: DraftStep[];
  needs_review: boolean;
  review_reasons: string[];
  generation_warnings: string[];
  excluded_actions: ExcludedAction[];
}

export interface ActionPhase {
  phase_id: string;
  order: number;
  phase_label: string;
  operation: string;
  tool_or_surface: string | null;
  expected_result: string | null;
  action_utterance_ids: string[];
  context_utterance_ids: string[];
  assigned_part_id: string | null;
  needs_review: boolean;
  review_reasons: string[];
}

export interface UnassignedPhase extends ActionPhase {
  excluded_reason: string | null;
}

export interface ReviewQueueItem {
  review_id: string;
  type:
    | "unassigned_phase"
    | "phase_context_too_broad"
    | "part_needs_review"
    | "step_needs_review"
    | "excluded_action"
    | "unattached_context"
    | "unsupported_claim_removed"
    | "script_not_human_verified";
  severity: ReviewSeverity;
  part_id: string | null;
  phase_id: string | null;
  step_id: string | null;
  utterance_ids: string[];
  message: string;
}

export interface ScriptRow {
  utterance_id: string;
  start_seconds: number;
  end_seconds: number;
  timestamp: string;
  text: string;
  script_chapter_id: string | null;
  catchup_part_ids: string[];
}

export interface ScriptChapter {
  chapter_id: string;
  order: number;
  title: string;
  start_seconds: number;
  end_seconds: number;
  utterance_ids: string[];
}

export interface RecommendationClaim {
  text: string;
  evidence: Evidence[];
}

export interface RecommendationData {
  eyebrow: string;
  title: string;
  body: string;
  claims: RecommendationClaim[];
  evidence: Evidence[];
}

export interface ToolData {
  name: string;
  canonical_name: string;
  url: string | null;
  description: string;
  evidence: Evidence[];
}

export interface PartPreviewData {
  part_id: string;
  title: string;
  start_seconds: number;
  end_seconds: number;
  thumbnail: ThumbnailData | null;
}

export interface VideoDetailData {
  recommendation: RecommendationData | null;
  tools: ToolData[];
  tags: string[];
  part_preview: PartPreviewData[];
}

export interface SourceData {
  video_id: string;
  title?: string;
  source_url?: string;
  channel_name?: string;
  published_at?: string;
  duration_seconds?: number;
  source_language?: string;
  [key: string]: unknown;
}

export interface CurationGeneration {
  schema_version: string;
  status: string;
  needs_review_count: number;
  review_reasons: string[];
  phase_accounting: unknown[];
  [key: string]: unknown;
}

export interface ReviewDraft {
  schema_version: typeof REVIEW_SCHEMA_VERSION;
  source: SourceData;
  video_detail: VideoDetailData;
  script_chapters: ScriptChapter[];
  script: ScriptRow[];
  draft_parts: DraftPart[];
  action_phases: ActionPhase[];
  unassigned_phases: UnassignedPhase[];
  review_queue: ReviewQueueItem[];
  curation_generation: CurationGeneration;
}

export interface PublishedContent {
  schema_version: typeof PUBLISHED_SCHEMA_VERSION;
  source: SourceData;
  video_detail: VideoDetailData;
  script_chapters: ScriptChapter[];
  catchup_parts: Omit<DraftPart, "review_reasons">[];
  script: ScriptRow[];
  curation_generation: CurationGeneration;
}

export type EditorSelection =
  | { kind: "video" }
  | { kind: "part"; partId: string }
  | { kind: "step"; partId: string; stepId: string }
  | { kind: "phase"; phaseId: string }
  | { kind: "unassigned"; phaseId: string }
  | { kind: "review"; reviewId?: string }
  | { kind: "script" };

export type EvidenceMode =
  | { kind: "step"; partId: string; stepId: string }
  | { kind: "learn_more"; partId: string; stepId: string; index: number }
  | { kind: "prompt"; partId: string; stepId: string }
  | { kind: "warning"; partId: string; stepId: string }
  | null;

export interface ValidationIssue {
  id: string;
  severity: ReviewSeverity;
  code: string;
  message: string;
  partId?: string;
  stepId?: string;
  phaseId?: string;
  utteranceIds?: string[];
}

export interface ValidationReport {
  issues: ValidationIssue[];
  errorCount: number;
  blockingCount: number;
  warningCount: number;
  canPublish: boolean;
}
