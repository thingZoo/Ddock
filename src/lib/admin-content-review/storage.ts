import { parseReviewDraftText } from "./guards";
import type { PublishedContent, ReviewDraft } from "./types";

export const LAST_REVIEW_KEY = "ddock:admin-review:last";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export function reviewStorageKey(videoId: string): string {
  return `ddock:admin-review:${videoId}`;
}

export function publishedPreviewStorageKey(videoId: string): string {
  return `ddock:published-preview:${videoId}`;
}

// MVP-only browser persistence. Backend/database persistence is future work.
export function saveReviewDraft(storage: StorageLike, draft: ReviewDraft): void {
  storage.setItem(reviewStorageKey(draft.source.video_id), JSON.stringify(draft));
  storage.setItem(LAST_REVIEW_KEY, draft.source.video_id);
}

export function loadReviewDraft(
  storage: StorageLike,
  videoId: string,
): ReviewDraft | null {
  const value = storage.getItem(reviewStorageKey(videoId));
  return value ? parseReviewDraftText(value) : null;
}

export function loadLastReviewDraft(storage: StorageLike): ReviewDraft | null {
  const videoId = storage.getItem(LAST_REVIEW_KEY);
  return videoId ? loadReviewDraft(storage, videoId) : null;
}

export function savePublishedPreview(
  storage: StorageLike,
  content: PublishedContent,
): void {
  storage.setItem(
    publishedPreviewStorageKey(content.source.video_id),
    JSON.stringify(content),
  );
}
