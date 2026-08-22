"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

/**
 * 바텀시트 껍데기 — 알아보기·더보기가 같이 씁니다 (355:9050)
 *
 * 두 가지로 서요.
 *  - 기본: 내용 높이만큼, 최대 88%. (알아보기)
 *  - `belowVideo`: 처음엔 영상 아래까지만 올라오고, 위로 끌거나 스크롤하면 화면 끝까지. (더보기)
 */
export function BottomSheet({
  open,
  onClose,
  children,
  maxHeight = "88%",
  belowVideo = false,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  maxHeight?: string;
  /** 처음 열릴 때 영상 아래에서 멈췄다가, 올리면 전체 화면이 돼요 */
  belowVideo?: boolean;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  /** 영상 높이(16:9). 시트가 처음 멈추는 자리예요 */
  const [videoH, setVideoH] = useState(211);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!open) return;
    const w = wrapRef.current?.clientWidth ?? 375;
    setVideoH(Math.round((w * 9) / 16));
    setExpanded(false);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  const rest = belowVideo ? (expanded ? 0 : videoH) : 0;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={wrapRef}
          className="absolute inset-0 z-50 flex justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/40" onClick={onClose} />
          <motion.div
            className="absolute bottom-0 flex w-full flex-col overflow-hidden rounded-t-card bg-[var(--bg-modal)]"
            style={belowVideo ? { height: "100%" } : { maxHeight }}
            initial={{ y: "100%" }}
            animate={{ y: rest }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 32, stiffness: 320 }}
            drag="y"
            dragConstraints={{ top: rest, bottom: rest }}
            dragElastic={{ top: belowVideo && !expanded ? 0.6 : 0, bottom: 0.4 }}
            onDragEnd={(_, info) => {
              const up = info.offset.y < -60 || info.velocity.y < -500;
              const down = info.offset.y > 60 || info.velocity.y > 500;
              if (belowVideo && !expanded && up) {
                setExpanded(true);
                return;
              }
              if (belowVideo && expanded && down) {
                setExpanded(false);
                return;
              }
              if (info.offset.y > 110 || info.velocity.y > 600) onClose();
            }}
          >
            <div className="flex shrink-0 justify-center py-3">
              <span className="h-1 w-10 rounded-pill bg-zinc-300" />
            </div>
            {/*
             * 스크롤을 시작하면 시트가 화면 끝까지 올라가요.
             * flex 로 높이를 잡아야 안쪽이 잘리지 않습니다 (예전엔 % 높이라 아래가 잘렸어요).
             */}
            <div
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-5"
              onScroll={(e) => {
                if (belowVideo && !expanded && e.currentTarget.scrollTop > 4) setExpanded(true);
              }}
            >
              {children}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
