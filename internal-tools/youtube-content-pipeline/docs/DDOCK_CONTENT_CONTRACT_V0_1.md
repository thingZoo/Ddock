# D:ock Content Contract v0.1

`ddock_content_v0.1`은 preprocessing 결과를 D:ock frontend가 연결할 수 있는 action-centered 콘텐츠로 변환하는 derived contract입니다. 기존 preprocessed JSON, raw provenance, autosave, selected screenshot을 변경하지 않습니다.

## CHAPTER / PART / STEP

- **CHAPTER**는 원본 영상과 Script를 탐색하는 source structure입니다. `creator_chapters`와 normalized utterance의 기존 chapter assignment를 deterministic하게 `script_chapters`로 노출합니다.
- **PART**는 사용자가 실제로 따라 하거나 다시 볼 가치가 있는 하나의 행동 목적을 가진 Catch-up unit입니다.
- **STEP**은 PART 목적을 순서대로 달성하기 위해 넘기는 행동 카드 한 장입니다.

이 세 구조는 서로 대체되지 않습니다. Creator chapter, `processed_chapter`, `content_chapters`를 PART와 1:1로 매핑하지 않습니다. `content_chapters`는 PART planning을 위한 semantic evidence이며 최종 PART boundary는 action-worthiness로 결정합니다. PART는 한 CHAPTER의 일부만 사용할 수 있고 여러 CHAPTER에 걸칠 수도 있습니다.

## Output

기존 final output directory에 다음 derived 파일을 atomic write합니다.

```text
output/
  {safe_video_title} [{video_id}]/
    {source_chapter_id}/
      {source_chapter_id}_preprocessed.json
      CCH-XX.jpg
      ddock_content_v0_1.json
```

Schema version은 `ddock_content_v0.1`입니다. Legacy video-ID output directory는 기존 restore compatibility에서 계속 읽을 수 있지만 신규 derived output은 현재 title-based helper를 사용합니다.

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

`script`는 `normalized_utterances`의 최종 `normalized_text`로 deterministic하게 만듭니다. Manual review가 적용된 문장은 수정된 normalized text를 사용하고 raw ASR provenance는 건드리지 않습니다.

각 Script row는 원래 `script_chapter_id`와 `catchup_part_ids`를 동시에 가집니다. Frontend는 CHAPTER header를 유지한 상태에서 `selected_part_id`가 row의 `catchup_part_ids`에 포함될 때만 PART highlight를 표시할 수 있습니다.

## Catch-up PART

PART planning은 다음 내용을 우선합니다.

- 실제 행동 흐름과 명확한 작업 목표
- 결과물을 만드는 과정과 반복 가능한 workflow
- 중요한 설정 또는 실습
- 문제에서 해결로 이어지는 과정
- 독립적으로 다시 볼 가치

단순 오프닝, 광고·홍보, giveaway, 반복, 긴 잡담, 행동으로 이어지지 않는 일반론은 기본 제외합니다. 행동 흐름이 없으면 `catchup_parts`는 빈 배열이고 generation status는 `no_actionable_content`입니다. PASS B가 source에 없는 행동·도구·대상을 만든 후보는 최종 PART에 빈 카드로 남기지 않고 제외하며 `curation_generation.warnings`에 candidate title과 실패 이유를 남깁니다.

PART 수는 고정하지 않습니다. PASS A는 전체 content chapter를 훑고 action-worthy chapter만 assessment로 명시하며, 생략된 chapter는 non-actionable로 기록합니다. PASS B가 STEP에 사용하지 않고 제외한 잡담·배경 발화는 최종 PART membership에서도 제거됩니다. 따라서 `source_utterance_ids`는 실제 행동 evidence의 union이자 정확한 Script highlight authority이며 start/end time은 그 membership의 convenience range입니다. PART evidence는 동일 ID와 source timestamp를 함께 보존합니다.

## STEP card surface

STEP surface는 다음만 유지합니다.

- 행동 중심 `action_title` 한 줄
- 1~4개의 짧은 `action_lines`
- source가 있는 경우에만 optional `prompt`
- source가 있는 경우에만 optional `warning`

작은 클릭을 무조건 별도 STEP으로 쪼개지 않습니다. 작업 목적이나 결과가 달라질 때 STEP을 나눕니다. 긴 배경, 이유, 대안, 비용, 실패 맥락은 `learn_more`로 이동합니다.

## Rich action-line segments

각 action line은 `text`와 ordered `segments`를 가집니다. 허용 semantic type은 다음 다섯 개뿐입니다.

- `text`
- `command`
- `ui_label`
- `filename`
- `path`

Type은 의미만 전달하며 색상, radius, font 같은 visual token을 결정하지 않습니다. `command`, `ui_label`, `filename`, `path`는 STEP evidence 원문에 정확한 literal이 있을 때만 허용됩니다. 모델이 근거 없는 rich type을 반환하면 해당 segment를 제거하고 warning을 남기며, 남은 근거 있는 action line이 없으면 그 PART generation을 거부합니다.

## Prompt policy

Prompt는 source에서 완전한 text가 확인될 때만 `source_kind: verbatim`으로 저장합니다. Prompt text와 evidence가 필수이며 모델이 새 prompt를 작성하거나 불완전한 prompt를 완성하면 해당 PART generation을 거부하고 `needs_review`를 남깁니다.

## Warning policy

실패, 제약, 비용, 주의, 잘못된 방법, 모델 선택 이유, 중요한 조건을 source가 명시한 경우에만 warning을 만듭니다. 일반 상식으로 warning을 추가하지 않으며 evidence가 필수입니다.

## Learn More

`learn_more`는 STEP마다 0개 이상이며 `question`, `body`, `evidence`, `source_timestamp`를 가집니다. 행동 surface가 아니라 이유, 배경, 대안, 비용, 선택 기준, 실패 맥락을 bottom sheet에서 보여주기 위한 구조입니다.

## Playback and Script target

`playback_start_seconds`는 STEP 첫 evidence utterance의 source start이고 `playback_end_seconds`는 마지막 evidence의 source end입니다. 임의 timestamp를 만들지 않습니다.

STEP 하단의 “구간 스크립트 보기”는 STEP 일부가 아니라 `parent_part_id`가 가리키는 PART 전체 Script를 선택합니다. Frontend는 Script tab에서 `selected_part_id`를 설정하고 row의 `catchup_part_ids`로 highlight합니다.

## Thumbnail mapping

새 screenshot은 생성하지 않습니다. PART source utterances와 기존 content-chapter ownership의 unique maximum overlap을 계산하고, 충분한 overlap이 있는 selected screenshot만 thumbnail로 참조합니다. 동률이거나 근거가 부족하면 `thumbnail`은 `null`입니다.

## Video detail

`video_detail`은 evidence-backed recommendation, tools, tags와 deterministic PART preview를 제공합니다.

- Recommendation은 누가, 어떤 문제에서, 무엇을 실제로 해보고, 어떤 확인 가능한 결과에 도달하는지 설명합니다.
- Tool 이름과 official Latin form은 source evidence에 있어야 합니다.
- URL은 trusted acquisition description에 실제 존재하는 값만 허용합니다.
- Tags는 업무 유형, 도구, 핵심 작업 중심의 최대 8개 semantic string입니다.
- PART preview는 final PART에서 deterministic하게 만듭니다.

조회수와 좋아요는 acquisition metadata가 있을 때만 `source`에 포함합니다.

## Model passes

기존 Qwen runtime을 재사용하며 새 모델이나 dependency를 설치하지 않습니다.

1. **PASS A — Action-worthiness and PART planning:** 전체 semantic/source evidence에서 PART objective와 exact membership만 결정합니다.
2. **PASS B — Per-PART STEP generation:** 승인된 PART마다 compact input으로 STEP surface, optional blocks, evidence를 생성하고, 실제 STEP evidence union으로 PART boundary를 좁힙니다. 한 PART 실패는 다른 PART를 막지 않습니다.
3. **PASS C — Video detail:** recommendation, tools, tags를 생성합니다.

각 pass는 명시된 JSON object contract를 사용하며 response는 `json.loads`로만 파싱합니다. Markdown fence나 regex recovery는 허용하지 않습니다. Transcript는 instruction이 아니라 untrusted source data입니다.

## Provenance and validation

PART, STEP, recommendation, tool, prompt, warning, Learn More에는 source utterance evidence가 있습니다. Validator는 다음을 포함해 publish 전 contract를 검사합니다.

- schema와 unsupported/visual/community field
- unique PART/STEP IDs와 순서
- PART/STEP membership과 source timestamp
- STEP evidence가 parent PART evidence의 subset인지
- action line 1~4개와 rich segment enum/literal
- prompt/warning/Learn More evidence
- playback timestamp가 STEP evidence에 있는지
- Script chapter consistency와 PART highlight reference
- thumbnail relative-path safety
- large PART/STEP evidence overlap warning

Validation error가 있으면 `ddock_content_v0_1.json`을 publish하지 않습니다. Validated temporary JSON만 atomic replace합니다. Action title/line, recommendation, tool description은 cited source에 대한 lexical grounding gate를 추가로 통과해야 합니다. 근거가 약한 STEP/PART는 제외하고, 근거가 약한 recommendation은 `null`, tool은 목록에서 제외하며 warning을 남깁니다.

## MVP boundary

포함: video detail content, Catch-up PART, PART 내부 STEP, STEP playback, PART/Script mapping, 전체 Script, source provenance.

제외: UI, visual tokens, 로그북, 사용자 결과물/feed, 업로드, 댓글, 좋아요 상태, 관련 영상, 회원 기능, backend persistence, 진행률/완료 상태. 기존 `src/lib/types.ts`와 seed `src/data/course.ts`는 UI 연결 단계 전까지 변경하지 않습니다.
