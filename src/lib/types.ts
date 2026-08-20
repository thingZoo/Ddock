// 디자이너를 위한 AI 브리핑 서비스 — 데이터 모델
// 프로젝트 문서 `B안_카드구성.md` 기준 (v0.6.1 명세 반영 전 임시 필드명)
// 참고: claude/작업현황.md 의 "다음에 할 것" — 필드명은 명세서 확정되면 교체 예정

export type Difficulty = "입문" | "중급" | "심화";

/** 표면에 노출되는 프롬프트 복사 블록 */
export interface PromptBlock {
  id: string;
  code: string;
}

/** ⓘ 바텀시트 — 선택적으로 열어보는 부가 설명 */
export interface InfoSheet {
  id: string;
  question: string; // 바텀시트 제목 (질문형인 경우가 많음)
  body: string; // 본문 (마크다운 유사 텍스트, 줄바꿈은 \n\n 문단 구분)
  timeRange?: string; // 원본 영상 구간 (예: "22:51~24:38")
}

/** ⚠ 주의 배지 — 표면에 항상 노출 (열어보기 전에 알아야 하는 것) */
export interface Warning {
  id: string;
  title: string;
  body: string;
  timeRange?: string;
}

/** STEP — 학습 카드 안의 실행 단위 */
export interface Step {
  id: string;
  order: number;
  title: string;
  timeRange?: string;
  action: string; // 액션 1줄 — 어디를 누르고 뭘 치는지
  prompt?: PromptBlock; // 표면 프롬프트 블록 (8개 STEP에만 존재)
  warnings: Warning[];
  infoSheets: InfoSheet[];
}

/** 학습 카드 — 표면 단위 (B안 기준 5개) */
export interface LearningCard {
  id: string;
  order: number;
  title: string; // 질문형 + feat. 도구명
  timeRange: string;
  summary: string; // 접힌 상태에 보이는 1줄
  tags: string[]; // 태그 칩
  difficulty: Difficulty;
  steps: Step[];
  checkpoint: string; // "✓ 여기까지 하면" 문장
  checkpointTimeRange?: string;
}

/** 하나의 원본 영상(코스) — 지금은 1개만 존재 */
export interface Course {
  id: string;
  title: string;
  sourceUrl: string;
  durationLabel: string;
  description: string;
  tags: string[];
  cards: LearningCard[];
}
