"use client";

import { useState } from "react";
import Image from "next/image";
import type { PromptBlock as PromptBlockType } from "@/lib/types";

/**
 * 프롬프트 블록 (355:9792)
 * 카드가 늘어나면 안 돼서 4줄까지만 보여주고 …로 자릅니다.
 * 복사는 잘린 화면 글이 아니라 원문 전체가 들어가요.
 */
export function PromptBlock({ prompt }: { prompt: PromptBlockType }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* 클립보드를 막아둔 브라우저 — 조용히 넘어가요 */
    }
  }

  return (
    <div className="flex h-[104px] w-full flex-col gap-2 rounded-card bg-zinc-100 px-4 pb-4 pt-2">
      <div className="flex items-center justify-between">
        <span className="t-2xs-medium text-icon-inactive">
          {copied ? "복사했어요" : prompt.label ?? "복사해서 그대로 쓰세요"}
        </span>
        <button type="button" onClick={copy} aria-label="프롬프트 전체 복사" className="p-1 -m-1">
          <Image src="/icons/copy.svg" alt="" width={12} height={12} />
        </button>
      </div>
      <p className="t-2xs-semibold clamp-4 whitespace-pre-wrap text-zinc-600">{prompt.code}</p>
    </div>
  );
}
