import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { chromium } from "playwright";

import { createReviewFixture } from "../src/lib/admin-content-review/test-fixture.ts";

const baseUrl = process.env.DDOCK_ADMIN_BASE_URL ?? "http://127.0.0.1:3101";
const fixturePath = process.env.DDOCK_ADMIN_PREPROCESSED_FIXTURE;
const review = createReviewFixture();
const preprocessed = fixturePath
  ? JSON.parse(await readFile(fixturePath, "utf8"))
  : {
      schema_version: "script_preprocessing_v0.3.15.1",
      video_id: "fixture-video",
      normalized_utterances: [
        {
          utterance_id: "UT-00001",
          start_seconds: 0,
          end_seconds: 8,
          normalized_text: "설정 메뉴를 엽니다.",
        },
      ],
    };

const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.DDOCK_ADMIN_CHROME_PATH ??
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage();
const consoleErrors = [];
const consoleWarnings = [];
const failedRequests = [];
const apiRequests = [];
const apiStatuses = [];

page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
  if (message.type() === "warning") consoleWarnings.push(message.text());
});
page.on("requestfailed", (request) => {
  failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`);
});
page.on("request", (request) => {
  if (request.url().includes("/api/admin/local-curation")) {
    apiRequests.push(`${request.method()} ${request.url()}`);
  }
});
page.on("response", (response) => {
  if (response.url().includes("/api/admin/local-curation")) {
    apiStatuses.push(response.status());
  }
});

const filePayload = (name, value) => ({
  name,
  mimeType: "application/json",
  buffer: Buffer.from(JSON.stringify(value)),
});

try {
  await page.goto(`${baseUrl}/admin/content-review`, { waitUntil: "networkidle" });

  const preprocessingButton = page.getByRole("button", {
    name: "전처리 JSON 불러오기",
  });
  const reviewButton = page.getByRole("button", { name: "Review JSON 불러오기" });
  assert.equal(await preprocessingButton.count(), 1, "preprocessing import button missing");
  assert.equal(await reviewButton.count(), 1, "review import button missing");
  assert.equal(await preprocessingButton.isEnabled(), true);
  assert.equal(await reviewButton.isEnabled(), true);
  assert.equal(await page.locator('input[type="file"]').count(), 2);

  const reviewChooserPromise = page.waitForEvent("filechooser");
  await reviewButton.click();
  const reviewChooser = await reviewChooserPromise;
  await reviewChooser.setFiles(filePayload("review.json", review));
  await page.getByText("Admin Review Fixture", { exact: true }).waitFor();

  for (const label of [
    "전처리 JSON 불러오기",
    "Review JSON 불러오기",
    "초안 내보내기",
    "발행 전 검사",
    "미리보기",
    "발행 파일 만들기",
  ]) {
    assert.equal(await page.getByRole("button", { name: label }).count(), 1, `${label} missing`);
  }

  await page.evaluate(() => window.localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });

  const preprocessingChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "전처리 JSON 불러오기" }).click();
  const preprocessingChooser = await preprocessingChooserPromise;
  await preprocessingChooser.setFiles(filePayload("preprocessed.json", preprocessed));
  await page.getByText("전처리 JSON 준비됨", { exact: true }).waitFor();
  await page.getByText(`${preprocessed.normalized_utterances.length}개 발화 · API 비용 없음`, {
    exact: true,
  }).waitFor();

  const generateButton = page.getByRole("button", { name: "로컬 AI 초안 생성" });
  assert.equal(await generateButton.isEnabled(), true);

  const preprocessingInput = page.locator('input[type="file"]').nth(1);
  await preprocessingInput.setInputFiles(
    filePayload("invalid.json", { schema_version: "invalid" }),
  );
  await page.getByText("불러오기 실패", { exact: true }).waitFor();
  assert.equal(await page.getByText("전처리 JSON 준비됨", { exact: true }).count(), 1);
  assert.equal(await generateButton.isEnabled(), true);
  await page.getByRole("button", { name: "닫기" }).click();

  let releaseSuccess;
  const successGate = new Promise((resolve) => {
    releaseSuccess = resolve;
  });
  await page.route("**/api/admin/local-curation", async (route) => {
    await successGate;
    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body: [
        JSON.stringify({ type: "progress", stage: "writing_steps", part_index: 1 }),
        JSON.stringify({ type: "result", review }),
        "",
      ].join("\n"),
    });
  });

  await generateButton.click();
  await page.getByText(/초안 준비 중/).waitFor();
  const loadingVisible = await page.getByText(/초안 준비 중/).isVisible();
  releaseSuccess();

  await page.getByText("MCP 설정을 준비해요", { exact: true }).first().waitFor();
  await page.getByText("MCP 탭을 열어요", { exact: true }).first().waitFor();

  const partButton = page.getByRole("button", { name: /PART-01.*MCP 설정을 준비해요/ });
  const stepButton = page.getByRole("button", { name: /STEP-01.*MCP 탭을 열어요/ });
  assert.equal(await partButton.count(), 1);
  assert.equal(await stepButton.count(), 1);
  await partButton.click();
  await page.getByRole("heading", { name: "PART 편집" }).waitFor();
  await stepButton.click();
  await page.getByRole("heading", { name: "STEP 편집" }).waitFor();

  await page.getByRole("button", { name: "미리보기" }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "미리보기 닫기" }).click();
  await page.getByRole("button", { name: "발행 전 검사" }).click();
  await page.getByRole("region", { name: "검사 결과" }).waitFor();

  const acceptanceConsoleErrors = [...consoleErrors];
  const acceptanceFailedRequests = [...failedRequests];
  assert.equal(
    acceptanceConsoleErrors.length,
    0,
    `console errors: ${acceptanceConsoleErrors.join("\n")}`,
  );
  assert.equal(
    acceptanceFailedRequests.length,
    0,
    `failed requests: ${acceptanceFailedRequests.join("\n")}`,
  );

  await page.unroute("**/api/admin/local-curation");
  await page.route("**/api/admin/local-curation", async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        error: "로컬 AI 기능이 비활성화되어 있습니다. DDOCK_ENABLE_LOCAL_AI=1로 실행해주세요.",
      }),
    });
  });
  await page.getByRole("button", { name: "로컬 AI 초안 생성" }).click();
  await page.getByText("생성 실패", { exact: true }).waitFor();
  assert.equal(await page.getByText("Admin Review Fixture", { exact: true }).count(), 1);

  process.stdout.write(
    `${JSON.stringify(
      {
        rootHydrated: true,
        fileInputs: 2,
        reviewImport: true,
        preprocessingImport: true,
        utteranceCount: preprocessed.normalized_utterances.length,
        localAiEnabled: true,
        loadingVisible,
        stateInjection: true,
        partNavigation: true,
        stepNavigation: true,
        partClick: true,
        stepClick: true,
        previewClick: true,
        validateClick: true,
        apiRequests,
        apiStatuses,
        consoleErrors: acceptanceConsoleErrors,
        consoleWarnings,
        failedRequests: acceptanceFailedRequests,
        intentionalDisabledResponseErrors: consoleErrors.slice(
          acceptanceConsoleErrors.length,
        ),
      },
      null,
      2,
    )}\n`,
  );
} finally {
  await browser.close();
}
