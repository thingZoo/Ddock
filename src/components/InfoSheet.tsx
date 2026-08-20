"use client";

import { useState } from "react";
import type { InfoSheet as InfoSheetType } from "@/lib/types";

export function InfoSheetTrigger({ sheet }: { sheet: InfoSheetType }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-full border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-600 transition hover:border-neutral-400"
      >
        <span
          className="flex h-4 w-4 items-center justify-center rounded-full bg-neutral-200 text-[10px] font-semibold text-neutral-700"
          aria-hidden
        >
          i
        </span>
        {sheet.question}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <h3 className="text-base font-semibold text-neutral-900">{sheet.question}</h3>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-neutral-400 hover:text-neutral-700"
                aria-label="닫기"
              >
                ✕
              </button>
            </div>
            <p className="whitespace-pre-line text-sm leading-relaxed text-neutral-700">
              {sheet.body}
            </p>
            {sheet.timeRange && (
              <p className="mt-3 text-xs text-neutral-400">{sheet.timeRange}</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
