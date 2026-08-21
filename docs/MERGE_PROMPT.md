# 팀원 홈 화면 합치기 — 작업 지시서

> 이 문서를 Claude Code(또는 작업하는 사람)에게 그대로 붙여넣으면 돼요.
> 2026-08-21 기준 · 저장소 `thingZoo/Ddock` · main `b0afbbd`

---

## 0. 먼저 알아야 할 것

이 저장소에는 **성격이 다른 작업 세 갈래**가 섞여 있어요. 헷갈리면 서로 덮어씁니다.

| 갈래 | 무엇 | 어디 | 상태 |
|---|---|---|---|
| A. 전처리 파이프라인 | 유튜브 자막을 받아 한국어로 정규화 | `internal-tools/youtube-content-pipeline/` | main 에 병합됨 (PR #2) |
| B. 콘텐츠 큐레이션 | 전처리 결과 → PART/STEP 자동 생성 | `feature/content-curation-v01` | 브랜치에만 있음 |
| **C. 영상 상세페이지 (이번 작업)** | **Next.js 화면** | **`src/`, `public/`, `scripts/`, `docs/`** | **main 에 병합됨 (PR #3·#4·#5)** |

**C는 이미 main 에 들어가 있어요.** `feature/video-detail-page` 브랜치에 main 보다 새로운 커밋은 없습니다.

B 브랜치는 `internal-tools/` 만 건드리고 `src/` 는 한 줄도 안 바꿨어요. 그래서 A·B·C 는 파일이 겹치지 않고, 순서 상관없이 합쳐집니다.

---

## 1. 이번에 할 일

팀원이 만든 **메인 홈 화면**을 main 에 합쳐요. 홈에서 영상을 고르면 이미 있는 상세페이지로 들어가게 이어붙이는 게 전부입니다.

```
팀원          메인 홈 (영상 목록)
                │  영상 카드 탭
                ▼
이미 있음      영상 상세페이지  /videos/[courseId]
```

---

## 2. 접점은 딱 두 개

### 2-1. 라우트

홈에서 이렇게 보내면 돼요.

```tsx
import Link from "next/link";
<Link href={`/videos/${course.id}`}>…</Link>
```

`src/app/videos/[courseId]/page.tsx` 는 이미 있어요. **건드리지 마세요.**

### 2-2. Course 최소 필드

`src/lib/types.ts` 의 `Course` 는 필드가 많지만, **홈이 알아야 할 건 세 개뿐**이에요.

```ts
{ id: string; title: string; thumbnail: string }
```

나머지(`youtubeId` `parts` `script` `scriptChapters` …)는 상세페이지 전용이라 홈에서 안 읽어도 됩니다.

영상 목록은 `src/data/course.ts` 의 `allCourses` 를 그대로 쓰세요. 지금은 실제 영상 1개(`vI4RdXMSq8c`)가 들어 있어요.

```ts
import { allCourses } from "@/data/course";
```

---

## 3. 지금 `src/app/page.tsx` 는 임시예요

제가 만들어둔 홈은 상세페이지로 들어가는 입구만 있는 **자리 표시용**이에요.
팀원 홈 화면으로 **통째로 교체**하면 됩니다. 지우고 새로 써도 괜찮아요.

---

## 4. 재사용해야 하는 것 (새로 만들지 마세요)

### 4-1. 앱 틀 — `.app-shell` / `.app-scroll`

`src/app/globals.css` 에 있어요. 홈 화면도 이걸 써야 상세페이지와 크기·비율이 맞아요.

```
폰 (< 480px)      100% 폭 · 100dvh — 화면을 꽉 채움
데스크톱 (>= 480) 375 × min(812, 100dvh - 48) 폰 프레임 · 라운드 24 · 그림자
바깥 배경          --shell-bg (#F4F4F5)
```

```tsx
<div className="app-shell">
  {/* 위에 고정될 것 (헤더 등) */}
  <div className="app-scroll">
    {/* 스크롤될 목록 */}
  </div>
</div>
```

**페이지 전체가 스크롤되면 안 돼요.** 틀 안에서만 스크롤합니다.
`min-h-screen` 이나 `<body>` 스크롤을 새로 만들지 마세요.

### 4-2. 디자인 토큰

`globals.css` 의 CSS 변수와 `t-*` 타이포 유틸을 쓰세요. 피그마와 1:1 로 맞춰둔 값이에요.

```
색     --zinc-950/900/800/700/600/500/300/200/100/25, --orange-500/200/25,
       --red-100/25/50, --blue-09/03, --border, --chip-bg, --chip-selected
모양   --r-card 12 / --r-pill 100 / --r-chip 4 / --shadow-card
타이포 t-xl-bold, t-md-bold, t-md-semibold, t-sm-bold/semibold/medium/normal,
       t-xs-bold/semibold/medium/normal/body, t-2xs-bold/semibold/medium/normal
```

**하드코딩한 hex 나 `text-[15px]` 같은 임의 값을 새로 넣지 마세요.** 근거는 `docs/DESIGN_SPEC.md` 에 있어요.

### 4-3. 바로 쓸 수 있는 컴포넌트

| 컴포넌트 | 쓰임 |
|---|---|
| `PartCard` + `ProgressGauge` | 파트 카드와 게이지 |
| `Chip` (`SquareChip` / `PillChip`) | 태그 칩, 메타 칩 |
| `BottomSheet` | 바텀시트 껍데기 (드래그로 닫힘) |
| `PlayPauseButton` | 재생 / 멈춤 (70px · 44px) |
| `YouTubeIcon` | 유튜브 마크 |

`Tabs` 는 상세페이지 전용(`캐치업/스크립트/로그북`)이에요. 홈에 탭이 필요하면 따로 만드세요.

### 4-4. 진행 상태

`src/lib/progress.ts` — `useProgress()` 하나로 읽고 씁니다.

```tsx
const { doneOf, markDone } = useProgress();
doneOf("part-1")            // 끝낸 STEP 수
markDone("part-1", 3)       // 3개까지 끝난 걸로 표시 (줄어들지 않음)
```

`localStorage` 키는 `ddock:progress:v1`. 홈에서 "이어서 보기" 같은 걸 만든다면 이걸 읽으세요.
**저장 방식을 새로 만들지 마세요.** 서버가 붙으면 이 파일 하나만 갈아끼웁니다.

---

## 5. 건드리면 안 되는 것

```
src/app/videos/[courseId]/page.tsx     상세페이지 라우트
src/components/*                       상세페이지 컴포넌트 20개
src/data/course.ts                     실제 영상 데이터 (스크립트 85문단 포함)
src/lib/types.ts                       데이터 모델
src/lib/progress.ts                    진행 상태 저장
src/app/globals.css                    토큰·앱 틀  ← 값 수정 금지, 추가만
scripts/setup-fonts.mjs                Pretendard 준비 (빌드 전 자동 실행)
public/img, public/icons               피그마·유튜브에서 뽑은 에셋
internal-tools/**                      전처리 파이프라인 (다른 갈래)
```

`globals.css` 에 홈 전용 클래스를 **추가**하는 건 괜찮아요. 기존 토큰 값을 바꾸는 건 안 돼요.

`package.json` 의 `predev` / `prebuild` 는 폰트 준비 스크립트예요. 지우면 글꼴이 깨집니다.

---

## 6. 작업 순서

1. main 최신을 받아 `feature/home` 브랜치 생성
   ```bash
   git checkout main && git pull
   git checkout -b feature/home
   ```
2. `src/app/page.tsx` 를 팀원 홈 화면으로 교체
3. 홈 화면 루트를 `.app-shell` 로 감싸고, 목록은 `.app-scroll` 안에
4. 영상 카드 → `/videos/${course.id}` 링크 연결
5. 아래 검증 통과 후 PR

---

## 7. 검증 (이거 다 통과해야 머지)

```bash
npm install
npm run build          # 통과해야 함
npx eslint src --max-warnings 0   # 경고 0
npm run start
```

**손으로 확인할 것**

- [ ] 홈 → 영상 카드 탭 → 상세페이지 진입
- [ ] 상세페이지 3개 탭(캐치업·스크립트·로그북) 전부 정상
- [ ] 캐치업에서 카드를 밀어 넘기면 게이지가 차고, 새로고침해도 남음
- [ ] 4/4 가 되면 파트 카드 배경이 흰색 → 회색
- [ ] 스크립트 탭에서 `Pt. 4` 를 누르면 챕터 헤더는 그대로, 해당 문단만 강조
- [ ] 썸네일 재생 버튼 → 유튜브 재생 / 카드 재생 버튼 → 그 STEP 구간만
- [ ] **폰 폭(375·390·430)에서 페이지가 세로로 넘치지 않음**
- [ ] 데스크톱에서 폰 프레임이 가운데 정렬됨

마지막 두 개가 제일 자주 깨져요. 홈 화면에 `min-h-screen` 을 쓰면 바로 어긋납니다.

---

## 8. 참고 문서

| 무엇 | 어디 |
|---|---|
| 디자인 명세 (토큰·컴포넌트 수치·피그마 노드 ID) | `docs/DESIGN_SPEC.md` |
| 프로젝트 개요·폴더 구조 | `README.md` |
| 피그마 완성 시안 | <https://www.figma.com/design/EdZwX1tGIvLJfeXTajVhwv/AI?node-id=355-8772> |

---

## 부록 — 상세페이지에 뭐가 들어있나

**화면**

- 첫화면 — 썸네일 + 재생 버튼, 브레드크럼, 제목, 메타행, 탭, 파트 카드 4장
- 더보기 바텀시트 — 메타 칩, 추천 카드, 다루는 도구 5개, 파트별 확인하기, 태그 8개, 채널, 관련 영상
- 캐치업 탭 — 카드 스와이프 스택 (기본형 / 프롬프트형 / 주의형), 더 알아보기 시트, 완료 화면
- 스크립트 탭 — 원본 챕터 9개 + 파트 필터·강조
- 로그북 탭 — 빈 상태

**콘텐츠 (실제 데이터)**

원본 <https://www.youtube.com/watch?v=vI4RdXMSq8c> · Sandy Lee AI · 21분 28초

| 구조 | 개수 |
|---|---|
| 원본 챕터 | 9 |
| 스크립트 문단 | 85 (전처리 한국어 번역본) |
| 캐치업 파트 | 4 |
| STEP 카드 | 14 (4/4/3/3) |
| 프롬프트 블록 | 3 · 주의 박스 2 · 더 알아보기 17 |

**챕터와 파트는 다른 구조예요.** 파트 1~3 은 전부 `CH-07` 안에 있고, 파트 4 는 `CH-08`~`CH-09` 에 걸쳐 있어요. 85문단 중 35개만 파트에 쓰였고 나머지 50개(도입·비용·잡담)는 스크립트에만 남아 있습니다.

**아직 없는 것** — 별점 · 사진 첨부 · 결과물 작성 폼 · 로그북 목록 · 파트 카드 스와이프 카메라. 서버(Supabase) 붙일 때 한 번에 할 예정이에요.
