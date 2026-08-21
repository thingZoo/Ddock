import assert from "node:assert/strict";
import test from "node:test";

import { parseReviewDraft, parseReviewDraftText, ReviewImportError } from "./guards";
import {
  addStep,
  assignPhaseToPart,
  createPartFromPhase,
  excludePhase,
  reorderPart,
  reorderStep,
} from "./operations";
import { toPublishedCandidate } from "./publish";
import {
  loadLastReviewDraft,
  saveReviewDraft,
  type StorageLike,
} from "./storage";
import { createReviewFixture } from "./test-fixture";
import { PUBLISHED_SCHEMA_VERSION } from "./types";
import { validateReviewDraft } from "./validation";

class MemoryStorage implements StorageLike {
  private values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
}

test("valid review JSON import", () => {
  const draft = createReviewFixture();
  assert.equal(parseReviewDraftText(JSON.stringify(draft)).source.video_id, "fixture-video");
});

test("invalid schema rejection", () => {
  const draft = createReviewFixture() as unknown as Record<string, unknown>;
  draft.schema_version = "invalid";
  assert.throws(() => parseReviewDraft(draft), ReviewImportError);
});

test("localStorage save and restore", () => {
  const storage = new MemoryStorage();
  saveReviewDraft(storage, createReviewFixture());
  assert.equal(loadLastReviewDraft(storage)?.source.video_id, "fixture-video");
});

test("PART edit keeps ID", () => {
  const draft = createReviewFixture();
  const id = draft.draft_parts[0].part_id;
  draft.draft_parts[0].title = "수정된 제목";
  assert.equal(draft.draft_parts[0].part_id, id);
});

test("PART reorder keeps IDs", () => {
  const draft = createPartFromPhase(createReviewFixture(), "PHASE-002");
  const ids = draft.draft_parts.map((part) => part.part_id);
  const reordered = reorderPart(draft, ids[1], -1);
  assert.deepEqual(reordered.draft_parts.map((part) => part.part_id), [ids[1], ids[0]]);
});

test("STEP add creates a unique ID", () => {
  const draft = createReviewFixture();
  const updated = addStep(draft, "PART-01");
  const ids = updated.draft_parts[0].steps.map((step) => step.step_id);
  assert.equal(ids.length, new Set(ids).size);
});

test("STEP reorder keeps IDs", () => {
  let draft = addStep(createReviewFixture(), "PART-01");
  const ids = draft.draft_parts[0].steps.map((step) => step.step_id);
  draft = reorderStep(draft, "PART-01", ids[1], -1);
  assert.deepEqual(draft.draft_parts[0].steps.map((step) => step.step_id), [ids[1], ids[0]]);
});

test("unassigned phase assigns to existing PART", () => {
  const draft = assignPhaseToPart(createReviewFixture(), "PHASE-002", "PART-01");
  assert.equal(draft.action_phases[1].assigned_part_id, "PART-01");
  assert.equal(draft.unassigned_phases.length, 0);
});

test("unassigned phase creates PART", () => {
  const draft = createPartFromPhase(createReviewFixture(), "PHASE-002");
  assert.equal(draft.draft_parts.length, 2);
  assert.equal(draft.action_phases[1].assigned_part_id, draft.draft_parts[1].part_id);
});

test("phase exclusion requires reason", () => {
  assert.throws(() => excludePhase(createReviewFixture(), "PHASE-002", "  "));
  assert.equal(
    excludePhase(createReviewFixture(), "PHASE-002", "반복 설명").unassigned_phases[0]
      .excluded_reason,
    "반복 설명",
  );
});

test("blocking unassigned phase prevents candidate", () => {
  assert.equal(validateReviewDraft(createReviewFixture()).canPublish, false);
});

test("excluded phase clears unassigned blocker", () => {
  const draft = excludePhase(createReviewFixture(), "PHASE-002", "중복 workflow");
  const report = validateReviewDraft(draft);
  assert.equal(
    report.issues.some((issue) => issue.code === "unresolved_unassigned_phase"),
    false,
  );
});

test("STEP evidence outside PART is rejected", () => {
  const draft = createReviewFixture();
  draft.draft_parts[0].steps[0].source_utterance_ids = ["UT-00004"];
  assert.ok(
    validateReviewDraft(draft).issues.some(
      (issue) => issue.code === "step_evidence_outside_part",
    ),
  );
});

test("Learn More evidence outside PART is rejected", () => {
  const draft = createReviewFixture();
  draft.draft_parts[0].steps[0].learn_more = [
    {
      question: "왜인가요?",
      body: "설명",
      source_timestamp: "00:30",
      evidence: [{ utterance_id: "UT-00004", start_seconds: 30, end_seconds: 38 }],
    },
  ];
  assert.ok(
    validateReviewDraft(draft).issues.some(
      (issue) => issue.code === "learn_more_evidence_outside_part",
    ),
  );
});

test("duplicate IDs are rejected", () => {
  const draft = createReviewFixture();
  draft.draft_parts.push(structuredClone(draft.draft_parts[0]));
  assert.ok(
    validateReviewDraft(draft).issues.some((issue) => issue.code === "duplicate_part_id"),
  );
});

test("draft converts to published candidate", () => {
  const published = toPublishedCandidate(createReviewFixture());
  assert.ok(Array.isArray(published.catchup_parts));
  assert.equal("draft_parts" in published, false);
});

test("review-only fields are removed", () => {
  const published = toPublishedCandidate(createReviewFixture()) as unknown as Record<
    string,
    unknown
  >;
  assert.equal("action_phases" in published, false);
  assert.equal("unassigned_phases" in published, false);
  assert.equal("review_queue" in published, false);
  assert.equal(
    "review_reasons" in (published.catchup_parts as Record<string, unknown>[])[0],
    false,
  );
});

test("published schema version is correct", () => {
  assert.equal(
    toPublishedCandidate(createReviewFixture()).schema_version,
    PUBLISHED_SCHEMA_VERSION,
  );
});
