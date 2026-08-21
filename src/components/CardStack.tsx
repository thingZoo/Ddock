"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { Part } from "@/lib/types";
import { LearningCard } from "./LearningCard";
import { InfoSheetView } from "./InfoSheetView";
import { useYouTube } from "./YouTubePlayer";

/**
 * 카드 스와이프 스택 (355:9749)
 * 앞 카드 335×420, 뒤 카드는 0.9배로 뒤에 깔려요.
 */
export function CardStack({
  part,
  onFinish,
  onSeeScript,
  onIndexChange,
}: {
  part: Part;
  onFinish: () => void;
  onSeeScript: (sec: number) => void;
  onIndexChange?: (oneBased: number) => void;
}) {
  const [index, setIndex] = useState(0);
  const [infoOpen, setInfoOpen] = useState(false);
  const { playing, playFrom, toggle } = useYouTube();
  const [activeStepId, setActiveStepId] = useState<string | null>(null);

  useEffect(() => {
    onIndexChange?.(index + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  const step = part.steps[index];
  const next = part.steps[index + 1];
  const isLast = index === part.steps.length - 1;

  function go(dir: 1 | -1) {
    const t = index + dir;
    if (t < 0) return;
    if (t >= part.steps.length) {
      onFinish();
      return;
    }
    setIndex(t);
    onIndexChange?.(t + 1);
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
    <div className="relative">
      <div className="relative flex h-[424px] w-full items-start justify-center pt-1">
        {/* 뒤 카드 */}
        {next && (
          <div
            className="absolute top-[29px] origin-top scale-90 opacity-60"
            style={{ filter: "blur(0.2px)" }}
          >
            <div className="pointer-events-none">
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
            className="absolute top-1 z-10"
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
              onSeeScript={() => onSeeScript(step.startSec)}
            />
          </motion.div>
        </AnimatePresence>
      </div>

      {/* 넘기기 힌트 + 버튼 (스와이프가 안 되는 환경 대비) */}
      <div className="flex items-center justify-center gap-3 pb-6">
        <button
          type="button"
          onClick={() => go(-1)}
          disabled={index === 0}
          className="t-xs-bold rounded-pill border border-border px-4 py-2 text-zinc-600 disabled:opacity-30"
        >
          이전
        </button>
        <span className="t-2xs-medium text-zinc-500">← 밀어서 넘기기 →</span>
        <button
          type="button"
          onClick={() => go(1)}
          className="t-xs-bold rounded-pill bg-zinc-900 px-4 py-2 text-white"
        >
          {isLast ? "완료" : "다음"}
        </button>
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
