"use client";

import type { InfoSheet } from "@/lib/types";
import { BottomSheet } from "./BottomSheet";

/** 알아보기 시트 (355:9618) — 카드에 딸린 ⓘ 를 한 장에 모아 보여줘요 */
export function InfoSheetView({
  open,
  onClose,
  sheets,
  onJump,
}: {
  open: boolean;
  onClose: () => void;
  sheets: InfoSheet[];
  onJump?: (sec: number) => void;
}) {
  return (
    <BottomSheet open={open} onClose={onClose}>
      <div className="flex flex-col gap-6 px-4">
        {sheets.map((s) => (
          <div key={s.id} className="flex flex-col gap-2">
            <h3 className="t-md-bold text-zinc-900">{s.question}</h3>
            <p className="t-xs-body whitespace-pre-line text-zinc-700">{s.body}</p>
            {s.timeLabel && (
              <button
                type="button"
                onClick={() => s.timeSec != null && onJump?.(s.timeSec)}
                className="t-xs-bold self-start text-orange-500"
              >
                영상 {s.timeLabel}
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          onClick={onClose}
          className="t-sm-bold mt-2 w-full rounded-card bg-zinc-100 py-4 text-zinc-700"
        >
          확인했어요
        </button>
      </div>
    </BottomSheet>
  );
}
