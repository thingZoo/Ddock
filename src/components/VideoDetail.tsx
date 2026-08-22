"use client";

import { useCallback, useState } from "react";
import Image from "next/image";
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
import { useProgress } from "@/lib/progress";

/** 61,240 → 6.1만 */
function compactCount(label: string) {
  const n = Number(label.replace(/[^0-9]/g, ""));
  if (!n) return label;
  if (n >= 10000) return `${(n / 10000).toFixed(1)}만`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}천`;
  return n.toLocaleString();
}

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
  const { doneOf } = useProgress();

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
  /*
   * 메타행 — 시안대로 짧게 ("2.8점" → "2.8", "61,240" → "6.1만").
   * 어드민에서 발행한 콘텐츠는 채널·날짜·별점이 비어 있을 수 있어 있는 것만 이어붙여요.
   */
  const headerMeta = [
    course.channel.name,
    course.publishedAt,
    course.ratingLabel ? `별점 ${course.ratingLabel.replace("점", "")}` : null,
    course.viewCountLabel ? `조회 ${compactCount(course.viewCountLabel)}` : null,
  ].filter((value): value is string => Boolean(value));
  const hasMoreContent =
    headerMeta.length > 0 ||
    course.recommend !== null ||
    course.tools.length > 0 ||
    course.tags.length > 0 ||
    course.relatedVideos.length > 0;

  /* 하던 데서 이어봐요. 다 끝낸 파트는 마지막 카드부터 다시 넘겨볼 수 있게 합니다. */
  const openPart = useCallback(
    (id: string) => {
      const total = course.parts.find((p) => p.id === id)?.steps.length ?? 0;
      const done = Math.min(doneOf(id), total);
      setActivePartId(id);
      setFinished(false);
      setStepIndex(total > 0 ? Math.min(done, total - 1) : 0);
      setTab("catchup");
      setMoreOpen(false);
    },
    [course.parts, doneOf]
  );

  /** 구간 스크립트 보기 — 이 STEP 이 아니라 PART 전체 스크립트를 열어요 */
  const seeScript = useCallback(() => {
    if (activePart) setScriptPartNo(activePart.partNo);
    setTab("script");
  }, [activePart]);

  /* 파트 목록에서만 보이는 제목·메타 블록 (1186:12670) */
  const metaHeader = (
        <header className="relative flex flex-col gap-1.5 pt-4">
          <p className="t-2xs-normal flex items-center gap-1 px-4 text-[#3a3a3e]">
            {course.breadcrumb.map((b, i) => (
              <span key={b} className="flex items-center gap-1">
                {i > 0 && <span className="h-0.5 w-0.5 rounded-full bg-zinc-400" />}
                {b}
              </span>
            ))}
          </p>

          <h1 className="t-xl-bold truncate px-4 text-black">{course.title}</h1>

          {hasMoreContent && (
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              className="flex items-center justify-between gap-2 px-4 text-left"
            >
              <span className="flex min-w-0 items-center gap-1">
                <YouTubeIcon size={16} />
                <span className="t-2xs-normal truncate text-[#3a3a3e]">
                  {headerMeta.length > 0 ? headerMeta.join(" · ") : "영상 정보"}
                </span>
              </span>
              <Image
                src="/icons/chevron-down.svg"
                alt=""
                width={16}
                height={16}
                className="shrink-0"
              />
            </button>
          )}

          {/* 보관함 — 아직 안 눌려요 (1186:12688) */}
          <button
            type="button"
            disabled
            aria-label="보관함에 담기 (준비 중)"
            className="absolute right-0 top-0 grid h-11 w-11 place-items-center"
          >
            <Image src="/icons/folder.svg" alt="" width={24} height={24} />
          </button>
        </header>
  );

  return (
    <div className="app-shell">
      <YouTubeProvider videoId={course.youtubeId} poster={course.thumbnail} onBack={goBack}>

        {/*
         * 파트 목록 화면에서는 제목·메타도 같이 스크롤돼요. 영상 아래에 붙어 남는 건 탭뿐입니다 (1186:12657).
         * 가이드·스크립트·로그북은 탭이 영상 바로 아래 고정이고 그 아래만 스크롤돼요.
         */}
        {!activePart && tab === "catchup" ? (
          <div className="app-scroll">
            {metaHeader}
            <div className="sticky top-0 z-20 bg-white">
              <Tabs value={tab} onChange={setTab} />
            </div>
            <div className="flex flex-col gap-0.5 px-4 pt-4">
              <div className="flex items-center gap-0.5">
                <h2 className="t-md-semibold text-zinc-900">캐치 포인트</h2>
                <span className="t-md-medium text-orange-500">{course.parts.length}</span>
              </div>
              {course.catchPointSubtitle && (
                <p className="t-xs-normal text-zinc-700">{course.catchPointSubtitle}</p>
              )}
            </div>
            <div className="flex flex-col gap-5 px-4 pb-10 pt-6">
              {course.parts.map((p) => (
                <PartCard key={p.id} part={p} onClick={() => openPart(p.id)} />
              ))}
            </div>
          </div>
        ) : (
          <>
            {!activePart && metaHeader}
            <Tabs value={tab} onChange={setTab} tight={Boolean(activePart)} />
          </>
        )}

        {tab === "catchup" && activePart && (
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
                  partId={activePart.id}
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
        )}

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
