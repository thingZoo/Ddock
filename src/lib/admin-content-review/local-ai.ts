import { parseReviewDraft, ReviewImportError } from "./guards";
import { syncDerivedFields } from "./operations";
import type { ReviewDraft } from "./types";

export const PREPROCESSING_SCHEMA_PREFIX = "script_preprocessing_v0.3.";

export interface PreprocessedInput {
  schema_version: string;
  video_id: string;
  normalized_utterances: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export type LocalGenerationStage =
  | "idle"
  | "preparing"
  | "classifying"
  | "composing"
  | "repairing_composition"
  | "writing_steps"
  | "repairing_steps"
  | "finalizing"
  | "complete";

export interface LocalGenerationProgress {
  type: "progress";
  stage: Exclude<LocalGenerationStage, "idle">;
  part_index?: number;
  part_count?: number;
  title?: string;
  unaccounted_anchor_ids?: string[];
}

interface LocalGenerationResult {
  type: "result";
  review: unknown;
}

interface LocalGenerationError {
  type: "error";
  message: string;
  error_type?: string;
}

type LocalGenerationEvent =
  | LocalGenerationProgress
  | LocalGenerationResult
  | LocalGenerationError;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parsePreprocessedInput(value: unknown): PreprocessedInput {
  if (!isRecord(value)) {
    throw new ReviewImportError("전처리 JSON의 root는 object여야 합니다.");
  }
  const schema = String(value.schema_version ?? "");
  if (schema === "ddock_content_review_v0.1") {
    throw new ReviewImportError("Review JSON이 아닌 전처리 JSON을 선택해주세요.");
  }
  if (!schema.startsWith(PREPROCESSING_SCHEMA_PREFIX)) {
    throw new ReviewImportError(`지원하지 않는 전처리 schema입니다: ${schema || "없음"}`);
  }
  const videoId = String(value.video_id ?? "").trim();
  if (!videoId) {
    throw new ReviewImportError("전처리 JSON에 video_id가 필요합니다.");
  }
  if (!Array.isArray(value.normalized_utterances) || value.normalized_utterances.length === 0) {
    throw new ReviewImportError("normalized_utterances가 있는 전처리 JSON이 필요합니다.");
  }
  return structuredClone(value) as PreprocessedInput;
}

export function parsePreprocessedInputText(text: string): PreprocessedInput {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new ReviewImportError("유효한 JSON 파일이 아닙니다.");
  }
  return parsePreprocessedInput(value);
}

export function injectGeneratedDraft(generated: unknown): ReviewDraft {
  return syncDerivedFields(parseReviewDraft(generated));
}

export function generatedDraftSummary(draft: ReviewDraft) {
  const partCount = draft.draft_parts.length;
  const stepCount = draft.draft_parts.reduce((total, part) => total + part.steps.length, 0);
  const blockingCount = draft.review_queue.filter((item) => item.severity === "blocking").length;
  const needsReview =
    draft.curation_generation.status === "completed_with_review" || blockingCount > 0;
  return {
    label: needsReview ? "초안 생성 완료 · 검토 필요" : "초안 생성 완료",
    partCount,
    stepCount,
    blockingCount,
  };
}

function parseEvent(line: string): LocalGenerationEvent {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new Error("로컬 AI 응답을 읽을 수 없습니다.");
  }
  if (!isRecord(value) || !["progress", "result", "error"].includes(String(value.type))) {
    throw new Error("로컬 AI가 지원하지 않는 응답을 반환했습니다.");
  }
  return value as unknown as LocalGenerationEvent;
}

export async function requestLocalDraft(
  preprocessed: PreprocessedInput,
  onProgress: (progress: LocalGenerationProgress) => void,
): Promise<ReviewDraft> {
  const response = await fetch("/api/admin/local-curation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(preprocessed),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(payload?.error || `로컬 AI 요청이 실패했습니다. (${response.status})`);
  }
  if (!response.body) {
    throw new Error("로컬 AI 응답 stream이 없습니다.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ReviewDraft | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = parseEvent(line);
      if (event.type === "progress") onProgress(event);
      if (event.type === "error") throw new Error(event.message || "로컬 AI 생성에 실패했습니다.");
      if (event.type === "result") result = parseReviewDraft(event.review);
    }
    if (done) break;
  }
  if (buffer.trim()) {
    const event = parseEvent(buffer);
    if (event.type === "progress") onProgress(event);
    if (event.type === "error") throw new Error(event.message || "로컬 AI 생성에 실패했습니다.");
    if (event.type === "result") result = parseReviewDraft(event.review);
  }
  if (!result) {
    throw new Error("로컬 AI가 review draft를 반환하지 않았습니다.");
  }
  return result;
}
