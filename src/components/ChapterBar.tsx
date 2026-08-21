"use client";

import type { Part } from "@/lib/types";

/** 가이드 상단 (355:9740 + 355:9744) */
export function ChapterBar({
  part,
  current,
  total,
  finished,
  onPickPart,
}: {
  part: Part;
  current: number;
  total: number;
  finished?: boolean;
  onPickPart?: () => void;
}) {
  const pct = finished ? 100 : (current / total) * 100;

  return (
    <div className="w-full bg-white">
      <button
        type="button"
        onClick={onPickPart}
        className="flex h-12 w-full items-center justify-center gap-1 px-4"
      >
        <span className="t-sm-bold shrink-0 text-zinc-900">{part.chapterNo}</span>
        <span className="t-sm-medium truncate text-zinc-700">{part.title}</span>
        <svg width="16" height="16" viewBox="0 0 16 16" className="shrink-0 text-zinc-500">
          <path
            d="M4 6l4 4 4-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      <div className="flex h-[22px] items-center gap-3 px-5">
        <div className="relative h-1 flex-1 overflow-hidden rounded-pill bg-zinc-200">
          <div
            className="absolute inset-y-0 left-0 rounded-pill bg-orange-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="t-2xs-medium w-[34px] shrink-0 text-right text-zinc-500">
          {finished ? "Finish" : `${current} / ${total}`}
        </span>
      </div>
    </div>
  );
}
