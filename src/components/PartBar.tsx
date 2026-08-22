"use client";

import Image from "next/image";
import type { Part } from "@/lib/types";

/**
 * 가이드 상단 바 (1206:8912)
 * `‹ Pt. N 제목` 한 줄과 그 아래 진행 바. 마지막 카드에서는 오른쪽이 `Finish` 로 바뀌어요.
 * 줄 전체가 눌려요 — 화살표만 누르게 하면 12px 이라 너무 작아서요.
 */
export function PartBar({
  part,
  current,
  total,
  finished,
  onBack,
}: {
  part: Part;
  current: number;
  total: number;
  finished?: boolean;
  onBack: () => void;
}) {
  const pct = finished ? 100 : (current / total) * 100;

  return (
    <div className="flex w-full shrink-0 flex-col items-center gap-4 px-8 pb-2 pt-3">
      <div className="flex w-full items-center gap-1">
        <button
          type="button"
          onClick={onBack}
          aria-label="파트 목록으로 돌아가기"
          className="flex min-w-0 flex-1 items-center gap-1 text-left"
        >
          <Image src="/icons/arrow-left-12.svg" alt="" width={12} height={12} className="shrink-0" />
          <span className="t-xs-medium shrink-0 text-orange-500">Pt. {part.partNo}</span>
          <span className="t-xs-medium truncate pl-1 text-zinc-700">{part.title}</span>
        </button>
        <span className="t-2xs-semibold shrink-0 text-orange-500">
          {finished ? "Finish" : `${current} / ${total}`}
        </span>
      </div>

      <div className="relative h-2 w-full overflow-hidden rounded-[99px] bg-zinc-300">
        <div
          className="absolute inset-y-0 left-0 rounded-[99px] bg-orange-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
