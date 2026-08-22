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

  /**
   * 지금 몇 번째 카드까지 왔는지 그대로 기록해요.
   * 뒤로 가거나 "처음으로" 를 누르면 게이지도 같이 줄어듭니다.
   */
  const setDone = useCallback((partId: string, n: number) => {
    const next = Math.max(0, n);
    if ((state[partId] ?? 0) === next) return;
    persist({ ...state, [partId]: next });
  }, []);

  const resetAll = useCallback(() => persist({}), []);

  return { progress, doneOf, setDone, resetAll };
}
