import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { publishedContentToCourse, resolveUserCourses } from "./adapter";
import { assertPublishedContent, PublishedContentGuardError } from "./guard";
import { loadAllPublishedContent } from "./loader";
import { createLegacyCourse, createPublishedFixture } from "./test-fixture";

test("valid ddock_content_v0.1 converts to Course", () => {
  const course = publishedContentToCourse(createPublishedFixture());
  assert.equal(course.title, "Published Fixture");
  assert.equal(course.parts.length, 2);
});

test("review schema is rejected", () => {
  const value = { ...createPublishedFixture(), schema_version: "ddock_content_review_v0.1" };
  assert.throws(() => assertPublishedContent(value), PublishedContentGuardError);
});

test("source.video_id maps to youtubeId", () => {
  assert.equal(
    publishedContentToCourse(createPublishedFixture()).youtubeId,
    "fixture-video",
  );
});

test("matching legacy video keeps its route id", () => {
  assert.equal(
    publishedContentToCourse(createPublishedFixture(), createLegacyCourse()).id,
    "legacy-route",
  );
});

test("new published video uses source.video_id as route id", () => {
  assert.equal(
    publishedContentToCourse(createPublishedFixture()).id,
    "fixture-video",
  );
});

test("published PARTs completely replace legacy PARTs", () => {
  const course = publishedContentToCourse(createPublishedFixture(), createLegacyCourse());
  assert.deepEqual(course.parts.map((part) => part.id), ["PART-01", "PART-02"]);
  assert.equal(course.parts.some((part) => part.id === "legacy-part"), false);
});

test("published null recommendation never falls back to legacy", () => {
  const published = createPublishedFixture();
  published.video_detail.recommendation = null;
  assert.equal(publishedContentToCourse(published, createLegacyCourse()).recommend, null);
});

test("published tags are exact and do not merge legacy tags", () => {
  assert.deepEqual(
    publishedContentToCourse(createPublishedFixture(), createLegacyCourse()).tags,
    ["Cursor", "MCP"],
  );
});

test("PART order maps to partNo", () => {
  assert.deepEqual(
    publishedContentToCourse(createPublishedFixture()).parts.map((part) => part.partNo),
    [1, 2],
  );
});

test("action_objective maps to checkpoint", () => {
  assert.deepEqual(
    publishedContentToCourse(createPublishedFixture()).parts[0].checkpoint,
    { text: "설정 화면이 열린 상태를 확인한다" },
  );
});

test("rich action segments map text and literal types without rewriting", () => {
  const parts = publishedContentToCourse(createPublishedFixture()).parts[0].steps[0]
    .actions[0].parts;
  assert.deepEqual(
    parts.map((part) => part.kind),
    ["text", "code", "text", "code", "text", "code", "text", "code", "text"],
  );
  assert.deepEqual(
    parts.filter((part) => part.kind === "code").map((part) => part.value),
    ["npm run dev", "Settings", ".env", "/workspace/.env"],
  );
});

test("empty rich segments fall back to ActionLine.text", () => {
  assert.deepEqual(
    publishedContentToCourse(createPublishedFixture()).parts[0].steps[1].actions[0],
    { parts: [{ kind: "text", value: "연결 상태 확인" }] },
  );
});

test("prompt is preserved verbatim", () => {
  assert.equal(
    publishedContentToCourse(createPublishedFixture()).parts[0].steps[0].prompt?.code,
    "컴포넌트를 구현해 줘",
  );
});

test("warning is preserved", () => {
  assert.deepEqual(
    publishedContentToCourse(createPublishedFixture()).parts[0].steps[0].warning,
    {
      title: "키를 공유하지 마세요",
      body: "API 키는 공개 저장소에 올리지 마세요.",
    },
  );
});

test("Learn More maps question, body, timestamp, and evidence time", () => {
  assert.deepEqual(
    publishedContentToCourse(createPublishedFixture()).parts[0].steps[0].infoSheets[0],
    {
      id: "PART-01-STEP-01-INFO-1",
      question: "왜 설정 파일을 쓰나요?",
      body: "키를 코드와 분리할 수 있습니다.",
      timeLabel: "00:00",
      timeSec: 0,
    },
  );
});

test("prompt and warning are both preserved on one STEP", () => {
  const step = publishedContentToCourse(createPublishedFixture()).parts[0].steps[0];
  assert.ok(step.prompt);
  assert.ok(step.warning);
});

test("multi-PART script membership is preserved", () => {
  const row = publishedContentToCourse(createPublishedFixture()).script[1];
  assert.equal(row.partNo, 1);
  assert.deepEqual(row.partNos, [1, 2]);
});

test("null script chapter remains null without a fake chapter", () => {
  const row = publishedContentToCourse(createPublishedFixture()).script[2];
  assert.equal(row.chapterId, null);
  assert.equal(row.chapterLabel, undefined);
});

test("non-public part thumbnail falls back to hero", () => {
  const course = publishedContentToCourse(createPublishedFixture(), createLegacyCourse());
  assert.equal(course.parts[0].thumbnail, "/img/hero.jpg");
  assert.equal(course.parts[1].thumbnail, "/img/part2.jpg");
});

test("missing source stats create no fake values", () => {
  const published = createPublishedFixture();
  delete published.source.view_count;
  delete published.source.like_count;
  const course = publishedContentToCourse(published, createLegacyCourse());
  assert.equal(course.ratingLabel, undefined);
  assert.equal(course.viewCountLabel, undefined);
  assert.equal(course.likeLabel, undefined);
});

test("published tools use canonical names and presentation-only legacy icons", () => {
  const course = publishedContentToCourse(createPublishedFixture(), createLegacyCourse());
  assert.deepEqual(
    course.tools.map((tool) => ({ name: tool.name, icon: tool.icon })),
    [
      { name: "Cursor", icon: "/img/tool1.jpg" },
      { name: "Example CLI", icon: undefined },
    ],
  );
});

test("legacy-only course resolves unchanged", () => {
  const legacy = createLegacyCourse();
  assert.equal(resolveUserCourses([legacy], [])[0], legacy);
});

test("published course overrides the same-video legacy course", () => {
  const course = resolveUserCourses(
    [createLegacyCourse()],
    [createPublishedFixture()],
  )[0];
  assert.equal(course.id, "legacy-route");
  assert.equal(course.title, "Published Fixture");
});

test("published-only course is added beside legacy courses", () => {
  const published = createPublishedFixture();
  published.source.video_id = "new-video";
  const courses = resolveUserCourses([createLegacyCourse()], [published]);
  assert.deepEqual(courses.map((course) => course.id), ["legacy-route", "new-video"]);
});

test("duplicate published video IDs are rejected", () => {
  const first = createPublishedFixture();
  const second = structuredClone(first);
  assert.throws(
    () => resolveUserCourses([], [first, second]),
    /duplicate published video_id/,
  );
});

test("duplicate resulting course IDs are rejected", () => {
  const legacy = createLegacyCourse();
  const published = createPublishedFixture();
  published.source.video_id = legacy.id;
  assert.throws(
    () => resolveUserCourses([legacy], [published]),
    /duplicate resulting course.id/,
  );
});

test("empty published directory is valid", () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "ddock-loader-empty-"));
  try {
    assert.deepEqual(loadAllPublishedContent(directory), []);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("loader reports invalid filename and reason", () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "ddock-loader-invalid-"));
  try {
    writeFileSync(path.join(directory, "bad.json"), JSON.stringify({ schema_version: "bad" }));
    assert.throws(
      () => loadAllPublishedContent(directory),
      /Invalid published content bad.json: schema_version/,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("loader reads a valid published candidate", () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "ddock-loader-valid-"));
  try {
    writeFileSync(
      path.join(directory, "fixture-video_ddock_content_v0_1.json"),
      JSON.stringify(createPublishedFixture()),
    );
    assert.equal(loadAllPublishedContent(directory)[0].source.video_id, "fixture-video");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
