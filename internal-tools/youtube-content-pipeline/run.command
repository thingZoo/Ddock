#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

fail() {
  echo "YouTube AI 통합 도구 실행 준비 오류: $1" >&2
  echo "이 창을 닫지 말고 위 오류 내용을 확인해 주세요." >&2
  exit 1
}

for REQUIRED_FILE in \
  app_v0316_launcher.py \
  app.py \
  preprocessor.py \
  v0315_1_patch.py \
  v0316_extension.py \
  korean_full_scope.py \
  review_store.py \
  content_chapters.py \
  content_chapter_segmentation.py \
  content_chapter_role_audit.py \
  runtime_generation_metrics.py \
  korean_evidence_normalization.py \
  korean_asr_editorial_review.py \
  korean_audio_reasr.py \
  profiles/verified_correction_memory_v0_1.json \
  profiles/verified_correction_memory_v0_2.json \
  profiles/canonical_entity_registry_v0_2.json \
  profiles/canonical_entity_registry_v0_3.json \
  screenshot_ui.py \
  screenshot_runtime.py \
  screenshot_output.py \
  screenshot_candidates.py \
  representative_moment.py \
  youtube_acquisition_runtime.py \
  youtube_acquisition_ui.py \
  youtube_acquisition/collector.py \
  requirements.txt
do
  if [ ! -f "$REQUIRED_FILE" ]; then
    fail "필수 파일이 없습니다: $REQUIRED_FILE"
  fi
done

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  BOOTSTRAP_PYTHON="${YSP_PYTHON:-/usr/bin/python3}"
  if [ ! -x "$BOOTSTRAP_PYTHON" ]; then
    BOOTSTRAP_PYTHON="$(command -v python3 || true)"
  fi
  if [ -z "$BOOTSTRAP_PYTHON" ] || [ ! -x "$BOOTSTRAP_PYTHON" ]; then
    fail "Python 3를 찾을 수 없습니다. macOS Python 3 환경을 확인해 주세요."
  fi
  if ! "$BOOTSTRAP_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    fail "Python 3.9 이상이 필요합니다."
  fi
  echo "통합 도구 전용 Python 환경을 최초 1회 준비합니다."
  "$BOOTSTRAP_PYTHON" -m venv .venv || fail ".venv 생성에 실패했습니다."
fi

if ! "$PYTHON" -c 'import streamlit, pandas, requests, isodate, youtube_transcript_api, mlx, mlx_lm' >/dev/null 2>&1; then
  echo "필요한 Python 패키지를 최초 1회 준비합니다. Qwen 모델 파일은 다운로드하지 않습니다."
  "$PYTHON" -m pip install -r requirements.txt || fail "Python 패키지 설치에 실패했습니다."
fi

mkdir -p autosave/screenshot_candidates output/collections
exec "$PYTHON" -m streamlit run app_v0316_launcher.py
