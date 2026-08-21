# Ddock

MVP프로젝트 영상 요약 콘텐츠 자동화 — 디자이너를 위한 AI 브리핑 서비스.
영상 스크립트를 "안 봐도 손으로 따라할 수 있는" 학습 카드로 바꿔서 보여주는 웹앱입니다.

## 담당

| 화면 | 담당 | 브랜치 |
|---|---|---|
| 메인 홈 (영상 목록) | 팀원 | `feature/home` |
| **영상 상세페이지** | ZOO | `feature/video-detail-page` |

접점은 라우트 하나예요 — 홈에서 `/videos/[id]` 로 넘겨주면 됩니다.
맞출 필드는 `Course` 의 `id` `title` `thumbnail` 세 개뿐이에요.

## 지금 되는 것

피그마 `완성` 페이지 › `상세페이지_캐치업 플로우` 를 그대로 옮겼어요.

- **첫화면** — 썸네일 + 재생 버튼, 브레드크럼, 제목, 메타행, 탭, 파트 카드 4장
- **더보기 시트** — 메타 칩, 추천 카드, 다루는 도구, 파트별 확인하기, 태그, 채널, 관련 영상
- **캐치업 탭** — 카드 스와이프 스택. 기본형 / 프롬프트형 / 주의형 3종
  - 프롬프트가 길어도 카드는 안 늘어나요. 4줄까지 보이고 `…`, 복사는 원문 전체
  - `더 알아보기` → ⓘ 바텀시트, `구간 스크립트 보기` → 스크립트 탭 해당 위치로 점프
  - 마지막 카드를 넘기면 완료 화면 → 다음 파트로
- **스크립트 탭** — 전체 / 파트별 필터, 타임스탬프를 누르면 그 지점부터 재생
- **로그북 탭** — 빈 상태 (기록 기능은 다음 단계)
- **유튜브 연동** — 썸네일 재생 버튼은 전체 재생, 카드 우상단 버튼은 그 STEP 구간만 재생

## 화면 비율 (반응형)

폰에서는 화면을 꽉 채우고, 데스크톱에서는 폰 모양 프레임으로 가운데 정렬돼요.
페이지 전체가 세로로 늘어나지 않고 **틀 안에서만 스크롤**합니다.

```
폰 (< 480px)
  .app-shell  width 100%  height 100dvh
  → 375·390·430 어떤 폭이든 가장자리까지 꽉 참

데스크톱 (>= 480px)
  .app-shell  max-width 375  height min(812px, 100dvh - 48px)
              border-radius 24  shadow
  바깥 배경   --shell-bg #F4F4F5
```

- 썸네일은 고정 211px 이 아니라 `aspect-video` 라 폭에 따라 같이 줄어요
- 학습 카드도 절대좌표가 아니라 flex 라 남는 높이에 맞춰 줄어듭니다
- 바텀시트는 화면이 아니라 **앱 틀 안**에서 올라와요 (데스크톱에서 프레임 밖으로 안 새요)
- 값은 `src/app/globals.css` 의 `.app-shell` / `.app-scroll` 에 있어요

## 콘텐츠 (실제 데이터)

원본 영상 <https://www.youtube.com/watch?v=vI4RdXMSq8c> — Sandy Lee AI,
"How I Fully Automated Video Editing (Claude Code)" 21분 28초.

| 구조 | 개수 | 출처 |
|---|---|---|
| 원본 챕터 | 9개 | 크리에이터가 영상 설명에 적어둔 목차 |
| 스크립트 문단 | 85개 | 전처리 결과(`script_preprocessing_v0.3.15.1`)의 `normalized_utterances` 한국어 번역본 |
| 캐치업 파트 | 4개 | 챕터 중 행동 가치가 있는 구간만 골라 묶은 큐레이션 결과 |
| STEP 카드 | 14개 | 파트별 4 / 4 / 3 / 3 |

**챕터와 파트는 다른 구조예요.** 파트 1~3 은 전부 `CH-07` 안에 있고, 파트 4 는 `CH-08`~`CH-09` 에 걸쳐 있어요.
스크립트 85문단 중 파트에 쓰인 건 35개, 나머지 50개는 도입·비용 설명·잡담이라 캐치업에서 뺐습니다.

## 진행 상태 저장

STEP 을 넘길 때마다 `localStorage` 에 기록해요 (`ddock:progress:v1`).

- 파트 카드 게이지가 끝낸 STEP 만큼 차요
- 다 끝내면(4/4) 카드 배경이 흰색 → `#F4F4F5` 로 바뀝니다
- 새로고침해도 남아요. 기기·브라우저별로만 남고 서버엔 안 올라가요
- 서버가 붙으면 `src/lib/progress.ts` 의 저장 부분만 갈아끼우면 됩니다

## 아직 없는 것

별점 · 사진 첨부 · 결과물 작성 폼 · 로그북 목록 · 파트 카드 스와이프 → 카메라.
전부 서버(Supabase DB + Storage)가 있어야 반쪽을 면해서 다음 단계로 미뤘어요.

파트 썸네일은 유튜브가 주는 프레임(mq1~3)이라 STEP 구간과 정확히 일치하진 않아요. 실제 프레임 캡처로 바꾸면 좋습니다.

## 개발

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # 배포 전 검증
```

`npm run dev` / `npm run build` 앞에서 `scripts/setup-fonts.mjs` 가 자동으로 돌아요.
Pretendard 서브셋(92개)을 `node_modules` 에서 `public/fonts` 로 복사합니다.
폰트 바이너리는 저장소에 안 넣어요 (`.gitignore`).

## 배포

Vercel에 이 저장소를 연결하면 기본 설정 그대로 됩니다. 환경변수는 아직 없어요.

## 폴더

```
docs/DESIGN_SPEC.md      디자인 명세 — 토큰·컴포넌트 수치·노드 ID 색인
src/app/                 라우트
src/components/          화면 조각 (아래 참고)
src/data/course.ts       시드 콘텐츠
src/lib/types.ts         데이터 모델
public/img · public/icons  피그마에서 뽑은 에셋
scripts/setup-fonts.mjs  Pretendard 준비
```

### 컴포넌트

| 파일 | 하는 일 | 피그마 |
|---|---|---|
| `VideoDetail` | 상세페이지 전체 뼈대·탭 전환 | 355:8868 |
| `YouTubePlayer` | 유튜브 IFrame + 재생 상태 공유 | — |
| `PlayPauseButton` | 재생 / 멈춤 (70px · 44px) | 360:13595 / 360:13690 |
| `Tabs` | 캐치업 / 스크립트 / 로그북 | 355:8932 |
| `PartCard` + `ProgressGauge` | 파트 카드와 게이지 | 357:13400 |
| `MoreSheet` | 더보기 바텀시트 8개 섹션 | 355:9050 |
| `CardStack` + `LearningCard` | 학습 카드 스와이프 | 355:9749 / 355:9781 |
| `PromptBlock` | 4줄 clamp + 원문 전체 복사 | 355:9792 |
| `WarningBox` | 주의 박스 | 355:9596 |
| `InfoSheetView` | 더 알아보기 시트 | 355:9618 |
| `ChapterBar` | CH 제목 + 진행 게이지 | 355:9740 |
| `CompleteCard` | 파트 완료 | 355:9402 |
| `ScriptTab` | 스크립트 전체·구간별 | 355:9911 / 355:9971 |
| `LogTab` | 로그북 빈 상태 | 355:10032 |

## 디자인 토큰

값은 `src/app/globals.css` 의 CSS 변수 + `t-*` 타이포 유틸에 있어요.
피그마와 1:1로 맞춰뒀습니다. 자세한 근거는 `docs/DESIGN_SPEC.md`.
