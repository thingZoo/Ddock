"use client";

import { useEffect, useRef, useState } from "react";
import { addPart, addStep, cloneDraft, syncDerivedFields, toggleEvidence } from "@/lib/admin-content-review/operations";
import { downloadJson } from "@/lib/admin-content-review/download";
import { parseReviewDraftText, ReviewImportError } from "@/lib/admin-content-review/guards";
import { draftFilename, publishedFilename, toPublishedCandidate } from "@/lib/admin-content-review/publish";
import { loadLastReviewDraft, savePublishedPreview, saveReviewDraft } from "@/lib/admin-content-review/storage";
import type { EditorSelection, EvidenceMode, ReviewDraft, ValidationIssue, ValidationReport } from "@/lib/admin-content-review/types";
import { validateReviewDraft } from "@/lib/admin-content-review/validation";
import { EditorPanel, type DraftMutator } from "./EditorPanel";
import { NavigationPanel } from "./NavigationPanel";
import { PreviewDialog } from "./PreviewDialog";
import { SourceReviewPanel, type QueueFilter, type RightPanelTab } from "./SourceReviewPanel";
import styles from "./AdminContentReview.module.css";

type SaveState = "saved" | "saving" | "dirty";

function issueSelection(issue: ValidationIssue): EditorSelection {
  if (issue.stepId && issue.partId) return { kind: "step", partId: issue.partId, stepId: issue.stepId };
  if (issue.partId) return { kind: "part", partId: issue.partId };
  if (issue.phaseId) return { kind: "unassigned", phaseId: issue.phaseId };
  return { kind: "review", reviewId: issue.id };
}

function EmptyImport({ restored, onRestore, onImport }: { restored: ReviewDraft | null; onRestore: () => void; onImport: () => void }) {
  return (
    <main className={styles.emptyRoot}>
      <section className={styles.emptyImport}>
        <span className={styles.brandMark}>D:ock</span>
        <p className={styles.eyebrow}>ADMIN CONTENT REVIEW</p>
        <h1>AI draft를 검수하고<br />발행 후보를 만드세요.</h1>
        <p>지원 형식은 <code>ddock_content_review_v0.1</code> JSON입니다. 파일은 브라우저에서만 읽습니다.</p>
        <div className={styles.emptyActions}>
          <button className={styles.primaryButton} onClick={onImport}>Review JSON 가져오기</button>
          {restored && <button className={styles.secondaryButton} onClick={onRestore}>마지막 autosave 복원 · {restored.source.video_id}</button>}
        </div>
      </section>
    </main>
  );
}

export function AdminContentReview() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [restored, setRestored] = useState<ReviewDraft | null>(null);
  const [selection, setSelection] = useState<EditorSelection>({ kind: "video" });
  const [rightTab, setRightTab] = useState<RightPanelTab>("source");
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [importError, setImportError] = useState<string | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { setRestored(loadLastReviewDraft(window.localStorage)); } catch { setRestored(null); }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!draft) return;
    let saveFrame = 0;
    const timer = window.setTimeout(() => {
      setSaveState("saving");
      saveFrame = window.requestAnimationFrame(() => {
        saveReviewDraft(window.localStorage, draft);
        setSaveState("saved");
      });
    }, 500);
    return () => {
      window.clearTimeout(timer);
      window.cancelAnimationFrame(saveFrame);
    };
  }, [draft]);

  const replace = (next: ReviewDraft) => {
    setDraft(syncDerivedFields(next));
    setSaveState("dirty");
    setReport(null);
  };
  const mutate: DraftMutator = (mutator) => {
    if (!draft) return;
    const next = cloneDraft(draft);
    mutator(next);
    replace(next);
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    try {
      const imported = parseReviewDraftText(await file.text());
      setDraft(syncDerivedFields(imported));
      setSelection({ kind: "video" });
      setImportError(null);
      setReport(null);
      setSaveState("dirty");
    } catch (error) {
      setImportError(error instanceof ReviewImportError ? error.message : "Review JSON을 읽을 수 없습니다.");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  };
  const validate = () => {
    if (!draft) return null;
    const nextReport = validateReviewDraft(draft);
    setReport(nextReport);
    return nextReport;
  };
  const publish = () => {
    if (!draft) return;
    const nextReport = validate();
    if (!nextReport?.canPublish) return;
    const candidate = toPublishedCandidate(draft);
    savePublishedPreview(window.localStorage, candidate);
    downloadJson(publishedFilename(draft.source.video_id), candidate);
  };
  const choose = (next: EditorSelection) => {
    setSelection(next);
    setEvidenceMode(null);
    if (next.kind === "review") setRightTab("queue");
    if (next.kind === "script") setRightTab("source");
    if (next.kind === "phase" || next.kind === "unassigned") setRightTab("phases");
  };

  if (!draft) {
    return (
      <>
        <input ref={inputRef} hidden type="file" accept="application/json,.json" onChange={(event) => void importFile(event.target.files?.[0])} />
        <EmptyImport restored={restored} onRestore={() => { if (restored) { setDraft(restored); setSaveState("saved"); } }} onImport={() => inputRef.current?.click()} />
        {importError && <div className={styles.importToast} role="alert"><strong>Import 실패</strong><span>{importError}</span><button onClick={() => setImportError(null)}>닫기</button></div>}
      </>
    );
  }

  const preview = toPublishedCandidate(draft);
  return (
    <div className={styles.adminRoot}>
      <input ref={inputRef} hidden type="file" accept="application/json,.json" onChange={(event) => void importFile(event.target.files?.[0])} />
      <header className={styles.topBar}>
        <div className={styles.brandBlock}><strong>D:ock</strong><span>Admin Content Review</span></div>
        <div className={styles.documentIdentity}><b>{draft.source.title ?? "Untitled video"}</b><span>{draft.source.video_id} · <code>{draft.schema_version}</code></span></div>
        <div className={styles.headerActions}>
          <span className={styles.saveState} data-state={saveState}><i />{saveState === "saved" ? "Saved" : saveState === "saving" ? "Saving…" : "Unsaved"}</span>
          <button className={styles.headerButton} onClick={() => inputRef.current?.click()}>Import</button>
          <button className={styles.headerButton} onClick={() => downloadJson(draftFilename(draft.source.video_id), draft)}>Export Draft</button>
          <button className={styles.headerButton} onClick={validate}>Validate</button>
          <button className={styles.headerButton} onClick={() => setShowPreview(true)}>Admin Preview</button>
          <button className={styles.publishButton} onClick={publish}>Publish Candidate</button>
        </div>
      </header>

      {report && (
        <section className={report.canPublish ? styles.validationSuccess : styles.validationPanel} aria-label="Preflight 결과">
          <div className={styles.validationSummary}>
            <span className={styles.eyebrow}>BROWSER PREFLIGHT</span>
            <strong>{report.canPublish ? "Publish candidate 생성 가능" : `${report.blockingCount} blocking · ${report.warningCount} warning`}</strong>
            <small>Python publish validator가 canonical source of truth입니다.</small>
          </div>
          <div className={styles.validationIssues}>
            {report.issues.slice(0, 8).map((issue) => (
              <button key={issue.id} onClick={() => choose(issueSelection(issue))}>
                <span>{issue.severity}</span><b>{issue.code}</b><small>{issue.message}</small>
              </button>
            ))}
          </div>
          <button className={styles.iconButton} onClick={() => setReport(null)} aria-label="Validation 결과 닫기">×</button>
        </section>
      )}

      <div className={styles.workspace}>
        <NavigationPanel
          draft={draft}
          selection={selection}
          onSelect={choose}
          onAddPart={() => { const next = addPart(draft); replace(next); const part = next.draft_parts.at(-1); if (part) choose({ kind: "part", partId: part.part_id }); }}
          onAddStep={(partId) => { const next = addStep(draft, partId); replace(next); const step = next.draft_parts.find((part) => part.part_id === partId)?.steps.at(-1); if (step) choose({ kind: "step", partId, stepId: step.step_id }); }}
        />
        <EditorPanel key={JSON.stringify(selection)} draft={draft} selection={selection} mutate={mutate} replace={replace} onSelect={choose} onEvidenceMode={(mode) => { setEvidenceMode(mode); setRightTab("source"); }} />
        <SourceReviewPanel
          draft={draft}
          selection={selection}
          tab={rightTab}
          queueFilter={queueFilter}
          evidenceMode={evidenceMode}
          onTabChange={setRightTab}
          onQueueFilterChange={setQueueFilter}
          onSelect={choose}
          onEvidenceToggle={(utteranceId) => { if (evidenceMode) replace(toggleEvidence(draft, evidenceMode, utteranceId)); }}
          onEvidenceModeClose={() => setEvidenceMode(null)}
        />
      </div>
      {importError && <div className={styles.importToast} role="alert"><strong>Import 실패</strong><span>{importError}</span><button onClick={() => setImportError(null)}>닫기</button></div>}
      {showPreview && <PreviewDialog content={preview} onClose={() => setShowPreview(false)} />}
    </div>
  );
}
