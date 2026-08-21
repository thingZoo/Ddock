"use client";

import type { Poll } from "@/data/ddockHome";
import styles from './PollCard.module.css';

const doneRing = "/ddock/icons/done-ring.svg";
const doneCheck = "/ddock/icons/done-check.svg";

interface PollCardProps {
  poll: Poll;
  /** 사용자가 고른 선택지 인덱스. 고르기 전이면 null이고 득표율이 '??%'로 가려진다. */
  selected: number | null;
  onVote: (pollId: string, optionIndex: number) => void;
}

const HIDDEN_RATIO = '??%';

export function PollCard({ poll, selected, onVote }: PollCardProps) {
  const voted = selected !== null;
  const firstRatio = poll.firstRatio ?? 50;
  const secondRatio = 100 - firstRatio;

  return (
    <article className={styles.card}>
      <div className={styles.media}>
        <img
          className={styles.mediaImage}
          src={poll.thumbnail}
          alt=""
          style={poll.thumbnailPosition ? { objectPosition: poll.thumbnailPosition } : undefined}
        />
        {poll.remainingLabel && (
          <div className={styles.deadline}>
            <span className={styles.deadlineBadge}>{poll.remainingLabel}</span>
          </div>
        )}
      </div>

      <div className={styles.panel}>
        <div className={styles.meta}>
          <span className={styles.voterCount}>{poll.voterCount}명 참여</span>
          <h2 className={styles.question}>{poll.question}</h2>
        </div>

        <div className={styles.result}>
          <div className={styles.resultRow}>
            <div className={`${styles.resultSide} ${styles.resultSideStart}`}>
              <span className={styles.chip}>{poll.options[0]}</span>
              <span className={styles.percent}>{voted ? `${firstRatio}%` : HIDDEN_RATIO}</span>
            </div>
            <div className={styles.resultSide}>
              <span className={styles.percent}>{voted ? `${secondRatio}%` : HIDDEN_RATIO}</span>
              <span className={styles.chip}>{poll.options[1]}</span>
            </div>
          </div>

          <div className={styles.sliderWrap}>
            <div
              className={`${styles.track} ${voted ? styles.trackVoted : ''}`}
              role="img"
              aria-label={
                voted
                  ? `${poll.options[0]} ${firstRatio}%, ${poll.options[1]} ${secondRatio}%`
                  : '투표하면 결과를 볼 수 있어요'
              }
            >
              <div
                className={`${styles.fill} ${voted ? styles.fillVoted : ''}`}
                style={{ width: `${voted ? firstRatio : 50}%` }}
              />
            </div>
          </div>
        </div>

        <div className={styles.actions}>
          {poll.options.map((option, index) => {
            const isSelected = selected === index;
            /*
             * 투표 전에는 위치로 밝은/어두운 스타일이 갈리고,
             * 투표 후에는 고른 쪽이 어두운 스타일 + 체크 아이콘을 갖는다.
             */
            const isDark = voted ? isSelected : index === 1;
            return (
              <button
                key={option}
                type="button"
                className={[
                  styles.button,
                  isDark ? styles.buttonDark : styles.buttonLight,
                  isSelected ? styles.buttonSelected : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                aria-pressed={isSelected}
                onClick={() => onVote(poll.id, index)}
              >
                {isSelected && (
                  <span className={styles.checkIcon}>
                    <img className={styles.checkRing} src={doneRing} alt="" />
                    <span className={styles.checkMarkBox}>
                      <img className={styles.checkMark} src={doneCheck} alt="" />
                    </span>
                  </span>
                )}
                {option}
              </button>
            );
          })}
        </div>
      </div>
    </article>
  );
}
