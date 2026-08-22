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
  if (!ids.length) return <span className={styles.emptyInline}>근거 구간 없음</span>;
  return (
    <div className={styles.chipList}>
      {ids.map((id) => (
        <span key={id} className={styles.evidenceChip}>{id}</span>
      ))}
    </div>
  );
}

function reviewReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    unassigned_phase: "미배치 작업",
    phase_context_too_broad: "작업 맥락 범위 확인",
    part_needs_review: "PART 검토 필요",
    step_needs_review: "STEP 검토 필요",
    excluded_action: "제외된 작업",
    unattached_context: "연결되지 않은 맥락",
    unsupported_claim_removed: "근거 없는 문장 제거",
    script_not_human_verified: "스크립트 검수 필요",
    uncertain_entity: "이름 확인 필요",
    checkpoint_missing: "완료 확인 근거 없음",
    prompt_removed: "프롬프트 제거",
    weak_grounding: "근거 연결 확인",
    source_claim_needs_verification: "원본 주장 확인 필요",
    unaccounted_action_anchor: "확인되지 않은 작업",
    low_action_anchor_coverage: "일부 작업이 PART에 포함되지 않았어요",
    supplemental_action_anchor: "추가로 발견한 작업이에요",
    possible_duplicate_part: "비슷한 PART를 확인해 주세요",
    workflow_grouping_review: "PART 구성을 다시 확인해 주세요",
    writing_style_review: "사용자 문구를 자연스럽게 다듬어 주세요",
  };
  return labels[reason] ?? reason;
}

function VideoDetailEditor({ draft, mutate }: { draft: ReviewDraft; mutate: DraftMutator }) {
  const recommendation = draft.video_detail.recommendation;
  return (
    <div className={styles.editorStack}>
      <SectionTitle
        title="영상 정보"
        description="사용자 화면에 표시될 추천 문구, 도구, 태그를 검수합니다."
      />
      <section className={styles.editorCard}>
        <div className={styles.cardHeader}>
          <div><span className={styles.eyebrow}>추천</span><h3>추천 문구</h3></div>
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
              + 추천 문구 추가
            </button>
          )}
        </div>
        {recommendation ? (
          <div className={styles.formGrid}>
            <Field label="상단 문구" value={recommendation.eyebrow} onChange={(value) => mutate((next) => { next.video_detail.recommendation!.eyebrow = value; })} />
            <Field label="제목" value={recommendation.title} onChange={(value) => mutate((next) => { next.video_detail.recommendation!.title = value; })} />
            <div className={styles.fullField}>
              <Field label="본문" multiline value={recommendation.body} onChange={(value) => mutate((next) => { next.video_detail.recommendation!.body = value; })} />
            </div>
            <details className={`${styles.details} ${styles.fullField}`}>
              <summary>문장별 근거 {recommendation.claims.length}개</summary>
              {recommendation.claims.map((claim, index) => (
                <div key={`${claim.text}-${index}`} className={styles.claimRow}>
                  <p>{claim.text}</p>
                  <EvidenceChips ids={claim.evidence.map((item) => item.utterance_id)} />
                </div>
              ))}
            </details>
          </div>
        ) : (
          <p className={styles.emptyMessage}>추천 문구가 없습니다.</p>
        )}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}>
          <div><span className={styles.eyebrow}>도구</span><h3>도구</h3></div>
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
                <Field label="이름" value={tool.name} onChange={(value) => mutate((next) => { next.video_detail.tools[index].name = value; })} />
                <Field label="공식 이름" value={tool.canonical_name} onChange={(value) => mutate((next) => { next.video_detail.tools[index].canonical_name = value; })} />
                <Field label="URL" value={tool.url ?? ""} onChange={(value) => mutate((next) => { next.video_detail.tools[index].url = value || null; })} />
                <Field label="설명" value={tool.description} onChange={(value) => mutate((next) => { next.video_detail.tools[index].description = value; })} />
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
        <span className={styles.eyebrow}>태그</span>
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
      <SectionTitle title={`${part.part_id} · PART 편집`} description="PART ID와 원본 근거는 유지하고 사용자용 문구를 정리합니다." />
      <section className={styles.editorCard}>
        <div className={styles.entityHeader}>
          <div>
            <span className={styles.entityId}>{part.part_id}</span>
            <p>순서 {part.order} · {part.start_timestamp}–{part.end_timestamp}</p>
          </div>
          <label className={styles.reviewToggle}>
            <input type="checkbox" checked={part.needs_review} onChange={(event) => mutate((value) => { value.draft_parts.find((item) => item.part_id === partId)!.needs_review = event.target.checked; })} />
            검토 필요
          </label>
        </div>
        <div className={styles.formStack}>
          <Field label="제목" value={part.title} onChange={(value) => mutate((next) => { next.draft_parts.find((item) => item.part_id === partId)!.title = value; })} />
          <Field label="요약" multiline value={part.summary ?? ""} onChange={(value) => mutate((next) => { next.draft_parts.find((item) => item.part_id === partId)!.summary = value || null; })} />
          <Field label="작업 목표" multiline value={part.action_objective} onChange={(value) => mutate((next) => { next.draft_parts.find((item) => item.part_id === partId)!.action_objective = value; })} />
        </div>
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>원본 근거</span><h3>원본 연결</h3></div></div>
        <dl className={styles.definitionGrid}>
          <div><dt>스크립트 챕터</dt><dd>{part.source_script_chapter_ids.join(", ") || "—"}</dd></div>
          <div><dt>대표 이미지</dt><dd>{part.thumbnail?.relative_path ?? "미확정"}</dd></div>
          <div><dt>원본 구간</dt><dd>{part.source_utterance_ids.length}</dd></div>
          <div><dt>작업 구간</dt><dd>{part.action_utterance_ids.length}</dd></div>
        </dl>
        <EvidenceChips ids={part.source_utterance_ids} />
        {part.review_reasons.length > 0 && (
          <div className={styles.reasonList}>{part.review_reasons.map((reason) => <span key={reason}>{reviewReasonLabel(reason)}</span>)}</div>
        )}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PART 작업</span><h3>PART 구조</h3></div></div>
        <div className={styles.actionRow}>
          <button className={styles.secondaryButton} disabled={!previous} onClick={() => replace(reorderPart(draft, partId, -1))}>↑ 위로</button>
          <button className={styles.secondaryButton} disabled={!nextPart} onClick={() => replace(reorderPart(draft, partId, 1))}>↓ 아래로</button>
          <button className={styles.secondaryButton} disabled={!previous} onClick={() => previous && replace(mergeParts(draft, previous.part_id, partId))}>이전과 병합</button>
          <button className={styles.secondaryButton} disabled={!nextPart} onClick={() => nextPart && replace(mergeParts(draft, partId, nextPart.part_id))}>다음과 병합</button>
          <button
            className={styles.dangerButton}
            onClick={() => {
              if (!window.confirm(`${partId}를 삭제할까요? 연결된 작업 단계는 미배치 작업으로 이동합니다.`)) return;
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
      <SectionTitle title={`${step.step_id} · STEP 편집`} description="화면 문구와 원본 근거를 함께 검수합니다." />
      <section className={styles.editorCard}>
        <div className={styles.entityHeader}>
          <div><span className={styles.entityId}>{step.step_id}</span><p>순서 {step.order} · 재생 {step.playback_start_seconds}초–{step.playback_end_seconds}초</p></div>
          <label className={styles.reviewToggle}><input type="checkbox" checked={step.needs_review} onChange={(event) => updateStep((target) => { target.needs_review = event.target.checked; })} />검토 필요</label>
        </div>
        <Field label="작업 제목" value={step.action_title} onChange={(value) => updateStep((target) => { target.action_title = value; })} />
        <div className={styles.subsectionHeader}><h3>작업 문장</h3><button className={styles.smallTextButton} onClick={() => updateStep((target) => { target.action_lines.push({ text: "", segments: [{ type: "text", text: "" }], source_utterance_ids: [] }); })}>+ 문장 추가</button></div>
        <div className={styles.actionLineList}>
          {step.action_lines.map((line, lineIndex) => (
            <div className={styles.nestedCard} key={`${step.step_id}-line-${lineIndex}`}>
              <Field
                label={`문장 ${lineIndex + 1}`}
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
                <summary>세부 형식</summary>
                {line.segments.map((segment, segmentIndex) => (
                  <div className={styles.segmentRow} key={`${lineIndex}-${segmentIndex}`}>
                    <select
                      value={segment.type}
                      aria-label="문장 형식"
                      onChange={(event) =>
                        updateStep((target) => {
                          target.action_lines[lineIndex].segments[segmentIndex].type = event.target.value as RichSegmentType;
                        })
                      }
                    >
                      {(["text", "command", "ui_label", "filename", "path"] as const).map((type) => <option key={type}>{type}</option>)}
                    </select>
                    <input
                      aria-label="문장 내용"
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
          <div><strong>STEP 근거 구간</strong><span>상위 PART의 작업 구간 안에서 선택합니다.</span></div>
          <button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "step", partId, stepId })}>근거 구간 선택</button>
          <EvidenceChips ids={step.source_utterance_ids} />
        </div>
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>프롬프트</span><h3>원문 프롬프트</h3></div>{step.prompt ? <button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.prompt = null; })}>삭제</button> : <button className={styles.secondaryButton} onClick={() => updateStep((target) => { target.prompt = { text: "", source_kind: "verbatim", evidence: [] }; })}>+ 프롬프트 추가</button>}</div>
        {step.prompt ? (
          <><Field label="프롬프트 문장" multiline value={step.prompt.text} helper="프롬프트는 원본 근거에 실제 문장 그대로 존재해야 합니다." onChange={(value) => updateStep((target) => { target.prompt!.text = value; })} /><div className={styles.inlineMeta}><EvidenceChips ids={step.prompt.evidence.map((item) => item.utterance_id)} /><button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "prompt", partId, stepId })}>근거 구간 선택</button></div></>
        ) : <p className={styles.emptyMessage}>프롬프트가 없습니다.</p>}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>주의</span><h3>원본에 있는 위험</h3></div>{step.warning ? <button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.warning = null; })}>삭제</button> : <button className={styles.secondaryButton} onClick={() => updateStep((target) => { target.warning = { title: "", body: "", evidence: [] }; })}>+ 주의 추가</button>}</div>
        <p className={styles.helperText}>단순 팁이 아니라 원본에서 확인되는 비용·실패·손실 위험만 사용합니다.</p>
        {step.warning && (
          <div className={styles.formStack}>
            <Field label="주의 제목" value={step.warning.title} onChange={(value) => updateStep((target) => { target.warning!.title = value; })} />
            <Field label="주의 내용" multiline value={step.warning.body} onChange={(value) => updateStep((target) => { target.warning!.body = value; })} />
            <div className={styles.inlineMeta}><EvidenceChips ids={step.warning.evidence.map((item) => item.utterance_id)} /><button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "warning", partId, stepId })}>근거 구간 선택</button></div>
          </div>
        )}
      </section>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>더 알아보기</span><h3>보충 설명</h3></div><button className={styles.secondaryButton} onClick={() => updateStep((target) => { target.learn_more.push({ question: "", body: "", evidence: [], source_timestamp: "00:00" }); })}>+ 더 알아보기</button></div>
        <div className={styles.toolList}>
          {step.learn_more.map((item, itemIndex) => (
            <div className={styles.nestedCard} key={`${step.step_id}-learn-${itemIndex}`}>
              <Field label="질문" value={item.question} onChange={(value) => updateStep((target) => { target.learn_more[itemIndex].question = value; })} />
              <Field label="설명" multiline value={item.body} onChange={(value) => updateStep((target) => { target.learn_more[itemIndex].body = value; })} />
              <div className={styles.inlineMeta}><span className={styles.sourceTimestamp}>{item.source_timestamp}</span><EvidenceChips ids={item.evidence.map((value) => value.utterance_id)} /><button className={styles.secondaryButton} onClick={() => onEvidenceMode({ kind: "learn_more", partId, stepId, index: itemIndex })}>근거 구간 선택</button><button className={styles.dangerTextButton} onClick={() => updateStep((target) => { target.learn_more.splice(itemIndex, 1); })}>삭제</button></div>
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
      <SectionTitle title={`${phase.phase_id} · 작업 단계`} description="AI가 찾은 작업 흐름과 원본 근거입니다." />
      <section className={styles.editorCard}>
        <dl className={styles.phaseDefinition}>
          <div><dt>이름</dt><dd>{phase.phase_label}</dd></div>
          <div><dt>작업</dt><dd>{phase.operation}</dd></div>
          <div><dt>도구 / 화면</dt><dd>{phase.tool_or_surface ?? "—"}</dd></div>
          <div><dt>예상 결과</dt><dd>{phase.expected_result ?? "—"}</dd></div>
          <div><dt>연결된 PART</dt><dd>{phase.assigned_part_id ?? "미배치"}</dd></div>
          <div><dt>검토 필요</dt><dd>{phase.needs_review ? "예" : "아니요"}</dd></div>
        </dl>
        <div className={styles.evidenceColumns}><div><strong>작업 근거</strong><EvidenceChips ids={phase.action_utterance_ids} /></div><div><strong>맥락 근거</strong><EvidenceChips ids={phase.context_utterance_ids} /></div></div>
        {phase.review_reasons.length > 0 && <div className={styles.reasonList}>{phase.review_reasons.map((reason) => <span key={reason}>{reviewReasonLabel(reason)}</span>)}</div>}
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
      <SectionTitle title={`${phase.phase_id} · 미배치 작업`} description="PART에 연결하거나 새 PART를 만들거나 제외하세요." />
      <section className={`${styles.editorCard} ${phase.excluded_reason ? "" : styles.blockingCard}`}>
        <span className={phase.excluded_reason ? styles.resolvedKicker : styles.blockingKicker}>{phase.excluded_reason ? "해결됨 · 제외" : "발행 전 필수 확인"}</span>
        <h3>{phase.phase_label}</h3>
        <p className={styles.phaseOperation}>{phase.operation}</p>
        <dl className={styles.definitionGrid}><div><dt>도구</dt><dd>{phase.tool_or_surface ?? "—"}</dd></div><div><dt>예상 결과</dt><dd>{phase.expected_result ?? "—"}</dd></div><div><dt>원본 시간</dt><dd>{phase.action_utterance_ids.map((id) => draft.script.find((row) => row.utterance_id === id)?.timestamp).filter(Boolean).join("–") || "—"}</dd></div><div><dt>근거 구간</dt><dd>작업 {phase.action_utterance_ids.length} · 맥락 {phase.context_utterance_ids.length}</dd></div></dl>
        <div className={styles.reasonList}>{phase.review_reasons.map((value) => <span key={value}>{reviewReasonLabel(value)}</span>)}</div>
      </section>
      <section className={styles.editorCard}>
        <h3>1. 기존 PART에 연결</h3>
        <div className={styles.assignGrid}>{draft.draft_parts.map((part) => <button key={part.part_id} className={styles.assignButton} onClick={() => { replace(assignPhaseToPart(draft, phaseId, part.part_id)); onSelect({ kind: "part", partId: part.part_id }); }}><strong>{part.part_id}</strong><span>{part.title}</span></button>)}</div>
      </section>
      <section className={styles.editorCard}>
        <h3>2. 새 PART로 만들기</h3>
        <p className={styles.helperText}>이 작업의 근거 구간과 내용을 사용해 편집 가능한 PART를 만듭니다.</p>
        <button className={styles.primaryButton} onClick={() => { const next = createPartFromPhase(draft, phaseId); const created = next.draft_parts.at(-1); replace(next); if (created) onSelect({ kind: "part", partId: created.part_id }); }}>이 작업으로 새 PART 만들기</button>
      </section>
      <section className={styles.editorCard}>
        <h3>3. 명시적으로 제외</h3>
        <Field label="제외 이유" multiline value={reason} onChange={(value) => { setReason(value); setError(null); }} helper="제외 이유를 입력해야 발행 전 필수 확인이 해결됩니다." />
        {error && <p className={styles.inlineError} role="alert">{error}</p>}
        <button className={styles.secondaryButton} onClick={() => { try { replace(excludePhase(draft, phaseId, reason)); setError(null); } catch (caught) { setError(caught instanceof Error ? caught.message : "제외할 수 없습니다."); } }}>제외 이유 저장</button>
      </section>
    </div>
  );
}

function ReviewSummary({ draft }: { draft: ReviewDraft }) {
  const unresolved = draft.review_queue.filter((item) => !isReviewItemResolved(draft, item));
  return <div className={styles.editorStack}><SectionTitle title="검토 필요" description="원인이 되는 항목을 수정하면 발행 전 필수 확인에서 사라집니다." /><section className={styles.editorCard}><div className={styles.metricGrid}><div><strong>{unresolved.filter((item) => item.severity === "blocking").length}</strong><span>필수 확인</span></div><div><strong>{unresolved.filter((item) => item.severity === "warning").length}</strong><span>주의</span></div><div><strong>{draft.unassigned_phases.filter((item) => !item.excluded_reason?.trim()).length}</strong><span>미해결 작업</span></div></div><p className={styles.helperText}>오른쪽 검토 필요 탭에서 항목을 선택하면 관련 편집 화면과 원본 근거로 이동합니다.</p></section></div>;
}

function ScriptSummary({ draft }: { draft: ReviewDraft }) {
  return <div className={styles.editorStack}><SectionTitle title="원본 스크립트" description="원본 스크립트는 관리자 화면에서 수정할 수 없습니다." /><section className={styles.editorCard}><div className={styles.metricGrid}><div><strong>{draft.script_chapters.length}</strong><span>챕터</span></div><div><strong>{draft.script.length}</strong><span>문장</span></div><div><strong>{draft.script.filter((row) => row.catchup_part_ids.length).length}</strong><span>PART 연결 문장</span></div></div><div className={styles.readOnlyNotice}><strong>읽기 전용</strong><p>근거 구간 선택은 초안의 연결 정보만 수정하며 스크립트 원문과 전처리 근거는 변경하지 않습니다.</p></div></section></div>;
}

function MissingEditor() {
  return <div className={styles.missingEditor}><strong>선택한 항목을 찾을 수 없습니다.</strong><p>왼쪽 메뉴에서 다른 항목을 선택해주세요.</p></div>;
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
