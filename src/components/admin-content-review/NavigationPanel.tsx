import type { EditorSelection, ReviewDraft } from "@/lib/admin-content-review/types";
import { isReviewItemResolved } from "@/lib/admin-content-review/validation";
import styles from "./AdminContentReview.module.css";

interface NavigationPanelProps {
  draft: ReviewDraft;
  selection: EditorSelection;
  onSelect: (selection: EditorSelection) => void;
  onAddPart: () => void;
  onAddStep: (partId: string) => void;
}

function selected(selection: EditorSelection, kind: EditorSelection["kind"], id?: string) {
  if (selection.kind !== kind) return false;
  if (!id) return true;
  if (selection.kind === "part") return selection.partId === id;
  if (selection.kind === "step") return selection.stepId === id;
  if (selection.kind === "phase" || selection.kind === "unassigned") {
    return selection.phaseId === id;
  }
  return false;
}

export function NavigationPanel({
  draft,
  selection,
  onSelect,
  onAddPart,
  onAddStep,
}: NavigationPanelProps) {
  const blocking = draft.review_queue.filter(
    (item) => item.severity === "blocking" && !isReviewItemResolved(draft, item),
  ).length;
  const warnings = draft.review_queue.filter(
    (item) => item.severity === "warning" && !isReviewItemResolved(draft, item),
  ).length;
  const unresolvedPhases = draft.unassigned_phases.filter(
    (phase) => !phase.excluded_reason?.trim(),
  ).length;

  return (
    <aside className={styles.leftPanel} aria-label="콘텐츠 구조">
      <div className={styles.navScroll}>
        <section className={styles.navSection}>
          <p className={styles.navLabel}>VIDEO</p>
          <button
            className={selected(selection, "video") ? styles.navItemActive : styles.navItem}
            onClick={() => onSelect({ kind: "video" })}
          >
            <span>Video Detail</span>
            <span className={styles.navMeta}>Metadata</span>
          </button>
        </section>

        <section className={styles.navSection}>
          <div className={styles.navSectionHeader}>
            <p className={styles.navLabel}>PARTS</p>
            <button className={styles.smallTextButton} onClick={onAddPart}>
              + 추가
            </button>
          </div>
          <div className={styles.navList}>
            {draft.draft_parts.map((part) => (
              <div key={part.part_id} className={styles.partNavGroup}>
                <button
                  className={selected(selection, "part", part.part_id) ? styles.navItemActive : styles.navItem}
                  onClick={() => onSelect({ kind: "part", partId: part.part_id })}
                >
                  <span className={styles.navTitle}>
                    <strong>{part.part_id}</strong>
                    <small>{part.title || "제목 없음"}</small>
                  </span>
                  {part.needs_review && <span className={styles.warningDot} aria-label="검토 필요" />}
                </button>
                <div className={styles.stepNavList}>
                  {part.steps.map((step) => (
                    <button
                      key={step.step_id}
                      className={selected(selection, "step", step.step_id) ? styles.stepNavActive : styles.stepNav}
                      onClick={() =>
                        onSelect({ kind: "step", partId: part.part_id, stepId: step.step_id })
                      }
                    >
                      <span>{step.step_id.replace(`${part.part_id}-`, "")}</span>
                      <small>{step.action_title || "제목 없음"}</small>
                    </button>
                  ))}
                  <button className={styles.addStepButton} onClick={() => onAddStep(part.part_id)}>
                    + STEP 추가
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.navSection}>
          <div className={styles.navSectionHeader}>
            <p className={styles.navLabel}>UNASSIGNED PHASES</p>
            <span className={unresolvedPhases ? styles.blockingBadge : styles.countBadge}>
              {unresolvedPhases}
            </span>
          </div>
          {draft.unassigned_phases.map((phase) => (
            <button
              key={phase.phase_id}
              className={selected(selection, "unassigned", phase.phase_id) ? styles.navItemActive : styles.navItem}
              onClick={() => onSelect({ kind: "unassigned", phaseId: phase.phase_id })}
            >
              <span className={styles.navTitle}>
                <strong>{phase.phase_id}</strong>
                <small>{phase.phase_label}</small>
              </span>
              {phase.excluded_reason ? (
                <span className={styles.resolvedBadge}>제외됨</span>
              ) : (
                <span className={styles.warningDot} aria-label="미해결" />
              )}
            </button>
          ))}
        </section>

        <section className={styles.navSection}>
          <button
            className={selected(selection, "review") ? styles.navSummaryActive : styles.navSummary}
            onClick={() => onSelect({ kind: "review" })}
          >
            <span>Review Queue</span>
            <span className={styles.navBadges}>
              <span className={styles.blockingBadge}>{blocking}</span>
              <span className={styles.warningBadge}>{warnings}</span>
            </span>
          </button>
          <button
            className={selected(selection, "script") ? styles.navSummaryActive : styles.navSummary}
            onClick={() => onSelect({ kind: "script" })}
          >
            <span>Source Script</span>
            <span className={styles.countBadge}>{draft.script.length}</span>
          </button>
        </section>
      </div>
    </aside>
  );
}
