import {
  PUBLISHED_SCHEMA_VERSION,
  type PublishedContent,
} from "./types";

const REVIEW_SCHEMA_VERSION = "ddock_content_review_v0.1";

export class PublishedContentGuardError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PublishedContentGuardError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(
  value: Record<string, unknown>,
  key: string,
): Record<string, unknown> {
  const candidate = value[key];
  if (!isRecord(candidate)) {
    throw new PublishedContentGuardError(`${key} must be an object`);
  }
  return candidate;
}

function requireArray(value: Record<string, unknown>, key: string): void {
  if (!Array.isArray(value[key])) {
    throw new PublishedContentGuardError(`${key} must be an array`);
  }
}

function arrayValue(value: Record<string, unknown>, key: string): unknown[] {
  requireArray(value, key);
  return value[key] as unknown[];
}

function requireString(
  value: Record<string, unknown>,
  key: string,
  path: string,
): void {
  if (typeof value[key] !== "string") {
    throw new PublishedContentGuardError(`${path}.${key} must be a string`);
  }
}

function requireNumber(
  value: Record<string, unknown>,
  key: string,
  path: string,
): void {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw new PublishedContentGuardError(`${path}.${key} must be a finite number`);
  }
}

function recordAt(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new PublishedContentGuardError(`${path} must be an object`);
  }
  return value;
}

function requireStringArray(
  value: Record<string, unknown>,
  key: string,
  path: string,
): void {
  const items = arrayValue(value, key);
  if (!items.every((item) => typeof item === "string")) {
    throw new PublishedContentGuardError(`${path}.${key} must contain only strings`);
  }
}

/**
 * Frontend structural guard only.
 * Python published validator remains canonical source of truth.
 */
export function assertPublishedContent(value: unknown): asserts value is PublishedContent {
  if (!isRecord(value)) {
    throw new PublishedContentGuardError("published content must be an object");
  }

  if (value.schema_version === REVIEW_SCHEMA_VERSION) {
    throw new PublishedContentGuardError(
      "review draft schema ddock_content_review_v0.1 is not publishable",
    );
  }
  if (value.schema_version !== PUBLISHED_SCHEMA_VERSION) {
    throw new PublishedContentGuardError(
      `schema_version must be ${PUBLISHED_SCHEMA_VERSION}`,
    );
  }

  const source = requireRecord(value, "source");
  if (typeof source.video_id !== "string" || source.video_id.trim() === "") {
    throw new PublishedContentGuardError("source.video_id must be a non-empty string");
  }

  const videoDetail = requireRecord(value, "video_detail");
  const recommendation = videoDetail.recommendation;
  if (recommendation !== null && !isRecord(recommendation)) {
    throw new PublishedContentGuardError(
      "video_detail.recommendation must be an object or null",
    );
  }
  if (isRecord(recommendation)) {
    requireString(recommendation, "eyebrow", "video_detail.recommendation");
    requireString(recommendation, "title", "video_detail.recommendation");
    requireString(recommendation, "body", "video_detail.recommendation");
  }
  for (const [index, candidate] of arrayValue(videoDetail, "tools").entries()) {
    const tool = recordAt(candidate, `video_detail.tools[${index}]`);
    requireString(tool, "name", `video_detail.tools[${index}]`);
    requireString(tool, "canonical_name", `video_detail.tools[${index}]`);
    requireString(tool, "description", `video_detail.tools[${index}]`);
    if (tool.url !== null && typeof tool.url !== "string") {
      throw new PublishedContentGuardError(
        `video_detail.tools[${index}].url must be a string or null`,
      );
    }
  }
  requireStringArray(videoDetail, "tags", "video_detail");
  requireArray(videoDetail, "part_preview");

  for (const [index, candidate] of arrayValue(value, "script_chapters").entries()) {
    const chapter = recordAt(candidate, `script_chapters[${index}]`);
    requireString(chapter, "chapter_id", `script_chapters[${index}]`);
    requireString(chapter, "title", `script_chapters[${index}]`);
    requireNumber(chapter, "order", `script_chapters[${index}]`);
    requireNumber(chapter, "start_seconds", `script_chapters[${index}]`);
    requireNumber(chapter, "end_seconds", `script_chapters[${index}]`);
  }

  for (const [partIndex, candidate] of arrayValue(value, "catchup_parts").entries()) {
    const partPath = `catchup_parts[${partIndex}]`;
    const part = recordAt(candidate, partPath);
    requireString(part, "part_id", partPath);
    requireString(part, "title", partPath);
    requireString(part, "action_objective", partPath);
    requireNumber(part, "order", partPath);
    requireNumber(part, "start_seconds", partPath);
    requireNumber(part, "end_seconds", partPath);
    requireString(part, "start_timestamp", partPath);
    requireString(part, "end_timestamp", partPath);
    requireStringArray(part, "source_script_chapter_ids", partPath);
    if (part.summary !== null && typeof part.summary !== "string") {
      throw new PublishedContentGuardError(`${partPath}.summary must be a string or null`);
    }
    if (part.thumbnail !== null) {
      const thumbnail = recordAt(part.thumbnail, `${partPath}.thumbnail`);
      requireString(thumbnail, "relative_path", `${partPath}.thumbnail`);
    }

    for (const [stepIndex, stepCandidate] of arrayValue(part, "steps").entries()) {
      const stepPath = `${partPath}.steps[${stepIndex}]`;
      const step = recordAt(stepCandidate, stepPath);
      requireString(step, "step_id", stepPath);
      requireString(step, "action_title", stepPath);
      requireNumber(step, "order", stepPath);
      requireNumber(step, "playback_start_seconds", stepPath);
      requireNumber(step, "playback_end_seconds", stepPath);
      for (const [lineIndex, lineCandidate] of arrayValue(step, "action_lines").entries()) {
        const linePath = `${stepPath}.action_lines[${lineIndex}]`;
        const line = recordAt(lineCandidate, linePath);
        requireString(line, "text", linePath);
        for (const [segmentIndex, segmentCandidate] of arrayValue(
          line,
          "segments",
        ).entries()) {
          const segmentPath = `${linePath}.segments[${segmentIndex}]`;
          const segment = recordAt(segmentCandidate, segmentPath);
          requireString(segment, "type", segmentPath);
          requireString(segment, "text", segmentPath);
        }
      }
      if (step.prompt !== null) {
        const prompt = recordAt(step.prompt, `${stepPath}.prompt`);
        requireString(prompt, "text", `${stepPath}.prompt`);
      }
      if (step.warning !== null) {
        const warning = recordAt(step.warning, `${stepPath}.warning`);
        requireString(warning, "title", `${stepPath}.warning`);
        requireString(warning, "body", `${stepPath}.warning`);
      }
      for (const [learnIndex, learnCandidate] of arrayValue(
        step,
        "learn_more",
      ).entries()) {
        const learnPath = `${stepPath}.learn_more[${learnIndex}]`;
        const learnMore = recordAt(learnCandidate, learnPath);
        requireString(learnMore, "question", learnPath);
        requireString(learnMore, "body", learnPath);
        requireString(learnMore, "source_timestamp", learnPath);
        const learnEvidence = arrayValue(learnMore, "evidence");
        for (const [evidenceIndex, evidenceCandidate] of learnEvidence.entries()) {
          const evidencePath = `${learnPath}.evidence[${evidenceIndex}]`;
          const evidence = recordAt(evidenceCandidate, evidencePath);
          requireNumber(evidence, "start_seconds", evidencePath);
        }
      }
    }
  }

  for (const [index, candidate] of arrayValue(value, "script").entries()) {
    const rowPath = `script[${index}]`;
    const row = recordAt(candidate, rowPath);
    requireString(row, "utterance_id", rowPath);
    requireString(row, "timestamp", rowPath);
    requireString(row, "text", rowPath);
    requireNumber(row, "start_seconds", rowPath);
    requireNumber(row, "end_seconds", rowPath);
    requireStringArray(row, "catchup_part_ids", rowPath);
    if (row.script_chapter_id !== null && typeof row.script_chapter_id !== "string") {
      throw new PublishedContentGuardError(
        `${rowPath}.script_chapter_id must be a string or null`,
      );
    }
  }
  requireRecord(value, "curation_generation");
}

export function isPublishedContent(value: unknown): value is PublishedContent {
  try {
    assertPublishedContent(value);
    return true;
  } catch {
    return false;
  }
}
