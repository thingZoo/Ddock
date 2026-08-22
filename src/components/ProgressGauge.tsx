/**
 * 파트 카드 게이지 (1186:12724)
 * 라벨은 언제나 흰색이에요. 예전엔 오렌지에 걸친 만큼만 흰색으로 잘랐는데,
 * 새 시안은 회색 트랙 위에서도 흰색으로 둡니다.
 */
export function ProgressGauge({
  done,
  total,
  complete = false,
}: {
  done: number;
  total: number;
  /** 완료 카드는 트랙이 한 톤 밝아요 (zinc/200) */
  complete?: boolean;
}) {
  const pct = total > 0 ? Math.min(100, Math.max(0, (done / total) * 100)) : 0;

  return (
    <div
      className={`relative h-4 w-full overflow-hidden rounded-pill ${
        complete ? "bg-zinc-200" : "bg-zinc-300"
      }`}
    >
      {pct > 0 && (
        <div
          className="absolute inset-y-0 left-0 rounded-pill bg-orange-500"
          style={{ width: `${pct}%` }}
        />
      )}
      <span className="t-2xs-semibold absolute inset-0 grid place-items-center text-zinc-25">
        {done} / {total}
      </span>
    </div>
  );
}
