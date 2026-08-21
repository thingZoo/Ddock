"use client";

/** 파트 완료 (355:9402) — 다음 파트로 넘어가는 패널 */
export function CompleteCard({
  hasNext,
  onNext,
  onRestart,
}: {
  hasNext: boolean;
  onNext: () => void;
  onRestart: () => void;
}) {
  return (
    <div className="flex h-[424px] items-center justify-center gap-6 px-6">
      <div
        className="flex h-[300px] w-[200px] flex-col items-center justify-center gap-3 rounded-card px-5 text-center"
        style={{
          boxShadow: "var(--shadow-card)",
          backgroundImage:
            "linear-gradient(137.38deg, rgba(255,255,255,0.85) 4.4%, rgba(250,250,250,0.85) 96.83%)",
        }}
      >
        <p className="t-md-bold text-zinc-900">이 파트를 마쳤어요</p>
        <p className="t-xs-body text-zinc-600">
          별점과 결과물 기록은 다음 업데이트에서 열려요.
        </p>
        <button
          type="button"
          onClick={onRestart}
          className="t-xs-bold mt-2 rounded-pill border border-border bg-zinc-100 px-4 py-3 text-zinc-700"
        >
          처음으로
        </button>
      </div>

      {hasNext && (
        <button type="button" onClick={onNext} className="flex flex-col items-center gap-3">
          <svg width="56" height="32" viewBox="0 0 56 32" className="text-orange-500">
            <path
              d="M2 16h48M38 5l13 11-13 11"
              fill="none"
              stroke="currentColor"
              strokeWidth="4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="t-md-bold whitespace-nowrap text-zinc-900">
            다음 파트를
            <br />
            캐치-업
          </span>
        </button>
      )}
    </div>
  );
}
