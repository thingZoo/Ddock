"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Home } from "@/components/ddock/Home";
import { Explore } from "@/components/ddock/Explore";
import { TabBar, type TabKey } from "@/components/ddock/TabBar";

/**
 * 메인 셸 — 홈/발견 탭을 클라이언트 상태로 전환하고 하단 탭바를 얹어요.
 * 투표를 누르면 결과는 별도 라우트(/poll/[id])로 이동해 뒤로가기가 자연스럽습니다.
 */
export default function Page() {
  const [tab, setTab] = useState<TabKey>("home");
  const router = useRouter();

  return (
    <>
      {tab === "home" ? (
        <Home onPollSelect={(pollId) => router.push(`/poll/${pollId}`)} />
      ) : null}
      {tab === "discover" ? <Explore /> : null}
      <TabBar active={tab} onChange={setTab} />
    </>
  );
}
