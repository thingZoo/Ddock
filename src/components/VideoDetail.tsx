"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { YouTubeIcon } from "./YouTubeIcon";
import type { Course } from "@/lib/types";
import { YouTubeProvider } from "./YouTubePlayer";
import { Tabs, type TabKey } from "./Tabs";
import { PartCard } from "./PartCard";
import { MoreSheet } from "./MoreSheet";
import { PartBar } from "./PartBar";
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
  /** 0부터. 탭을 옮겼다 돌아와도 보던 카드가 그대로 나와요 */
  const [stepIndex, setStepIndex] = useState(0);
  const [scriptPartNo, setScriptPartNo] = useState<number | null>(null);
  const router = useRouter();

  /*
   * 들어온 길로 되돌린다 — 발견 탭에서 왔으면 발견 탭으로.
   * 링크를 바로 열어 히스토리가 없을 때만 홈으로 보낸다.
   */
  const goBack = useCallback(() => {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/");
  }, [router]);

  const activePart = course.parts.find((p) => p.id === activePartId) ?? null;
  const activeIdx = activePart ? course.parts.indexOf(activePart) : -1;
  const nextPart = activeIdx >= 0 ? course.parts[activeIdx + 1] : undefined;
  const headerMeta = [course.channel.name, course.publishedAt, course.helpLabel].filter(
    (value): value is string => Boolean(value),
  );
  const hasMoreContent =
    headerMeta.length > 0 ||
    course.recommend !== null ||
    course.tools.length > 0 ||
    course.tags.length > 0 ||
    course.relatedVideos.length > 0;

  const openPart = useCallback((id: string) => {
    setActivePartId(id);
    setFinished(false);
    setStepIndex(0);
    setTab("catchup");
    setMoreOpen(false);
  }, []);

  /** 구간 스크립트 보기 — 이 STEP 이 아니라 PART 전체 스크립트를 열어요 */
  const seeScript = useCallback(() => {
    if (activePart) setScriptPartNo(activePart.partNo);
    setTab("script");
  }, [activePart]);

  return (
    <div className="app-shell">
      <YouTubeProvider videoId={course.youtubeId} poster={course.thumbnail} onBack={goBack}>
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
            {hasMoreContent && (
              <button
                type="button"
                onClick={() => setMoreOpen(true)}
                className="flex items-center gap-2 px-4 pt-2.5 text-left"
              >
                <YouTubeIcon size={16} />
                <span className="t-2xs-medium flex-1 text-zinc-500">
                  {headerMeta.length > 0 ? headerMeta.join("\u00a0\u00a0") : "영상 정보"}
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
            )}
          </header>
        )}

        <Tabs value={tab} onChange={setTab} />

        {tab === "catchup" &&
          (activePart ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <PartBar
                part={activePart}
                current={finished ? activePart.steps.length : stepIndex + 1}
                total={activePart.steps.length}
                finished={finished}
                onBack={() => setActivePartId(null)}
              />
              {finished ? (
                <CompleteCard
                  part={activePart}
                  hasNext={Boolean(nextPart)}
                  onNext={() => nextPart && openPart(nextPart.id)}
                  onRestart={() => setActivePartId(null)}
                />
              ) : (
                <CardStack
                  key={activePart.id}
                  part={activePart}
                  index={stepIndex}
                  onIndexChange={setStepIndex}
                  onFinish={() => setFinished(true)}
                  onSeeScript={seeScript}
                />
              )}
            </div>
          ) : (
            <div className="app-scroll">
              <div className="flex items-center gap-1 px-4 pb-2 pt-6">
                <h2 className="t-md-semibold text-zinc-900">CATCH-UP PART</h2>
                <span className="t-md-semibold text-orange-500">{course.parts.length}</span>
              </div>
              <div className="flex flex-col gap-5 px-4 pb-10">
                {course.parts.map((p) => (
                  <PartCard key={p.id} part={p} onClick={() => openPart(p.id)} />
                ))}
              </div>
            </div>
          ))}

        {tab === "script" && (
          <div className="app-scroll">
            <ScriptTab
              course={course}
              selectedPartNo={scriptPartNo}
              onSelectPart={setScriptPartNo}
            />
          </div>
        )}

        {tab === "log" && (
          <div className="app-scroll">
            <LogTab />
          </div>
        )}

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
