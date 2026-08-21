import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ddock — 디자이너를 위한 AI 브리핑",
  description: "영상을 안 봐도 손으로 따라할 수 있는 학습 카드",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#f4f4f5",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className="h-full">
      <head>
        {/* Pretendard 동적 서브셋 — 화면에 쓰인 글자 구간만 내려받아요.
            public/ 에 생성되는 파일이라 next/font 로는 못 걸어서 link 로 붙입니다. */}
        {/* eslint-disable-next-line @next/next/no-css-tags */}
        <link rel="stylesheet" href="/fonts/pretendard.css" />
      </head>
      <body className="flex min-h-[100dvh] justify-center bg-[var(--shell-bg)] sm:items-center">
        {children}
      </body>
    </html>
  );
}
