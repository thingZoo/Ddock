"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Home } from "@/components/ddock/Home";
import { Explore } from "@/components/ddock/Explore";
import { TabBar, TAB_KEYS, type TabKey } from "@/components/ddock/TabBar";
import { exploreTabs, type ExploreTab } from "@/data/ddockExplore";

/**
 * 메인 셸 — 어떤 탭을 보고 있는지를 URL 에 둬요.
 *   /                          홈
 *   /?tab=discover             발견
 *   /?tab=discover&sub=동영상   발견 › 동영상
 * 상세페이지에 들어갔다 뒤로 나와도 보던 자리가 그대로 남습니다.
 * 투표 결과는 별도 라우트(/poll/[id])예요.
 */
function Shell() {
  const router = useRouter();
  const params = useSearchParams();

  const rawTab = params.get("tab");
  const tab: TabKey = TAB_KEYS.includes(rawTab as TabKey) ? (rawTab as TabKey) : "home";

  const rawSub = params.get("sub");
  const subTab: ExploreTab = exploreTabs.includes(rawSub as ExploreTab)
    ? (rawSub as ExploreTab)
    : "ALL";

  /** 홈은 쿼리 없이 `/` 로 둬서 주소가 지저분해지지 않게 해요 */
  const goTab = (key: TabKey) => router.push(key === "home" ? "/" : `/?tab=${key}`);

  /* 발견 안쪽 탭은 히스토리를 쌓지 않아요. 뒤로가기가 탭 되짚기가 되면 답답하니까요. */
  const goSubTab = (next: ExploreTab) =>
    router.replace(
      next === "ALL" ? "/?tab=discover" : `/?tab=discover&sub=${encodeURIComponent(next)}`,
      { scroll: false }
    );

  const openVideo = (courseId: string) => router.push(`/videos/${courseId}`);

  return (
    <>
      {tab === "home" ? (
        <Home
          onPollSelect={(pollId) => router.push(`/poll/${pollId}`)}
          onVideoSelect={openVideo}
        />
      ) : null}
      {tab === "discover" ? (
        <Explore tab={subTab} onTabChange={goSubTab} onVideoSelect={openVideo} />
      ) : null}
      <TabBar active={tab} onChange={goTab} />
    </>
  );
}

export default function Page() {
  // useSearchParams 는 Suspense 안에서 써야 해요 (Next.js 요구사항)
  return (
    <Suspense fallback={null}>
      <Shell />
    </Suspense>
  );
}
