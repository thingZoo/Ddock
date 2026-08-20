"use client";

import { useState } from "react";
import type { PromptBlock } from "@/lib/types";

export function PromptBlockView({ prompt }: { prompt: PromptBlock }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(prompt.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API 미지원 브라우저 — 조용히 무시
    }
  }

  return (
    <div className="rounded-xl border border-neutral-200 bg-neutral-900 text-neutral-100">
      <div className="flex items-center justify-between border-b border-neutral-700 px-3 py-2">
        <span className="text-xs font-medium text-neutral-400">프롬프트</span>
        <button
          type="button"
          onClick={handleCopy}
          className="rounded-md bg-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-100 transition hover:bg-neutral-700"
        >
          {copied ? "복사됨" : "복사"}
        </button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words px-3 py-3 text-sm leading-relaxed">
        {prompt.code}
      </pre>
    </div>
  );
}
