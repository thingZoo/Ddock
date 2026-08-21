from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re

import pandas as pd

from preprocessor import export_editor_result


def dataframe_from_draft(draft):
    rows = []
    for index, item in enumerate(
        draft.get("normalized_utterances", []),
        start=1,
    ):
        rows.append(
            {
                "no": index,
                "utterance_id": item.get("utterance_id", ""),
                "timestamp": item.get("display_timestamp", ""),
                "raw_joined_text": item.get("raw_joined_text", ""),
                "normalized_text": item.get("normalized_text", ""),
                "confidence": item.get("confidence", "low"),
                "review_status": item.get("review_status", "needs_review"),
                "editor_note": item.get("editor_note", ""),
            }
        )
    return pd.DataFrame(rows)


def current_result(draft, df):
    rows = df.to_dict(orient="records")
    return export_editor_result(draft, rows)


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "unknown"))


def autosave_path(base_dir, result):
    video_id = _safe_name(result.get("video_id", "video"))
    chapter_id = _safe_name(
        result.get("processed_chapter", {}).get("chapter_id", "CH")
    )
    return Path(base_dir) / f"{video_id}_{chapter_id}_autosave.json"


def atomic_autosave(base_dir, result):
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    result = json.loads(json.dumps(result, ensure_ascii=False))
    result["local_autosave"] = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "mode": "whole_chapter_atomic_save",
    }
    target = autosave_path(base, result)
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, target)
    return target, result


def load_autosave(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
