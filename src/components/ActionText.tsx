import type { ActionLine } from "@/lib/types";

/** 불릿 한 줄 — 문장 안 `코드` 조각은 인라인 코드 칩 (355:9593) */
export function ActionText({ line }: { line: ActionLine }) {
  return (
    <span className="t-sm-normal text-zinc-700">
      {line.parts.map((p, i) =>
        p.kind === "code" ? (
          <span
            key={i}
            className="mx-px rounded-[2px] bg-[rgba(228,228,231,0.6)] px-0.5 text-zinc-900"
          >
            {p.value}
          </span>
        ) : (
          <span key={i}>{p.value}</span>
        )
      )}
    </span>
  );
}
