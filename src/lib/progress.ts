"use client";

import { useCallback, useSyncExternalStore } from "react";

/** partId → 끝낸 STEP 수 */
export type Progress = Record<string, number>;

const KEY = "ddock:progress:v1";
const EMPTY: Progress = {};

let state: Progress = EMPTY;
let loaded = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function load() {
  if (loaded) return;
  loaded = true;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) state = JSON.parse(raw) as Progress;
  } catch {
    /* 저장소를 막아둔 브라우저 — 빈 상태로 시작해요 */
  }
  emit();
}

function persist(next: Progress) {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* 저장 실패해도 화면은 그대로 돌아가요 */
  }
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  load();
  return () => {
    listeners.delete(l);
  };
}

const getSnapshot = () => state;
/** 서버 렌더에서는 항상 빈 값 — 하이드레이션이 어긋나지 않게 */
const getServerSnapshot = () => EMPTY;

/**
 * STEP 진행 상태를 브라우저에 저장해요.
 * 서버가 붙기 전까지는 localStorage 하나로 버팁니다 (기기별로만 남아요).
 */
export function useProgress() {
  const progress = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const doneOf = useCallback((partId: string) => progress[partId] ?? 0, [progress]);

  /** 최소 n개까지 끝난 것으로 표시 — 뒤로 가도 줄지 않아요 */
  const markDone = useCallback((partId: string, n: number) => {
    if (n <= (state[partId] ?? 0)) return;
    persist({ ...state, [partId]: n });
  }, []);

  const resetAll = useCallback(() => persist({}), []);

  return { progress, doneOf, markDone, resetAll };
}
