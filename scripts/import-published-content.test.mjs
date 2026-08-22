import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  importPublishedContent,
  validateImportCandidate,
} from "./import-published-content.mjs";

function candidate(videoId = "fixture-video") {
  return {
    schema_version: "ddock_content_v0.1",
    source: { video_id: videoId },
    video_detail: {},
    script_chapters: [],
    catchup_parts: [],
    script: [],
    curation_generation: {},
  };
}

function withTempDirectory(run) {
  const directory = mkdtempSync(path.join(os.tmpdir(), "ddock-content-import-"));
  try {
    return run(directory);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

test("valid candidate import", () =>
  withTempDirectory((directory) => {
    const source = path.join(directory, "candidate.json");
    writeFileSync(source, JSON.stringify(candidate()));
    const target = importPublishedContent({ sourcePath: source, repositoryRoot: directory });
    assert.equal(path.basename(target), "fixture-video_ddock_content_v0_1.json");
    assert.deepEqual(JSON.parse(readFileSync(target, "utf8")), candidate());
  }));

test("wrong schema reject", () => {
  assert.throws(
    () => validateImportCandidate({ ...candidate(), schema_version: "wrong" }),
    /schema_version/,
  );
});

test("review draft reject", () => {
  assert.throws(
    () =>
      validateImportCandidate({
        ...candidate(),
        schema_version: "ddock_content_review_v0.1",
      }),
    /review draft/,
  );
});

test("missing video_id reject", () => {
  assert.throws(
    () => validateImportCandidate({ ...candidate(), source: {} }),
    /source.video_id/,
  );
});

test("existing target reject without --force", () =>
  withTempDirectory((directory) => {
    const source = path.join(directory, "candidate.json");
    writeFileSync(source, JSON.stringify(candidate()));
    importPublishedContent({ sourcePath: source, repositoryRoot: directory });
    assert.throws(
      () => importPublishedContent({ sourcePath: source, repositoryRoot: directory }),
      /already exists/,
    );
  }));

test("overwrite success with --force", () =>
  withTempDirectory((directory) => {
    const source = path.join(directory, "candidate.json");
    writeFileSync(source, JSON.stringify(candidate()));
    const target = importPublishedContent({ sourcePath: source, repositoryRoot: directory });
    writeFileSync(source, JSON.stringify({ ...candidate(), marker: "replacement" }));
    importPublishedContent({
      sourcePath: source,
      repositoryRoot: directory,
      force: true,
    });
    assert.equal(JSON.parse(readFileSync(target, "utf8")).marker, "replacement");
  }));
