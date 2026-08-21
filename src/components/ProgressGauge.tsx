/**
 * 파트 카드 게이지 (357:13410)
 * 라벨은 두 겹이에요. 흰 겹을 채움 폭만큼 clip 해서, 오렌지가 라벨에 걸친 만큼만 흰색이 됩니다.
 * 피그마의 "163px 이상이면 흰색" 규칙을 고정 숫자 없이 만족시켜요.
 */
export function ProgressGauge({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.max(0, (done / total) * 100)) : 0;
  const label = `${done} / ${total}`;

  return (
    <div className="relative h-4 w-full overflow-hidden rounded-pill bg-zinc-300">
      {pct > 0 && (
        <div
          className="absolute inset-y-0 left-0 rounded-pill bg-orange-500"
          style={{ width: `${pct}%` }}
        />
      )}
      <span className="t-2xs-bold absolute inset-0 grid place-items-center text-zinc-600">
        {label}
      </span>
      <span
        className="t-2xs-bold absolute inset-0 grid place-items-center text-zinc-25"
        style={{ clipPath: `inset(0 ${100 - pct}% 0 0)` }}
        aria-hidden
      >
        {label}
      </span>
    </div>
  );
}
