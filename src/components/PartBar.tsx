"use client";

import Image from "next/image";
import type { Part } from "@/lib/types";

/**
 * 가이드 상단 바 (1159:9571 · 1153:2482)
 *
 * 예전엔 "CH 01 제목 ∨" 였는데 두 가지가 어긋나 있었어요.
 *  - ∨ 는 펼쳐진다는 신호인데 실제로는 화면이 바뀜 → ‹ 로 교체
 *  - 실제 데이터를 넣고 보니 챕터와 파트는 완전히 다른 구조 → "Pt. N" 으로 교체
 *
 * 바 전체가 눌려요. 화살표만 누르게 하면 16px 라 너무 작아서요.
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
    <div className="w-full shrink-0 bg-white">
      <div className="flex justify-center px-4 pt-3">
        <button
          type="button"
          onClick={onBack}
          aria-label="파트 목록으로 돌아가기"
          className="flex w-full items-center gap-1.5 rounded-card border border-border bg-zinc-100 px-4 py-3 text-left transition-colors active:bg-zinc-200"
        >
          <Image
            src="/icons/arrow-left.svg"
            alt=""
            width={16}
            height={16}
            className="shrink-0"
          />
          <span className="t-sm-medium shrink-0 text-zinc-600">Pt. {part.partNo}</span>
          <span className="t-sm-medium truncate text-zinc-600">{part.title}</span>
        </button>
      </div>

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
