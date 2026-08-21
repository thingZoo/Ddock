"use client";

import { PlayPauseButton } from "./PlayPauseButton";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

type Ctx = {
  playing: boolean;
  ready: boolean;
  /** 지정 초로 이동해서 재생. 끝나는 초를 주면 거기서 멈춰요 */
  playFrom: (sec: number, endSec?: number) => void;
  toggle: (sec?: number) => void;
  pause: () => void;
};

const PlayerCtx = createContext<Ctx | null>(null);
export const useYouTube = () => {
  const c = useContext(PlayerCtx);
  if (!c) throw new Error("YouTubeProvider 안에서 써주세요");
  return c;
};

type YTPlayer = {
  playVideo: () => void;
  pauseVideo: () => void;
  seekTo: (s: number, allowSeekAhead: boolean) => void;
  getCurrentTime: () => number;
  destroy: () => void;
};

declare global {
  interface Window {
    YT?: {
      Player: new (
        el: HTMLElement | string,
        opts: Record<string, unknown>
      ) => YTPlayer;
      PlayerState: { PLAYING: number; PAUSED: number; ENDED: number };
    };
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiPromise: Promise<void> | null = null;
function loadApi(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.YT?.Player) return Promise.resolve();
  if (apiPromise) return apiPromise;
  apiPromise = new Promise<void>((resolve) => {
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prev?.();
      resolve();
    };
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(s);
  });
  return apiPromise;
}

/** 썸네일 자리에 유튜브를 띄우고, 화면 곳곳의 재생 버튼이 같은 플레이어를 보게 해줘요 */
export function YouTubeProvider({
  videoId,
  poster,
  children,
}: {
  videoId: string;
  poster: string;
  children: React.ReactNode;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const stopAtRef = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadApi().then(() => {
      if (cancelled || !hostRef.current || playerRef.current) return;
      playerRef.current = new window.YT!.Player(hostRef.current, {
        videoId,
        playerVars: { playsinline: 1, rel: 0, modestbranding: 1, controls: 1 },
        events: {
          onReady: () => setReady(true),
          onStateChange: (e: { data: number }) => {
            const S = window.YT!.PlayerState;
            setPlaying(e.data === S.PLAYING);
            if (e.data === S.PLAYING) setStarted(true);
          },
        },
      });
    });
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  // 구간 재생 — 끝나는 지점에서 멈춰요
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      const stop = stopAtRef.current;
      const p = playerRef.current;
      if (stop == null || !p) return;
      if (p.getCurrentTime() >= stop) {
        p.pauseVideo();
        stopAtRef.current = null;
      }
    }, 400);
    return () => clearInterval(t);
  }, [playing]);

  const playFrom = useCallback((sec: number, endSec?: number) => {
    const p = playerRef.current;
    if (!p) return;
    stopAtRef.current = endSec ?? null;
    p.seekTo(sec, true);
    p.playVideo();
    setStarted(true);
  }, []);

  const pause = useCallback(() => {
    playerRef.current?.pauseVideo();
  }, []);

  const toggle = useCallback(
    (sec?: number) => {
      const p = playerRef.current;
      if (!p) return;
      if (playing) {
        p.pauseVideo();
      } else {
        if (sec != null) p.seekTo(sec, true);
        stopAtRef.current = null;
        p.playVideo();
        setStarted(true);
      }
    },
    [playing]
  );

  return (
    <PlayerCtx.Provider value={{ playing, ready, playFrom, toggle, pause }}>
      <div className="relative h-[211px] w-full shrink-0 overflow-hidden bg-black">
        <div ref={hostRef} className="absolute inset-0 h-full w-full" />
        {!started && (
          <div
            className="pointer-events-none absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${poster})` }}
          />
        )}
        <HeroPlayButton />
      </div>
      {children}
    </PlayerCtx.Provider>
  );
}

/**
 * 썸네일 가운데 큰 재생 버튼 (360:13602)
 * 재생이 시작되면 숨겨서 유튜브 자체 컨트롤을 쓰게 둡니다.
 */
export function HeroPlayButton() {
  const { playing, toggle } = useYouTube();
  if (playing) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center">
      <div className="pointer-events-auto">
        <PlayPauseButton playing={false} onToggle={() => toggle()} size={70} />
      </div>
    </div>
  );
}
