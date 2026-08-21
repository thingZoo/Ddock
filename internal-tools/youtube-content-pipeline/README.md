# D:ock YouTube Content Pipeline

**Status:** v0.3.16 / review-ready

**Initial implementation:** @thingZoo

YouTube 콘텐츠를 D:ock 서비스에서 사용할 수 있는 구조화된 데이터로 변환하기 위한 내부 콘텐츠 준비 파이프라인입니다. 현재 standalone 동작을 보존한 채 팀 저장소에 독립 모듈로 가져왔으며, Ddock 프런트엔드 런타임과는 아직 연결되어 있지 않습니다.

## Pipeline

```text
YouTube source
→ transcript acquisition/input
→ script preprocessing
→ Korean / foreign normalization
→ verified terminology/entity recovery
→ Korean selective audio re-ASR
→ content chapters
→ representative screenshot candidates
→ selected representative screenshot
→ optional manual script review
→ final structured output
```

## 핵심 데이터 계약

- `creator_chapters`: YouTube 제작자가 제공한 source chapter입니다.
- `processed_chapter`: 현재 preprocessing 실행 범위입니다. 제작자 chapter 하나 또는 전체 영상(`FULL`)이 될 수 있습니다.
- `content_chapters`: D:ock 콘텐츠/card unit으로 사용하는 최종 content segmentation입니다.

세 개념은 서로 대체할 수 없으며 source provenance, 처리 범위, 최종 콘텐츠 소유권을 각각 보존합니다. 자세한 흐름과 안전 원칙은 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.

## 현재 상태

v0.3.16에서 다음 기능을 review-ready 상태로 제공합니다.

- Korean / foreign preprocessing
- official terminology and entity normalization
- content chapter foundation and semantic segmentation
- selective Korean audio review/re-ASR
- representative screenshot planning, generation, and selection
- optional manual script review

다음 단계는 `content_chapters`와 normalized data를 D:ock frontend/content UI data contract에 연결하는 것입니다.

## 실행

지원 환경은 macOS, Python 3.9 이상입니다. Apple Silicon 로컬 모델 경로와 system `ffmpeg` 등 선택 기능의 의존성은 실행 환경에서 별도로 준비합니다. 모델 weight, runtime output, cache는 저장소에 포함하지 않습니다.

```bash
cd internal-tools/youtube-content-pipeline
./run.command
```

`run.command`는 최초 실행 시 모듈 내부에 `.venv`를 만들고 `requirements.txt`를 설치한 뒤 `app_v0316_launcher.py`를 Streamlit으로 실행합니다. Qwen 모델 weight를 직접 번들하지 않으며 기존 Hugging Face/MLX cache를 사용합니다.

Korean selective audio re-ASR은 선택 기능입니다. 검증된 조합은 `mlx-whisper==0.4.3`과 `mlx-community/whisper-large-v3-turbo`이며 모델 자체는 저장소에 포함하지 않습니다. 설치 및 명시적 로컬 모델 경로 설정은 [KOREAN_AUDIO_REASR_SETUP.md](KOREAN_AUDIO_REASR_SETUP.md)를 참고하세요.

## Runtime data

- 복구용 autosave와 screenshot candidate cache: `autosave/`
- 최종 결과: `output/{video_id}/{source_chapter_id}/`
- 최종 JSON: `{source_chapter_id}_preprocessed.json`
- 선택된 대표 이미지: `{content_chapter_id}.jpg`

`autosave/`, `output/`, `.venv/`, 모델/cache/media 파일은 로컬 runtime data이며 Git에 포함하지 않습니다.

## Source provenance

- Standalone source HEAD: `cb406114cac88360c3f93a72a423ebd274732573`
- Standalone tag: `v0.3.16-review-ready`
- Imported status: `0.3.16 / review-ready`

Standalone 저장소의 `.git` history는 이 모듈에 중첩하지 않았습니다. 위 provenance가 원본 개발 history와 팀 저장소의 import commit을 연결합니다.
