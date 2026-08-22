"use client";

export type TabKey = "catchup" | "script" | "log";

export const TAB_LABELS: Record<TabKey, string> = {
  catchup: "캐치업",
  script: "스크립트",
  log: "로그북",
};

/**
 * 상세 탭 (1186:12690)
 * 밑줄 탭에서 알약형 세그먼트로 바뀌었어요. 회색 트랙 안에서 흰 칩이 움직입니다.
 * 트랙 44 / 칩 36, 라운드 14 / 10.
 */
export function Tabs({
  value,
  onChange,
  tight = false,
}: {
  value: TabKey;
  onChange: (v: TabKey) => void;
  /** 가이드 화면은 위 여백이 조금 좁아요 (12 vs 16) */
  tight?: boolean;
}) {
  const keys: TabKey[] = ["catchup", "script", "log"];

  return (
    <div
      className={`flex w-full shrink-0 justify-center px-4 pb-1 ${tight ? "pt-3" : "pt-4"}`}
      role="tablist"
    >
      <div className="flex h-11 w-full gap-1 overflow-hidden rounded-[14px] bg-zinc-100 p-1">
        {keys.map((k) => {
          const active = k === value;
          return (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(k)}
              className={`grid h-9 flex-1 place-items-center rounded-[10px] transition-colors ${
                active
                  ? "t-sm-semibold bg-zinc-25 text-zinc-900 shadow-[0_1px_4px_rgba(0,0,0,0.08)]"
                  : "t-sm-medium text-zinc-500"
              }`}
            >
              {TAB_LABELS[k]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
