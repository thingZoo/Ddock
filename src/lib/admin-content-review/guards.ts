import {
  REVIEW_SCHEMA_VERSION,
  type ReviewDraft,
} from "./types";

export class ReviewImportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReviewImportError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireArray(
  value: Record<string, unknown>,
  key: string,
): asserts value is Record<string, unknown> & Record<typeof key, unknown[]> {
  if (!Array.isArray(value[key])) {
    throw new ReviewImportError(`필수 배열 field가 없습니다: ${key}`);
  }
}

export function parseReviewDraft(value: unknown): ReviewDraft {
  if (!isRecord(value)) {
    throw new ReviewImportError("JSON root는 object여야 합니다.");
  }
  if (value.schema_version !== REVIEW_SCHEMA_VERSION) {
    throw new ReviewImportError(
      `지원하지 않는 schema입니다. ${REVIEW_SCHEMA_VERSION} 파일을 선택해주세요.`,
    );
  }
  if (!isRecord(value.source) || typeof value.source.video_id !== "string") {
    throw new ReviewImportError("source.video_id가 필요합니다.");
  }
  if (!isRecord(value.video_detail)) {
    throw new ReviewImportError("video_detail object가 필요합니다.");
  }
  if (!isRecord(value.curation_generation)) {
    throw new ReviewImportError("curation_generation object가 필요합니다.");
  }
  for (const key of [
    "script_chapters",
    "script",
    "draft_parts",
    "action_phases",
    "unassigned_phases",
    "review_queue",
  ]) {
    requireArray(value, key);
  }
  return structuredClone(value) as unknown as ReviewDraft;
}

export function parseReviewDraftText(text: string): ReviewDraft {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new ReviewImportError("유효한 JSON 파일이 아닙니다.");
  }
  return parseReviewDraft(value);
}
