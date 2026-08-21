"use client";

import { useEffect } from "react";
import type { Course } from "@/lib/types";
import { useYouTube } from "./YouTubePlayer";

/**
 * 스크립트 탭 — 전체(355:9911) / 파트 선택(355:9971)
 *
 * 파트를 골라도 챕터 구조는 그대로 둡니다. 파트에 속한 문단만 옅게 강조해요.
 * (콘텐츠 명세: PART 가 CHAPTER 를 대체하지 않음)
 */
export function ScriptTab({
  course,
  selectedPartNo,
  onSelectPart,
}: {
  course: Course;
  selectedPartNo: number | null;
  onSelectPart: (partNo: number | null) => void;
}) {
  const { playFrom } = useYouTube();

  // 파트가 선택되면 그 파트의 첫 문단으로 스크롤해요
  useEffect(() => {
    if (selectedPartNo == null) return;
    const first = course.script.find((s) => s.partNo === selectedPartNo);
    if (!first) return;
    const id = requestAnimationFrame(() => {
      document
        .getElementById(`seg-${first.id}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => cancelAnimationFrame(id);
  }, [selectedPartNo, course.script]);

  // 챕터 헤더는 챕터가 바뀌는 첫 문단에만 붙여요
  const chapterHeadAt = new Set(
    course.script
      .filter((s, i) => i === 0 || s.chapter !== course.script[i - 1].chapter)
      .map((s) => s.id)
  );

  return (
    <div className="flex flex-col">
      {/* 파트 필터 */}
      <div className="scroll-x flex items-center gap-2 px-4 py-4">
        <span className="t-xs-medium shrink-0 text-zinc-500">파트별</span>
        {course.parts.map((p) => {
          const on = selectedPartNo === p.partNo;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onSelectPart(on ? null : p.partNo)}
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

      <div className="flex flex-col gap-4 px-4 pb-10">
        {course.script.map((s) => {
          const showChapter = chapterHeadAt.has(s.id);
          const active = selectedPartNo != null && s.partNo === selectedPartNo;
          return (
            <div key={s.id} id={`seg-${s.id}`} className="flex flex-col gap-3">
              {showChapter && <h3 className="t-md-bold pt-2 text-zinc-900">{s.chapter}</h3>}
              <div
                className={`-mx-2 flex flex-col gap-2 rounded-lg px-2 py-2 transition-colors ${
                  active ? "bg-orange-25" : ""
                }`}
              >
                <button
                  type="button"
                  onClick={() => playFrom(s.timeSec)}
                  className={`t-2xs-medium w-fit rounded-chip px-1.5 py-1 ${
                    active ? "bg-orange-500 text-white" : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  {s.timeLabel}
                </button>
                <p className="t-sm-normal text-zinc-800">{s.text}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
