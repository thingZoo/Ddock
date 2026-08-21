// Ddock — 영상 상세페이지 데이터 모델
// 기준: Figma `완성` 페이지 › `상세페이지_캐치업 플로우` (355:8773)
// 명세: docs/DESIGN_SPEC.md

/** 학습 카드(STEP) 종류 — 표면에 뭘 띄우는지가 달라져요 */
export type StepVariant = "basic" | "prompt" | "warning";

/** ⓘ 바텀시트 — "더 알아보기"로 열리는 Q/A */
export interface InfoSheet {
  id: string;
  question: string;
  body: string;
  /** 원본 영상 위치 (예: "14:33") */
  timeLabel?: string;
  timeSec?: number;
}

/** ⚠ 주의 박스 — 표면에 항상 보여요 */
export interface Warning {
  title: string;
  body: string;
}

/** 복사용 프롬프트 블록 */
export interface PromptBlock {
  /** 화면엔 4줄까지만 보이지만 복사는 이 원문 전체가 들어가요 */
  code: string;
  label?: string;
}

/** 액션 한 줄 — 문장 안에 인라인 코드가 섞일 수 있어요 */
export interface ActionLine {
  /** 코드 조각이면 code, 아니면 text */
  parts: Array<{ kind: "text" | "code"; value: string }>;
}

/** 학습 카드 한 장 */
export interface Step {
  id: string;
  /** 카드 안 순서 (1부터) */
  order: number;
  variant: StepVariant;
  title: string;
  actions: ActionLine[];
  prompt?: PromptBlock;
  warning?: Warning;
  infoSheets: InfoSheet[];
  /** 구간 재생용 */
  startSec: number;
  endSec: number;
}

/** 파트 = 학습 카드 묶음 (첫화면의 카드 하나) */
export interface Part {
  id: string;
  /** 화면에 찍히는 번호 (Part 1) */
  partNo: number;
  /** 챕터 번호 (CH 01) */
  chapterNo: string;
  title: string;
  thumbnail: string;
  /** "09:51-12:36" */
  timeLabel: string;
  startSec: number;
  endSec: number;
  steps: Step[];
  /** 지금까지 끝낸 STEP 수 — MVP에선 시드 값 그대로 씁니다 */
  doneCount: number;
}

export interface Channel {
  name: string;
  avatar: string;
  url: string;
  platform: string;
}

/** 더보기 시트 — 추천 카드 */
export interface Recommend {
  badge: string;
  title: string;
  body: string;
}

/** 더보기 시트 — 이런 도구들을 다뤄요 */
export interface Tool {
  name: string;
  icon: string;
}

export interface ToolHighlight {
  name: string;
  url: string;
  desc: string;
}

/** 더보기 시트 — 이런 영상도 있어요 */
export interface RelatedVideo {
  id: string;
  title: string;
  thumbnail: string;
  duration: string;
  /** 0~1, 이어보기 게이지. 0이면 안 그려요 */
  progress: number;
  channelName: string;
  channelAvatar: string;
  likeLabel: string;
  viewLabel: string;
}

/** 스크립트 한 문단 */
export interface ScriptSegment {
  id: string;
  partNo: number;
  /** "CH 07 · Full live demo setup" */
  chapter: string;
  timeLabel: string;
  timeSec: number;
  text: string;
}

/** 영상 하나 = 상세페이지 하나 */
export interface Course {
  id: string;
  youtubeId: string;
  title: string;
  breadcrumb: string[];
  thumbnail: string;
  channel: Channel;
  publishedAt: string;
  publishedLabel: string;
  ratingLabel: string;
  helpLabel: string;
  viewLabel: string;
  viewCountLabel: string;
  likeLabel: string;
  tags: string[];
  recommend: Recommend;
  tools: Tool[];
  toolHighlight: ToolHighlight;
  relatedVideos: RelatedVideo[];
  parts: Part[];
  script: ScriptSegment[];
}

/** "09:51" / "1:10:08" → 초 */
export function toSec(label: string): number {
  const p = label.split(":").map(Number);
  if (p.length === 3) return p[0] * 3600 + p[1] * 60 + p[2];
  if (p.length === 2) return p[0] * 60 + p[1];
  return Number(label) || 0;
}

/** 초 → "09:51" */
export function toLabel(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** 파트 전체 STEP 수 */
export function totalSteps(part: Part): number {
  return part.steps.length;
}
