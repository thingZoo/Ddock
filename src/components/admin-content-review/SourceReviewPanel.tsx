import { isReviewItemResolved } from "@/lib/admin-content-review/validation";
import type {
  EditorSelection,
  EvidenceMode,
  ReviewDraft,
  ReviewQueueItem,
} from "@/lib/admin-content-review/types";
import styles from "./AdminContentReview.module.css";

export type RightPanelTab = "source" | "queue" | "phases";
export type QueueFilter = "all" | "blocking" | "warning";

interface SourceReviewPanelProps {
  draft: ReviewDraft;
  selection: EditorSelection;
  tab: RightPanelTab;
  queueFilter: QueueFilter;
  evidenceMode: EvidenceMode;
  onTabChange: (tab: RightPanelTab) => void;
  onQueueFilterChange: (filter: QueueFilter) => void;
  onSelect: (selection: EditorSelection) => void;
  onEvidenceToggle: (utteranceId: string) => void;
  onEvidenceModeClose: () => void;
}

function reviewTarget(item: ReviewQueueItem): EditorSelection {
  if (item.step_id && item.part_id) {
    return { kind: "step", partId: item.part_id, stepId: item.step_id };
  }
  if (item.part_id) return { kind: "part", partId: item.part_id };
  if (item.phase_id) return { kind: "phase", phaseId: item.phase_id };
  return { kind: "review", reviewId: item.review_id };
}

function evidenceContext(draft: ReviewDraft, mode: Exclude<EvidenceMode, null>) {
  const part = draft.draft_parts.find((value) => value.part_id === mode.partId);
  const step = part?.steps.find((value) => value.step_id === mode.stepId);
  if (!part || !step) return { allowed: new Set<string>(), selected: new Set<string>() };
  const allowed = new Set(
    mode.kind === "step" ? part.action_utterance_ids : part.source_utterance_ids,
  );
  const selected = new Set(
    mode.kind === "step"
      ? step.source_utterance_ids
      : mode.kind === "prompt"
        ? step.prompt?.evidence.map((value) => value.utterance_id) ?? []
        : mode.kind === "warning"
          ? step.warning?.evidence.map((value) => value.utterance_id) ?? []
          : step.learn_more[mode.index]?.evidence.map((value) => value.utterance_id) ?? [],
  );
  return { allowed, selected };
}

function selectedRows(draft: ReviewDraft, selection: EditorSelection) {
  const primary = new Set<string>();
  const context = new Set<string>();
  if (selection.kind === "part") {
    draft.draft_parts
      .find((part) => part.part_id === selection.partId)
      ?.source_utterance_ids.forEach((id) => primary.add(id));
  } else if (selection.kind === "step") {
    draft.draft_parts
      .find((part) => part.part_id === selection.partId)
      ?.steps.find((step) => step.step_id === selection.stepId)
      ?.source_utterance_ids.forEach((id) => primary.add(id));
  } else if (selection.kind === "phase" || selection.kind === "unassigned") {
    const phase = draft.action_phases.find((value) => value.phase_id === selection.phaseId);
    phase?.action_utterance_ids.forEach((id) => primary.add(id));
    phase?.context_utterance_ids.forEach((id) => context.add(id));
  }
  return { primary, context };
}

export function SourceReviewPanel({
  draft,
  selection,
  tab,
  queueFilter,
  evidenceMode,
  onTabChange,
  onQueueFilterChange,
  onSelect,
  onEvidenceToggle,
  onEvidenceModeClose,
}: SourceReviewPanelProps) {
  const highlighted = selectedRows(draft, selection);
  const picker = evidenceMode ? evidenceContext(draft, evidenceMode) : null;
  const chapterMap = new Map(
    draft.script_chapters.map((chapter) => [chapter.chapter_id, chapter]),
  );
  const queue = draft.review_queue.filter(
    (item) => queueFilter === "all" || item.severity === queueFilter,
  );

  return (
    <aside className={styles.rightPanel} aria-label="Source evidence와 review">
      <div className={styles.rightTabs} role="tablist" aria-label="검수 자료">
        {(["source", "queue", "phases"] as const).map((value) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            className={tab === value ? styles.rightTabActive : styles.rightTab}
            onClick={() => onTabChange(value)}
          >
            {value === "source" ? "Source" : value === "queue" ? "Queue" : "Phases"}
          </button>
        ))}
      </div>

      {tab === "source" && (
        <div className={styles.rightContent}>
          {evidenceMode && (
            <div className={styles.evidenceModeBar}>
              <div>
                <strong>Evidence 선택 모드</strong>
                <span>{evidenceMode.kind.replace("_", " ")}</span>
              </div>
              <button onClick={onEvidenceModeClose}>완료</button>
            </div>
          )}
          <div className={styles.scriptList}>
            {draft.script.map((row, index) => {
              const previousChapter = draft.script[index - 1]?.script_chapter_id;
              const showChapter = row.script_chapter_id !== previousChapter;
              const isPrimary = highlighted.primary.has(row.utterance_id);
              const isContext = highlighted.context.has(row.utterance_id);
              const canPick = Boolean(picker?.allowed.has(row.utterance_id));
              const isPicked = Boolean(picker?.selected.has(row.utterance_id));
              return (
                <div key={row.utterance_id}>
                  {showChapter && (
                    <div className={styles.chapterHeader}>
                      <span>{row.script_chapter_id ?? "NO CHAPTER"}</span>
                      <strong>
                        {row.script_chapter_id
                          ? chapterMap.get(row.script_chapter_id)?.title
                          : "Unassigned script"}
                      </strong>
                    </div>
                  )}
                  <label
                    className={`${styles.scriptRow} ${isPrimary ? styles.scriptRowPrimary : ""} ${isContext ? styles.scriptRowContext : ""} ${isPicked ? styles.scriptRowPicked : ""}`}
                  >
                    {evidenceMode && (
                      <input
                        type="checkbox"
                        checked={isPicked}
                        disabled={!canPick}
                        onChange={() => onEvidenceToggle(row.utterance_id)}
                        aria-label={`${row.utterance_id} evidence 선택`}
                      />
                    )}
                    <span className={styles.scriptTime}>{row.timestamp}</span>
                    <span className={styles.scriptBody}>
                      <span>{row.text}</span>
                      <small>
                        {row.utterance_id}
                        {row.catchup_part_ids.length
                          ? ` · ${row.catchup_part_ids.join(", ")}`
                          : ""}
                      </small>
                    </span>
                  </label>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {tab === "queue" && (
        <div className={styles.rightContent}>
          <div className={styles.filterRow}>
            {(["all", "blocking", "warning"] as const).map((value) => (
              <button
                key={value}
                className={queueFilter === value ? styles.filterActive : styles.filterButton}
                onClick={() => onQueueFilterChange(value)}
              >
                {value === "all" ? "전체" : value === "blocking" ? "Blocking" : "Warning"}
              </button>
            ))}
          </div>
          <div className={styles.queueList}>
            {queue.map((item) => {
              const resolved = isReviewItemResolved(draft, item);
              return (
                <button
                  key={item.review_id}
                  className={`${styles.queueCard} ${item.severity === "blocking" ? styles.queueBlocking : styles.queueWarning}`}
                  onClick={() => onSelect(reviewTarget(item))}
                >
                  <span className={styles.queueCardTop}>
                    <strong>{item.type}</strong>
                    <span>{resolved ? "Resolved" : item.severity}</span>
                  </span>
                  <span className={styles.queueMessage}>{item.message}</span>
                  <small>
                    {[item.part_id, item.phase_id, item.step_id].filter(Boolean).join(" · ") || item.review_id}
                  </small>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {tab === "phases" && (
        <div className={styles.rightContent}>
          <div className={styles.phaseList}>
            {draft.action_phases.map((phase) => {
              const excluded = draft.unassigned_phases.find(
                (item) => item.phase_id === phase.phase_id,
              )?.excluded_reason;
              const state = phase.assigned_part_id ?? (excluded ? "제외됨" : "미배치");
              return (
                <button
                  key={phase.phase_id}
                  className={styles.phaseCard}
                  onClick={() => onSelect({ kind: "phase", phaseId: phase.phase_id })}
                >
                  <span className={styles.phaseCardTop}>
                    <strong>{phase.phase_id}</strong>
                    <span className={phase.assigned_part_id || excluded ? styles.resolvedBadge : styles.blockingBadge}>
                      {state}
                    </span>
                  </span>
                  <b>{phase.phase_label}</b>
                  <span>{phase.operation}</span>
                  <small>
                    action {phase.action_utterance_ids.length} · context {phase.context_utterance_ids.length}
                  </small>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </aside>
  );
}
