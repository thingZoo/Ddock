import type { Poll } from '../data/home';
import styles from './PollCard.module.css';

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
              className={styles.track}
              role="img"
              aria-label={
                voted
                  ? `${poll.options[0]} ${firstRatio}%, ${poll.options[1]} ${secondRatio}%`
                  : '투표하면 결과를 볼 수 있어요'
              }
            >
              <div className={styles.fill} style={{ width: `${voted ? firstRatio : 50}%` }} />
            </div>
          </div>
        </div>

        <div className={styles.actions}>
          {poll.options.map((option, index) => (
            <button
              key={option}
              type="button"
              className={[
                styles.button,
                index === 0 ? styles.buttonPrimary : styles.buttonSecondary,
                selected === index ? styles.buttonSelected : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-pressed={selected === index}
              onClick={() => onVote(poll.id, index)}
            >
              {option}
            </button>
          ))}
        </div>
      </div>
    </article>
  );
}
