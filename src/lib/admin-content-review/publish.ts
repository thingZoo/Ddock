import { syncDerivedFields } from "./operations";
import {
  PUBLISHED_SCHEMA_VERSION,
  type DraftPart,
  type PublishedContent,
  type ReviewDraft,
} from "./types";

function publishedPart(part: DraftPart): Omit<DraftPart, "review_reasons"> {
  const { review_reasons: reviewReasons, ...value } = structuredClone(part);
  void reviewReasons;
  return value;
}

export function toPublishedCandidate(draft: ReviewDraft): PublishedContent {
  const synced = syncDerivedFields(draft);
  const catchupParts = synced.draft_parts.map(publishedPart);
  return {
    schema_version: PUBLISHED_SCHEMA_VERSION,
    source: structuredClone(synced.source),
    video_detail: {
      ...structuredClone(synced.video_detail),
      part_preview: catchupParts.map((part) => ({
        part_id: part.part_id,
        title: part.title,
        start_seconds: part.start_seconds,
        end_seconds: part.end_seconds,
        thumbnail: part.thumbnail,
      })),
    },
    script_chapters: structuredClone(synced.script_chapters),
    catchup_parts: catchupParts,
    script: structuredClone(synced.script),
    curation_generation: {
      ...structuredClone(synced.curation_generation),
      status: "published",
      needs_review_count: 0,
      review_reasons: [],
      phase_accounting: [],
    },
  };
}

export function draftFilename(videoId: string): string {
  return `${videoId}_ddock_content_review_v0_1.json`;
}

export function publishedFilename(videoId: string): string {
  return `${videoId}_ddock_content_v0_1.json`;
}
