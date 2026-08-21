import {
  toLabel,
  type ActionLine,
  type Course,
  type Part,
  type ScriptSegment,
  type Step,
  type Tool,
} from "../types";
import type {
  PublishedActionLine,
  PublishedContent,
  PublishedSource,
} from "./types";

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function countLabel(value: unknown): string | undefined {
  const number = finiteNumber(value);
  return number === undefined ? undefined : Math.trunc(number).toLocaleString("ko-KR");
}

function dateLabel(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  return `${Number(match[1])}년 ${Number(match[2])}월 ${Number(match[3])}일`;
}

function dateValue(value: string | undefined): string | undefined {
  return value?.match(/^\d{4}-\d{2}-\d{2}/)?.[0] ?? value;
}

function durationLabel(seconds: number | undefined): string | undefined {
  if (seconds === undefined) return undefined;
  const whole = Math.max(0, Math.round(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  return hours > 0
    ? `${hours}시간 ${minutes}분 ${rest}초`
    : `${minutes}분 ${rest}초`;
}

function normalizeToolName(value: string): string {
  return value.trim().toLocaleLowerCase("en-US");
}

function publicCompatibleAsset(value: unknown): string | undefined {
  const path = nonEmptyString(value);
  if (!path) return undefined;
  return path.startsWith("/") || /^https?:\/\//.test(path) ? path : undefined;
}

function sourceString(source: PublishedSource, key: string): string | undefined {
  return nonEmptyString(source[key]);
}

function sourceNumber(source: PublishedSource, key: string): number | undefined {
  return finiteNumber(source[key]);
}

function actionLine(line: PublishedActionLine): ActionLine {
  if (line.segments.length === 0) {
    return { parts: [{ kind: "text", value: line.text }] };
  }
  return {
    parts: line.segments.map((segment) => ({
      kind: segment.type === "text" ? "text" : "code",
      value: segment.text,
    })),
  };
}

function step(value: PublishedContent["catchup_parts"][number]["steps"][number]): Step {
  return {
    id: value.step_id,
    order: value.order,
    variant: value.prompt ? "prompt" : value.warning ? "warning" : "basic",
    title: value.action_title,
    actions: value.action_lines.map(actionLine),
    prompt: value.prompt
      ? { code: value.prompt.text, label: "복사해서 사용하세요" }
      : undefined,
    warning: value.warning
      ? { title: value.warning.title, body: value.warning.body }
      : undefined,
    infoSheets: value.learn_more.map((item, index) => ({
      id: `${value.step_id}-INFO-${index + 1}`,
      question: item.question,
      body: item.body,
      timeLabel: item.source_timestamp || undefined,
      timeSec: item.evidence[0]?.start_seconds ?? value.playback_start_seconds,
    })),
    startSec: value.playback_start_seconds,
    endSec: value.playback_end_seconds,
  };
}

function mapTools(published: PublishedContent, legacyCourse?: Course): Tool[] {
  const legacyIcons = new Map(
    (legacyCourse?.tools ?? [])
      .filter((tool) => tool.icon)
      .map((tool) => [normalizeToolName(tool.name), tool.icon]),
  );

  return published.video_detail.tools.map((value) => {
    const name = value.canonical_name.trim() || value.name;
    return {
      name,
      icon: legacyIcons.get(normalizeToolName(name)),
      url: value.url ?? undefined,
      description: value.description.trim() || undefined,
    };
  });
}

function heroThumbnail(published: PublishedContent, legacyCourse?: Course): string {
  const legacyHero = publicCompatibleAsset(legacyCourse?.thumbnail);
  return legacyHero ?? `https://i.ytimg.com/vi/${published.source.video_id}/hqdefault.jpg`;
}

function mapParts(published: PublishedContent, hero: string): Part[] {
  return published.catchup_parts.map((value) => ({
    id: value.part_id,
    partNo: value.order,
    title: value.title,
    thumbnail: publicCompatibleAsset(value.thumbnail?.relative_path) ?? hero,
    timeLabel:
      value.start_timestamp && value.end_timestamp
        ? `${value.start_timestamp}-${value.end_timestamp}`
        : `${toLabel(value.start_seconds)}-${toLabel(value.end_seconds)}`,
    startSec: value.start_seconds,
    endSec: value.end_seconds,
    steps: value.steps.map(step),
    chapterIds: [...value.source_script_chapter_ids],
    summary: value.summary ?? "",
    tool: null,
    checkpoint: { text: value.action_objective },
  }));
}

function mapScript(
  published: PublishedContent,
  parts: Part[],
): ScriptSegment[] {
  const partNumbers = new Map(parts.map((part) => [part.id, part.partNo]));
  const chapterLabels = new Map(
    published.script_chapters.map((chapter) => [chapter.chapter_id, chapter.title]),
  );

  return published.script.map((row) => {
    const membership = row.catchup_part_ids
      .map((partId) => partNumbers.get(partId))
      .filter((partNo): partNo is number => partNo !== undefined);
    return {
      id: row.utterance_id,
      chapterId: row.script_chapter_id,
      chapterLabel:
        row.script_chapter_id === null
          ? undefined
          : chapterLabels.get(row.script_chapter_id),
      partNo: membership[0] ?? null,
      partNos: membership,
      timeLabel: row.timestamp,
      timeSec: row.start_seconds,
      endSec: row.end_seconds,
      text: row.text,
    };
  });
}

export function publishedContentToCourse(
  published: PublishedContent,
  legacyCourse?: Course,
): Course {
  const source = published.source;
  const sourcePublishedAt = sourceString(source, "published_at");
  const sourceDuration = sourceNumber(source, "duration_seconds");
  const hero = heroThumbnail(published, legacyCourse);
  const parts = mapParts(published, hero);
  const tools = mapTools(published, legacyCourse);
  const highlightTool = tools.find((tool) => tool.description || tool.url);
  const viewCount = countLabel(source.view_count);
  const likeCount = countLabel(source.like_count);

  return {
    id: legacyCourse?.id ?? source.video_id,
    youtubeId: source.video_id,
    title: nonEmptyString(source.title) ?? legacyCourse?.title ?? source.video_id,
    breadcrumb: legacyCourse ? [...legacyCourse.breadcrumb] : [],
    thumbnail: hero,
    channel: {
      name: nonEmptyString(source.channel_name) ?? legacyCourse?.channel.name ?? "",
      avatar: legacyCourse?.channel.avatar,
      url: legacyCourse?.channel.url,
      platform: legacyCourse?.channel.platform,
    },
    sourceUrl: sourceString(source, "source_url"),
    publishedAt: dateValue(sourcePublishedAt) ?? legacyCourse?.publishedAt,
    publishedLabel: dateLabel(sourcePublishedAt) ?? legacyCourse?.publishedLabel,
    ratingLabel: undefined,
    helpLabel: undefined,
    viewLabel: viewCount ? `조회수 ${viewCount}회` : undefined,
    viewCountLabel: viewCount,
    likeLabel: likeCount,
    tags: [...published.video_detail.tags],
    recommend: published.video_detail.recommendation
      ? {
          badge: published.video_detail.recommendation.eyebrow,
          title: published.video_detail.recommendation.title,
          body: published.video_detail.recommendation.body,
        }
      : null,
    tools,
    toolHighlight: highlightTool
      ? {
          name: highlightTool.name,
          url: highlightTool.url,
          desc: highlightTool.description,
        }
      : undefined,
    relatedVideos: legacyCourse ? [...legacyCourse.relatedVideos] : [],
    parts,
    scriptChapters: published.script_chapters.map((chapter) => ({
      id: chapter.chapter_id,
      label: chapter.title,
      startSec: chapter.start_seconds,
      endSec: chapter.end_seconds,
    })),
    script: mapScript(published, parts),
    durationLabel: durationLabel(sourceDuration) ?? legacyCourse?.durationLabel,
  };
}

export function resolveUserCourses(
  legacyCourses: Course[],
  publishedContents: PublishedContent[],
): Course[] {
  const legacyByVideoId = new Map<string, Course>();
  for (const legacy of legacyCourses) {
    if (legacyByVideoId.has(legacy.youtubeId)) {
      throw new Error(`duplicate legacy video_id: ${legacy.youtubeId}`);
    }
    legacyByVideoId.set(legacy.youtubeId, legacy);
  }

  const publishedByVideoId = new Map<string, PublishedContent>();
  for (const published of publishedContents) {
    const videoId = published.source.video_id;
    if (publishedByVideoId.has(videoId)) {
      throw new Error(`duplicate published video_id: ${videoId}`);
    }
    publishedByVideoId.set(videoId, published);
  }

  const resolved = legacyCourses.map((legacy) => {
    const published = publishedByVideoId.get(legacy.youtubeId);
    if (!published) return legacy;
    publishedByVideoId.delete(legacy.youtubeId);
    return publishedContentToCourse(published, legacy);
  });

  for (const published of publishedByVideoId.values()) {
    resolved.push(publishedContentToCourse(published));
  }

  const ids = new Set<string>();
  for (const course of resolved) {
    if (ids.has(course.id)) {
      throw new Error(`duplicate resulting course.id: ${course.id}`);
    }
    ids.add(course.id);
  }
  return resolved;
}
