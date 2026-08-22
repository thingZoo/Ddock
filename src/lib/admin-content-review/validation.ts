import {
  REVIEW_SCHEMA_VERSION,
  type DraftPart,
  type DraftStep,
  type ReviewDraft,
  type ReviewQueueItem,
  type ValidationIssue,
  type ValidationReport,
} from "./types";

// Browser preflight only. The Python contract validator remains source of truth.

function duplicateValues(values: string[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  values.forEach((value) => {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  });
  return [...duplicates];
}

function stepHasCoreFields(step: DraftStep, part: DraftPart): boolean {
  return (
    Boolean(step.action_title.trim()) &&
    step.action_lines.length > 0 &&
    step.action_lines.every((line) => Boolean(line.text.trim())) &&
    step.source_utterance_ids.length > 0 &&
    step.source_utterance_ids.every((id) =>
      part.action_utterance_ids.includes(id),
    ) &&
    !step.needs_review
  );
}

function partHasCoreFields(part: DraftPart): boolean {
  return (
    Boolean(part.title.trim()) &&
    Boolean(part.action_objective.trim()) &&
    part.steps.length > 0 &&
    part.steps.every((step) => stepHasCoreFields(step, part)) &&
    !part.needs_review
  );
}

export function isReviewItemResolved(
  draft: ReviewDraft,
  item: ReviewQueueItem,
): boolean {
  if (item.type === "unassigned_phase" && item.phase_id) {
    const phase = draft.action_phases.find(
      (value) => value.phase_id === item.phase_id,
    );
    const unassigned = draft.unassigned_phases.find(
      (value) => value.phase_id === item.phase_id,
    );
    return Boolean(phase?.assigned_part_id || unassigned?.excluded_reason?.trim());
  }
  if (item.type === "part_needs_review" && item.part_id) {
    const part = draft.draft_parts.find((value) => value.part_id === item.part_id);
    return Boolean(part && partHasCoreFields(part));
  }
  if (item.type === "step_needs_review" && item.part_id && item.step_id) {
    const part = draft.draft_parts.find((value) => value.part_id === item.part_id);
    const step = part?.steps.find((value) => value.step_id === item.step_id);
    return Boolean(part && step && stepHasCoreFields(step, part));
  }
  return false;
}

export function validateReviewDraft(draft: ReviewDraft): ValidationReport {
  const issues: ValidationIssue[] = [];
  let sequence = 0;
  const add = (
    issue: Omit<ValidationIssue, "id" | "severity"> & {
      severity?: ValidationIssue["severity"];
    },
  ) => {
    sequence += 1;
    issues.push({
      id: `PREFLIGHT-${String(sequence).padStart(3, "0")}`,
      severity: issue.severity ?? "blocking",
      ...issue,
    });
  };

  if (draft.schema_version !== REVIEW_SCHEMA_VERSION) {
    add({
      code: "invalid_schema_version",
      message: `${REVIEW_SCHEMA_VERSION} draft만 publish할 수 있습니다.`,
    });
  }

  const partIds = new Set(draft.draft_parts.map((part) => part.part_id));
  const phaseIds = new Set(draft.action_phases.map((phase) => phase.phase_id));
  const scriptIds = new Set(draft.script.map((row) => row.utterance_id));
  const steps = draft.draft_parts.flatMap((part) => part.steps);

  for (const value of duplicateValues(draft.draft_parts.map((part) => part.part_id))) {
    add({ code: "duplicate_part_id", message: `중복 PART ID: ${value}` });
  }
  for (const value of duplicateValues(steps.map((step) => step.step_id))) {
    add({ code: "duplicate_step_id", message: `중복 STEP ID: ${value}` });
  }
  for (const value of duplicateValues(draft.action_phases.map((phase) => phase.phase_id))) {
    add({ code: "duplicate_phase_id", message: `중복 Phase ID: ${value}` });
  }
  for (const value of duplicateValues(draft.review_queue.map((item) => item.review_id))) {
    add({ code: "duplicate_review_id", message: `중복 Review ID: ${value}` });
  }

  draft.unassigned_phases.forEach((phase) => {
    if (!phase.excluded_reason?.trim()) {
      add({
        code: "unresolved_unassigned_phase",
        message: `${phase.phase_id}를 PART에 연결하거나 명시적으로 제외해주세요.`,
        phaseId: phase.phase_id,
        utteranceIds: phase.action_utterance_ids,
      });
    }
    if (!phaseIds.has(phase.phase_id)) {
      add({
        code: "invalid_unassigned_phase_reference",
        message: `${phase.phase_id}가 action_phases에 없습니다.`,
        phaseId: phase.phase_id,
      });
    }
  });

  draft.action_phases.forEach((phase) => {
    if (phase.assigned_part_id && !partIds.has(phase.assigned_part_id)) {
      add({
        code: "invalid_phase_part_reference",
        message: `${phase.phase_id}의 PART reference가 유효하지 않습니다.`,
        phaseId: phase.phase_id,
      });
    }
  });

  draft.draft_parts.forEach((part) => {
    if (part.needs_review) {
      add({
        code: "part_needs_review",
        message: `${part.part_id}가 아직 needs_review 상태입니다.`,
        partId: part.part_id,
      });
    }
    if (!part.title.trim()) {
      add({
        code: "part_title_required",
        message: `${part.part_id} title이 비어 있습니다.`,
        partId: part.part_id,
      });
    }
    if (!part.action_objective.trim()) {
      add({
        code: "part_action_objective_required",
        message: `${part.part_id} action objective가 비어 있습니다.`,
        partId: part.part_id,
      });
    }
    if (!part.steps.length) {
      add({
        code: "part_steps_required",
        message: `${part.part_id}에 최소 한 개의 STEP이 필요합니다.`,
        partId: part.part_id,
      });
    }
    part.source_utterance_ids.forEach((id) => {
      if (!scriptIds.has(id)) {
        add({
          code: "unknown_part_source",
          message: `${part.part_id}가 존재하지 않는 source ${id}를 참조합니다.`,
          partId: part.part_id,
          utteranceIds: [id],
        });
      }
    });
    part.steps.forEach((step) => {
      if (step.needs_review) {
        add({
          code: "step_needs_review",
          message: `${step.step_id}가 아직 needs_review 상태입니다.`,
          partId: part.part_id,
          stepId: step.step_id,
        });
      }
      if (step.parent_part_id !== part.part_id) {
        add({
          code: "invalid_step_parent",
          message: `${step.step_id}의 parent PART reference가 잘못되었습니다.`,
          partId: part.part_id,
          stepId: step.step_id,
        });
      }
      if (!step.action_title.trim()) {
        add({
          code: "step_title_required",
          message: `${step.step_id} title이 비어 있습니다.`,
          partId: part.part_id,
          stepId: step.step_id,
        });
      }
      if (!step.action_lines.length || step.action_lines.some((line) => !line.text.trim())) {
        add({
          code: "step_action_line_required",
          message: `${step.step_id}에 비어 있지 않은 action line이 필요합니다.`,
          partId: part.part_id,
          stepId: step.step_id,
        });
      }
      const outside = step.source_utterance_ids.filter(
        (id) => !part.action_utterance_ids.includes(id),
      );
      if (outside.length) {
        add({
          code: "step_evidence_outside_part",
          message: `${step.step_id} evidence가 parent PART action 범위 밖입니다.`,
          partId: part.part_id,
          stepId: step.step_id,
          utteranceIds: outside,
        });
      }
      step.action_lines.forEach((line) => {
        const outsideLine = line.source_utterance_ids.filter(
          (id) => !step.source_utterance_ids.includes(id),
        );
        if (outsideLine.length) {
          add({
            code: "action_line_evidence_outside_step",
            message: `${step.step_id} action line evidence가 STEP 범위 밖입니다.`,
            partId: part.part_id,
            stepId: step.step_id,
            utteranceIds: outsideLine,
          });
        }
      });
      step.learn_more.forEach((item, index) => {
        const outsideLearnMore = item.evidence
          .map((value) => value.utterance_id)
          .filter((id) => !part.source_utterance_ids.includes(id));
        if (outsideLearnMore.length) {
          add({
            code: "learn_more_evidence_outside_part",
            message: `${step.step_id} Learn More ${index + 1} evidence가 PART 범위 밖입니다.`,
            partId: part.part_id,
            stepId: step.step_id,
            utteranceIds: outsideLearnMore,
          });
        }
      });
      if (step.prompt) {
        const promptIds = step.prompt.evidence.map((value) => value.utterance_id);
        const promptSource = draft.script
          .filter((row) => promptIds.includes(row.utterance_id))
          .map((row) => row.text)
          .join("\n")
          .replace(/\s+/g, " ");
        if (!promptIds.length) {
          add({
            code: "prompt_evidence_required",
            message: `${step.step_id} Prompt에 source evidence가 필요합니다.`,
            partId: part.part_id,
            stepId: step.step_id,
          });
        } else if (!promptSource.includes(step.prompt.text.trim().replace(/\s+/g, " "))) {
          add({
            code: "prompt_not_verbatim",
            message: `${step.step_id} Prompt가 cited source의 verbatim text가 아닙니다.`,
            partId: part.part_id,
            stepId: step.step_id,
            utteranceIds: promptIds,
          });
        }
      }
    });
  });

  draft.review_queue.forEach((item) => {
    if (item.part_id && !partIds.has(item.part_id)) {
      add({
        code: "invalid_review_part_reference",
        message: `${item.review_id}의 PART reference가 유효하지 않습니다.`,
      });
    }
    if (item.phase_id && !phaseIds.has(item.phase_id)) {
      add({
        code: "invalid_review_phase_reference",
        message: `${item.review_id}의 Phase reference가 유효하지 않습니다.`,
      });
    }
    if (
      item.step_id &&
      !steps.some((step) => step.step_id === item.step_id)
    ) {
      add({
        code: "invalid_review_step_reference",
        message: `${item.review_id}의 STEP reference가 유효하지 않습니다.`,
      });
    }
    if (item.severity === "blocking" && !isReviewItemResolved(draft, item)) {
      const representedByDerivedRule = [
        "unassigned_phase",
        "part_needs_review",
        "step_needs_review",
      ].includes(item.type);
      if (!representedByDerivedRule) {
        add({
          code: "blocking_review_item",
          message: `${item.review_id}: ${item.message}`,
          partId: item.part_id ?? undefined,
          stepId: item.step_id ?? undefined,
          phaseId: item.phase_id ?? undefined,
          utteranceIds: item.utterance_ids,
        });
      }
    }
    if (item.severity === "warning" && !isReviewItemResolved(draft, item)) {
      add({
        code: `review_${item.type}`,
        severity: "warning",
        message: item.message,
        partId: item.part_id ?? undefined,
        stepId: item.step_id ?? undefined,
        phaseId: item.phase_id ?? undefined,
        utteranceIds: item.utterance_ids,
      });
    }
  });

  const blockingCount = issues.filter(
    (issue) => issue.severity === "blocking",
  ).length;
  const warningCount = issues.filter(
    (issue) => issue.severity === "warning",
  ).length;
  return {
    issues,
    errorCount: blockingCount,
    blockingCount,
    warningCount,
    canPublish: blockingCount === 0,
  };
}
