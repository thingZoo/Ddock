"use client";

export type TabKey = "catchup" | "script" | "log";

export const TAB_LABELS: Record<TabKey, string> = {
  catchup: "캐치업",
  script: "스크립트",
  log: "로그북",
};

/** Tabs/Line/ProductDetail (355:8932) — 3등분, 활성 표시는 라벨 폭만큼 2px */
export function Tabs({
  value,
  onChange,
}: {
  value: TabKey;
  onChange: (v: TabKey) => void;
}) {
  const keys: TabKey[] = ["catchup", "script", "log"];
  return (
    <div className="relative w-full border-b border-border bg-white">
      <div className="flex">
        {keys.map((k) => {
          const active = k === value;
          return (
            <button
              key={k}
              type="button"
              onClick={() => onChange(k)}
              className="relative flex h-10 flex-1 items-center justify-center"
            >
              <span
                className={`${active ? "t-sm-bold text-zinc-900" : "t-sm-medium text-zinc-500"} relative pb-0.5`}
              >
                {TAB_LABELS[k]}
                {active && (
                  <span className="absolute -bottom-[7px] left-0 h-0.5 w-full rounded-pill bg-zinc-900" />
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
