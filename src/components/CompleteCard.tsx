"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  animate,
  motion,
  useMotionValue,
  useMotionValueEvent,
  useTransform,
} from "framer-motion";

/**
 * 파트 완료 (1180:9506)
 *
 * 별점·사진·메모는 시안대로 그려두고 아직 안 눌려요 (Supabase 붙일 때 연결).
 *
 * 스와이프 안내 (1180:9538)
 *  카드가 뜨면 스스로 한 번 왼쪽으로 밀렸다가 제자리로 돌아와요.
 *  미는 동안 오른쪽에 `Next Catch-Up` 이 드러났다가 같이 사라집니다.
 *  안내가 끝나면 리뷰를 쓰든 그냥 넘기든 사용자 마음이에요.
 *  손으로 끌 때도 같은 모습이고, 80px 넘게 끌면 다음 파트로 넘어갑니다.
 */
export function CompleteCard({
  partId,
  hasNext,
  onNext,
  onRestart,
}: {
  /** 파트가 바뀌면 안내를 다시 한 번 보여주려고 받아요 */
  partId: string;
  hasNext: boolean;
  onNext: () => void;
  onRestart: () => void;
}) {
  const x = useMotionValue(0);
  /** 왼쪽으로 140px 밀리면 1 */
  const pulled = useTransform(x, (v) => Math.min(1, Math.max(0, -v / 140)));
  const cardScale = useTransform(pulled, [0, 1], [1, 0.94]);
  const cardOpacity = useTransform(pulled, [0, 1], [1, 0.7]);
  const hintOpacity = useTransform(pulled, [0, 0.1], [0, 1]);

  /** 안내가 실제로 보일 때만 눌리게 (안 보일 때 투명 버튼이 카드를 가리면 안 되니까) */
  const [hintActive, setHintActive] = useState(false);
  useMotionValueEvent(pulled, "change", (v) => setHintActive(v > 0.05));

  /* 저절로 도는 미리보기. 사용자가 손을 대면 바로 멈춰요. */
  const preview = useRef<{ stop: () => void } | null>(null);

  useEffect(() => {
    if (!hasNext) return;
    x.set(0);
    const ctrl = animate(x, [0, -112, -112, 0], {
      duration: 2,
      delay: 0.45,
      times: [0, 0.3, 0.6, 1],
      ease: "easeInOut",
    });
    preview.current = ctrl;
    return () => ctrl.stop();
  }, [hasNext, partId, x]);

  return (
    <div className="relative flex min-h-0 flex-1 items-start justify-center px-5 pb-6 pt-1">
      <motion.div
        className="w-full max-w-[335px] rounded-card"
        style={{
          x,
          scale: cardScale,
          opacity: cardOpacity,
          boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
          backdropFilter: "blur(6px)",
          backgroundImage:
            "linear-gradient(137.38deg, rgba(255,255,255,0.85) 4.4%, rgba(250,250,250,0.85) 96.83%)",
        }}
        drag={hasNext ? "x" : false}
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={0.5}
        onDragStart={() => preview.current?.stop()}
        onDragEnd={(_, info) => {
          if (info.offset.x < -80 || info.velocity.x < -500) onNext();
        }}
      >
        <div className="flex flex-col items-center gap-6 px-5 pb-5 pt-8">
          <p className="t-xl-bold w-full text-zinc-900">이 파트가 도움이 되었나요?</p>

          {/* 별점 — 시안만, 아직 안 눌려요 */}
          <div className="flex items-center gap-3" aria-label="별점 (준비 중)">
            {[0, 1, 2].map((i) => (
              <Image key={i} src="/icons/star-outline.svg" alt="" width={42} height={42} />
            ))}
          </div>

          <div className="flex w-full flex-col gap-3">
            <button
              type="button"
              disabled
              className="flex h-[42px] items-center justify-center gap-1 rounded-card border border-orange-500 text-orange-500"
            >
              <Image src="/icons/camera.svg" alt="" width={16} height={16} />
              <span className="t-sm-bold">사진 첨부하기</span>
            </button>

            <div className="min-h-[74px] rounded-card bg-zinc-100 p-4">
              <p className="t-xs-normal text-[#3a3a3e]">
                막혔던 지점이나 나만의 변형을 적어주세요 (선택)
              </p>
            </div>
          </div>
        </div>

        <div className="flex gap-2 px-5 pb-5">
          <button
            type="button"
            onClick={onRestart}
            className="t-sm-bold flex-1 rounded-[10px] border border-border py-3 text-zinc-700"
          >
            처음으로
          </button>
          <button
            type="button"
            disabled
            className="t-sm-bold flex-1 rounded-[10px] border border-border bg-zinc-100 py-3 text-[#3a3a3e]"
          >
            결과물 로그
          </button>
        </div>
      </motion.div>

      {hasNext && (
        <motion.button
          type="button"
          onClick={onNext}
          aria-label="다음 파트로"
          className={`absolute right-3 top-[36%] z-20 flex flex-col items-center gap-2 ${
            hintActive ? "" : "pointer-events-none"
          }`}
          style={{ opacity: hintOpacity }}
        >
          <Image src="/icons/arrow-right-46.svg" alt="" width={46} height={46} />
          <span className="t-md-semibold whitespace-nowrap text-center text-zinc-900">
            Next
            <br />
            Catch-Up
          </span>
        </motion.button>
      )}
    </div>
  );
}
