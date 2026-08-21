"use client";

import { useState } from 'react';
import { findPoll, findPollResult, type CommentItem } from "@/data/ddockPollResult";
import styles from './PollResult.module.css';

const backIcon = "/ddock/icons/back.svg";
const doneRing = "/ddock/icons/done-ring-light.svg";
const doneCheck = "/ddock/icons/done-check-light.svg";
const likeIcon = "/ddock/icons/like-result.svg";
const likeActiveIcon = "/ddock/icons/like-active.svg";
const eyeIcon = "/ddock/icons/eye-result.svg";
const kebabIcon = "/ddock/icons/kebab.svg";
const sendIcon = "/ddock/icons/send.svg";
const dividerIcon = "/ddock/icons/divider.svg";
const tooltipOrange = "/ddock/icons/tooltip-orange.svg";
const tooltipLime = "/ddock/icons/tooltip-lime.svg";

interface PollResultProps {
  pollId: string;
  onBack: () => void;
}

/**
 * 막대 높이를 계산할 기준값.
 * 시안의 y축(60 / 30 / 15 / 0)은 간격이 일정한데 값은 절반씩 줄어 선형이 아니다.
 * 여기서는 최댓값·1/2·1/4·0 이라는 시안의 패턴만 가져오고 눈금은 실제 데이터에서 만든다.
 */
function buildAxis(max: number): number[] {
  return [max, Math.round(max / 2), Math.round(max / 4), 0];
}

function Comment({ comment, isReply }: { comment: CommentItem; isReply?: boolean }) {
  return (
    <div className={styles.comment}>
      <img
        className={`${styles.commentAvatar} ${isReply ? styles.replyAvatar : ''}`}
        src={comment.avatar}
        alt=""
      />
      <div className={styles.commentBody}>
        <div className={styles.commentMeta}>
          <span className={styles.commentAuthor}>{comment.author}</span>
          <span className={styles.metaDot} />
          <span className={styles.commentTime}>{comment.timeLabel}</span>
          <button className={styles.commentKebabButton} type="button" aria-label="댓글 더보기">
            <img className={styles.commentKebab} src={kebabIcon} alt="" />
          </button>
        </div>
        <p className={styles.commentText}>{comment.text}</p>
        <button className={styles.replyButton} type="button">
          답글달기
        </button>
        {comment.replies && comment.replies.length > 0 && (
          <div className={styles.replyList}>
            {comment.replies.map((reply) => (
              <Comment key={reply.id} comment={reply} isReply />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function PollResult({ pollId, onBack }: PollResultProps) {
  const [draft, setDraft] = useState('');
  const [liked, setLiked] = useState(false);
  const poll = findPoll(pollId);
  const result = findPollResult(pollId);

  if (!poll) {
    return null;
  }

  const totalVotes = result.votes[0] + result.votes[1];
  /*
   * 시안은 표 수와 퍼센트를 각각 따로 적어두고 서로 정확히 나누어떨어지지 않는다.
   * 홈 카드와 결과 화면의 퍼센트가 어긋나지 않도록 비율은 투표 데이터의 값을 그대로 쓰고,
   * 표 수는 결과 데이터의 값을 그대로 보여준다.
   */
  const firstPercent = poll.firstRatio ?? Math.round((result.votes[0] / totalVotes) * 100);
  const secondPercent = 100 - firstPercent;

  const chartMax = Math.max(...result.daily.map((d) => d.first + d.second), 1);
  const axis = buildAxis(chartMax);
  // 시안은 답글을 빼고 최상위 댓글 수만 센다
  const commentCount = result.comments.length;

  return (
    <div className={styles.page}>
      <div className={styles.hero}>
        <img
          className={styles.heroImage}
          src={poll.thumbnail}
          alt=""
          style={poll.thumbnailPosition ? { objectPosition: poll.thumbnailPosition } : undefined}
        />
        <div className={styles.heroHeader}>
          <button className={styles.back} type="button" aria-label="뒤로가기" onClick={onBack}>
            <img className={styles.backIcon} src={backIcon} alt="" />
          </button>
        </div>
      </div>

      <div className={styles.content}>
        <div className={styles.summary}>
          <span className={styles.tag}>{result.category}</span>
          <h1 className={styles.title}>{poll.question}</h1>
          <span className={styles.period}>{result.periodLabel}</span>
        </div>

        <div className={styles.result}>
          <div className={styles.tooltips}>
            <div className={styles.tooltipStart}>
              <span className={styles.tooltip}>
                <img className={styles.tooltipBg} src={tooltipOrange} alt="" />
                <span className={styles.tooltipLabel}>{poll.options[0]}</span>
              </span>
            </div>
            <span className={styles.tooltip}>
              <img className={styles.tooltipBg} src={tooltipLime} alt="" />
              <span className={styles.tooltipLabel}>{poll.options[1]}</span>
            </span>
          </div>

          <div
            className={styles.progress}
            role="img"
            aria-label={`${poll.options[0]} ${firstPercent}%, ${poll.options[1]} ${secondPercent}%`}
          >
            <div className={styles.progressInner} style={{ width: `${firstPercent}%` }} />
            <span className={`${styles.progressLabel} ${styles.progressLabelStart}`}>
              {firstPercent}%
            </span>
            <span className={`${styles.progressLabel} ${styles.progressLabelEnd}`}>
              {secondPercent}%
            </span>
          </div>

          <div className={styles.completed}>
            <span className={styles.checkIcon}>
              <img className={styles.checkRing} src={doneRing} alt="" />
              <span className={styles.checkMarkBox}>
                <img className={styles.checkMark} src={doneCheck} alt="" />
              </span>
            </span>
            {totalVotes}명 투표 완료
          </div>
        </div>

        <section className={styles.stats}>
          <h2 className={styles.statsTitle}>총 투표 통계</h2>

          <div className={styles.chart}>
            <div className={styles.axis}>
              {axis.map((value) => (
                <span key={value}>{value}</span>
              ))}
            </div>

            <div className={styles.plot}>
              <div className={styles.bars}>
                {result.daily.map((entry) => {
                  if (entry.empty) {
                    return (
                      <div className={styles.barGroup} key={entry.day}>
                        <div className={`${styles.segment} ${styles.segmentEmpty}`} />
                      </div>
                    );
                  }
                  return (
                    <div className={styles.barGroup} key={entry.day}>
                      <div
                        className={`${styles.segment} ${styles.segmentFirst}`}
                        style={{ height: `${(entry.first / chartMax) * 100}%` }}
                      />
                      <div
                        className={`${styles.segment} ${styles.segmentSecond}`}
                        style={{ height: `${(entry.second / chartMax) * 100}%` }}
                      />
                    </div>
                  );
                })}
              </div>

              <div className={styles.dayLabels}>
                {result.daily.map((entry) => (
                  <span className={styles.dayLabel} key={entry.day}>
                    {entry.day}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className={styles.legend}>
            <div className={styles.legendItem}>
              <span className={styles.legendName}>{poll.options[0]}</span>
              <span className={styles.legendValue}>
                <span className={styles.legendCount}>{result.votes[0]}</span>
                <span className={styles.legendUnit}>표</span>
              </span>
            </div>
            <img className={styles.legendDivider} src={dividerIcon} alt="" />
            <div className={styles.legendItem}>
              <span className={styles.legendName}>{poll.options[1]}</span>
              <span className={styles.legendValue}>
                <span className={styles.legendCount}>{result.votes[1]}</span>
                <span className={styles.legendUnit}>표</span>
              </span>
            </div>
          </div>
        </section>

        <div className={styles.action}>
          <div className={styles.actionStart}>
            <button
              type="button"
              className={`${styles.tagPill} ${styles.likeChip} ${liked ? styles.likeChipActive : ''}`}
              aria-pressed={liked}
              aria-label="공감하기"
              onClick={() => setLiked((prev) => !prev)}
            >
              <img className={styles.tagIcon} src={liked ? likeActiveIcon : likeIcon} alt="" />
              {result.likeCount + (liked ? 1 : 0)}
            </button>
            <span className={styles.reaction}>
              <span className={styles.avatarGroup}>
                {result.comments.slice(0, 2).map((comment) => (
                  <img key={comment.id} src={comment.avatar} alt="" />
                ))}
              </span>
              <span className={styles.reactionText}>
                <span className={styles.reactionName}>{result.reactionUser}</span> 외{' '}
                <span className={styles.reactionName}>{result.reactionOthers}명</span>이 공감했어요
              </span>
            </span>
          </div>
          <span className={`${styles.tagPill} ${styles.viewChip}`}>
            <img className={styles.tagIcon} src={eyeIcon} alt="" />
            {result.viewCount}
          </span>
        </div>
      </div>

      <section className={styles.comments}>
        <h2 className={styles.commentsHeading}>
          댓글
          <span className={styles.commentsCount}>{commentCount}</span>
        </h2>
        <div className={styles.commentList}>
          {result.comments.map((comment) => (
            <Comment key={comment.id} comment={comment} />
          ))}
        </div>
      </section>

      <div className={styles.composer}>
        <div className={styles.composerField}>
          <input
            className={styles.composerInput}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="메시지를 입력해주세요"
            aria-label="댓글 입력"
          />
          <button className={styles.composerSend} type="button" aria-label="보내기">
            <img className={styles.composerSendIcon} src={sendIcon} alt="" />
          </button>
        </div>
      </div>
    </div>
  );
}
