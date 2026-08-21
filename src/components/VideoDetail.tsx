"use client";

import { useCallback, useState } from "react";
import { YouTubeIcon } from "./YouTubeIcon";
import type { Course } from "@/lib/types";
import { YouTubeProvider } from "./YouTubePlayer";
import { Tabs, type TabKey } from "./Tabs";
import { PartCard } from "./PartCard";
import { MoreSheet } from "./MoreSheet";
import { ChapterBar } from "./ChapterBar";
import { CardStack } from "./CardStack";
import { CompleteCard } from "./CompleteCard";
import { ScriptTab } from "./ScriptTab";
import { LogTab } from "./LogTab";

export function VideoDetail({ course }: { course: Course }) {
  const [tab, setTab] = useState<TabKey>("catchup");
  const [moreOpen, setMoreOpen] = useState(false);
  /** null 이면 파트 목록, 값이 있으면 그 파트의 가이드 */
  const [activePartId, setActivePartId] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);
  const [stepNo, setStepNo] = useState(1);
  const [jumpToSec, setJumpToSec] = useState<number | null>(null);

  const activePart = course.parts.find((p) => p.id === activePartId) ?? null;
  const activeIdx = activePart ? course.parts.indexOf(activePart) : -1;
  const nextPart = activeIdx >= 0 ? course.parts[activeIdx + 1] : undefined;

  const openPart = useCallback((id: string) => {
    setActivePartId(id);
    setFinished(false);
    setStepNo(1);
    setTab("catchup");
    setMoreOpen(false);
  }, []);

  const seeScript = useCallback((sec: number) => {
    setJumpToSec(sec);
    setTab("script");
  }, []);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[var(--app-w)] flex-col bg-white">
      <YouTubeProvider videoId={course.youtubeId} poster={course.thumbnail}>
        {/* 파트 목록 화면일 때만 제목/메타 노출 (355:8868) */}
        {!activePart && (
          <header className="flex flex-col pb-3 pt-3">
            <p className="t-2xs-medium flex items-center gap-1.5 px-4 text-zinc-500">
              {course.breadcrumb.map((b, i) => (
                <span key={b} className="flex items-center gap-1.5">
                  {i > 0 && <span className="h-0.5 w-0.5 rounded-full bg-zinc-300" />}
                  {b}
                </span>
              ))}
            </p>
            <h1 className="t-xl-bold px-4 pt-2 text-zinc-900">{course.title}</h1>
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              className="flex items-center gap-2 px-4 pt-2.5 text-left"
            >
              <YouTubeIcon size={16} />
              <span className="t-2xs-medium flex-1 text-zinc-500">
                {course.channel.name}&nbsp;&nbsp;{course.publishedAt}&nbsp;&nbsp;
                {course.helpLabel}
              </span>
              <svg width="16" height="16" viewBox="0 0 16 16" className="text-zinc-500">
                <path
                  d="M4 6l4 4 4-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </header>
        )}

        <Tabs value={tab} onChange={setTab} />

        {tab === "catchup" &&
          (activePart ? (
            <>
              <ChapterBar
                part={activePart}
                current={finished ? activePart.steps.length : stepNo}
                total={activePart.steps.length}
                finished={finished}
                onPickPart={() => setActivePartId(null)}
              />
              {finished ? (
                <CompleteCard
                  hasNext={Boolean(nextPart)}
                  onNext={() => nextPart && openPart(nextPart.id)}
                  onRestart={() => setActivePartId(null)}
                />
              ) : (
                <CardStack
                  key={activePart.id}
                  part={activePart}
                  onFinish={() => setFinished(true)}
                  onSeeScript={seeScript}
                  onIndexChange={setStepNo}
                />
              )}
            </>
          ) : (
            <>
              <div className="flex items-center gap-1 px-4 pb-2 pt-6">
                <h2 className="t-md-semibold text-zinc-900">CATCH-UP PART</h2>
                <span className="t-md-semibold text-orange-500">{course.parts.length}</span>
              </div>
              <div className="flex flex-col gap-5 px-4 pb-10">
                {course.parts.map((p) => (
                  <PartCard key={p.id} part={p} onClick={() => openPart(p.id)} />
                ))}
              </div>
            </>
          ))}

        {tab === "script" && (
          <ScriptTab
            course={course}
            jumpToSec={jumpToSec}
            onConsumeJump={() => setJumpToSec(null)}
          />
        )}

        {tab === "log" && <LogTab />}

        <MoreSheet
          open={moreOpen}
          onClose={() => setMoreOpen(false)}
          course={course}
          onPickPart={openPart}
        />
      </YouTubeProvider>
    </div>
  );
}
