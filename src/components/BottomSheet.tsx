"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";

/** 바텀시트 껍데기 — 알아보기·더보기가 같이 씁니다 (355:9050) */
export function BottomSheet({
  open,
  onClose,
  children,
  maxHeight = "88%",
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  maxHeight?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-50 flex justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/40" onClick={onClose} />
          <motion.div
            className="absolute bottom-0 w-full overflow-hidden rounded-t-card bg-[var(--bg-modal)]"
            style={{ maxHeight }}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 32, stiffness: 320 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.4 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 110 || info.velocity.y > 600) onClose();
            }}
          >
            <div className="flex justify-center py-3">
              <span className="h-1 w-10 rounded-pill bg-zinc-300" />
            </div>
            <div className="max-h-[calc(100%-40px)] overflow-y-auto overscroll-contain pb-8">
              {children}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
