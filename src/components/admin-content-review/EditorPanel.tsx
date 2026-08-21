import { useState } from "react";
import {
  assignPhaseToPart,
  createPartFromPhase,
  deletePart,
  deleteStep,
  excludePhase,
  mergeParts,
  reorderPart,
  reorderStep,
  splitPartAtStep,
} from "@/lib/admin-content-review/operations";
import type {
  EditorSelection,
  EvidenceMode,
  DraftStep,
  ReviewDraft,
  RichSegmentType,
} from "@/lib/admin-content-review/types";
import { isReviewItemResolved } from "@/lib/admin-content-review/validation";
import styles from "./AdminContentReview.module.css";

export type DraftMutator = (mutator: (draft: ReviewDraft) => void) => void;

interface EditorPanelProps {
  draft: ReviewDraft;
  selection: EditorSelection;
  mutate: DraftMutator;
  replace: (draft: ReviewDraft) => void;
  onSelect: (selection: EditorSelection) => void;
  onEvidenceMode: (mode: Exclude<EvidenceMode, null>) => void;
}

function Field({
  label,
  value,
  onChange,
  multiline = false,
  helper,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  helper?: string;
}) {
  const id = `field-${label.replace(/\s+/g, "-")}`;
  return (
    <label className={styles.field} htmlFor={id}>
      <span>{label}</span>
      {multiline ? (
        <textarea id={id} value={value} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input id={id} value={value} onChange={(event) => onChange(event.target.value)} />
      )}
      {helper && <small>{helper}</small>}
    </label>
  );
}

function SectionTitle({ title, description }: { title: string; description?: string }) {
  return (
    <div className={styles.sectionTitle}>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
  );
}

function EvidenceChips({ ids }: { ids: string[] }) {
  if (!ids.length) return <span className={styles.emptyInline}>Evidence 없음</span>;
  return (
    <div className={styles.chipList}>
      {ids.map((id) => (
        <span key={id} className={styles.evidenceChip}>{id}</span>
      ))}
    </div>
  );
}

function VideoDetailEditor({ draft, mutate }: { draft: ReviewDraft; mutate: DraftMutator }) {
  const recommendation = draft.video_detail.recommendation;
  return (
    <div className={styles.editorStack}>
      <SectionTitle
        title="Video Detail"
        description="사용자 상세 화면에 노출될 recommendation, tools, tags를 검수합니다."
      />
      <section className={styles.editorCard}>
        <div className={styles.cardHeader}>
          <div><span className={styles.eyebrow}>RECOMMENDATION</span><h3>추천 문구</h3></div>
          {!recommendation && (
            <button
              className={styles.secondaryButton}
              onClick={() =>
                mutate((next) => {
                  next.video_detail.recommendation = {
                    eyebrow: "추천해요",
                    title: "",
                    body: "",
                    claims: [],
                    evidence: [],
                  };
                })
              }
            >
              + Recommendation
            </button>
          )}
        </div>
        {recommendation ? (
          <div className={styles.formGrid}>
            <Field label="Eyebrow" value={recommendation.eyebrow} onChange={(value) => mutate((next) => { next.video_detail.recommendation!.eyebrow = value; })} />
            <Field label="Title" value={recommendation.title} onChange={(value) => mutate((next) => { next.video_detail.recommendation!.title = value; })} />
            <div className={styles.fullField}>
              <Field label="Body" multiline value={recommendation.body} onChange={(value) => mutate((next) => { next.video_detail.recommendation!.body = value; })} />
            </div>
            <details className={`${styles.details} ${styles.fullField}`}>
              <summary>Claim evidence {recommendation.claims.length}개</summary>
              {recommendation.claims.map((claim, index) => (
                <div key={`${claim.text}-${index}`} className={styles.claimRow}>
                  <p>{claim.text}</p>
                  <EvidenceChips ids={claim.evidence.map((item) => item.utterance_id)} />
                </div>
              ))}
            </details>
          </div>
        ) : (
          <p className={styles.emptyMessage}>Recommendation이 없습니다.</p>
        )}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}>
          <div><span className={styles.eyebrow}>TOOLS</span><h3>도구</h3></div>
          <button
            className={styles.secondaryButton}
            onClick={() =>
              mutate((next) => {
                next.video_detail.tools.push({
                  name: "",
                  canonical_name: "",
                  url: null,
                  description: "",
                  evidence: [],
                });
              })
            }
          >
            + 도구
          </button>
        </div>
        <div className={styles.toolList}>
          {draft.video_detail.tools.map((tool, index) => (
            <div className={styles.nestedCard} key={`${tool.canonical_name}-${index}`}>
              <div className={styles.formGrid}>
                <Field label="Name" value={tool.name} onChange={(value) => mutate((next) => { next.video_detail.tools[index].name = value; })} />
                <Field label="Canonical name" value={tool.canonical_name} onChange={(value) => mutate((next) => { next.video_detail.tools[index].canonical_name = value; })} />
                <Field label="URL" value={tool.url ?? ""} onChange={(value) => mutate((next) => { next.video_detail.tools[index].url = value || null; })} />
                <Field label="Description" value={tool.description} onChange={(value) => mutate((next) => { next.video_detail.tools[index].description = value; })} />
              </div>
              <div className={styles.inlineMeta}>
                <EvidenceChips ids={tool.evidence.map((item) => item.utterance_id)} />
                <button className={styles.dangerTextButton} onClick={() => mutate((next) => { next.video_detail.tools.splice(index, 1); })}>삭제</button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.editorCard}>
        <span className={styles.eyebrow}>TAGS</span>
        <Field
          label="쉼표로 구분"
          value={draft.video_detail.tags.join(", ")}
          onChange={(value) =>
            mutate((next) => {
              next.video_detail.tags = value.split(",").map((item) => item.trim()).filter(Boolean);
            })
          }
        />
      </section>
    </div>
  );
}

function PartEditor({
  draft,
  partId,
  mutate,
  replace,
  onSelect,
}: {
  draft: ReviewDraft;
  partId: string;
  mutate: DraftMutator;
  replace: (draft: ReviewDraft) => void;
  onSelect: (selection: EditorSelection) => void;
}) {
  const part = draft.draft_parts.find((value) => value.part_id === partId);
  if (!part) return <MissingEditor />;
  const index = draft.draft_parts.findIndex((value) => value.part_id === partId);
  const previous = draft.draft_parts[index - 1];
  const nextPart = draft.draft_parts[index + 1];
  return (
    <div className={styles.editorStack}>
      <SectionTitle title={`${part.part_id} · PART Editor`} description="PART ID와 provenance는 유지하고 사용자 목적 문구를 정리합니다." />
      <section className={styles.editorCard}>
        <div className={styles.entityHeader}>
          <div>
            <span className={styles.entityId}>{part.part_id}</span>
            <p>Order {part.order} · {part.start_timestamp}–{part.end_timestamp}</p>
          </div>
          <label className={styles.reviewToggle}>
            <input type="checkbox" checked={part.needs_review} onChange={(event) => mutate((value) => { value.draft_parts.find((item) => item.part_id === partId)!.needs_review = event.target.checked; })} />
            needs review
          </label>
        </div>
        <div className={styles.formStack}>
          <Field label="Title" value={part.title} onChange={(value) => mutate((next) => { next.draft_parts.find((item) => item.part_id === partId)!.title = value; })} />
          <Field label="Summary" multiline value={part.summary ?? ""} onChange={(value) => mutate((next) => { next.draft_parts.find((item) => item.part_id === partId)!.summary = value || null; })} />
          <Field label="Action objective" multiline value={part.action_objective} onChange={(value) => mutate((next) => { next.draft_parts.find((item) => item.part_id === partId)!.action_objective = value; })} />
        </div>
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVENANCE</span><h3>Source membership</h3></div></div>
        <dl className={styles.definitionGrid}>
          <div><dt>Script chapters</dt><dd>{part.source_script_chapter_ids.join(", ") || "—"}</dd></div>
          <div><dt>Thumbnail</dt><dd>{part.thumbnail?.relative_path ?? "Uncertain"}</dd></div>
          <div><dt>Source rows</dt><dd>{part.source_utterance_ids.length}</dd></div>
          <div><dt>Action rows</dt><dd>{part.action_utterance_ids.length}</dd></div>
        </dl>
        <EvidenceChips ids={part.source_utterance_ids} />
        {part.review_reasons.length > 0 && (
          <div className={styles.reasonList}>{part.review_reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
        )}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>OPERATIONS</span><h3>PART 구조</h3></div></div>
        <div className={styles.actionRow}>
          <button className={styles.secondaryButton} disabled={!previous} onClick={() => replace(reorderPart(draft, partId, -1))}>↑ 위로</button>
          <button className={styles.secondaryButton} disabled={!nextPart} onClick={() => replace(reorderPart(draft, partId, 1))}>↓ 아래로</button>
          <button className={styles.secondaryButton} disabled={!previous} onClick={() => previous && replace(mergeParts(draft, previous.part_id, partId))}>이전과 병합</button>
          <button className={styles.secondaryButton} disabled={!nextPart} onClick={() => nextPart && replace(mergeParts(draft, partId, nextPart.part_id))}>다음과 병합</button>
          <button
            className={styles.dangerButton}
            onClick={() => {
              if (!window.confirm(`${partId}를 삭제할까요? 연결된 phase는 unassigned로 이동합니다.`)) return;
              const fallback = previous?.part_id ?? nextPart?.part_id;
              replace(deletePart(draft, partId));
              onSelect(fallback ? { kind: "part", partId: fallback } : { kind: "video" });
            }}
          >
            PART 삭제
          </button>
        </div>
      </section>
    </div>
  );
}

function StepEditor({
  draft,
  partId,
  stepId,
  mutate,
  replace,
  onSelect,
  onEvidenceMode,
}: {
  draft: ReviewDraft;
  partId: string;
  stepId: string;
  mutate: DraftMutator;
  replace: (draft: ReviewDraft) => void;
  onSelect: (selection: EditorSelection) => void;
  onEvidenceMode: (mode: Exclude<EvidenceMode, null>) => void;
}) {
  const part = draft.draft_parts.find((value) => value.part_id === partId);
  const step = part?.steps.find((value) => value.step_id === stepId);
  if (!part || !step) return <MissingEditor />;
  const stepIndex = part.steps.findIndex((value) => value.step_id === stepId);
  const updateStep = (callback: (target: DraftStep) => void) =>
    mutate((next) => {
      const target = next.draft_parts.find((value) => value.part_id === partId)!.steps.find((value) => value.step_id === stepId)!;
      callback(target);
    });
  return (
    <div className={styles.editorStack}>
      <SectionTitle title={`${step.step_id} · STEP Editor`} description="Surface copy와 source evidence를 함께 검수합니다." />
      <section className={styles.editorCard}>
        <div className={styles.entityHeader}>
          <div><span className={styles.entityId}>{step.step_id}</span><p>Order {step.order} · playback {step.playback_start_seconds}s–{step.playback_end_seconds}s</p></div>
          <label className={styles.reviewToggle}><input type="checkbox" checked={step.needs_review} onChange={(event) => updateStep((target) => { target.needs_review = event.target.checked; })} />needs review</label>
        </div>
        <Field label="Action title" value={step.action_title} onChange={(value) => updateStep((target) => { target.action_title = value; })} />
        <div className={styles.subsectionHeader}><h3>Action lines</h3><button className={styles.smallTextButton} onClick={() => updateStep((target) => { target.action_lines.push({ text: "", segments: [{ type: "text", text: "" }], source_utterance_ids: [] }); })}>+ Line</button></div>
        <div className={styles.actionLineList}>
          {step.action_lines.map((line, lineIndex) => (
            <div className={styles.nestedCard} key={`${step.step_id}-line-${lineIndex}`}>
              <Field
                label={`Line ${lineIndex + 1}`}
                value={line.text}
                onChange={(value) =>
                  updateStep((target) => {
                    target.action_lines[lineIndex].text = value;
                    target.action_lines[lineIndex].segments = [{ type: "text", text: value }];
                  })
                }
              />
              <div className={styles.inlineMeta}><EvidenceChips ids={line.source_utterance_ids} /><button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.action_lines.splice(lineIndex, 1); })}>삭제</button></div>
              <details className={styles.details}>
                <summary>Rich segments</summary>
                {line.segments.map((segment, segmentIndex) => (
                  <div className={styles.segmentRow} key={`${lineIndex}-${segmentIndex}`}>
                    <select
                      value={segment.type}
                      aria-label="segment type"
                      onChange={(event) =>
                        updateStep((target) => {
                          target.action_lines[lineIndex].segments[segmentIndex].type = event.target.value as RichSegmentType;
                        })
                      }
                    >
                      {(["text", "command", "ui_label", "filename", "path"] as const).map((type) => <option key={type}>{type}</option>)}
                    </select>
                    <input
                      aria-label="segment text"
                      value={segment.text}
                      onChange={(event) =>
                        updateStep((target) => {
                          const targetLine = target.action_lines[lineIndex];
                          targetLine.segments[segmentIndex].text = event.target.value;
                          targetLine.text = targetLine.segments.map((item) => item.text).join("");
                        })
                      }
                    />
                  </div>
                ))}
              </details>
            </div>
          ))}
        </div>
        <div className={styles.evidenceBox}>
          <div><strong>STEP evidence</strong><span>Parent PART action 범위 안에서 선택합니다.</span></div>
          <button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "step", partId, stepId })}>Evidence 선택</button>
          <EvidenceChips ids={step.source_utterance_ids} />
        </div>
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROMPT</span><h3>Verbatim prompt</h3></div>{step.prompt ? <button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.prompt = null; })}>삭제</button> : <button className={styles.secondaryButton} onClick={() => updateStep((target) => { target.prompt = { text: "", source_kind: "verbatim", evidence: [] }; })}>+ Prompt 추가</button>}</div>
        {step.prompt ? (
          <><Field label="Prompt text" multiline value={step.prompt.text} helper="Published Prompt는 cited source에 실제 존재하는 verbatim text여야 합니다." onChange={(value) => updateStep((target) => { target.prompt!.text = value; })} /><div className={styles.inlineMeta}><EvidenceChips ids={step.prompt.evidence.map((item) => item.utterance_id)} /><button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "prompt", partId, stepId })}>Evidence 선택</button></div></>
        ) : <p className={styles.emptyMessage}>Prompt가 없습니다.</p>}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>WARNING</span><h3>Source-backed risk</h3></div>{step.warning ? <button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.warning = null; })}>삭제</button> : <button className={styles.secondaryButton} onClick={() => updateStep((target) => { target.warning = { title: "", body: "", evidence: [] }; })}>+ Warning 추가</button>}</div>
        <p className={styles.helperText}>단순 팁이 아니라 source가 명시한 비용·실패·손실 위험만 사용합니다.</p>
        {step.warning && (
          <div className={styles.formStack}>
            <Field label="Warning title" value={step.warning.title} onChange={(value) => updateStep((target) => { target.warning!.title = value; })} />
            <Field label="Warning body" multiline value={step.warning.body} onChange={(value) => updateStep((target) => { target.warning!.body = value; })} />
            <div className={styles.inlineMeta}><EvidenceChips ids={step.warning.evidence.map((item) => item.utterance_id)} /><button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "warning", partId, stepId })}>Evidence 선택</button></div>
          </div>
        )}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>LEARN MORE</span><h3>Context blocks</h3></div><button className={styles.secondaryButton} onClick={() => updateStep((target) => { target.learn_more.push({ question: "", body: "", evidence: [], source_timestamp: "00:00" }); })}>+ Learn More</button></div>
        <div className={styles.toolList}>
          {step.learn_more.map((item, itemIndex) => (
            <div className={styles.nestedCard} key={`${step.step_id}-learn-${itemIndex}`}>
              <Field label="Question" value={item.question} onChange={(value) => updateStep((target) => { target.learn_more[itemIndex].question = value; })} />
              <Field label="Body" multiline value={item.body} onChange={(value) => updateStep((target) => { target.learn_more[itemIndex].body = value; })} />
              <div className={styles.inlineMeta}><span className={styles.sourceTimestamp}>{item.source_timestamp}</span><EvidenceChips ids={item.evidence.map((value) => value.utterance_id)} /><button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "learn_more", partId, stepId, index: itemIndex })}>Evidence 선택</button><button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.learn_more.splice(itemIndex, 1); })}>삭제</button></div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.editorCard}>
        <div className={styles.actionRow}>
          <button className={styles.secondaryButton} disabled={stepIndex === 0} onClick={() => replace(reorderStep(draft, partId, stepId, -1))}>↑ 위로</button>
          <button className={styles.secondaryButton} disabled={stepIndex === part.steps.length - 1} onClick={() => replace(reorderStep(draft, partId, stepId, 1))}>↓ 아래로</button>
          <button className={styles.secondaryButton} disabled={stepIndex === 0} onClick={() => { const nextDraft = splitPartAtStep(draft, partId, stepId); const created = nextDraft.draft_parts.find((value) => !draft.draft_parts.some((current) => current.part_id === value.part_id)); replace(nextDraft); if (created) onSelect({ kind: "part", partId: created.part_id }); }}>이 STEP부터 새 PART로 분리</button>
          <button className={styles.dangerButton} onClick={() => { if (!window.confirm(`${stepId}를 삭제할까요?`)) return; replace(deleteStep(draft, partId, stepId)); onSelect({ kind: "part", partId }); }}>STEP 삭제</button>
        </div>
      </section>
    </div>
  );
}

function PhaseEditor({ draft, phaseId }: { draft: ReviewDraft; phaseId: string }) {
  const phase = draft.action_phases.find((value) => value.phase_id === phaseId);
  if (!phase) return <MissingEditor />;
  return (
    <div className={styles.editorStack}>
      <SectionTitle title={`${phase.phase_id} · Action Phase`} description="AI가 발견한 내부 workflow evidence입니다." />
      <section className={styles.editorCard}>
        <dl className={styles.phaseDefinition}>
          <div><dt>Label</dt><dd>{phase.phase_label}</dd></div>
          <div><dt>Operation</dt><dd>{phase.operation}</dd></div>
          <div><dt>Tool / surface</dt><dd>{phase.tool_or_surface ?? "—"}</dd></div>
          <div><dt>Expected result</dt><dd>{phase.expected_result ?? "—"}</dd></div>
          <div><dt>Assigned PART</dt><dd>{phase.assigned_part_id ?? "미배치"}</dd></div>
          <div><dt>Needs review</dt><dd>{phase.needs_review ? "Yes" : "No"}</dd></div>
        </dl>
        <div className={styles.evidenceColumns}><div><strong>Action evidence</strong><EvidenceChips ids={phase.action_utterance_ids} /></div><div><strong>Context evidence</strong><EvidenceChips ids={phase.context_utterance_ids} /></div></div>
        {phase.review_reasons.length > 0 && <div className={styles.reasonList}>{phase.review_reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>}
      </section>
    </div>
  );
}

function UnassignedEditor({ draft, phaseId, replace, onSelect }: { draft: ReviewDraft; phaseId: string; replace: (draft: ReviewDraft) => void; onSelect: (selection: EditorSelection) => void }) {
  const phase = draft.unassigned_phases.find((value) => value.phase_id === phaseId);
  const [reason, setReason] = useState(phase?.excluded_reason ?? "");
  const [error, setError] = useState<string | null>(null);
  if (!phase) return <MissingEditor />;
  return (
    <div className={styles.editorStack}>
      <SectionTitle title={`${phase.phase_id} · Unassigned Phase`} description="Assign, create PART, explicit exclude 중 하나로 해결합니다." />
      <section className={`${styles.editorCard} ${phase.excluded_reason ? "" : styles.blockingCard}`}>
        <span className={phase.excluded_reason ? styles.resolvedKicker : styles.blockingKicker}>{phase.excluded_reason ? "RESOLVED · EXCLUDED" : "PUBLISH BLOCKER"}</span>
        <h3>{phase.phase_label}</h3>
        <p className={styles.phaseOperation}>{phase.operation}</p>
        <dl className={styles.definitionGrid}><div><dt>Tool</dt><dd>{phase.tool_or_surface ?? "—"}</dd></div><div><dt>Expected</dt><dd>{phase.expected_result ?? "—"}</dd></div><div><dt>Source time</dt><dd>{phase.action_utterance_ids.map((id) => draft.script.find((row) => row.utterance_id === id)?.timestamp).filter(Boolean).join("–") || "—"}</dd></div><div><dt>Evidence</dt><dd>action {phase.action_utterance_ids.length} · context {phase.context_utterance_ids.length}</dd></div></dl>
        <div className={styles.reasonList}>{phase.review_reasons.map((value) => <span key={value}>{value}</span>)}</div>
      </section>
      <section className={styles.editorCard}>
        <h3>1. 기존 PART에 연결</h3>
        <div className={styles.assignGrid}>{draft.draft_parts.map((part) => <button key={part.part_id} className={styles.assignButton} onClick={() => { replace(assignPhaseToPart(draft, phaseId, part.part_id)); onSelect({ kind: "part", partId: part.part_id }); }}><strong>{part.part_id}</strong><span>{part.title}</span></button>)}</div>
      </section>
      <section className={styles.editorCard}>
        <h3>2. 새 PART로 만들기</h3>
        <p className={styles.helperText}>Phase evidence와 operation으로 편집 가능한 PART를 만듭니다.</p>
        <button className={styles.primaryButton} onClick={() => { const next = createPartFromPhase(draft, phaseId); const created = next.draft_parts.at(-1); replace(next); if (created) onSelect({ kind: "part", partId: created.part_id }); }}>새 PART 생성</button>
      </section>
      <section className={styles.editorCard}>
        <h3>3. 명시적으로 제외</h3>
        <Field label="Excluded reason" multiline value={reason} onChange={(value) => { setReason(value); setError(null); }} helper="빈 이유는 publish blocker를 해결하지 않습니다." />
        {error && <p className={styles.inlineError} role="alert">{error}</p>}
        <button className={styles.secondaryButton} onClick={() => { try { replace(excludePhase(draft, phaseId, reason)); setError(null); } catch (caught) { setError(caught instanceof Error ? caught.message : "제외할 수 없습니다."); } }}>제외 이유 저장</button>
      </section>
    </div>
  );
}

function ReviewSummary({ draft }: { draft: ReviewDraft }) {
  const unresolved = draft.review_queue.filter((item) => !isReviewItemResolved(draft, item));
  return <div className={styles.editorStack}><SectionTitle title="Review Queue" description="실제 underlying issue를 수정하면 derived preflight에서 blocker가 사라집니다." /><section className={styles.editorCard}><div className={styles.metricGrid}><div><strong>{unresolved.filter((item) => item.severity === "blocking").length}</strong><span>Blocking source items</span></div><div><strong>{unresolved.filter((item) => item.severity === "warning").length}</strong><span>Warnings</span></div><div><strong>{draft.unassigned_phases.filter((item) => !item.excluded_reason?.trim()).length}</strong><span>Unresolved phases</span></div></div><p className={styles.helperText}>오른쪽 Queue tab에서 item을 선택하면 관련 editor와 source evidence로 이동합니다.</p></section></div>;
}

function ScriptSummary({ draft }: { draft: ReviewDraft }) {
  return <div className={styles.editorStack}><SectionTitle title="Source Script" description="Script provenance는 이 Admin에서 수정할 수 없습니다." /><section className={styles.editorCard}><div className={styles.metricGrid}><div><strong>{draft.script_chapters.length}</strong><span>Chapters</span></div><div><strong>{draft.script.length}</strong><span>Utterances</span></div><div><strong>{draft.script.filter((row) => row.catchup_part_ids.length).length}</strong><span>PART-linked rows</span></div></div><div className={styles.readOnlyNotice}><strong>Read only</strong><p>Evidence picker는 draft reference만 수정하며 script text와 preprocessing provenance를 변경하지 않습니다.</p></div></section></div>;
}

function MissingEditor() {
  return <div className={styles.missingEditor}><strong>선택한 항목을 찾을 수 없습니다.</strong><p>왼쪽 navigation에서 다른 항목을 선택해주세요.</p></div>;
}

export function EditorPanel({ draft, selection, mutate, replace, onSelect, onEvidenceMode }: EditorPanelProps) {
  return (
    <main className={styles.centerPanel}>
      <div className={styles.centerScroll}>
        {selection.kind === "video" && <VideoDetailEditor draft={draft} mutate={mutate} />}
        {selection.kind === "part" && <PartEditor draft={draft} partId={selection.partId} mutate={mutate} replace={replace} onSelect={onSelect} />}
        {selection.kind === "step" && <StepEditor draft={draft} partId={selection.partId} stepId={selection.stepId} mutate={mutate} replace={replace} onSelect={onSelect} onEvidenceMode={onEvidenceMode} />}
        {selection.kind === "phase" && <PhaseEditor draft={draft} phaseId={selection.phaseId} />}
        {selection.kind === "unassigned" && <UnassignedEditor key={selection.phaseId} draft={draft} phaseId={selection.phaseId} replace={replace} onSelect={onSelect} />}
        {selection.kind === "review" && <ReviewSummary draft={draft} />}
        {selection.kind === "script" && <ScriptSummary draft={draft} />}
      </div>
    </main>
  );
}
