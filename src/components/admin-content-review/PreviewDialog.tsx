"use client";

import type { PublishedContent } from "@/lib/admin-content-review/types";
import styles from "./AdminContentReview.module.css";

interface PreviewDialogProps {
  content: PublishedContent;
  onClose: () => void;
}

export function PreviewDialog({ content, onClose }: PreviewDialogProps) {
  return (
    <div className={styles.dialogBackdrop} role="presentation" onMouseDown={onClose}>
      <section
        className={styles.previewDialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="preview-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className={styles.dialogHeader}>
          <div>
            <span className={styles.eyebrow}>관리자 미리보기</span>
            <h2 id="preview-title">{content.source.title ?? content.source.video_id}</h2>
            <p>발행 파일에 표시될 내용을 읽기 전용으로 확인합니다.</p>
          </div>
          <button className={styles.iconButton} onClick={onClose} aria-label="미리보기 닫기">×</button>
        </header>
        <div className={styles.previewBody}>
          {content.video_detail.recommendation && (
            <section className={styles.previewRecommendation}>
              <span>{content.video_detail.recommendation.eyebrow}</span>
              <h3>{content.video_detail.recommendation.title}</h3>
              <p>{content.video_detail.recommendation.body}</p>
            </section>
          )}
          <div className={styles.previewPartList}>
            {content.catchup_parts.map((part) => (
              <article className={styles.previewPart} key={part.part_id}>
                <div className={styles.previewPartHeader}>
                  <span>{part.part_id}</span>
                  <small>{part.start_timestamp}–{part.end_timestamp}</small>
                </div>
                <h3>{part.title}</h3>
                {part.summary && <p>{part.summary}</p>}
                <div className={styles.previewSteps}>
                  {part.steps.map((step) => (
                    <div key={step.step_id}>
                      <strong>{step.order}. {step.action_title}</strong>
                      {step.action_lines.map((line, index) => <p key={`${step.step_id}-${index}`}>{line.text}</p>)}
                      {step.prompt && <blockquote><b>프롬프트</b>{step.prompt.text}</blockquote>}
                      {step.warning && <aside><b>{step.warning.title}</b><span>{step.warning.body}</span></aside>}
                      {step.learn_more.map((item, index) => (
                        <details key={`${step.step_id}-more-${index}`}>
                          <summary>{item.question}</summary>
                          <p>{item.body}</p>
                        </details>
                      ))}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
