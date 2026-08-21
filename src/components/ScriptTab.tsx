"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Course } from "@/lib/types";
import { useYouTube } from "./YouTubePlayer";

/** 스크립트 탭 — 전체(355:9911) / 구간별(355:9971) */
export function ScriptTab({
  course,
  jumpToSec,
  onConsumeJump,
}: {
  course: Course;
  jumpToSec: number | null;
  onConsumeJump: () => void;
}) {
  const [partNo, setPartNo] = useState<number | null>(null);
  const { playFrom } = useYouTube();
  const listRef = useRef<HTMLDivElement>(null);

  const rows = useMemo(
    () => (partNo == null ? course.script : course.script.filter((s) => s.partNo === partNo)),
    [course.script, partNo]
  );

  // 가이드에서 "구간 스크립트 보기"로 넘어오면 해당 문단으로 스크롤
  useEffect(() => {
    if (jumpToSec == null) return;
    const target = [...course.script]
      .reverse()
      .find((s) => s.timeSec <= jumpToSec);
    if (target) {
      setPartNo(target.partNo);
      requestAnimationFrame(() => {
        document
          .getElementById(`seg-${target.id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
    onConsumeJump();
  }, [jumpToSec, course.script, onConsumeJump]);

  let lastChapter = "";

  return (
    <div className="flex flex-col">
      {/* 파트 필터 */}
      <div className="scroll-x flex items-center gap-2 px-4 py-4">
        <span className="t-xs-medium shrink-0 text-zinc-500">파트별</span>
        {course.parts.map((p) => {
          const on = partNo === p.partNo;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => setPartNo(on ? null : p.partNo)}
              className={`t-xs-medium flex shrink-0 items-center gap-1 rounded-pill border px-2.5 py-1.5 ${
                on
                  ? "border-orange-500 bg-orange-25 text-orange-500"
                  : "border-border bg-white text-zinc-600"
              }`}
            >
              <span
                className={`grid h-3.5 w-3.5 place-items-center rounded-full border ${
                  on ? "border-orange-500" : "border-zinc-300"
                }`}
              >
                <span className="block h-[5px] w-[5px] rounded-full bg-current" />
              </span>
              Pt. {p.partNo}
            </button>
          );
        })}
      </div>

      <div ref={listRef} className="flex flex-col gap-4 px-4 pb-10">
        {rows.map((s) => {
          const showChapter = s.chapter !== lastChapter;
          lastChapter = s.chapter;
          return (
            <div key={s.id} id={`seg-${s.id}`} className="flex flex-col gap-3">
              {showChapter && (
                <h3 className="t-md-bold pt-2 text-zinc-900">{s.chapter}</h3>
              )}
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => playFrom(s.timeSec)}
                  className={`t-2xs-medium w-fit rounded-chip px-1.5 py-1 ${
                    partNo == null ? "bg-zinc-100 text-zinc-600" : "bg-orange-500 text-white"
                  }`}
                >
                  {s.timeLabel}
                </button>
                <p className="t-sm-normal text-zinc-800">{s.text}</p>
              </div>
            </div>
          );
        })}
        {rows.length === 0 && (
          <p className="t-sm-normal py-16 text-center text-zinc-500">
            이 파트의 스크립트가 아직 없어요.
          </p>
        )}
      </div>
    </div>
  );
}
