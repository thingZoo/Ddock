"use client";

import Image from "next/image";

/**
 * 재생 / 멈춤 (360:13595 · 360:13690)
 * 컴포넌트 하나에 상태 둘. 크기는 두 자리에서 다르게 써요 — 썸네일 70, 카드 44.
 */
export function PlayPauseButton({
  playing,
  onToggle,
  size = 70,
  label,
}: {
  playing: boolean;
  onToggle: () => void;
  /** 바깥 박스 (터치 영역). 아이콘은 박스 - 22 */
  size?: 70 | 44;
  label?: string;
}) {
  const icon = size === 70 ? 48 : 32;
  const barH = size === 70 ? 20 : 14;
  const barW = size === 70 ? 4 : 3;
  const gap = size === 70 ? 6 : 4;

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={label ?? (playing ? "멈춤" : "재생")}
      className="relative grid shrink-0 place-items-center p-2"
      style={{ width: size, height: size }}
    >
      <span className="relative block" style={{ width: icon, height: icon }}>
        <Image
          src={size === 70 ? "/icons/play-48.svg" : "/icons/play-32.svg"}
          alt=""
          width={icon}
          height={icon}
          className={playing ? "opacity-100" : "opacity-100"}
          priority
        />
        {playing && (
          <span
            className="absolute inset-0 flex items-center justify-center"
            style={{ gap }}
          >
            <i
              className="block rounded-[1px] bg-white"
              style={{ width: barW, height: barH, boxShadow: "var(--shadow-bar)" }}
            />
            <i
              className="block rounded-[1px] bg-white"
              style={{ width: barW, height: barH, boxShadow: "var(--shadow-bar)" }}
            />
          </span>
        )}
      </span>
    </button>
  );
}
