"use client";

import type { Part } from "@/lib/types";

/** 파트 완료 (355:9402) — 체크포인트 확인 + 다음 파트로 */
export function CompleteCard({
  part,
  hasNext,
  onNext,
  onRestart,
}: {
  part: Part;
  hasNext: boolean;
  onNext: () => void;
  onRestart: () => void;
}) {
  const cp = part.checkpoint;

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center gap-5 px-5 pb-6">
      <div
        className="flex max-h-full w-full max-w-[210px] flex-col justify-center gap-3 rounded-card p-5"
        style={{
          boxShadow: "var(--shadow-card)",
          backgroundImage:
            "linear-gradient(137.38deg, rgba(255,255,255,0.85) 4.4%, rgba(250,250,250,0.85) 96.83%)",
        }}
      >
        <p className="t-md-bold text-zinc-900">이 파트를 마쳤어요</p>

        <div className="flex flex-col gap-1.5 rounded-xl bg-orange-25 p-3">
          <span className="t-2xs-bold text-orange-500">✓ 여기까지 하면</span>
          {cp.items ? (
            <ul className="flex flex-col gap-1">
              {cp.items.map((it) => (
                <li key={it} className="t-2xs-medium flex gap-1.5 text-zinc-700">
                  <span className="text-orange-500">·</span>
                  {it}
                </li>
              ))}
            </ul>
          ) : (
            <p className="t-2xs-medium text-zinc-700">{cp.text}</p>
          )}
        </div>

        <button
          type="button"
          onClick={onRestart}
          className="t-xs-bold mt-1 rounded-pill border border-border bg-zinc-100 px-4 py-2.5 text-zinc-700"
        >
          목록으로
        </button>
      </div>

      {hasNext && (
        <button type="button" onClick={onNext} className="flex shrink-0 flex-col items-center gap-2">
          <svg width="48" height="28" viewBox="0 0 56 32" className="text-orange-500">
            <path
              d="M2 16h48M38 5l13 11-13 11"
              fill="none"
              stroke="currentColor"
              strokeWidth="4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="t-sm-bold whitespace-nowrap text-zinc-900">
            다음 파트를
            <br />
            캐치-업
          </span>
        </button>
      )}
    </div>
  );
}
