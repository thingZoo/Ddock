import { useRef, useState } from 'react';
import { PollCard } from './PollCard';
import type { Poll } from '../data/home';
import styles from './PollDeck.module.css';

interface PollDeckProps {
  polls: Poll[];
  /** pollId → 사용자가 고른 선택지 인덱스 */
  votes: Record<string, number>;
  onVote: (pollId: string, optionIndex: number) => void;
  /** 앞으로 올라온 투표가 바뀔 때 알린다. 배경 이미지를 함께 바꾸는 데 쓴다. */
  onActivePollChange?: (poll: Poll) => void;
}

/** 뒤 카드의 축소 비율과 중심 이동량 (Figma 285x366 vs 324x416) */
const BACK_SCALE = 0.8796;
const BACK_SHIFT = 38.5;
/** 이만큼 끌면 다음 카드로 넘어간다 */
const SWIPE_THRESHOLD = 80;
/** 넘길 때 카드가 화면 밖으로 빠져나가는 거리 */
const EXIT_DISTANCE = 420;
/** 드래그를 클릭이 아닌 스와이프로 볼 최소 이동 거리 */
const DRAG_THRESHOLD = 4;

export function PollDeck({ polls, votes, onVote, onActivePollChange }: PollDeckProps) {
  const [index, setIndex] = useState(0);
  const [dragX, setDragX] = useState(0);
  const [dragging, setDragging] = useState(false);
  /** 전환 애니메이션 중에는 transition을 켜둔다 */
  const [animating, setAnimating] = useState(false);

  const activeRef = useRef(false);
  const movedRef = useRef(false);
  const exitingRef = useRef(false);
  const startXRef = useRef(0);

  if (polls.length === 0) return null;

  const frontPoll = polls[index % polls.length];
  const backPoll = polls[(index + 1) % polls.length];

  // 끈 거리에 비례해 뒤 카드가 제자리로 올라온다 (0 = 뒤, 1 = 앞)
  const progress = Math.min(Math.abs(dragX) / SWIPE_THRESHOLD, 1);
  const backScale = BACK_SCALE + (1 - BACK_SCALE) * progress;
  const backShift = BACK_SHIFT * (1 - progress);
  const backOpacity = 0.8 + 0.2 * progress;

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (animating || polls.length < 2) return;
    activeRef.current = true;
    movedRef.current = false;
    startXRef.current = event.clientX;
    setDragging(true);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeRef.current) return;
    const dx = event.clientX - startXRef.current;

    if (!movedRef.current && Math.abs(dx) > DRAG_THRESHOLD) {
      movedRef.current = true;
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        /* 캡처할 수 없는 포인터면 그냥 넘어간다 */
      }
    }
    if (movedRef.current) setDragX(dx);
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeRef.current) return;
    activeRef.current = false;
    setDragging(false);

    try {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    } catch {
      /* 이미 해제됐으면 무시한다 */
    }

    setAnimating(true);
    if (Math.abs(dragX) >= SWIPE_THRESHOLD) {
      exitingRef.current = true;
      setDragX(dragX > 0 ? EXIT_DISTANCE : -EXIT_DISTANCE);
    } else {
      setDragX(0);
    }
  };

  const handleTransitionEnd = () => {
    if (!animating) return;
    setAnimating(false);

    if (exitingRef.current) {
      exitingRef.current = false;
      // transition을 끈 상태에서 다음 카드를 앞으로 당겨 놓아야 되돌아가는 잔상이 없다
      setIndex((prev) => prev + 1);
      setDragX(0);
      onActivePollChange?.(backPoll);
    }
  };

  // 카드를 끌었을 뿐인데 투표가 눌리지 않도록 직후의 click은 버린다
  const handleClickCapture = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!movedRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    movedRef.current = false;
  };

  const frontClasses = [
    styles.layer,
    styles.front,
    dragging ? styles.dragging : '',
    animating ? styles.animated : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={styles.deck}>
      {polls.length > 1 && (
        <div
          className={`${styles.layer} ${styles.back} ${animating ? styles.animated : ''}`}
          style={{
            transform: `translateX(${backShift}px) scale(${backScale})`,
            opacity: backOpacity,
          }}
          aria-hidden="true"
        >
          <PollCard poll={backPoll} selected={votes[backPoll.id] ?? null} onVote={() => {}} />
        </div>
      )}

      <div
        className={frontClasses}
        style={{
          transform: `translateX(${dragX}px)`,
          opacity: exitingRef.current && animating ? 0 : 1,
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onClickCapture={handleClickCapture}
        onTransitionEnd={handleTransitionEnd}
      >
        <PollCard poll={frontPoll} selected={votes[frontPoll.id] ?? null} onVote={onVote} />
      </div>
    </div>
  );
}
