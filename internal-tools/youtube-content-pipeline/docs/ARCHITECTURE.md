# D:ock YouTube Content Pipeline Architecture

## Data flow

```text
Acquisition / Input
        ↓
Preprocessing
        ↓
Normalized utterances
        ↓
Content chapters
        ↓
Screenshot assets
        ↓
Optional review
        ↓
Final output
```

Acquisition preserves the YouTube source locator, transcript segments, timestamps, language, and creator-provided chapters. Preprocessing selects a `processed_chapter` scope and produces normalized utterances without replacing the source layer. `content_chapters` groups that processed material into stable D:ock content/card units. Screenshot candidates and the selected representative image remain assets owned by a content chapter. Optional script review records edits and provenance before final JSON and selected JPG assets are packaged.

## Chapter contracts

- `creator_chapters` belong to the source and reflect YouTube creator metadata.
- `processed_chapter` identifies the preprocessing scope, including a creator chapter or `FULL` whole-video processing.
- `content_chapters` are the final semantic units consumed by D:ock content/card workflows.

Keeping these layers separate prevents a UI/content decision from rewriting source metadata or changing the scope that produced the normalized text.

## Safety invariants

- **Raw provenance is immutable.** Source URL/video ID, original segments, timestamps, language, and creator chapter metadata are retained rather than overwritten by normalized values.
- **The normalized layer is editable.** Deterministic/model-assisted cleanup and manual review modify normalized output while recording review and correction provenance.
- **Content chapter ownership is stable.** A content chapter keeps a stable source scope and utterance relationship across screenshot and review operations.
- **Screenshot selection is independent of typo correction.** Choosing or replacing a representative image does not rewrite normalized text; manual script correction does not silently change the selected screenshot asset.
- **Optional failures are contained.** Audio re-ASR, semantic chapter enrichment, screenshot extraction, and review UI failures must not invalidate the baseline preprocessing result.

## Runtime boundaries

Local environments, model weights, media downloads, autosaves, screenshot candidate caches, and generated output remain outside Git. The repository contains code, tests, small terminology profiles, and documentation only.

## Imported baseline

- Standalone source: `cb406114cac88360c3f93a72a423ebd274732573`
- Standalone tag: `v0.3.16-review-ready`
- Module status: `0.3.16 / review-ready`
