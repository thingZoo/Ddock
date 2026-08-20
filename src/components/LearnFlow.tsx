"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { Course } from "@/lib/types";
import { PromptBlockView } from "./PromptBlockView";
import { WarningBadge } from "./WarningBadge";
import { InfoSheetTrigger } from "./InfoSheet";

/**
 * 따라잡기 탭 — 시안 B (카드형 넘기기)
 * 학습 카드 안에서 STEP을 하나씩 넘기고, 카드 끝에서 체크포인트를 확인해요.
 */
export function LearnFlow({ course }: { course: Course }) {
  const [cardIndex, setCardIndex] = useState(0);
  const [stepIndex, setStepIndex] = useState(0);
  const [done, setDone] = useState<Set<string>>(new Set());

  const card = course.cards[cardIndex];
  const step = card.steps[stepIndex];
  const isLastStep = stepIndex === card.steps.length - 1;
  const isLastCard = cardIndex === course.cards.length - 1;

  const totalSteps = useMemo(
    () => course.cards.reduce((sum, c) => sum + c.steps.length, 0),
    [course]
  );
  const completedSteps = useMemo(
    () =>
      course.cards
        .slice(0, cardIndex)
        .reduce((sum, c) => sum + c.steps.length, 0) + stepIndex,
    [course, cardIndex, stepIndex]
  );

  function goPrevStep() {
    if (stepIndex > 0) {
      setStepIndex(stepIndex - 1);
    } else if (cardIndex > 0) {
      const prevCard = course.cards[cardIndex - 1];
      setCardIndex(cardIndex - 1);
      setStepIndex(prevCard.steps.length - 1);
    }
  }

  function goNextStep() {
    if (!isLastStep) {
      setStepIndex(stepIndex + 1);
      return;
    }
    setDone((prev) => new Set(prev).add(card.id));
    if (!isLastCard) {
      setCardIndex(cardIndex + 1);
      setStepIndex(0);
    }
  }

  const atVeryStart = cardIndex === 0 && stepIndex === 0;
  const finished = isLastCard && isLastStep && done.has(card.id);

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 pb-10 pt-6">
      <div>
        <Link href={`/videos/${course.id}`} className="text-xs text-neutral-400 hover:text-neutral-600">
          ← {course.title}
        </Link>
      </div>

      {/* 진행도 */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-xs text-neutral-500">
          <span>
            카드 {cardIndex + 1}/{course.cards.length} · STEP {stepIndex + 1}/{card.steps.length}
          </span>
          <span>
            {completedSteps}/{totalSteps}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-100">
          <div
            className="h-full rounded-full bg-neutral-800 transition-all"
            style={{ width: `${(completedSteps / totalSteps) * 100}%` }}
          />
        </div>
      </div>

      {/* 학습 카드 헤더 */}
      <div className="rounded-2xl border border-neutral-200 bg-white p-4">
        <p className="text-xs font-medium text-neutral-400">{card.timeRange}</p>
        <h1 className="mt-1 text-lg font-bold leading-snug text-neutral-900">{card.title}</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">{card.summary}</p>
      </div>

      {!finished ? (
        <div className="rounded-2xl border border-neutral-200 bg-white p-5">
          <p className="text-xs font-medium text-neutral-400">
            STEP {step.order} · {step.timeRange}
          </p>
          <h2 className="mt-1 text-base font-semibold text-neutral-900">{step.title}</h2>

          <div className="mt-3 rounded-xl bg-neutral-50 p-3">
            <p className="text-sm font-medium text-neutral-500">액션</p>
            <p className="mt-1 text-sm leading-relaxed text-neutral-800">{step.action}</p>
          </div>

          {step.warnings.length > 0 && (
            <div className="mt-3 flex flex-col gap-2">
              {step.warnings.map((w) => (
                <WarningBadge key={w.id} warning={w} />
              ))}
            </div>
          )}

          {step.prompt && (
            <div className="mt-3">
              <PromptBlockView prompt={step.prompt} />
            </div>
          )}

          {step.infoSheets.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {step.infoSheets.map((s) => (
                <InfoSheetTrigger key={s.id} sheet={s} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-2xl border border-neutral-200 bg-neutral-900 p-5 text-neutral-50">
          <p className="text-sm font-medium text-neutral-300">✓ 마지막 체크포인트</p>
          <p className="mt-1.5 text-sm leading-relaxed whitespace-pre-line">{card.checkpoint}</p>
          <p className="mt-4 text-sm font-semibold text-neutral-100">
            수고하셨어요 — 5개 학습 카드를 모두 마쳤어요.
          </p>
          <Link
            href={`/videos/${course.id}`}
            className="mt-4 inline-block rounded-lg bg-white px-4 py-2 text-sm font-medium text-neutral-900"
          >
            상세페이지로 돌아가기
          </Link>
        </div>
      )}

      {/* STEP 끝, 카드 안 끝났을 때: 체크포인트 미리보기 없이 바로 다음 카드로 진입하도록 처리됨 */}
      {isLastStep && !finished && (
        <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
          <p className="text-xs font-medium text-neutral-500">✓ 여기까지 하면</p>
          <p className="mt-1 text-sm leading-relaxed text-neutral-700 whitespace-pre-line">
            {card.checkpoint}
          </p>
        </div>
      )}

      {!finished && (
        <div className="flex items-center justify-between gap-3 pt-1">
          <button
            type="button"
            onClick={goPrevStep}
            disabled={atVeryStart}
            className="rounded-lg border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-600 disabled:opacity-30"
          >
            이전
          </button>
          <button
            type="button"
            onClick={goNextStep}
            className="flex-1 rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white"
          >
            {isLastStep ? (isLastCard ? "완료" : "다음 카드로") : "다음 STEP"}
          </button>
        </div>
      )}
    </div>
  );
}
