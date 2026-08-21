export {
  PUBLISHED_SCHEMA_VERSION,
  type PublishedContent,
} from "../admin-content-review/types";

export type {
  ActionLine as PublishedActionLine,
  DraftStep as PublishedStep,
  LearnMoreBlock as PublishedLearnMore,
  ScriptChapter as PublishedScriptChapter,
  ScriptRow as PublishedScriptRow,
  SourceData as PublishedSource,
  ToolData as PublishedTool,
  VideoDetailData as PublishedVideoDetail,
} from "../admin-content-review/types";

import type { PublishedContent } from "../admin-content-review/types";

export type PublishedPart = PublishedContent["catchup_parts"][number];
