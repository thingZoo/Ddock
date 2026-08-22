import type {
  ActionPhase,
  DraftPart,
  DraftStep,
  Evidence,
  EvidenceMode,
  ReviewDraft,
  ScriptRow,
} from "./types";

export function cloneDraft(draft: ReviewDraft): ReviewDraft {
  return structuredClone(draft);
}

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

function scriptOrder(draft: ReviewDraft): Map<string, number> {
  return new Map(draft.script.map((row, index) => [row.utterance_id, index]));
}

function orderedIds(draft: ReviewDraft, values: string[]): string[] {
  const order = scriptOrder(draft);
  return unique(values).sort(
    (left, right) =>
      (order.get(left) ?? Number.MAX_SAFE_INTEGER) -
      (order.get(right) ?? Number.MAX_SAFE_INTEGER),
  );
}

function evidenceFor(draft: ReviewDraft, ids: string[]): Evidence[] {
  const rows = new Map(draft.script.map((row) => [row.utterance_id, row]));
  return orderedIds(draft, ids).flatMap((id) => {
    const row = rows.get(id);
    return row
      ? [
          {
            utterance_id: id,
            start_seconds: row.start_seconds,
            end_seconds: row.end_seconds,
          },
        ]
      : [];
  });
}

function formatTimestamp(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function syncPart(draft: ReviewDraft, part: DraftPart, index: number): void {
  part.order = index + 1;
  part.source_utterance_ids = orderedIds(draft, part.source_utterance_ids);
  part.action_utterance_ids = orderedIds(
    draft,
    part.action_utterance_ids.filter((id) =>
      part.source_utterance_ids.includes(id),
    ),
  );
  const rows = new Map(draft.script.map((row) => [row.utterance_id, row]));
  const sourceRows = part.source_utterance_ids.flatMap((id) => {
    const row = rows.get(id);
    return row ? [row] : [];
  });
  if (sourceRows.length) {
    part.start_seconds = Math.min(...sourceRows.map((row) => row.start_seconds));
    part.end_seconds = Math.max(...sourceRows.map((row) => row.end_seconds));
    part.start_timestamp = formatTimestamp(part.start_seconds);
    part.end_timestamp = formatTimestamp(part.end_seconds);
    part.source_script_chapter_ids = unique(
      sourceRows.flatMap((row) =>
        row.script_chapter_id ? [row.script_chapter_id] : [],
      ),
    );
  }
  part.evidence = evidenceFor(draft, part.source_utterance_ids);
  part.steps.forEach((step, stepIndex) => {
    step.parent_part_id = part.part_id;
    step.order = stepIndex + 1;
  });
}

export function syncDerivedFields(draft: ReviewDraft): ReviewDraft {
  const next = cloneDraft(draft);
  next.draft_parts.forEach((part, index) => syncPart(next, part, index));
  const memberships = new Map<string, string[]>();
  next.draft_parts.forEach((part) => {
    part.source_utterance_ids.forEach((id) => {
      memberships.set(id, [...(memberships.get(id) ?? []), part.part_id]);
    });
  });
  next.script.forEach((row) => {
    row.catchup_part_ids = memberships.get(row.utterance_id) ?? [];
  });
  next.video_detail.part_preview = next.draft_parts.map((part) => ({
    part_id: part.part_id,
    title: part.title,
    start_seconds: part.start_seconds,
    end_seconds: part.end_seconds,
    thumbnail: part.thumbnail,
  }));
  return next;
}

function nextNumericId(values: string[], prefix: string, digits: number): string {
  const expression = new RegExp(`^${prefix}(\\d+)$`);
  const maximum = values.reduce((current, value) => {
    const match = value.match(expression);
    return match ? Math.max(current, Number(match[1])) : current;
  }, 0);
  return `${prefix}${String(maximum + 1).padStart(digits, "0")}`;
}

export function nextPartId(draft: ReviewDraft): string {
  return nextNumericId(
    draft.draft_parts.map((part) => part.part_id),
    "PART-",
    2,
  );
}

export function nextStepId(draft: ReviewDraft, partId: string): string {
  const used = draft.draft_parts.flatMap((part) =>
    part.steps.map((step) => step.step_id),
  );
  return nextNumericId(used, `${partId}-STEP-`, 2);
}

function emptyPart(partId: string, order: number): DraftPart {
  return {
    part_id: partId,
    order,
    title: "새 PART",
    summary: null,
    action_objective: "",
    source_utterance_ids: [],
    action_utterance_ids: [],
    source_script_chapter_ids: [],
    start_seconds: 0,
    end_seconds: 0,
    start_timestamp: "00:00",
    end_timestamp: "00:00",
    evidence: [],
    thumbnail: null,
    steps: [],
    needs_review: true,
    review_reasons: ["part_needs_review"],
    generation_warnings: [],
    excluded_actions: [],
  };
}

export function addPart(draft: ReviewDraft): ReviewDraft {
  const next = cloneDraft(draft);
  next.draft_parts.push(emptyPart(nextPartId(next), next.draft_parts.length + 1));
  return syncDerivedFields(next);
}

export function deletePart(draft: ReviewDraft, partId: string): ReviewDraft {
  const next = cloneDraft(draft);
  next.draft_parts = next.draft_parts.filter((part) => part.part_id !== partId);
  next.action_phases.forEach((phase) => {
    if (phase.assigned_part_id !== partId) return;
    phase.assigned_part_id = null;
    phase.needs_review = true;
    phase.review_reasons = unique([...phase.review_reasons, "unassigned_phase"]);
    if (!next.unassigned_phases.some((item) => item.phase_id === phase.phase_id)) {
      next.unassigned_phases.push({ ...structuredClone(phase), excluded_reason: null });
    }
  });
  next.review_queue.forEach((item) => {
    if (item.part_id === partId) item.part_id = null;
  });
  return syncDerivedFields(next);
}

export function reorderPart(
  draft: ReviewDraft,
  partId: string,
  direction: -1 | 1,
): ReviewDraft {
  const next = cloneDraft(draft);
  const index = next.draft_parts.findIndex((part) => part.part_id === partId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= next.draft_parts.length) return next;
  [next.draft_parts[index], next.draft_parts[target]] = [
    next.draft_parts[target],
    next.draft_parts[index],
  ];
  return syncDerivedFields(next);
}

export function mergeParts(
  draft: ReviewDraft,
  targetPartId: string,
  sourcePartId: string,
): ReviewDraft {
  const next = cloneDraft(draft);
  const target = next.draft_parts.find((part) => part.part_id === targetPartId);
  const source = next.draft_parts.find((part) => part.part_id === sourcePartId);
  if (!target || !source || target === source) return next;
  target.source_utterance_ids = orderedIds(next, [
    ...target.source_utterance_ids,
    ...source.source_utterance_ids,
  ]);
  target.action_utterance_ids = orderedIds(next, [
    ...target.action_utterance_ids,
    ...source.action_utterance_ids,
  ]);
  target.steps = [...target.steps, ...source.steps];
  target.review_reasons = unique([
    ...target.review_reasons,
    ...source.review_reasons,
  ]);
  target.generation_warnings = unique([
    ...target.generation_warnings,
    ...source.generation_warnings,
  ]);
  target.excluded_actions = [...target.excluded_actions, ...source.excluded_actions];
  next.action_phases.forEach((phase) => {
    if (phase.assigned_part_id === sourcePartId) phase.assigned_part_id = targetPartId;
  });
  next.review_queue.forEach((item) => {
    if (item.part_id === sourcePartId) item.part_id = targetPartId;
  });
  next.draft_parts = next.draft_parts.filter((part) => part.part_id !== sourcePartId);
  return syncDerivedFields(next);
}

export function splitPartAtStep(
  draft: ReviewDraft,
  partId: string,
  stepId: string,
): ReviewDraft {
  const next = cloneDraft(draft);
  const index = next.draft_parts.findIndex((part) => part.part_id === partId);
  const part = next.draft_parts[index];
  if (!part) return next;
  const splitIndex = part.steps.findIndex((step) => step.step_id === stepId);
  if (splitIndex <= 0) return next;
  const movedSteps = part.steps.splice(splitIndex);
  const movedActionIds = orderedIds(
    next,
    movedSteps.flatMap((step) => step.source_utterance_ids),
  );
  if (!movedActionIds.length) return next;
  const movedSourceIds = orderedIds(next, [
    ...movedActionIds,
    ...movedSteps.flatMap((step) =>
      step.learn_more.flatMap((item) =>
        item.evidence.map((evidence) => evidence.utterance_id),
      ),
    ),
  ]);
  const newPart = emptyPart(nextPartId(next), index + 2);
  newPart.title = `${part.title} (분리)`;
  newPart.summary = part.summary;
  newPart.action_objective = part.action_objective;
  newPart.source_utterance_ids = movedSourceIds;
  newPart.action_utterance_ids = movedActionIds;
  newPart.steps = movedSteps;
  part.action_utterance_ids = part.action_utterance_ids.filter(
    (id) => !movedActionIds.includes(id),
  );
  part.source_utterance_ids = part.source_utterance_ids.filter(
    (id) => !movedSourceIds.includes(id),
  );
  next.action_phases.forEach((phase) => {
    if (
      phase.assigned_part_id === partId &&
      phase.action_utterance_ids.some((id) => movedActionIds.includes(id))
    ) {
      phase.assigned_part_id = newPart.part_id;
    }
  });
  const movedStepIds = new Set(movedSteps.map((step) => step.step_id));
  next.review_queue.forEach((item) => {
    if (item.step_id && movedStepIds.has(item.step_id)) item.part_id = newPart.part_id;
  });
  next.draft_parts.splice(index + 1, 0, newPart);
  return syncDerivedFields(next);
}

function emptyStep(stepId: string, partId: string, order: number): DraftStep {
  return {
    step_id: stepId,
    parent_part_id: partId,
    order,
    action_title: "새 STEP",
    action_lines: [
      { text: "", segments: [{ type: "text", text: "" }], source_utterance_ids: [] },
    ],
    source_utterance_ids: [],
    evidence: [],
    playback_start_seconds: 0,
    playback_end_seconds: 0,
    prompt: null,
    warning: null,
    learn_more: [],
    needs_review: true,
  };
}

export function addStep(draft: ReviewDraft, partId: string): ReviewDraft {
  const next = cloneDraft(draft);
  const part = next.draft_parts.find((value) => value.part_id === partId);
  if (!part) return next;
  part.steps.push(emptyStep(nextStepId(next, partId), partId, part.steps.length + 1));
  return syncDerivedFields(next);
}

export function deleteStep(
  draft: ReviewDraft,
  partId: string,
  stepId: string,
): ReviewDraft {
  const next = cloneDraft(draft);
  const part = next.draft_parts.find((value) => value.part_id === partId);
  if (!part) return next;
  part.steps = part.steps.filter((step) => step.step_id !== stepId);
  next.review_queue.forEach((item) => {
    if (item.step_id === stepId) item.step_id = null;
  });
  return syncDerivedFields(next);
}

export function reorderStep(
  draft: ReviewDraft,
  partId: string,
  stepId: string,
  direction: -1 | 1,
): ReviewDraft {
  const next = cloneDraft(draft);
  const part = next.draft_parts.find((value) => value.part_id === partId);
  if (!part) return next;
  const index = part.steps.findIndex((step) => step.step_id === stepId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= part.steps.length) return next;
  [part.steps[index], part.steps[target]] = [part.steps[target], part.steps[index]];
  return syncDerivedFields(next);
}

function phaseSourceIds(draft: ReviewDraft, phase: ActionPhase): string[] {
  return orderedIds(draft, [
    ...phase.action_utterance_ids,
    ...phase.context_utterance_ids,
  ]);
}

export function assignPhaseToPart(
  draft: ReviewDraft,
  phaseId: string,
  partId: string,
): ReviewDraft {
  const next = cloneDraft(draft);
  const phase = next.action_phases.find((value) => value.phase_id === phaseId);
  const part = next.draft_parts.find((value) => value.part_id === partId);
  if (!phase || !part) return next;
  phase.assigned_part_id = partId;
  phase.needs_review = phase.review_reasons.some(
    (reason) => reason !== "unassigned_phase",
  );
  phase.review_reasons = phase.review_reasons.filter(
    (reason) => reason !== "unassigned_phase",
  );
  part.source_utterance_ids = orderedIds(next, [
    ...part.source_utterance_ids,
    ...phaseSourceIds(next, phase),
  ]);
  part.action_utterance_ids = orderedIds(next, [
    ...part.action_utterance_ids,
    ...phase.action_utterance_ids,
  ]);
  next.unassigned_phases = next.unassigned_phases.filter(
    (value) => value.phase_id !== phaseId,
  );
  return syncDerivedFields(next);
}

export function createPartFromPhase(
  draft: ReviewDraft,
  phaseId: string,
): ReviewDraft {
  const next = cloneDraft(draft);
  const phase = next.action_phases.find((value) => value.phase_id === phaseId);
  if (!phase) return next;
  const part = emptyPart(nextPartId(next), next.draft_parts.length + 1);
  part.title = phase.phase_label;
  part.action_objective = phase.operation;
  part.source_utterance_ids = phaseSourceIds(next, phase);
  part.action_utterance_ids = orderedIds(next, phase.action_utterance_ids);
  next.draft_parts.push(part);
  return assignPhaseToPart(next, phaseId, part.part_id);
}

export function excludePhase(
  draft: ReviewDraft,
  phaseId: string,
  reason: string,
): ReviewDraft {
  if (!reason.trim()) throw new Error("제외 이유를 입력해주세요.");
  const next = cloneDraft(draft);
  const phase = next.unassigned_phases.find((value) => value.phase_id === phaseId);
  if (!phase) return next;
  phase.excluded_reason = reason.trim();
  return next;
}

function rowEvidence(row: ScriptRow): Evidence {
  return {
    utterance_id: row.utterance_id,
    start_seconds: row.start_seconds,
    end_seconds: row.end_seconds,
  };
}

export function toggleEvidence(
  draft: ReviewDraft,
  mode: Exclude<EvidenceMode, null>,
  utteranceId: string,
): ReviewDraft {
  const next = cloneDraft(draft);
  const part = next.draft_parts.find((value) => value.part_id === mode.partId);
  const step = part?.steps.find((value) => value.step_id === mode.stepId);
  const row = next.script.find((value) => value.utterance_id === utteranceId);
  if (!part || !step || !row) return next;
  const current =
    mode.kind === "step"
      ? step.evidence
      : mode.kind === "prompt"
        ? step.prompt?.evidence
        : mode.kind === "warning"
          ? step.warning?.evidence
          : step.learn_more[mode.index]?.evidence;
  if (!current) return next;
  const exists = current.some((value) => value.utterance_id === utteranceId);
  const updated = exists
    ? current.filter((value) => value.utterance_id !== utteranceId)
    : [...current, rowEvidence(row)];
  updated.sort((left, right) => left.start_seconds - right.start_seconds);
  if (mode.kind === "step") {
    step.evidence = updated;
    step.source_utterance_ids = updated.map((value) => value.utterance_id);
    step.playback_start_seconds = updated[0]?.start_seconds ?? 0;
    step.playback_end_seconds = updated.at(-1)?.end_seconds ?? 0;
  } else if (mode.kind === "prompt" && step.prompt) {
    step.prompt.evidence = updated;
  } else if (mode.kind === "warning" && step.warning) {
    step.warning.evidence = updated;
  } else if (mode.kind === "learn_more") {
    const item = step.learn_more[mode.index];
    if (item) {
      item.evidence = updated;
      item.source_timestamp = updated.length
        ? formatTimestamp(updated[0].start_seconds)
        : "00:00";
    }
  }
  return next;
}
