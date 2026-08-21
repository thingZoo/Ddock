# Admin Content Review MVP

## 목적

`ddock_content_review_v0.1` AI curation draft를 운영자가 source provenance와 함께 검수하고, `ddock_content_v0.1` publish candidate를 만드는 내부 도구입니다. 기존 사용자 상세 화면과 데이터 adapter는 변경하지 않습니다.

## Route

`/admin/content-review`

첫 화면에서 review JSON을 import하거나 같은 브라우저에 저장된 마지막 draft를 복원합니다. Import는 JSON parse와 `schema_version`, 필수 top-level structure를 확인하며 실패한 파일은 현재 editor state를 덮어쓰지 않습니다.

## MVP persistence

MVP Admin persistence = localStorage입니다. Backend/database persistence와 multi-user audit log는 future work입니다.

- Draft: `ddock:admin-review:{video_id}`
- Last opened video: `ddock:admin-review:last`
- Published preview: `ddock:published-preview:{video_id}`

편집 후 500ms debounce autosave가 실행되며 화면에 변경사항 있음, 저장 중, 저장됨 상태가 표시됩니다.

## 편집 범위

- Video Detail: recommendation, tools, tags
- PART: title, summary, action objective, needs-review 상태, add/delete/reorder/adjacent merge/STEP 기준 split
- STEP: action title/lines, rich segments, playback evidence, Prompt, Warning, Learn More, add/delete/reorder
- Phase: action/context evidence 확인
- Unassigned Phase: 기존 PART 연결, 새 PART 생성, 이유를 포함한 explicit exclude
- Review Queue: severity filter와 관련 editor/source 이동
- Script: chapter를 유지한 read-only text와 PART/STEP/Phase highlight

Evidence picker는 STEP은 parent PART action 범위, Prompt/Warning/Learn More는 parent PART source 범위로 제한합니다. Script text와 preprocessing provenance는 수정하지 않습니다.

## Validation

Admin validator는 **Browser preflight; Python contract remains source of truth**입니다. Schema, unresolved phase, blocking review 상태, PART/STEP 필수 field, action line, evidence 범위, prompt evidence/verbatim, duplicate ID와 invalid reference를 검사합니다. Validation item을 누르면 관련 editor로 이동합니다.

Canonical Python publish validator를 브라우저 코드로 대체하지 않습니다. 최종 production publish 전에 Python validator가 다시 통과해야 합니다.

## Export Draft

현재 편집 상태를 `{video_id}_ddock_content_review_v0_1.json`으로 다운로드합니다. Review-only evidence와 queue를 유지합니다.

## Publish Candidate

Browser preflight blocker가 0일 때 `draft_parts`를 `catchup_parts`로 옮기고 top-level review fields와 PART `review_reasons`를 제거해 `{video_id}_ddock_content_v0_1.json`을 다운로드합니다. MVP publish = browser candidate export이며 production server publish가 아닙니다.

## Admin Preview

Publish candidate projection을 내부 read-only preview로 표시합니다. 영상 제목, recommendation, PART 순서, STEP action line, Prompt, Warning, Learn More의 문장 길이와 밀도를 확인하기 위한 화면이며 현재 사용자 상세 화면과 pixel-perfect parity를 목표로 하지 않습니다.

## Known limitations

- Backend/database, authentication, authorization, concurrent editing, server publish가 없습니다.
- Durable operation audit log와 draft version history가 없습니다.
- Browser preflight는 canonical Python validator의 일부 fail-closed rule만 빠르게 재현합니다.
- Preview는 user-facing `VideoDetail`을 재사용하지 않는 Admin 전용 projection입니다.
- Drag and drop 대신 명시적인 이동 버튼과 adjacent merge, selected-STEP split을 사용합니다.
- Admin-scoped lint는 통과합니다. 전체 repository lint에는 기존 `src/components/ddock/PollDeck.tsx`의 `react-hooks/refs` 오류 1건이 있으며 이 Admin branch는 해당 파일을 수정하지 않습니다. Build와 TypeScript 검사는 통과합니다.
