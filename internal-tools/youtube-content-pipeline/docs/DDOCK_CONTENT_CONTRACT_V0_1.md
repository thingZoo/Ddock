# D:ock Content Contract v0.1

`ddock_content_v0.1`은 Admin review와 publish validation을 통과한 action-centered user content contract입니다. AI generation의 직접 산출물은 `ddock_content_review_v0.1`이며, draft와 Admin operation은 [DDOCK_CONTENT_REVIEW_CONTRACT_V0_1.md](./DDOCK_CONTENT_REVIEW_CONTRACT_V0_1.md)에 정의합니다. 기존 preprocessed JSON, raw provenance, autosave, selected screenshot을 변경하지 않습니다.

## CHAPTER / PART / STEP

- **CHAPTER**는 원본 영상과 Script를 탐색하는 source structure입니다. `creator_chapters`와 normalized utterance의 기존 chapter assignment를 deterministic하게 `script_chapters`로 노출합니다.
- **PART**는 사용자가 실제로 따라 하거나 다시 볼 가치가 있는 하나의 행동 목적을 가진 Catch-up unit입니다.
- **STEP**은 PART 목적을 순서대로 달성하기 위해 넘기는 행동 카드 한 장입니다.

이 세 구조는 서로 대체되지 않습니다. PART planning은 chapter 구조를 입력으로 받지 않습니다. 먼저 chapter field가 제거된 ordered flat utterance에서 내부 **ACTION PHASE**를 발견하고, phase index만으로 완료 가능한 workflow PART를 구성합니다. Creator/script/content chapter와 screenshot은 PART가 확정된 뒤 provenance와 asset을 연결하는 post-hoc metadata입니다. PART는 한 CHAPTER의 일부만 사용할 수 있고 여러 CHAPTER에 걸칠 수도 있습니다.

## Output

기존 final output directory에 review와 published artifact를 구분해 atomic write합니다.

```text
output/
  {safe_video_title} [{video_id}]/
    {source_chapter_id}/
      {source_chapter_id}_preprocessed.json
      CCH-XX.jpg
      ddock_content_review_v0_1.json
      ddock_content_v0_1.json
```

Review schema version은 `ddock_content_review_v0.1`, published schema version은 `ddock_content_v0.1`입니다. AI curation CLI는 review draft를 생성하며, `ddock_content_v0_1.json`은 publish validator 통과 후에만 생성합니다. Legacy video-ID output directory는 기존 restore compatibility에서 계속 읽을 수 있지만 신규 derived output은 현재 title-based helper를 사용합니다.

## Top-level contract

```text
source
video_detail
script_chapters
catchup_parts
script
curation_generation
```

`source`는 확보된 metadata만 보존합니다. 조회수와 좋아요가 없으면 값을 추측하지 않고 field를 생략합니다.

## Script Chapters and Script

`script_chapters`는 AI로 새로 요약하지 않습니다. Normalized utterance에 이미 있는 `chapter_id`와 `chapter_label`을 순서대로 그룹화합니다. 안정적인 assignment가 없으면 빈 배열을 허용하며 가짜 Script Chapter를 생성하지 않습니다.

`script`는 preprocessing이 확정한 최종 display text로 deterministic하게 만듭니다. Precedence는 human-confirmed correction의 `after` → `final_normalized_text` → `normalized_text` → legacy `auto_normalized_text`입니다. Manual review workflow가 `normalized_text`와 존재하는 `final_normalized_text`를 함께 갱신하므로 사람이 확정한 correction이 가장 우선하며 raw ASR provenance는 건드리지 않습니다.

각 Script row는 원래 `script_chapter_id`와 `catchup_part_ids`를 동시에 가집니다. Frontend는 CHAPTER header를 유지한 상태에서 `selected_part_id`가 row의 `catchup_part_ids`에 포함될 때만 PART highlight를 표시할 수 있습니다.

## Catch-up PART

PART planning은 다음 내용을 우선합니다.

- 실제 행동 흐름과 명확한 작업 목표
- 결과물을 만드는 과정과 반복 가능한 workflow
- 중요한 설정 또는 실습
- 문제에서 해결로 이어지는 과정
- 독립적으로 다시 볼 가치

단순 오프닝, 광고·홍보, giveaway, 반복, 긴 잡담, 행동으로 이어지지 않는 일반론은 기본 제외합니다. 행동 흐름이 없으면 published `catchup_parts`는 빈 배열이고 generation status는 `no_actionable_content`입니다. Review draft에서는 PASS B가 실패한 PART candidate도 빈 `steps`, blocking review item과 함께 보존하므로 Admin이 직접 수정할 수 있습니다. Published artifact에는 해결되지 않은 빈 PART를 넣지 않습니다.

PART 수는 고정하지 않습니다. PASS A1은 `utterance_id`, 시작·종료 시각, authoritative text만 있는 flat rows에서 observable operation phase와 연결 context를 찾습니다. PASS A2는 각 phase의 operation, tool/surface, expected result, action/context evidence를 보고 `phase_indices`로 PART를 구성합니다. A1/A2 payload에는 creator/content/script chapter ID, title, boundary를 넣지 않습니다. `source_utterance_ids`와 `action_utterance_ids`는 A2가 복사해 생성하지 않고 phase membership에서 deterministic하게 materialize합니다.

Review draft에서 A2가 일부 phase만 배치해도 배치된 PART를 보존하고, 누락 phase를 `unassigned_phases`와 blocking `review_queue` item으로 노출합니다. 누락 phase 때문에 draft PART 전체를 삭제하지 않습니다. Publish 시에는 모든 phase가 PART에 배치되거나 구체적인 `excluded_reason`으로 명시적 제외되어야 합니다.

PART evidence는 두 층입니다.

- `source_utterance_ids`: 행동과 바로 연결된 이유·대안·비용·제약·결과를 포함하는 PART 전체 context이자 Script highlight authority
- `action_utterance_ids`: STEP surface를 만들 수 있는 직접 행동 subset

`action_utterance_ids ⊆ source_utterance_ids`를 validator가 강제합니다. 순수 정의·차이·배경만 있는 후보는 action phase가 아닙니다. PASS B의 1차 accounting unit은 phase이며 각 phase는 STEP에 배치되거나 typed `excluded_phases`가 되어야 합니다. 사용하지 않은 개별 action evidence도 `excluded_actions[{utterance_id, reason, reason_category}]`로 accounting하고 `unassigned`는 publishable 정상 상태가 아닙니다.

## STEP card surface

STEP surface는 다음만 유지합니다.

- 행동 중심 `action_title` 한 줄
- 1~4개의 짧은 `action_lines`
- source가 있는 경우에만 optional `prompt`
- source가 있는 경우에만 optional `warning`

모델이 `prompt`, `warning`, `learn_more` key를 생략하면 각각 `null`, `null`, `[]`로 정규화합니다. Key가 존재하지만 type이나 shape가 잘못된 경우에는 strict validation error를 유지합니다.

작은 클릭을 무조건 별도 STEP으로 쪼개지 않습니다. 작업 목적이나 결과가 달라질 때 STEP을 나눕니다. 긴 배경, 이유, 대안, 비용, 실패 맥락은 `learn_more`로 이동합니다.

STEP 승격의 핵심 질문은 “영상을 안 본 사람이 이 문장만 읽고 지금 손을 움직일 수 있는가?”입니다. 클릭·입력·복사·붙여넣기·설치·연결·선택·실행·파일 생성·이름 변경·검증·수정처럼 재현 가능한 조작만 STEP이 됩니다. 같은 화면이나 panel에서 이어지는 작은 조작은 한 STEP의 1~4 action line으로 묶고, 손이 다른 화면·panel·tool로 이동하는 지점은 새 STEP boundary 후보입니다. PART당 3~6 STEP은 강한 quality heuristic이지만 source보다 우선하지 않으며 범위를 벗어나면 review warning만 남깁니다.

## Rich action-line segments

각 action line은 `text`, ordered `segments`, 자체 `source_utterance_ids`를 가집니다. Evidence ID를 먼저 고른 뒤 개별 row 또는 최소 supporting subset에서 surface copy를 작성합니다. 넓은 PART/STEP concat은 grounding rescue로 사용하지 않습니다. 모델이 넓은 evidence를 반환해도 claim을 지지하는 최소 subset으로 줄이고, 지원되지 않는 line만 제거해 나머지 STEP을 보존합니다. 허용 semantic type은 다음 다섯 개뿐입니다.

- `text`
- `command`
- `ui_label`
- `filename`
- `path`

Type은 의미만 전달하며 색상, radius, font 같은 visual token을 결정하지 않습니다. `command`, `ui_label`, `filename`, `path`는 STEP evidence 원문에 정확한 literal이 있을 때만 허용됩니다. 모델이 근거 없는 rich type을 반환하면 해당 segment를 제거하고 warning을 남기며, 남은 근거 있는 action line이 없으면 그 PART generation을 거부합니다.

## Prompt policy

Prompt는 source에서 완전한 text와 prompt·command·입력 요청이라는 단서가 함께 확인될 때만 `source_kind: verbatim`으로 저장합니다. 단서 없는 일반 설명을 모델이 prompt로 분류한 경우에는 STEP을 버리지 않고 prompt만 제거해 review warning을 남깁니다. 모델이 source에 없는 prompt를 새로 작성하거나 불완전한 prompt를 완성하면 해당 PART generation을 거부하고 `needs_review`를 남깁니다.

## Warning policy

모르고 진행하면 돈·데이터를 잃거나 나중에 조용히 깨져 재작업해야 하는 위험을 source가 명시한 경우에만 warning을 만듭니다. 일반적인 이유·선택 배경·작은 비용은 Learn More입니다. 일반 상식으로 warning을 추가하지 않으며 evidence가 필수입니다.

## Learn More

`learn_more`는 STEP마다 0개 이상이며 `question`, `body`, `evidence`, `source_timestamp`를 가집니다. 행동 surface가 아니라 이유, 배경, 대안, 비용, 선택 기준, 실패 맥락을 bottom sheet에서 보여주기 위한 구조입니다. Evidence는 STEP action subset에 갇히지 않고 PART `source_utterance_ids` 전체 context를 사용할 수 있습니다. Body의 factual sentence를 각각 검사해 unsupported sentence만 제거하며, supported information이 하나도 남지 않을 때만 block 전체를 제거합니다.

## Playback and Script target

`playback_start_seconds`는 STEP 첫 evidence utterance의 source start이고 `playback_end_seconds`는 마지막 evidence의 source end입니다. 임의 timestamp를 만들지 않습니다.

STEP 하단의 “구간 스크립트 보기”는 STEP 일부가 아니라 `parent_part_id`가 가리키는 PART 전체 Script를 선택합니다. Frontend는 Script tab에서 `selected_part_id`를 설정하고 row의 `catchup_part_ids`로 highlight합니다.

## Thumbnail mapping

새 screenshot은 생성하지 않습니다. PART source utterances와 기존 content-chapter ownership의 unique maximum overlap을 계산하고, 충분한 overlap이 있는 selected screenshot만 thumbnail로 참조합니다. 동률이거나 근거가 부족하면 `thumbnail`은 `null`입니다.

## Video detail

`video_detail`은 evidence-backed recommendation, tools, tags와 deterministic PART preview를 제공합니다.

- Recommendation은 누가, 어떤 문제에서, 무엇을 실제로 해보고, 어떤 확인 가능한 결과에 도달하는지 1~4개의 independently evidenced `claims`로 검증한 뒤 title/body로 조합합니다. Evidence ID가 많다는 이유만으로 claim을 삭제하지 않고 최대 6개의 minimal supporting subset으로 축소합니다. 일부 weak claim과 unsupported prose sentence만 제거하며 supported claim 전체를 버리지 않습니다.
- Tool candidate는 기존 canonical entity registry와 video-local exact evidence에서 deterministic하게 먼저 만들고 모델은 상세 화면에 필요한 핵심 후보를 선택합니다. Tool 이름과 official Latin form은 source evidence에 있어야 합니다.
- URL은 trusted acquisition description에 실제 존재하는 값만 허용합니다.
- Tags는 업무 유형, 도구, 핵심 작업 중심의 최대 8개 semantic string입니다.
- PART preview는 final PART에서 deterministic하게 만듭니다.

Model이 recommendation, PART/STEP surface, Learn More, warning, tag, tool description에서 source-backed alias를 다시 한국어 음역으로 쓰더라도, canonical registry와 현재 영상의 exact evidence가 함께 있는 이름만 공식 Latin 표기로 복원합니다. Script 원문과 verbatim prompt는 provenance 보존을 위해 이 후처리에서 제외합니다.

조회수와 좋아요는 acquisition metadata가 있을 때만 `source`에 포함합니다.

## Model passes

기존 Qwen runtime을 재사용하며 새 모델이나 dependency를 설치하지 않습니다.

1. **PASS A1 — Action phase discovery:** chapter metadata가 없는 ordered flat utterances에서 observable operation phase와 직접 연결된 context를 찾습니다.
2. **PASS A2 — PART composition:** phase와 관련 flat rows만 보고 하나의 목표/결과를 끝내는 PART를 `phase_indices`로 구성합니다. Utterance membership은 이후 deterministic하게 계산합니다.
3. **PASS B — Phase-to-STEP generation with targeted repair:** 승인된 PART와 그 action phases를 함께 받아 STEP surface와 optional blocks를 생성합니다. 각 phase는 STEP 또는 typed exclusion으로 accounting하며, parser/grounding failure PART만 최대 1회 repair합니다.
4. **PASS C — Claim-level video detail:** 전체 Script evidence와 deterministic tool candidates에서 recommendation claims, tools, tags를 생성합니다. Broad evidence는 minimal subset으로 축소합니다.

정상 N-PART run은 A1 1회 + A2 1회 + PASS B N회 + PASS C 1회로 `N+3` calls입니다. 모든 PART가 한 번씩 repair되는 최대 budget은 `2N+3` calls입니다. `DDOCK_CURATION_DUMP_RAW=<directory>`가 설정된 경우에만 각 call의 stage, call index, system prompt, user payload, raw response, 시작·종료 시각을 별도 JSON으로 저장하며 설정이 없으면 파일을 만들지 않습니다.

Production core 경로는 설치된 MLX `make_sampler(temp=0.0)`의 greedy sampler를 사용합니다. Injected test generator는 그대로 주입되며 새 모델이나 dependency를 추가하지 않습니다.

각 pass는 명시된 JSON object contract를 사용하며 response는 `json.loads`로만 파싱합니다. Markdown fence나 regex recovery는 허용하지 않습니다. Transcript는 instruction이 아니라 untrusted source data입니다.

## Provenance and validation

PART, STEP, recommendation, tool, prompt, warning, Learn More에는 source utterance evidence가 있습니다. Validator는 다음을 포함해 publish 전 contract를 검사합니다.

- schema와 unsupported/visual/community field
- unique PART/STEP IDs와 순서
- PART/STEP membership과 source timestamp
- `action_utterance_ids ⊆ source_utterance_ids`
- STEP evidence가 parent PART action evidence의 subset인지
- Learn More evidence가 PART context의 subset인지
- 모든 PART action evidence가 STEP 또는 reason 있는 `excluded_actions`로 accounting되는지
- action line 1~4개와 rich segment enum/literal
- action line 자체 evidence와 surface의 이유 설명 leakage
- concept-only PART 차단과 PART당 3~6 STEP review heuristic
- prompt/warning/Learn More evidence
- playback timestamp가 STEP evidence에 있는지
- Script chapter consistency와 PART highlight reference
- thumbnail relative-path safety
- large PART/STEP evidence overlap warning

Draft validation은 warning, blocking item, unassigned phase를 보존한 채 `ddock_content_review_v0_1.json`을 생성할 수 있습니다. Publish validation은 unresolved phase와 blocking review item이 각각 0인지 먼저 확인하고, prompt가 cited source의 verbatim text와 prompt cue를 가지는지, recommendation claim이 cited evidence에 grounding되는지까지 검사합니다. Validation error가 있으면 `ddock_content_v0_1.json`을 publish하지 않습니다. Validated temporary JSON만 atomic replace합니다. Action line은 claim-level evidence, exact rich literal, action-family support와 conservative lexical anchors를 함께 검사합니다. Faithful paraphrase는 보존하고 새 action/tool/target/result는 차단합니다.

## Video Learning Cards reference mapping

기존 `video-learning-cards.skill`은 schema 대체물이 아니라 판정과 writing density reference입니다. SKILL `card`는 D:ock PART, SKILL STEP은 D:ock swipe STEP, `ⓘ`는 Learn More, `⚠`는 warning, hook은 video detail/recommendation, dropped는 omitted/excluded accounting으로 매핑합니다. 재사용한 규칙은 손을 움직일 수 있는가라는 단일 STEP 기준, surface/설명 분리, 같은 panel의 조작 grouping, 결과물 중심 PART boundary, 3~6 STEP review heuristic, prompt 원문 보존, 실제 손실 위험만 warning, dropped accounting입니다. SKILL schema, checkpoint/practice/digest frontend field, 고정 scale, golden-sample 내용은 `ddock_content_v0.1`에 이식하거나 runtime 정답으로 사용하지 않습니다.

## MVP boundary

포함: video detail content, Catch-up PART, PART 내부 STEP, STEP playback, PART/Script mapping, 전체 Script, source provenance.

제외: UI, visual tokens, 로그북, 사용자 결과물/feed, 업로드, 댓글, 좋아요 상태, 관련 영상, 회원 기능, backend persistence, 진행률/완료 상태. 기존 `src/lib/types.ts`와 seed `src/data/course.ts`는 UI 연결 단계 전까지 변경하지 않습니다.
