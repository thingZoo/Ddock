"use client";

import { useEffect, useRef, useState } from "react";
import { addPart, addStep, cloneDraft, syncDerivedFields, toggleEvidence } from "@/lib/admin-content-review/operations";
import { downloadJson } from "@/lib/admin-content-review/download";
import { parseReviewDraftText, ReviewImportError } from "@/lib/admin-content-review/guards";
import {
  injectGeneratedDraft,
  generatedDraftSummary,
  parsePreprocessedInputText,
  requestLocalDraft,
  type LocalGenerationStage,
  type PreprocessedInput,
} from "@/lib/admin-content-review/local-ai";
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

const generationLabels: Record<LocalGenerationStage, string> = {
  idle: "로컬 AI 초안 생성",
  preparing: "초안 준비 중",
  classifying: "작업 기준점 찾는 중",
  composing: "PART 구성 중",
  repairing_composition: "PART 경계 보정 중",
  writing_steps: "STEP 작성 중",
  repairing_steps: "누락된 STEP 보정 중",
  finalizing: "초안 정리 중",
  complete: "생성 완료",
};

function formatElapsed(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function EmptyImport({
  restored,
  preprocessed,
  generationStage,
  elapsedSeconds,
  onRestore,
  onReviewImport,
  onPreprocessedImport,
  onGenerate,
}: {
  restored: ReviewDraft | null;
  preprocessed: PreprocessedInput | null;
  generationStage: LocalGenerationStage;
  elapsedSeconds: number;
  onRestore: () => void;
  onReviewImport: () => void;
  onPreprocessedImport: () => void;
  onGenerate: () => void;
}) {
  const generating = !["idle", "complete"].includes(generationStage);
  return (
    <main className={styles.emptyRoot}>
      <section className={styles.emptyImport}>
        <span className={styles.brandMark}>D:ock 관리자</span>
        <p className={styles.eyebrow}>콘텐츠 검수</p>
        <h1>AI 초안을 검수하고<br />발행 파일을 만드세요.</h1>
        <p>전처리 JSON에서 로컬 AI 초안을 만들거나, 기존 <code>ddock_content_review_v0.1</code> 파일을 불러오세요.</p>
        {preprocessed && (
          <div className={styles.localAiReady}>
            <span>전처리 JSON 준비됨</span>
            <strong>{preprocessed.video_id}</strong>
            <small>{preprocessed.normalized_utterances.length}개 발화 · API 비용 없음</small>
          </div>
        )}
        <div className={styles.emptyActions}>
          <button className={styles.primaryButton} onClick={onPreprocessedImport}>전처리 JSON 불러오기</button>
          {preprocessed && (
            <button className={styles.localAiButton} disabled={generating} onClick={onGenerate}>
              {generating ? `${generationLabels[generationStage]} · ${formatElapsed(elapsedSeconds)}` : "로컬 AI 초안 생성"}
            </button>
          )}
          <button className={styles.secondaryButton} onClick={onReviewImport}>Review JSON 불러오기</button>
          {restored && <button className={styles.secondaryButton} onClick={onRestore}>마지막 자동 저장 복원 · {restored.source.video_id}</button>}
        </div>
      </section>
    </main>
  );
}

export function AdminContentReview() {
  const reviewInputRef = useRef<HTMLInputElement>(null);
  const preprocessingInputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [preprocessed, setPreprocessed] = useState<PreprocessedInput | null>(null);
  const [restored, setRestored] = useState<ReviewDraft | null>(null);
  const [selection, setSelection] = useState<EditorSelection>({ kind: "video" });
  const [rightTab, setRightTab] = useState<RightPanelTab>("source");
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [importError, setImportError] = useState<string | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [generationStage, setGenerationStage] = useState<LocalGenerationStage>("idle");
  const [generationStartedAt, setGenerationStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [generationError, setGenerationError] = useState<string | null>(null);

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

  useEffect(() => {
    if (generationStartedAt === null) return;
    const update = () => setElapsedSeconds(Math.floor((Date.now() - generationStartedAt) / 1000));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [generationStartedAt]);

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
      if (reviewInputRef.current) reviewInputRef.current.value = "";
    }
  };
  const importPreprocessedFile = async (file?: File) => {
    if (!file) return;
    try {
      setPreprocessed(parsePreprocessedInputText(await file.text()));
      setImportError(null);
      setGenerationError(null);
      setGenerationStage("idle");
    } catch (error) {
      setImportError(error instanceof ReviewImportError ? error.message : "전처리 JSON을 읽을 수 없습니다.");
    } finally {
      if (preprocessingInputRef.current) preprocessingInputRef.current.value = "";
    }
  };
  const generateLocalDraft = async () => {
    if (!preprocessed || !["idle", "complete"].includes(generationStage)) return;
    setGenerationStage("preparing");
    setGenerationStartedAt(Date.now());
    setElapsedSeconds(0);
    setGenerationError(null);
    try {
      const generated = await requestLocalDraft(preprocessed, (progress) => {
        setGenerationStage(progress.stage);
      });
      setDraft(injectGeneratedDraft(generated));
      setSelection({ kind: "video" });
      setReport(null);
      setSaveState("dirty");
      setGenerationStage("complete");
    } catch (error) {
      setGenerationError(error instanceof Error ? error.message : "로컬 AI 생성에 실패했습니다.");
      setGenerationStage("idle");
    } finally {
      setGenerationStartedAt(null);
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
        <input ref={reviewInputRef} hidden type="file" accept="application/json,.json" onChange={(event) => void importFile(event.target.files?.[0])} />
        <input ref={preprocessingInputRef} hidden type="file" accept="application/json,.json" onChange={(event) => void importPreprocessedFile(event.target.files?.[0])} />
        <EmptyImport
          restored={restored}
          preprocessed={preprocessed}
          generationStage={generationStage}
          elapsedSeconds={elapsedSeconds}
          onRestore={() => { if (restored) { setDraft(restored); setSaveState("saved"); } }}
          onReviewImport={() => reviewInputRef.current?.click()}
          onPreprocessedImport={() => preprocessingInputRef.current?.click()}
          onGenerate={() => void generateLocalDraft()}
        />
        {importError && <div className={styles.importToast} role="alert"><strong>불러오기 실패</strong><span>{importError}</span><button onClick={() => setImportError(null)}>닫기</button></div>}
        {generationError && <div className={styles.importToast} role="alert"><strong>생성 실패</strong><span>{generationError}</span><button onClick={() => setGenerationError(null)}>닫기</button></div>}
      </>
    );
  }

  const preview = toPublishedCandidate(draft);
  const generatedSummary = generatedDraftSummary(draft);
  return (
    <div className={styles.adminRoot}>
      <input ref={reviewInputRef} hidden type="file" accept="application/json,.json" onChange={(event) => void importFile(event.target.files?.[0])} />
      <input ref={preprocessingInputRef} hidden type="file" accept="application/json,.json" onChange={(event) => void importPreprocessedFile(event.target.files?.[0])} />
      <header className={styles.topBar}>
        <div className={styles.brandBlock}><strong>D:ock</strong><span>관리자 콘텐츠 검수</span></div>
        <div className={styles.documentIdentity}><b>{draft.source.title ?? "제목 없는 영상"}</b><span>{draft.source.video_id} · <code>{draft.schema_version}</code></span></div>
        <div className={styles.headerActions}>
          <span className={styles.saveState} data-state={saveState}><i />{saveState === "saved" ? "저장됨" : saveState === "saving" ? "저장 중…" : "변경사항 있음"}</span>
          <button className={styles.headerButton} onClick={() => preprocessingInputRef.current?.click()}>전처리 JSON 불러오기</button>
          <button className={styles.headerButton} onClick={() => reviewInputRef.current?.click()}>Review JSON 불러오기</button>
          {preprocessed && (
            <button className={styles.localAiHeaderButton} disabled={generationStartedAt !== null} onClick={() => void generateLocalDraft()}>
              {generationStartedAt !== null ? `${generationLabels[generationStage]} · ${formatElapsed(elapsedSeconds)}` : "로컬 AI 초안 생성"}
            </button>
          )}
          <button className={styles.headerButton} onClick={() => downloadJson(draftFilename(draft.source.video_id), draft)}>초안 내보내기</button>
          <button className={styles.headerButton} onClick={validate}>발행 전 검사</button>
          <button className={styles.headerButton} onClick={() => setShowPreview(true)}>미리보기</button>
          <button className={styles.publishButton} onClick={publish}>발행 파일 만들기</button>
        </div>
      </header>

      {(generationStartedAt !== null || generationStage === "complete") && (
        <section className={styles.localAiStatus} aria-live="polite">
          <span className={styles.eyebrow}>Local MLX Qwen · API 비용 없음</span>
          <strong>{generationStage === "complete" ? generatedSummary.label : generationLabels[generationStage]}</strong>
          <small>{generationStartedAt !== null ? `경과 시간 ${formatElapsed(elapsedSeconds)}` : `PART ${generatedSummary.partCount} · STEP ${generatedSummary.stepCount} · 필수 확인 ${generatedSummary.blockingCount}`}</small>
        </section>
      )}

      {report && (
        <section className={report.canPublish ? styles.validationSuccess : styles.validationPanel} aria-label="검사 결과">
          <div className={styles.validationSummary}>
            <span className={styles.eyebrow}>발행 전 검사</span>
            <strong>{report.canPublish ? "발행 준비 완료" : `${report.blockingCount}개 필수 확인 · ${report.warningCount}개 주의`}</strong>
            <small>최종 발행 검증 기준은 Python validator입니다.</small>
          </div>
          <div className={styles.validationIssues}>
            {report.issues.slice(0, 8).map((issue) => (
              <button key={issue.id} onClick={() => choose(issueSelection(issue))}>
                <span>{issue.severity === "blocking" ? "필수 확인" : "주의"}</span><b>검사 항목</b><small>{issue.message}</small>
              </button>
            ))}
          </div>
          <button className={styles.iconButton} onClick={() => setReport(null)} aria-label="검사 결과 닫기">×</button>
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
      {importError && <div className={styles.importToast} role="alert"><strong>불러오기 실패</strong><span>{importError}</span><button onClick={() => setImportError(null)}>닫기</button></div>}
      {generationError && <div className={styles.importToast} role="alert"><strong>생성 실패</strong><span>{generationError}</span><button onClick={() => setGenerationError(null)}>닫기</button></div>}
      {showPreview && <PreviewDialog content={preview} onClose={() => setShowPreview(false)} />}
    </div>
  );
}
