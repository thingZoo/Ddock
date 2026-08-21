"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { Part } from "@/lib/types";
import { LearningCard } from "./LearningCard";
import { InfoSheetView } from "./InfoSheetView";
import { useYouTube } from "./YouTubePlayer";
import { useProgress } from "@/lib/progress";

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
  const { markDone } = useProgress();

  const step = part.steps[index];
  const next = part.steps[index + 1];

  function go(dir: 1 | -1) {
    const t = index + dir;
    if (t < 0) return;
    // 앞으로 넘길 때만 "여기까지 했다"로 기록해요. 뒤로 가도 줄지 않습니다.
    if (dir === 1) markDone(part.id, index + 1);
    if (t >= part.steps.length) {
      onFinish();
      return;
    }
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
      <div className="relative flex min-h-0 flex-1 items-stretch justify-center px-5 pb-1 pt-1">
        {/* 뒤 카드 */}
        {next && (
          <div className="pointer-events-none absolute inset-x-5 inset-y-1 flex justify-center overflow-hidden opacity-60">
            <div className="h-full w-full max-w-[335px] origin-top translate-y-6 scale-90">
              <LearningCard
                step={next}
                onOpenInfo={() => {}}
                onPlaySegment={() => {}}
                playing={false}
                onSeeScript={() => {}}
                dimmed
              />
            </div>
          </div>
        )}

        {/* 앞 카드 */}
        <AnimatePresence initial={false} mode="popLayout">
          <motion.div
            key={step.id}
            className="z-10 h-full w-full max-w-[335px]"
            initial={{ x: 40, opacity: 0, scale: 0.96 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            exit={{ x: -320, opacity: 0 }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
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

      {/* 넘기기 안내 */}
      <div className="flex shrink-0 items-center justify-center py-3">
        <span className="t-2xs-medium text-zinc-500">← 밀어서 넘기기 →</span>
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
