import { constants, copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PUBLISHED_SCHEMA_VERSION = "ddock_content_v0.1";
const REVIEW_SCHEMA_VERSION = "ddock_content_review_v0.1";

export function parseImportArguments(argv) {
  const force = argv.includes("--force");
  const positional = argv.filter((value) => value !== "--force");
  if (positional.length !== 1) {
    throw new Error(
      "Usage: npm run content:import -- <published-json-path> [--force]",
    );
  }
  return { sourcePath: positional[0], force };
}

export function validateImportCandidate(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("published content must be a JSON object");
  }
  if (value.schema_version === REVIEW_SCHEMA_VERSION) {
    throw new Error("review draft ddock_content_review_v0.1 cannot be imported");
  }
  if (value.schema_version !== PUBLISHED_SCHEMA_VERSION) {
    throw new Error(`schema_version must be ${PUBLISHED_SCHEMA_VERSION}`);
  }
  const videoId = value.source?.video_id;
  if (typeof videoId !== "string" || videoId.trim() === "") {
    throw new Error("source.video_id must be a non-empty string");
  }
  if (!/^[A-Za-z0-9_-]+$/.test(videoId)) {
    throw new Error("source.video_id contains unsafe filename characters");
  }
  return videoId;
}

export function importPublishedContent({
  sourcePath,
  force = false,
  repositoryRoot = process.cwd(),
}) {
  const absoluteSource = path.resolve(sourcePath);
  if (!existsSync(absoluteSource)) {
    throw new Error(`source file not found: ${absoluteSource}`);
  }

  let value;
  try {
    value = JSON.parse(readFileSync(absoluteSource, "utf8"));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`invalid JSON: ${reason}`);
  }

  const videoId = validateImportCandidate(value);
  const targetDirectory = path.join(repositoryRoot, "content", "published");
  const targetPath = path.join(
    targetDirectory,
    `${videoId}_ddock_content_v0_1.json`,
  );
  mkdirSync(targetDirectory, { recursive: true });

  if (existsSync(targetPath) && !force) {
    throw new Error(`target already exists: ${targetPath} (use --force to overwrite)`);
  }
  copyFileSync(
    absoluteSource,
    targetPath,
    force ? 0 : constants.COPYFILE_EXCL,
  );
  return targetPath;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    const options = parseImportArguments(process.argv.slice(2));
    const target = importPublishedContent(options);
    console.log(`Imported published content: ${target}`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
