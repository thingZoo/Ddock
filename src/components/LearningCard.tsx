"use client";

import type { Step } from "@/lib/types";
import { ActionText } from "./ActionText";
import { PromptBlock } from "./PromptBlock";
import { WarningBox } from "./WarningBox";
import { PlayPauseButton } from "./PlayPauseButton";

/**
 * 학습 카드 (355:9781)
 *
 * 피그마는 335 × 420 고정이지만 화면이 작아지면 줄어들어야 해서 flex 로 짰어요.
 * 세로 구성: 상단바 52 → 간격 24 → 본문 → 하단 CTA 72
 * 프롬프트가 길어져도 카드가 늘어나지 않아요 (본문에서 4줄로 자름).
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
      className="flex h-full w-full flex-col rounded-card"
      style={{
        boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
        backdropFilter: "blur(6px)",
        backgroundImage:
          "linear-gradient(137.38deg, rgba(255,255,255,0.85) 4.4%, rgba(250,250,250,0.85) 96.83%)",
      }}
      aria-hidden={dimmed}
    >
      {/* 상단 바 */}
      <div className="flex h-[52px] shrink-0 items-start justify-between px-4 pt-2">
        {infoCount > 0 ? (
          <button
            type="button"
            onClick={onOpenInfo}
            className="flex items-center gap-1 rounded-pill border border-zinc-200 bg-zinc-100 px-2.5 py-2 backdrop-blur-[2px]"
          >
            <span className="t-2xs-bold grid w-3.5 place-items-center rounded-pill bg-zinc-700 p-0.5 text-zinc-25">
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

      {/* 본문 — 제목 → gap 24 → 불릿(최소 104) → gap 8 → 프롬프트 / 주의 */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 px-5 pt-6">
        <div className="flex w-full flex-col gap-6">
          <h2 className="t-xl-bold text-zinc-900">{step.title}</h2>
          <ul className="flex min-h-[104px] w-full flex-col gap-1.5">
            {step.actions.map((a, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-orange-500" aria-hidden />
                <ActionText line={a} />
              </li>
            ))}
          </ul>
        </div>

        {step.variant === "prompt" && step.prompt && <PromptBlock prompt={step.prompt} />}
        {step.variant === "warning" && step.warning && <WarningBox warning={step.warning} />}
      </div>

      {/* 하단 CTA */}
      <div className="flex shrink-0 justify-center pb-5 pt-3">
        <button
          type="button"
          onClick={onSeeScript}
          className="t-xs-bold whitespace-nowrap rounded-pill border border-zinc-200 bg-zinc-100 px-4 py-3 text-zinc-700"
        >
          구간 스크립트 보기
        </button>
      </div>
    </div>
  );
}
