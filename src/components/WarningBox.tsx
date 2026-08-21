import Image from "next/image";
import type { Warning } from "@/lib/types";

/** 주의 박스 (355:9596) — RED/25 배경 + Red/50 테두리 + RED/100 제목 */
export function WarningBox({ warning }: { warning: Warning }) {
  return (
    <div
      className="flex w-full flex-col gap-2 rounded-card p-4"
      style={{
        background: "var(--red-25)",
        border: "1px solid var(--red-50)",
      }}
    >
      <div className="flex items-center gap-1">
        <Image src="/icons/warning.svg" alt="" width={12} height={12} className="shrink-0" />
        <span className="t-2xs-bold" style={{ color: "var(--red-100)" }}>
          {warning.title}
        </span>
      </div>
      <p className="t-2xs-normal text-zinc-600">{warning.body}</p>
    </div>
  );
}
