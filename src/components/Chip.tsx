import Image from "next/image";

/** 사각 칩 — 태그 목록용 (355:9147) */
export function SquareChip({ label }: { label: string }) {
  return (
    <span className="t-xs-medium inline-flex items-center justify-center gap-1 rounded-chip bg-zinc-100 px-1 py-0.5 text-zinc-600">
      {label}
    </span>
  );
}

/** 알약 칩 — 더보기 메타용 (355:9057). 아이콘 크기가 제각각이라 size 를 받아요 */
export function PillChip({
  icon,
  iconSize = 14,
  label,
  selected = false,
}: {
  icon?: string;
  iconSize?: number;
  label: string;
  selected?: boolean;
}) {
  return (
    <span
      className={`t-xs-medium inline-flex items-center justify-center gap-1 rounded-pill px-2.5 py-1.5 ${
        selected ? "bg-zinc-800 text-white" : "bg-zinc-100 text-zinc-500"
      }`}
    >
      {icon && (
        <Image src={icon} alt="" width={iconSize} height={iconSize} className="shrink-0" />
      )}
      {label}
    </span>
  );
}
