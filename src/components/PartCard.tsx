"use client";

import Image from "next/image";
import type { Part } from "@/lib/types";
import { ProgressGauge } from "./ProgressGauge";
import { useProgress } from "@/lib/progress";

/**
 * 파트 카드 (357:13400 / 13414 / 13428)
 * 배경이 상태에 따라 달라요 — 완료면 zinc/100, 아니면 흰색.
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
      <div className="flex w-full items-center gap-[7px] pr-2">
        <div className="relative h-[72px] w-[110px] shrink-0">
          <Image
            src={part.thumbnail}
            alt=""
            fill
            sizes="110px"
            className="rounded-[2px] object-cover"
          />
          <span className="absolute left-0 top-0 p-1">
            <span
              className="t-2xs-medium flex items-center justify-center rounded-chip px-1 py-0.5 text-zinc-25"
              style={{
                backgroundImage:
                  "linear-gradient(-4.8deg, rgba(17,24,39,0.6) 7.39%, rgba(75,85,99,0.6) 92.65%)",
                backdropFilter: "blur(6px)",
              }}
            >
              Part {part.partNo}
            </span>
          </span>
        </div>

        <div className="flex h-14 min-w-0 flex-1 flex-col justify-center gap-0.5">
          <p className="t-sm-bold clamp-2 text-zinc-900">{part.title}</p>
          <p className="t-2xs-medium text-[#3a3a3e]">{part.timeLabel}</p>
        </div>
      </div>

      <ProgressGauge done={done} total={total} />
    </button>
  );
}
