"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { Part } from "@/lib/types";
import { LearningCard } from "./LearningCard";
import { InfoSheetView } from "./InfoSheetView";
import { useYouTube } from "./YouTubePlayer";
import { useProgress } from "@/lib/progress";

/** 넘기는 방향에 따라 들어오고 나가는 쪽이 바뀌어요 */
const SLIDE = {
  enter: (dir: number) => ({ x: dir > 0 ? 48 : -48, opacity: 0, scale: 0.96 }),
  center: { x: 0, opacity: 1, scale: 1 },
  exit: (dir: number) => ({ x: dir > 0 ? -320 : 320, opacity: 0, scale: 0.96 }),
};

/**
 * 카드 스와이프 스택 (355:9749)
 * 앞 카드 위에 뒤 카드가 0.9배로 깔려요. 좌우로 밀어서 넘깁니다.
 * 카드 크기는 남는 공간에 맞춰 줄어들어요 (피그마 기준 335 × 420).
 */
export function CardStack({
  part,
  index,
  onIndexChange,
  onFinish,
  onSeeScript,
}: {
  part: Part;
  /** 0부터. 탭을 옮겼다 와도 자리를 지키려고 위에서 들고 있어요 */
  index: number;
  onIndexChange: (zeroBased: number) => void;
  onFinish: () => void;
  onSeeScript: () => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const { playing, playFrom, toggle } = useYouTube();
  const [activeStepId, setActiveStepId] = useState<string | null>(null);
  const { setDone } = useProgress();

  const step = part.steps[index];
  const next = part.steps[index + 1];

  /*
   * 넘긴 방향. 앞으로 갈 땐 카드가 왼쪽으로 빠지고 새 카드가 오른쪽에서 들어와요.
   * 뒤로 갈 땐 그 반대로 돌려줘야 튕기는 느낌이 안 나요.
   * AnimatePresence 의 custom 으로 넘겨야 "빠져나가는 카드"까지 방향이 맞습니다.
   */
  const [dir, setDir] = useState<1 | -1>(1);

  function go(d: 1 | -1) {
    const t = index + d;
    if (t < 0) return;
    setDir(d);
    if (t >= part.steps.length) {
      setDone(part.id, part.steps.length);
      onFinish();
      return;
    }
    // 지금 서 있는 자리를 그대로 기록해요 — 뒤로 가면 게이지도 줄어듭니다.
    setDone(part.id, t);
    onIndexChange(t);
  }

  function playSegment() {
    if (playing && activeStepId === step.id) {
      toggle();
      return;
    }
    setActiveStepId(step.id);
    playFrom(step.startSec, step.endSec);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative flex min-h-0 flex-1 items-stretch justify-center px-5 pb-5 pt-1">
        {/* 뒤 카드 — 오른쪽으로 살짝 비껴 보이는 회색 판 하나 (1180:9939) */}
        {next && (
          <div
            className="pointer-events-none absolute inset-x-5 bottom-5 top-1 flex justify-center"
            aria-hidden
          >
            <div className="h-full w-full max-w-[335px] origin-center translate-x-[22px] scale-[0.94] rounded-card bg-[#e8e8e8] opacity-90 shadow-[0_4px_6px_rgba(0,0,0,0.08)]" />
          </div>
        )}

        {/* 앞 카드 */}
        <AnimatePresence initial={false} mode="popLayout" custom={dir}>
          <motion.div
            key={step.id}
            className="z-10 h-full w-full max-w-[335px]"
            custom={dir}
            variants={SLIDE}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ type: "spring", damping: 32, stiffness: 260 }}
            drag="x"
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={0.5}
            onDragEnd={(_, info) => {
              if (info.offset.x < -80 || info.velocity.x < -500) go(1);
              else if (info.offset.x > 80 || info.velocity.x > 500) go(-1);
            }}
          >
            <LearningCard
              step={step}
              onOpenInfo={() => setInfoOpen(true)}
              onPlaySegment={playSegment}
              playing={playing && activeStepId === step.id}
              onSeeScript={onSeeScript}
            />
          </motion.div>
        </AnimatePresence>
      </div>

      <InfoSheetView
        open={infoOpen}
        onClose={() => setInfoOpen(false)}
        sheets={step.infoSheets}
        onJump={(sec) => {
          setInfoOpen(false);
          setActiveStepId(step.id);
          playFrom(sec);
        }}
      />
    </div>
  );
}
