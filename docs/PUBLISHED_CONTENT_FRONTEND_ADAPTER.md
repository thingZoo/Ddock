# Published Content Frontend Adapter

## 목적

Admin에서 승인된 `ddock_content_v0.1`을 기존 D:ock Video Detail의 rendering
model인 `Course`로 변환합니다. Published contract가 content truth이고 `Course`는
현재 UI를 위한 adapter 결과입니다.

## 구조

```text
Admin review
→ Publish Candidate download
→ npm run content:import
→ content/published/*.json
→ server filesystem loader
→ frontend structural guard
→ PublishedContent
→ Course adapter / user course resolver
→ /videos/[courseId]
```

- `src/lib/published-content/types.ts`: Admin 구현과 별도의 frontend type boundary
- `guard.ts`: frontend 최소 구조 검사
- `loader.ts`: build/server 전용 filesystem loader
- `adapter.ts`: `PublishedContent`에서 `Course`로의 deterministic translation
- `resolver.ts`: published-first, legacy-fallback user course 목록

## Candidate 가져오기

Admin의 **발행 파일 만들기**로 다운로드한 JSON을 repository root에서 가져옵니다.

```bash
npm run content:import -- ~/Downloads/G0d9CHLpnnc_ddock_content_v0_1.json
```

대상은 `content/published/{video_id}_ddock_content_v0_1.json`입니다. 같은 파일이
있으면 중단하며, 검토한 교체가 맞을 때만 `--force`를 명시합니다.

```bash
npm run content:import -- ~/Downloads/G0d9CHLpnnc_ddock_content_v0_1.json --force
```

Review draft (`ddock_content_review_v0.1`)는 import할 수 없습니다.

## Published-first와 legacy fallback

같은 `video_id`의 published content가 있으면 PART, STEP, recommendation, tools,
tags, Script, Script Chapter는 published 값만 사용합니다. Published 값이 `null`
또는 빈 배열이어도 legacy curation을 섞지 않습니다.

기존 `Course`는 삭제하지 않고 published가 없는 영상의 fallback으로 유지합니다.
같은 영상에서는 기존 route id와 breadcrumb, 로컬 hero, 채널 avatar/URL, tool icon,
related video 같은 presentation-only 값을 재사용할 수 있습니다. Published source에
없는 조회수, 좋아요, 평점은 만들거나 legacy에서 되살리지 않습니다.

## ID와 asset 정책

같은 영상의 legacy `Course`가 있으면 route id를 유지합니다. 신규 영상은
`source.video_id`를 route id로 사용합니다.

PART thumbnail의 `relative_path`가 `/...` 또는 absolute web URL처럼 browser에서
쓸 수 있는 값이 아니면 같은 영상의 local hero 또는 deterministic YouTube
thumbnail을 사용합니다. 현재 pipeline screenshot을 Next public asset으로 승격하는
작업은 후속 범위입니다. Tool icon이 없으면 이미지 placeholder를 만들지 않고 text로
표시합니다.

## Script membership

Published Script row의 `catchup_part_ids`는 여러 PART를 포함할 수 있습니다.
`ScriptSegment.partNos`에 모든 PART 번호를 보존하고, 기존 `partNo`는 첫 값 또는
`null`로 유지합니다. Script highlight, scroll target, badge는 `partNos`를 우선하고
legacy row에는 기존 `partNo`를 사용합니다. `script_chapter_id: null`은 그대로
보존하며 가짜 chapter header를 만들지 않습니다.

## 검증과 MVP 한계

Python published validator가 canonical source of truth입니다. Frontend guard와 import
CLI 검사는 잘못된 schema/shape를 빠르게 차단하는 보조 검사일 뿐 canonical
validation을 대체하지 않습니다.

현재 backend/database가 없으므로 browser Admin이 production repository에 직접 쓰지
않습니다. 운영 handoff는 candidate download → local import → deploy의 수동 1-step
방식입니다. Backend가 도입되면 publish validation을 통과한 artifact를 저장하고 user
resolver에 공급하는 부분을 서버 publish integration으로 교체합니다.
