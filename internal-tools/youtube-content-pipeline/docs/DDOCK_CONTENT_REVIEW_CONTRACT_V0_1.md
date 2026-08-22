# D:ock Content Review Contract v0.1

`ddock_content_review_v0.1`은 AI curation 결과를 최종 사용자 콘텐츠가 아니라 Admin이 수정할 수 있는 draft로 보존하는 internal contract입니다. 운영 순서는 다음과 같습니다.

```text
PREPROCESSING
→ AI CURATION DRAFT
→ ADMIN REVIEW
→ VALIDATE FOR PUBLISH
→ PUBLISH
→ USER UI
```

AI uncertainty, omission, unassigned phase, excluded action, unattached context, grounding salvage는 draft 생성을 막지 않습니다. 이 상태는 `review_queue`에 드러나며, publish validator만 fail-closed입니다.

## Artifacts

- Admin Review Draft: `ddock_content_review_v0_1.json`, schema `ddock_content_review_v0.1`
- Published User Content: `ddock_content_v0_1.json`, schema `ddock_content_v0.1`

Generation CLI의 기본 artifact는 review draft입니다. Published artifact는 Admin이 blocking item을 해결한 뒤 명시적으로 publish conversion을 실행할 때만 생성합니다.

## Top-level shape

```json
{
  "schema_version": "ddock_content_review_v0.1",
  "source": {},
  "video_detail": {},
  "script_chapters": [],
  "script": [],
  "draft_parts": [],
  "action_phases": [],
  "unassigned_phases": [],
  "review_queue": [],
  "curation_generation": {}
}
```

`source`, `video_detail`, `script_chapters`, `script`, `curation_generation`은 published contract와 같은 provenance와 generation evidence를 보존합니다. `script[].text`는 preprocessing provenance이며 Admin curation이 임의로 교정하지 않습니다.

## Draft PART

`draft_parts[]`는 published PART 구조를 재사용하고 `review_reasons`를 추가합니다.

```text
part_id, order, title, summary, action_objective
source_utterance_ids, action_utterance_ids, source_script_chapter_ids
start_seconds, end_seconds, start_timestamp, end_timestamp, evidence
thumbnail, steps, needs_review, review_reasons
generation_warnings, excluded_actions
```

A2가 유효한 일부 phase만 PART로 만들면 그 PART를 그대로 보존합니다. 다른 phase가 누락됐다는 이유로 유효한 PART를 삭제하지 않습니다. PASS B가 실패한 PART candidate도 `steps: []`, `needs_review: true`, `review_reasons: ["part_needs_review"]` 상태로 남아 Admin이 직접 STEP을 만들 수 있습니다.

## Action phase and unassigned phase

`action_phases[]`는 A1 결과를 삭제하지 않고 다음 형태로 보존합니다.

```text
phase_id, order, phase_label, operation
tool_or_surface, expected_result
action_utterance_ids, context_utterance_ids
assigned_part_id | null
needs_review, review_reasons
```

A2가 사용한 phase는 `assigned_part_id`가 PART를 가리킵니다. 사용하지 않은 phase는 `assigned_part_id: null`이며 같은 phase가 `unassigned_phases[]`에도 들어갑니다. `unassigned_phases[]`는 위 field에 `excluded_reason`을 추가합니다.

Admin은 unassigned phase를 다음 셋 중 하나로 해결합니다.

- 기존 PART에 연결: action phase의 `assigned_part_id`를 설정하고 unassigned entry를 제거합니다.
- 새 PART 생성: 새 draft PART를 만들고 `assigned_part_id`를 설정한 뒤 unassigned entry를 제거합니다.
- 명시적 제외: unassigned entry의 `excluded_reason`에 구체적인 비어 있지 않은 이유를 저장합니다.

빈 `excluded_reason`은 해결로 인정하지 않습니다. 명시적으로 제외된 phase는 publish 시 unassigned blocker에서 제외되지만, review artifact에는 판단 근거로 남습니다.

## Review queue

각 item은 다음 metadata만 가집니다.

```json
{
  "review_id": "REV-001",
  "type": "unassigned_phase",
  "severity": "warning | blocking",
  "part_id": null,
  "phase_id": "PHASE-003",
  "step_id": null,
  "utterance_ids": [],
  "message": "..."
}
```

지원 type은 다음과 같습니다.

- `unassigned_phase`
- `phase_context_too_broad`
- `part_needs_review`
- `step_needs_review`
- `excluded_action`
- `unattached_context`
- `unsupported_claim_removed`
- `script_not_human_verified`

`warning`과 `blocking` 모두 draft file에 저장할 수 있습니다. `blocking`은 draft write를 막지 않으며 Admin publish 전에 해결하거나 해당 review item을 제거해야 한다는 뜻입니다. `unassigned_phase`, `part_needs_review`, `step_needs_review`는 기본 blocking입니다. Broad phase context, grounding salvage, excluded action, unattached context, human-unverified script는 기본 warning입니다.

Grounding salvage가 line, prompt, Learn More sentence, recommendation claim을 제거하면 원본 model warning과 함께 `unsupported_claim_removed` review item을 남깁니다. 제거된 unsupported content 자체를 published surface에 복원하지 않습니다.

## Broad phase context warning

`phase_context_too_broad`는 특정 영상 ID, utterance ID, chapter ID 또는 G0 fixture 수치를 사용하지 않습니다. Context row가 최소한의 sample 크기를 넘은 상태에서 다음 중 하나가 성립하면 warning입니다.

- context time span이 180초 이상
- context span이 전체 script time span의 35% 이상
- context row가 전체 script row의 35% 이상
- context에 서로 다른 강한 action family가 4개 이상

이 경고는 phase와 draft를 삭제하지 않고 Admin에게 범위를 확인하도록 합니다.

## Stable IDs

자동 generation에서 ID는 source order 기반으로 deterministic하게 부여합니다.

- phase: `PHASE-001`, `PHASE-002`, ...
- part: `PART-01`, `PART-02`, ...
- step: `{part_id}-STEP-01`, `{part_id}-STEP-02`, ...
- review: deterministic queue order의 `REV-001`, `REV-002`, ...

동일한 input과 동일한 model responses로 생성한 같은 draft에서는 ID projection이 같습니다. Admin save는 기존 entity의 ID를 보존해야 합니다. Edit와 reorder는 ID를 재발급하지 않습니다. Create만 새 unique ID를 발급하며, merge/split/delete는 어떤 ID를 유지·폐기했는지 Admin audit log에 기록해야 합니다. 현재 contract는 audit persistence나 Admin UI를 구현하지 않습니다.

## Admin operation contract

Admin implementation은 다음 최소 operation을 제공해야 합니다.

### PART

- `create`: source/action evidence와 새 stable part ID로 PART 생성
- `edit`: title, summary, objective, evidence, thumbnail 등 수정; ID 유지
- `delete`: PART 제거; 소유 phase를 unassigned 또는 explicit exclude로 이동
- `reorder`: `order`만 재계산; ID 유지
- `merge`: target PART ID 하나를 유지하고 evidence/STEP/phase ownership 통합
- `split`: 원 PART ID 하나를 유지하고 추가 PART에 새 ID 발급; phase ownership 재배치

### PHASE

- `assign_to_part`: 기존 PART에 연결하고 unassigned blocker 제거
- `create_part_from_phase`: 새 PART를 만들고 phase 연결
- `exclude`: 구체적인 `excluded_reason`을 저장하고 unassigned blocker 해결

### STEP

- `create`: PART action evidence subset으로 새 STEP 생성
- `edit`: surface/evidence/optional block 수정; ID 유지
- `delete`: STEP 제거 후 PART action accounting 재검사
- `reorder`: `order`만 재계산; ID 유지

### LEARN MORE

- `create`: PART context evidence를 가진 block 생성
- `edit`: question/body/evidence 수정
- `delete`: block 제거
- `attach`: 특정 STEP에 연결하되 evidence는 parent PART context subset 유지

### FINAL

- `validate_for_publish`: draft validation 뒤 publish-only blocking rules 실행
- `publish`: validation이 성공한 draft를 `ddock_content_v0.1`로 변환하고 atomic write

## Draft validation vs publish validation

Draft validator는 schema, field shape, unique ID, reference, source provenance를 검사합니다. Warning 또는 blocking review item과 unresolved phase는 draft write를 실패시키지 않습니다.

Publish validator는 다음을 추가로 요구합니다.

- unresolved `unassigned_phase` 0
- blocking `review_queue` item 0
- PART title과 action objective 존재
- STEP/action line/optional block evidence 유효
- PART/STEP source provenance 유효
- unsupported prompt 0; prompt는 cited source의 verbatim text이며 prompt cue가 있어야 함
- unsupported recommendation claim 0; claim은 cited evidence에 grounding되어야 함
- 기존 `ddock_content_v0.1` validator 전체 통과

Publish conversion은 `draft_parts`를 `catchup_parts`로 옮기고 review-only field를 제거합니다. Published schema version은 바뀌지 않습니다.

## Non-goals

이번 contract는 Admin UI, frontend user surface, backend persistence, audit log storage를 구현하지 않습니다. `src/`, `public/`, Next.js 코드는 이 branch에서 변경하지 않습니다. Qwen architecture를 추가하거나 actual generation을 다시 실행하지 않습니다.
