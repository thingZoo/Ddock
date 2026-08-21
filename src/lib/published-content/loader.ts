import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { assertPublishedContent } from "./guard";
import type { PublishedContent } from "./types";

export const PUBLISHED_CONTENT_DIRECTORY = path.join(
  process.cwd(),
  "content",
  "published",
);

export function loadAllPublishedContent(
  directory = PUBLISHED_CONTENT_DIRECTORY,
): PublishedContent[] {
  let filenames: string[];
  try {
    filenames = readdirSync(directory)
      .filter((filename) => filename.endsWith(".json"))
      .sort();
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return [];
    throw error;
  }

  return filenames.map((filename) => {
    const sourcePath = path.join(directory, filename);
    let value: unknown;
    try {
      value = JSON.parse(readFileSync(sourcePath, "utf8"));
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`Invalid published content ${filename}: ${reason}`);
    }
    try {
      assertPublishedContent(value);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`Invalid published content ${filename}: ${reason}`);
    }
    return value;
  });
}

export function loadPublishedContentByVideoId(
  videoId: string,
  directory = PUBLISHED_CONTENT_DIRECTORY,
): PublishedContent | undefined {
  const matches = loadAllPublishedContent(directory).filter(
    (content) => content.source.video_id === videoId,
  );
  if (matches.length > 1) {
    throw new Error(`duplicate published video_id: ${videoId}`);
  }
  return matches[0];
}
