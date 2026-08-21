"use client";

import { useEffect, useRef, useState } from 'react';
import { PollCard } from './PollCard';
import type { Poll } from "@/data/ddockHome";
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
const SWIPE_THRESHOLD = 60;
/** 짧게 튕겨도 넘어가도록 하는 속도 기준 (px/ms) */
const FLICK_VELOCITY = 0.35;
/** 넘길 때 카드가 화면 밖으로 빠져나가는 거리 */
const EXIT_DISTANCE = 420;
/** 드래그를 클릭이 아닌 스와이프로 볼 최소 이동 거리 */
const DRAG_THRESHOLD = 4;
/** 카드 전환 애니메이션 길이. CSS transition 과 맞춘다. */
const ANIMATION_MS = 280;

export function PollDeck({ polls, votes, onVote, onActivePollChange }: PollDeckProps) {
  const [index, setIndex] = useState(0);
  const [dragX, setDragX] = useState(0);
  const [dragging, setDragging] = useState(false);
  /** 전환 애니메이션이 도는 동안 true. 새 제스처를 막는 데 쓴다. */
  const [animating, setAnimating] = useState(false);

  const activeRef = useRef(false);
  const movedRef = useRef(false);
  /** 다음(+1) 또는 이전(-1)으로 넘길 때의 방향. 0이면 제자리로 돌아온다. */
  const stepRef = useRef(0);
  const startRef = useRef({ x: 0, time: 0 });
  const lastRef = useRef({ x: 0, time: 0 });
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  if (polls.length === 0) return null;

  const wrap = (value: number) => ((value % polls.length) + polls.length) % polls.length;
  const frontPoll = polls[wrap(index)];
  /* 끌고 있는 방향에 따라 뒤에 비칠 카드가 달라진다 */
  const backPoll = polls[wrap(index + (dragX > 0 ? -1 : 1))];

  // 끈 거리에 비례해 뒤 카드가 제자리로 올라온다 (0 = 뒤, 1 = 앞)
  const progress = Math.min(Math.abs(dragX) / SWIPE_THRESHOLD, 1);
  const backScale = BACK_SCALE + (1 - BACK_SCALE) * progress;
  const backShift = BACK_SHIFT * (1 - progress);
  const backOpacity = 0.8 + 0.2 * progress;

  /**
   * 전환을 마무리한다.
   * transitionend 는 브라우저가 트랜지션을 시작하지 않으면 아예 오지 않아
   * 상태가 고착되므로, 시간 기준으로 직접 끝낸다.
   */
  const finishGesture = () => {
    timerRef.current = null;
    setAnimating(false);
    setDragX(0);
    if (stepRef.current !== 0) {
      const next = index + stepRef.current;
      setIndex(next);
      onActivePollChange?.(polls[wrap(next)]);
      stepRef.current = 0;
    }
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (animating || polls.length < 2) return;
    activeRef.current = true;
    movedRef.current = false;
    const now = event.timeStamp;
    startRef.current = { x: event.clientX, time: now };
    lastRef.current = { x: event.clientX, time: now };
    setDragging(true);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeRef.current) return;
    const dx = event.clientX - startRef.current.x;

    if (!movedRef.current && Math.abs(dx) > DRAG_THRESHOLD) {
      movedRef.current = true;
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        /* 캡처할 수 없는 포인터면 그냥 넘어간다 */
      }
    }
    if (movedRef.current) {
      lastRef.current = { x: event.clientX, time: event.timeStamp };
      setDragX(dx);
    }
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

    const dx = event.clientX - startRef.current.x;
    const elapsed = Math.max(event.timeStamp - lastRef.current.time, 1);
    const velocity = Math.abs(event.clientX - lastRef.current.x) / elapsed;
    // 충분히 끌었거나, 짧아도 빠르게 튕겼으면 넘긴다
    const passed = Math.abs(dx) >= SWIPE_THRESHOLD || velocity >= FLICK_VELOCITY;

    setAnimating(true);
    if (passed && Math.abs(dx) > DRAG_THRESHOLD) {
      stepRef.current = dx > 0 ? -1 : 1;
      setDragX(dx > 0 ? EXIT_DISTANCE : -EXIT_DISTANCE);
    } else {
      stepRef.current = 0;
      setDragX(0);
    }

    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(finishGesture, ANIMATION_MS);
  };

  // 카드를 끌었을 뿐인데 투표가 눌리지 않도록 직후의 click은 버린다
  const handleClickCapture = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!movedRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    movedRef.current = false;
  };

  const exiting = animating && stepRef.current !== 0;

  return (
    <div className={styles.deck}>
      {polls.length > 1 && (
        <div
          className={`${styles.layer} ${styles.back} ${dragging ? styles.instant : ''}`}
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
        className={`${styles.layer} ${styles.front} ${dragging ? styles.instant : ''}`}
        style={{
          transform: `translateX(${dragX}px)`,
          opacity: exiting ? 0 : 1,
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onClickCapture={handleClickCapture}
      >
        <PollCard poll={frontPoll} selected={votes[frontPoll.id] ?? null} onVote={onVote} />
      </div>
    </div>
  );
}
