"use client";

import Image from "next/image";
import type { Part } from "@/lib/types";
import { ProgressGauge } from "./ProgressGauge";
import { useProgress } from "@/lib/progress";

/**
 * 파트 카드 (1186:12706)
 * 가로형이에요 — 왼쪽 썸네일 110×72, 오른쪽 제목·시간·"바로 학습하기", 아래 게이지.
 * 완료한 파트는 배경이 zinc/100 이 되고 썸네일에 검은 막이 덮여요.
 */
export function PartCard({ part, onClick }: { part: Part; onClick?: () => void }) {
  const { doneOf } = useProgress();
  const total = part.steps.length;
  const done = Math.min(doneOf(part.id), total);
  const complete = done >= total && total > 0;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full flex-col gap-5 rounded-card border border-border p-4 text-left ${
        complete ? "bg-zinc-100" : "bg-white"
      }`}
    >
      <div className="flex w-full items-start gap-3">
        <div className="relative h-[72px] w-[110px] shrink-0 overflow-hidden rounded-[4px]">
          <Image src={part.thumbnail} alt="" fill sizes="110px" className="object-cover" />
          {complete && <span className="absolute inset-0 bg-black/40" />}
          <span className="absolute left-0 top-0 p-2">
            <span className="t-xs-normal flex items-center justify-center rounded-[6px] bg-black/70 px-1.5 py-1 text-white backdrop-blur-[1px]">
              Part.{part.partNo}
            </span>
          </span>
        </div>

        <div className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
          <p className="t-sm-bold clamp-2 w-full text-zinc-900">{part.title}</p>
          <p className="t-2xs-medium w-full text-zinc-600">{part.timeLabel}</p>
          <span className="flex items-center gap-[5px] pt-0.5">
            <span className="t-xs-medium text-orange-500">바로 학습하기</span>
            <Image src="/icons/arrow-right-12.svg" alt="" width={12} height={12} />
          </span>
        </div>
      </div>

      <ProgressGauge done={done} total={total} complete={complete} />
    </button>
  );
}
