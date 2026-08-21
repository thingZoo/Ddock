# Optional Korean audio re-ASR setup

The Korean audio re-ASR stage is optional. The application does not install a
speech package or download model weights automatically. When either dependency
is absent, preprocessing continues with deterministic normalization and records
the affected rows as `review_pending`.

Recommended Apple Silicon runtime:

- Engine: `mlx-whisper==0.4.3`
- Model: `mlx-community/whisper-large-v3-turbo`
- Required system tool: `ffmpeg`

Install the Python package into this distribution's virtual environment only:

```bash
.venv/bin/python -m pip install "mlx-whisper==0.4.3"
```

Download the model explicitly to a user-chosen local directory. Then expose
that directory when launching the app:

```bash
export KOREAN_AUDIO_ASR_MODEL_PATH="/absolute/path/to/whisper-large-v3-turbo"
./run.command
```

The directory must already contain `config.json` and the complete
`*.safetensors` weights. A Hugging Face repository ID is never passed to the
runtime adapter, preventing an implicit model download.

The optional per-video review-duration budget defaults to 180 seconds of
clustered audio and can be adjusted without changing code:

```bash
export KOREAN_AUDIO_REVIEW_BUDGET_SECONDS="180"
```
