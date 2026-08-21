"use client";

import type { Step } from "@/lib/types";
import { ActionText } from "./ActionText";
import { PromptBlock } from "./PromptBlock";
import { WarningBox } from "./WarningBox";
import { PlayPauseButton } from "./PlayPauseButton";

/**
 * 학습 카드 (355:9781)
 * 335 × 420 고정. 프롬프트가 길어져도 카드는 안 늘어나요.
 */
export function LearningCard({
  step,
  onOpenInfo,
  onPlaySegment,
  playing,
  onSeeScript,
  dimmed = false,
}: {
  step: Step;
  onOpenInfo: () => void;
  onPlaySegment: () => void;
  playing: boolean;
  onSeeScript: () => void;
  dimmed?: boolean;
}) {
  const infoCount = step.infoSheets.length;

  return (
    <div
      className="relative h-[420px] w-[335px] shrink-0 rounded-card"
      style={{
        boxShadow: "var(--shadow-card)",
        backdropFilter: "blur(6px)",
        backgroundImage:
          "linear-gradient(137.38deg, rgba(255,255,255,0.85) 4.4%, rgba(250,250,250,0.85) 96.83%)",
      }}
      aria-hidden={dimmed}
    >
      {/* 상단 바 */}
      <div className="absolute left-0 top-0 flex w-full items-center justify-between px-4 pt-2">
        {infoCount > 0 ? (
          <button
            type="button"
            onClick={onOpenInfo}
            className="flex items-center gap-1 rounded-pill border border-border bg-zinc-100 px-2.5 py-1.5"
          >
            <span className="t-2xs-bold grid h-[18px] w-[18px] place-items-center rounded-pill bg-border text-zinc-600">
              {infoCount}
            </span>
            <span className="t-2xs-bold text-zinc-600">더 알아보기</span>
          </button>
        ) : (
          <span />
        )}
        <PlayPauseButton
          playing={playing}
          onToggle={onPlaySegment}
          size={44}
          label="이 구간 재생"
        />
      </div>

      {/* 본문 — 피그마 355:9782 구조 그대로
          제목 → gap 24 → 불릿 영역(104 고정) → gap 8 → 프롬프트 / 주의
          불릿 영역을 고정해야 줄 수가 달라져도 아래 박스 위치가 안 흔들려요 */}
      <div className="absolute left-5 right-5 top-[76px] flex h-[270px] flex-col items-center gap-2">
        <div className="flex w-full flex-col gap-6">
          <h2 className="t-xl-bold text-zinc-900">{step.title}</h2>
          <ul className="flex min-h-[104px] w-full flex-col gap-1.5">
            {step.actions.map((a, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-orange-500" />
                <ActionText line={a} />
              </li>
            ))}
          </ul>
        </div>

        {step.variant === "prompt" && step.prompt && <PromptBlock prompt={step.prompt} />}
        {step.variant === "warning" && step.warning && <WarningBox warning={step.warning} />}
      </div>

      {/* 하단 CTA */}
      <div className="absolute bottom-0 left-[108px] right-[108px] pb-5 pt-3">
        <button
          type="button"
          onClick={onSeeScript}
          className="t-xs-bold w-full whitespace-nowrap rounded-pill border border-border bg-zinc-100 px-4 py-3 text-zinc-700"
        >
          구간 스크립트 보기
        </button>
      </div>
    </div>
  );
}
