import { useEffect, useRef, useState, type ReactNode } from 'react';
import styles from './ScrollRow.module.css';

interface ScrollRowProps {
  children: ReactNode;
  /** 행마다 다른 gap·padding을 주기 위한 추가 클래스 */
  className?: string;
}

/** 드래그를 스크롤로 볼지 클릭으로 볼지 가르는 이동 거리(px) */
const DRAG_THRESHOLD = 4;

/**
 * 가로로 스크롤되는 카드 행.
 *
 * 터치에서는 브라우저 기본 스와이프를 그대로 쓰고, 마우스 환경에서만
 * 세로 휠을 가로 스크롤로 바꾸고 드래그로 끌 수 있게 한다.
 */
export function ScrollRow({ children, className }: ScrollRowProps) {
  const ref = useRef<HTMLDivElement>(null);
  /**
   * 드래그 진행 여부. 상태로 두면 pointerdown 직후의 pointermove가 아직
   * 갱신되지 않은 값을 읽어 첫 움직임을 놓치므로 ref로 관리한다.
   * dragging 상태는 커서 모양에만 쓴다.
   */
  const activeRef = useRef(false);
  const [dragging, setDragging] = useState(false);
  /** 드래그로 움직였는지. 움직였으면 뒤따라오는 click을 삼킨다. */
  const movedRef = useRef(false);
  const startRef = useRef({ x: 0, scrollLeft: 0 });

  // 세로 휠 → 가로 스크롤. preventDefault가 필요해 passive:false로 직접 등록한다.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onWheel = (event: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth) return;
      // 트랙패드 가로 제스처는 브라우저가 이미 처리하므로 건드리지 않는다
      if (Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;

      const next = el.scrollLeft + event.deltaY;
      const clamped = Math.max(0, Math.min(next, el.scrollWidth - el.clientWidth));
      // 이미 끝에 닿았으면 페이지 세로 스크롤을 막지 않는다
      if (clamped === el.scrollLeft) return;

      event.preventDefault();
      el.scrollLeft = clamped;
    };

    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'touch') return;
    const el = ref.current;
    if (!el || el.scrollWidth <= el.clientWidth) return;

    movedRef.current = false;
    startRef.current = { x: event.clientX, scrollLeft: el.scrollLeft };
    activeRef.current = true;
    setDragging(true);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeRef.current) return;
    const el = ref.current;
    if (!el) return;

    const dx = event.clientX - startRef.current.x;
    if (!movedRef.current && Math.abs(dx) > DRAG_THRESHOLD) {
      movedRef.current = true;
      try {
        // 포인터를 잡아두면 행 밖으로 나가도 계속 끌 수 있다.
        // 캡처가 실패하더라도 스크롤 자체는 계속 되어야 한다.
        el.setPointerCapture(event.pointerId);
      } catch {
        /* 캡처할 수 없는 포인터면 그냥 넘어간다 */
      }
    }
    if (movedRef.current) {
      el.scrollLeft = startRef.current.scrollLeft - dx;
    }
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeRef.current) return;
    activeRef.current = false;
    const el = ref.current;
    try {
      if (el?.hasPointerCapture(event.pointerId)) {
        el.releasePointerCapture(event.pointerId);
      }
    } catch {
      /* 이미 해제된 포인터면 무시한다 */
    }
    setDragging(false);
  };

  // 카드를 끌었을 뿐인데 열리는 일이 없도록, 드래그 직후의 click은 버린다.
  const handleClickCapture = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!movedRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    movedRef.current = false;
  };

  return (
    <div
      ref={ref}
      className={[styles.row, dragging ? styles.dragging : '', className]
        .filter(Boolean)
        .join(' ')}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onClickCapture={handleClickCapture}
    >
      {children}
    </div>
  );
}
