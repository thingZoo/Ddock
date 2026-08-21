"use client";

import { useEffect, useMemo } from "react";
import type { Course } from "@/lib/types";
import { useYouTube } from "./YouTubePlayer";

export function rowBelongsToPart(
  row: Course["script"][number],
  partNo: number,
): boolean {
  return row.partNos?.includes(partNo) ?? row.partNo === partNo;
}

function membershipLabel(row: Course["script"][number]): string | null {
  const values = row.partNos?.length ? row.partNos : row.partNo == null ? [] : [row.partNo];
  return values.length > 0 ? `Pt. ${values.join(" · ")}` : null;
}

/**
 * 스크립트 탭 (355:9911 / 355:9971)
 *
 * 원본 챕터 9개 구조를 그대로 두고, 고른 파트에 속한 문단만 강조해요.
 * 챕터와 파트는 다른 구조라 서로를 대체하지 않습니다.
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

  // 챕터가 바뀌는 첫 문단에만 헤더를 붙여요
  const chapterHeadAt = useMemo(
    () =>
      new Set(
        course.script
          .filter(
            (s, i) =>
              s.chapterId !== null &&
              (i === 0 || s.chapterId !== course.script[i - 1].chapterId),
          )
          .map((s) => s.id)
      ),
    [course.script]
  );

  const chapterIndex = useMemo(
    () => new Map(course.scriptChapters.map((c, i) => [c.id, i + 1])),
    [course.scriptChapters]
  );

  useEffect(() => {
    if (selectedPartNo == null) return;
    const first = course.script.find((s) => rowBelongsToPart(s, selectedPartNo));
    if (!first) return;
    const raf = requestAnimationFrame(() => {
      document
        .getElementById(`seg-${first.id}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => cancelAnimationFrame(raf);
  }, [selectedPartNo, course.script]);

  const selected = course.parts.find((p) => p.partNo === selectedPartNo);

  return (
    <div className="flex flex-col">
      {/* 파트 필터 */}
      <div className="sticky top-0 z-10 bg-white pb-2">
        <div className="scroll-x flex items-center gap-2 px-4 py-3">
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
        {selected && selected.chapterIds.length > 0 && (
          <p className="t-2xs-medium px-4 pb-1 text-zinc-500">
            {selected.title} — 챕터 {selected.chapterIds.join(", ")} 에 걸쳐 있어요
          </p>
        )}
      </div>

      <div className="flex flex-col px-4 pb-10">
        {course.script.map((s) => {
          const showChapter = chapterHeadAt.has(s.id);
          const active = selectedPartNo != null && rowBelongsToPart(s, selectedPartNo);
          const partLabel = membershipLabel(s);
          return (
            <div key={s.id} id={`seg-${s.id}`} className="flex flex-col">
              {showChapter && s.chapterId !== null && (
                <h3 className="t-md-bold pb-2 pt-5 text-zinc-900">
                  CH {String(chapterIndex.get(s.chapterId) ?? "").padStart(2, "0")} ·{" "}
                  {s.chapterLabel}
                </h3>
              )}
              <div
                className={`-mx-2 mb-1 flex flex-col gap-2 rounded-lg px-2 py-2.5 transition-colors ${
                  active ? "bg-orange-25" : ""
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => playFrom(s.timeSec, s.endSec)}
                    className={`t-2xs-medium rounded-chip px-1.5 py-1 ${
                      active ? "bg-orange-500 text-white" : "bg-zinc-100 text-zinc-600"
                    }`}
                  >
                    {s.timeLabel}
                  </button>
                  {partLabel && (
                    <span
                      className={`t-2xs-medium rounded-chip px-1.5 py-1 ${
                        active ? "text-orange-500" : "text-zinc-400"
                      }`}
                    >
                      {partLabel}
                    </span>
                  )}
                </div>
                <p className="t-sm-normal text-zinc-800">{s.text}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
