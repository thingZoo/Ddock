"use client";

import type { Poll } from "@/data/ddockHome";
import styles from './IssuePollCard.module.css';

const doneRing = "/ddock/icons/done-ring.svg";
const doneCheck = "/ddock/icons/done-check.svg";

interface IssuePollCardProps {
  poll: Poll;
  onSelect?: (pollId: string) => void;
}

/** 홈 하단 '투표로 알아보는 AI 이슈'에 쓰는, 결과가 이미 공개된 요약 카드 */
export function IssuePollCard({ poll, onSelect }: IssuePollCardProps) {
  const firstRatio = poll.firstRatio ?? 50;
  const rows = [
    { label: poll.options[0], ratio: firstRatio },
    { label: poll.options[1], ratio: 100 - firstRatio },
  ];
  const leadRatio = Math.max(rows[0].ratio, rows[1].ratio);

  return (
    <article className={styles.card}>
      <button
        className={styles.thumbnail}
        type="button"
        aria-label={`${poll.question} 자세히 보기`}
        onClick={() => onSelect?.(poll.id)}
      >
        <img
          className={styles.thumbnailImage}
          src={poll.thumbnail}
          alt=""
          style={poll.thumbnailPosition ? { objectPosition: poll.thumbnailPosition } : undefined}
        />
        {poll.participated && (
          <span className={styles.badgeWrap}>
            <span className={styles.badge}>
              <span className={styles.badgeIcon}>
                <img className={styles.badgeRing} src={doneRing} alt="" />
                <span className={styles.badgeCheckBox}>
                  <img className={styles.badgeCheck} src={doneCheck} alt="" />
                </span>
              </span>
              참여
            </span>
          </span>
        )}
      </button>

      <div className={styles.body}>
        <h3 className={styles.question}>{poll.question}</h3>

        <div className={styles.rows}>
          {rows.map((row) => {
            const isLead = row.ratio === leadRatio;
            return (
              <div className={styles.row} key={row.label}>
                <span className={styles.chipColumn}>
                  <span className={styles.chip}>{row.label}</span>
                </span>
                <span className={styles.sliderWrap}>
                  <span className={styles.track}>
                    <span
                      className={`${styles.fill} ${isLead ? styles.fillLead : ''}`}
                      style={{ width: `${row.ratio}%` }}
                    />
                  </span>
                </span>
                <span className={`${styles.percent} ${isLead ? styles.percentLead : ''}`}>
                  {row.ratio}%
                </span>
              </div>
            );
          })}
        </div>

        <div className={styles.footer}>
          {poll.periodLabel && <span className={styles.period}>{poll.periodLabel}</span>}
          <span className={styles.voterCount}>{poll.voterCount}명 참여</span>
        </div>
      </div>
    </article>
  );
}
