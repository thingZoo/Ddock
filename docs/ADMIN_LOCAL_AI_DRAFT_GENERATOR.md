# Admin Local AI Draft Generator

`/admin/content-review` can turn an existing `script_preprocessing_v0.3.*` JSON
into a `ddock_content_review_v0.1` Admin Review Draft. The draft is inserted
directly into the editor; review import, editing, autosave, export, validation,
preview, and publish-candidate behavior remain unchanged.

## Local-only setup

The route is disabled unless both values are supplied locally:

```sh
DDOCK_ENABLE_LOCAL_AI=1 \
DDOCK_LOCAL_PYTHON=/absolute/path/to/the/existing/mlx/python \
npm run dev:admin
```

The Admin-only development URL is
`http://localhost:3101/admin/content-review`. The existing `npm run dev`
command and its port behavior are unchanged.

The Python process reuses the repository's existing MLX Qwen loader and default
model. It runs with Hugging Face/Transformers offline flags and removes common
external LLM API keys from the child environment. Vercel execution is rejected.
No web lookup or external AI API is part of generation.

Optional diagnostics:

```sh
DDOCK_ADMIN_SKILL_DUMP_RAW=/absolute/path/to/raw-directory
DDOCK_ADMIN_SKILL_OUTPUT=/absolute/path/to/generated-review.json
```

Raw dumps contain each pass's input, prompt, raw response, parsed response, and
runtime. Do not enable them when the source material should not be retained.

## Resume after a deterministic failure

If PASS 1 and PASS 2 raw responses already succeeded but a later deterministic
parser or validator stopped the run, resume without repeating those model calls:

```sh
python ddock_admin_skill_generator.py \
  --preprocessed /absolute/path/to/preprocessed.json \
  --resume-from /absolute/path/to/previous-actual \
  --output /absolute/path/to/new-output/review.json
```

The source actual directory is read-only. Both available PASS 2 candidates are
replayed through the current parser and compared deterministically by valid
materialization, workflow recoverability, late-workflow preservation, invalid
references, weak-preparation warnings, writing-style warnings, and chronology.
Only PASS 3 is delegated to the local model. Resume metadata records replay and
model-call counts separately, so PASS 1 and PASS 2 model calls remain zero.

## Failure policy

Draft generation is fail-soft while publish validation remains fail-closed. A
usable PART and its grounded STEP, Learn More, Prompt, Warning, and Checkpoint
content survive unresolved anchor accounting. PASS 3 receives at most one targeted
repair call per PART; anchors still unresolved afterward become blocking Admin
review evidence. A zero-STEP PART also remains in the review draft with a blocking
review item. Unassigned PASS 2 anchors are projected into deterministic unassigned
phases so an Admin can connect, convert, or exclude them.

Only invalid preprocessing, unavailable model loading, unparseable PASS 1/PASS 2
JSON, zero action anchors, zero usable PART candidates, or an invalid review schema
fails the complete generation. Publish validation still rejects unresolved phases,
blocking review items, zero-STEP PARTs, and unsupported evidence.

## Generation pipeline

1. PASS 0 deterministically prepares provenance-preserving transcript rows and
   action-marker hints.
2. PASS 1 returns sparse direct-action `STEP` and optional `STEP_PREVIEW` seed
   anchor IDs. It is a fast locator, not a closed-world action inventory.
3. PASS 2 receives one immutable source-ordered action sequence addressed only by
   opaque `A01`-style action keys. Bounded context is embedded as read-only text
   without source IDs, so it cannot be selected as an action. The private Python
   map retains every action key's source utterance ID and provenance. The model
   returns only workflow start keys plus optional auxiliary and excluded decisions;
   every unspecified action defaults to core. Python materializes all contiguous
   membership, workflow IDs, order, and source spans, so missing membership and
   interleaved ownership are not representable in the normal path. Relative action-
   gap and weak-preparation signals can trigger at most one targeted boundary repair.
4. PASS 3 reads each PART's complete source span and action anchors independently. It
   creates source-grounded STEP lines, prompts, warnings, Learn More, and
   checkpoints without relying on global INFO or PASS 1 warning/checkpoint
   classification. It also accounts for every PART anchor by STEP assignment or
   explicit exclusion.
5. Action phases and review-queue items are derived from the draft for Admin
   review. Optional video-detail fields never block PART/STEP output.

The generation rubric is centralized in
`internal-tools/youtube-content-pipeline/prompts/ddock_admin_skill_v0_1.md`.
Prompt text is accepted only when it exists verbatim in source evidence; missing
or out-of-PART evidence is removed rather than invented.

PASS 1 uses one ultra-compact call. The response contains `mode` plus two ID
arrays: `step_ids` and `step_preview_ids`. Warning, checkpoint, background, and
conversation discovery is deferred to PASS 3. It contains no per-row objects,
transcript text, reasons, INFO/HOOK labels, or DROP rows/ranges.
Production parsing accepts whitespace, one Markdown fence, or short surrounding
prose by extracting the first balanced top-level JSON object. It never repairs a
truncated object or fabricates missing anchors. It deduplicates IDs in source
order and lets STEP win over an overlapping preview hint. Unknown IDs, malformed
schema, invalid mode, and an empty `step_ids` array fail deterministically.

PASS 2 requires a valid `start_action_key`, one `done_state`, and primary
tool/surface for every boundary. Invalid auxiliary or excluded keys are ignored
with review warnings; an invalid boundary item does not discard other usable
boundaries. A temporary compatibility path maps a source utterance ID back to its
unique action key, while a context-only source ID is ignored. Excluded wins an
auxiliary/excluded conflict, and boundary/core wins either classification. A
clearly over-collapsed composition receives at most one targeted PASS 2 repair
call. PASS 1 is not rerun and there is no generic repair loop. Noun-only PART/STEP
titles are preserved but projected as a non-blocking `writing_style_review`
warning for Admin copy review.

## Golden regression data

The human-reviewed G0 reference is stored only under
`internal-tools/youtube-content-pipeline/tests/fixtures/ddock_admin_skill_g0/`.
It is a deterministic quality fixture, never production runtime data. Production
code must not branch on its video ID, utterance IDs, timestamps, titles, or
expected card/step content.
