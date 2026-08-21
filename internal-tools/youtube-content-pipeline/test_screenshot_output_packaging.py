from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from screenshot_candidates import build_screenshot_plan, chapter_fingerprint
from screenshot_output import (
    final_chapter_directory,
    final_image_path,
    final_json_path,
    final_video_directory_name,
    resolve_selected_path,
    safe_video_title,
    scope_candidate_assets,
    scoped_candidate_relative_path,
)
from screenshot_runtime import (
    PINNED_YTDLP_CHANNEL,
    PINNED_YTDLP_SHA256,
    PINNED_YTDLP_VERSION,
    TOOL_VERSION_CHECK_TIMEOUT_SECONDS,
    generate_screenshot_candidates,
    inspect_pinned_yt_dlp,
    inspect_screenshot_tools,
    persist_selected_screenshot_packages,
    persist_selected_screenshot_package,
)
from screenshot_ui import (
    _candidate_failure_message,
    _screenshot_tool_status,
    build_screenshot_workflow_view,
)


def _result(
    video_id: str = "vI4RdXMSq8c",
    source_chapter_id: str = "CH-01",
    content_chapter_ids: tuple[str, ...] = ("CCH-01",),
) -> dict:
    chapters = []
    items = []
    utterances = []
    for index, content_chapter_id in enumerate(content_chapter_ids, 1):
        utterance_id = f"UT-{index:05d}"
        chapter = {
            "content_chapter_id": content_chapter_id,
            "title": f"chapter {index}",
            "summary": f"summary {index}",
            "boundary_reason": "fixture",
            "start_utterance_id": utterance_id,
            "end_utterance_id": utterance_id,
            "start_seconds": float(index * 10),
            "end_seconds": float(index * 10 + 5),
            "source_utterance_ids": [utterance_id],
        }
        chapters.append(chapter)
        utterances.append(
            {
                "utterance_id": utterance_id,
                "start_seconds": chapter["start_seconds"],
                "end_seconds": chapter["end_seconds"],
                "normalized_text": f"utterance {index}",
            }
        )
        items.append(
            {
                "content_chapter_id": content_chapter_id,
                "chapter_fingerprint": chapter_fingerprint(chapter),
                "status": "completed",
                "screenshot_candidates": [
                    {
                        "candidate_index": candidate_index,
                        "target_seconds": chapter["start_seconds"] + candidate_index,
                        "target_timestamp": f"00:{index * 10 + candidate_index:02d}",
                        "selection_role": "primary_anchor",
                        "relative_path": f"legacy-{candidate_index}.jpg",
                        "status": "completed",
                    }
                    for candidate_index in (1, 2, 3)
                ],
                "warnings": [],
            }
        )
    result = {
        "schema_version": "script_preprocessing_v0.3.16",
        "video_id": video_id,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "processed_chapter": {
            "chapter_id": source_chapter_id,
            "label": source_chapter_id,
        },
        "normalized_utterances": utterances,
        "content_chapters": chapters,
        "processing_report": {},
        "terminology": [],
    }
    assets = {
        "schema_version": "content_chapter_assets_v0.1",
        "status": "completed",
        "method": "semantic_screenshot_candidates_v0.2",
        "video_id": video_id,
        "source_url": result["source_url"],
        "items": items,
        "warnings": [],
    }
    result["content_chapter_assets"] = scope_candidate_assets(result, assets)
    return result


def _write_candidates(cache: Path, result: dict) -> None:
    for item in result["content_chapter_assets"]["items"]:
        for candidate in item["screenshot_candidates"]:
            path = cache / candidate["relative_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            seed = hashlib.sha256(
                (
                    result["video_id"]
                    + result["processed_chapter"]["chapter_id"]
                    + item["content_chapter_id"]
                    + str(candidate["candidate_index"])
                ).encode("utf-8")
            ).digest()
            Image.new(
                "RGB",
                (8, 8),
                color=(seed[0], seed[1], seed[2]),
            ).save(
                path,
                format="JPEG",
            )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ScreenshotOutputPackagingTests(unittest.TestCase):
    def test_korean_title_full_output_directory_is_readable_and_unique(self) -> None:
        result = _result(
            video_id="G0d9CHLpnnc",
            source_chapter_id="FULL",
        )
        result["source_title"] = "우리 디자인 시스템으로 바이브코딩 해봐요"
        self.assertEqual(
            final_chapter_directory(Path("/tmp/output"), result),
            Path("/tmp/output").resolve()
            / "우리 디자인 시스템으로 바이브코딩 해봐요 [G0d9CHLpnnc]"
            / "FULL",
        )

    def test_english_title_chapter_output_directory(self) -> None:
        result = _result(source_chapter_id="CH-08")
        result["source_title"] = "B-rolls with Higgsfield"
        self.assertEqual(
            final_video_directory_name(result),
            "B-rolls with Higgsfield [vI4RdXMSq8c]",
        )
        self.assertEqual(
            final_json_path(Path("/tmp/output"), result).name,
            "CH-08_preprocessed.json",
        )

    def test_safe_title_preserves_unicode_and_replaces_path_separators(self) -> None:
        self.assertEqual(
            safe_video_title("  Figma / Cursor\\ 실전\x00  "),
            "Figma ／ Cursor／ 실전",
        )
        self.assertLessEqual(
            len(safe_video_title("가" * 500).encode("utf-8")),
            180,
        )

    def test_missing_title_falls_back_to_video_id(self) -> None:
        result = _result(video_id="fallback-id", source_chapter_id="FULL")
        self.assertEqual(final_video_directory_name(result), "fallback-id")

    def test_same_title_with_different_video_ids_does_not_collide(self) -> None:
        first = _result(video_id="first-video")
        second = _result(video_id="second-video")
        first["source_title"] = second["source_title"] = "같은 제목"
        self.assertNotEqual(
            final_video_directory_name(first),
            final_video_directory_name(second),
        )

    def test_title_output_resolver_falls_back_to_legacy_video_id_path(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = _result(source_chapter_id="FULL")
            result["source_title"] = "새 제목"
            selected = {
                "relative_path": "CCH-01.jpg",
                "storage_kind": "final_output",
            }
            legacy = root / "vI4RdXMSq8c" / "FULL" / "CCH-01.jpg"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy-final")
            self.assertEqual(
                resolve_selected_path(root, result, selected),
                legacy.resolve(),
            )
            self.assertTrue(legacy.is_file())

    def test_owned_boundary_utterance_overlap_still_plans_candidate(self) -> None:
        result = _result(source_chapter_id="FULL")
        chapter = result["content_chapters"][0]
        chapter["start_seconds"] = 10.0
        chapter["end_seconds"] = 14.0
        row = result["normalized_utterances"][0]
        row["start_seconds"] = 9.5
        row["end_seconds"] = 16.0
        plan = build_screenshot_plan(result)
        item = plan["items"][0]
        self.assertEqual(item["status"], "planned")
        self.assertGreater(len(item["screenshot_candidates"]), 0)
        self.assertGreaterEqual(
            item["screenshot_candidates"][0]["target_seconds"],
            chapter["start_seconds"],
        )
        self.assertLessEqual(
            item["screenshot_candidates"][0]["target_seconds"],
            chapter["end_seconds"],
        )

    def test_non_overlapping_utterance_stores_structured_planning_failure(self) -> None:
        result = _result(source_chapter_id="FULL")
        chapter = result["content_chapters"][0]
        chapter["start_seconds"] = 100.0
        chapter["end_seconds"] = 110.0
        plan = build_screenshot_plan(result)
        item = plan["items"][0]
        self.assertEqual(item["status"], "skipped")
        self.assertEqual(item["failure_stage"], "candidate_planning")
        self.assertIn(
            "utterance_does_not_overlap_chapter_range",
            item["failure_reason"],
        )
        self.assertEqual(item["screenshot_candidates"], [])

    def test_completed_candidate_with_missing_cache_file_has_explicit_reason(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = _result(source_chapter_id="FULL")
            view = build_screenshot_workflow_view(
                result,
                root / "autosave" / "screenshot_candidates",
                root / "output",
            )
            candidate = view["items"][0]["candidates"][0]
            self.assertFalse(candidate["image_available"])
            self.assertEqual(candidate["display_reason"], "candidate_cache_file_missing")

    def test_failure_reason_is_human_readable_for_ui(self) -> None:
        message = _candidate_failure_message(
            "candidate_planning",
            "utterance_outside_chapter_range:UT-00037",
        )
        self.assertIn("candidate_planning", message)
        self.assertIn("timestamp 범위", message)
        self.assertIn("UT-00037", message)

    def test_screenshot_tools_ready_when_pinned_ytdlp_and_ffmpeg_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            executable = root / "yt-dlp_macos"
            executable.write_text("fixture", encoding="utf-8")
            executable.chmod(0o755)
            (root / "metadata.json").write_text(
                json.dumps(
                    {
                        "channel": PINNED_YTDLP_CHANNEL,
                        "version": PINNED_YTDLP_VERSION,
                        "sha256": PINNED_YTDLP_SHA256,
                    }
                ),
                encoding="utf-8",
            )

            def runner(command, **kwargs):
                self.assertEqual(kwargs["timeout"], TOOL_VERSION_CHECK_TIMEOUT_SECONDS)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    PINNED_YTDLP_VERSION + "\n",
                    "",
                )

            with patch(
                "screenshot_runtime.resolve_ffmpeg",
                return_value={
                    "available": True,
                    "path": "/fixture/ffmpeg",
                    "method": "fixture",
                    "reason": None,
                },
            ):
                tools = inspect_screenshot_tools(root, runner=runner)
            self.assertTrue(tools["ready"])

    def test_ytdlp_version_check_timeout_is_bounded_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            executable = root / "yt-dlp_macos"
            executable.write_text("fixture", encoding="utf-8")
            executable.chmod(0o755)
            (root / "metadata.json").write_text(
                json.dumps(
                    {
                        "channel": PINNED_YTDLP_CHANNEL,
                        "version": PINNED_YTDLP_VERSION,
                        "sha256": PINNED_YTDLP_SHA256,
                    }
                ),
                encoding="utf-8",
            )

            def timeout_runner(command, **kwargs):
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])

            status = inspect_pinned_yt_dlp(root, runner=timeout_runner)
            self.assertFalse(status["available"])
            self.assertEqual(status["reason"], "sidecar_version_check_timeout")
            self.assertEqual(
                status["timeout_seconds"],
                TOOL_VERSION_CHECK_TIMEOUT_SECONDS,
            )

    def test_ffmpeg_unavailable_is_an_explicit_not_ready_state(self) -> None:
        with patch(
            "screenshot_runtime.inspect_pinned_yt_dlp",
            return_value={"available": True, "version": PINNED_YTDLP_VERSION},
        ), patch(
            "screenshot_runtime.resolve_ffmpeg",
            return_value={
                "available": False,
                "path": None,
                "method": None,
                "reason": "ffmpeg_unavailable",
            },
        ):
            tools = inspect_screenshot_tools()
        self.assertFalse(tools["ready"])
        self.assertEqual(tools["ffmpeg"]["reason"], "ffmpeg_unavailable")

    def test_ready_tool_status_is_reused_across_streamlit_reruns(self) -> None:
        state = {}
        ready = {
            "ready": True,
            "yt_dlp": {
                "available": True,
                "version": PINNED_YTDLP_VERSION,
                "executable_path": "/fixture/yt-dlp",
            },
            "ffmpeg": {"available": True, "path": "/fixture/ffmpeg"},
        }
        with patch("screenshot_ui.inspect_screenshot_tools", return_value=ready) as inspect:
            self.assertTrue(_screenshot_tool_status(state)["ready"])
            self.assertTrue(_screenshot_tool_status(state)["ready"])
        inspect.assert_called_once()

    def test_production_generation_writes_only_scoped_candidate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output = root / "cache", root / "output"
            result = _result()
            chapter = result["content_chapters"][0]
            chapter.update(
                {
                    "start_utterance_id": "UT-00001",
                    "end_utterance_id": "UT-00003",
                    "start_seconds": 10.0,
                    "end_seconds": 35.0,
                    "source_utterance_ids": [
                        "UT-00001",
                        "UT-00002",
                        "UT-00003",
                    ],
                }
            )
            result["normalized_utterances"] = [
                {
                    "utterance_id": f"UT-{index:05d}",
                    "start_seconds": float(index * 10),
                    "end_seconds": float(index * 10 + 5),
                    "normalized_text": text,
                }
                for index, text in enumerate(
                    (
                        "공통 작업 과정 준비 단계",
                        "공통 작업 과정 제작 단계",
                        "공통 작업 과정 결과 확인 단계",
                    ),
                    1,
                )
            ]
            result.pop("content_chapter_assets", None)

            def runner(command, **kwargs):
                if command[0] == "/mock/yt-dlp":
                    template = Path(command[command.index("--output") + 1])
                    Path(str(template).replace("%(ext)s", "mp4")).write_bytes(
                        b"temporary-video"
                    )
                elif command[0] == "/mock/ffmpeg":
                    destination = Path(command[-1])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(
                        destination,
                        format="JPEG",
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            assets = generate_screenshot_candidates(
                result,
                output,
                candidate_cache_directory=cache,
                yt_dlp_executable="/mock/yt-dlp",
                ffmpeg_executable="/mock/ffmpeg",
                runner=runner,
            )
            candidates = assets["items"][0]["screenshot_candidates"]
            self.assertEqual(len(candidates), 3)
            self.assertTrue(all(candidate["status"] == "completed" for candidate in candidates))
            self.assertEqual(len(list(cache.rglob("candidate_*.jpg"))), 3)
            self.assertFalse(final_image_path(output, result, "CCH-01").exists())
            self.assertFalse(final_json_path(output, result).exists())
            self.assertEqual(assets["runtime"]["qwen_generation_calls"], 0)

    def test_candidate_generation_scope_creates_no_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = _result()
            cache = root / "autosave" / "screenshot_candidates"
            output = root / "output"
            _write_candidates(cache, result)
            self.assertEqual(
                scoped_candidate_relative_path(result, "CCH-01", 1),
                Path("vI4RdXMSq8c/CH-01/CCH-01/candidate_01.jpg"),
            )
            self.assertEqual(len(list(cache.rglob("candidate_*.jpg"))), 3)
            self.assertFalse(final_image_path(output, result, "CCH-01").exists())
            self.assertFalse(final_json_path(output, result).exists())

    def test_korean_full_candidate_generation_uses_existing_scoped_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache = root / "autosave" / "screenshot_candidates"
            output = root / "output"
            result = _result(
                video_id="korean-full-fixture",
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02"),
            )

            def runner(command, **kwargs):
                if command[0] == "/mock/yt-dlp":
                    template = Path(command[command.index("--output") + 1])
                    Path(str(template).replace("%(ext)s", "mp4")).write_bytes(
                        b"temporary-video"
                    )
                elif command[0] == "/mock/ffmpeg":
                    destination = Path(command[-1])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(
                        destination,
                        format="JPEG",
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            assets = generate_screenshot_candidates(
                result,
                output,
                candidate_cache_directory=cache,
                yt_dlp_executable="/mock/yt-dlp",
                ffmpeg_executable="/mock/ffmpeg",
                runner=runner,
            )
            self.assertEqual(assets["status"], "completed")
            self.assertEqual(assets["runtime"]["video_download_count"], 1)
            self.assertGreater(len(list((cache / "korean-full-fixture" / "FULL").rglob("candidate_*.jpg"))), 0)
            self.assertFalse((output / "korean-full-fixture" / "FULL").exists())

    def test_one_chapter_extraction_failure_does_not_hide_other_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache = root / "autosave" / "screenshot_candidates"
            result = _result(
                video_id="partial-fixture",
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02"),
            )

            def runner(command, **kwargs):
                if command[0] == "/mock/yt-dlp":
                    template = Path(command[command.index("--output") + 1])
                    Path(str(template).replace("%(ext)s", "mp4")).write_bytes(b"video")
                elif command[0] == "/mock/ffmpeg":
                    if "CCH-02" in str(command[-1]):
                        raise subprocess.CalledProcessError(1, command)
                    destination = Path(command[-1])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (8, 8), color=(1, 2, 3)).save(destination)
                return subprocess.CompletedProcess(command, 0, "", "")

            assets = generate_screenshot_candidates(
                result,
                root / "output",
                candidate_cache_directory=cache,
                yt_dlp_executable="/mock/yt-dlp",
                ffmpeg_executable="/mock/ffmpeg",
                runner=runner,
            )
            self.assertEqual(assets["status"], "partial")
            by_id = {
                item["content_chapter_id"]: item for item in assets["items"]
            }
            self.assertEqual(by_id["CCH-01"]["status"], "completed")
            self.assertEqual(by_id["CCH-02"]["status"], "failed")
            self.assertEqual(
                by_id["CCH-02"]["failure_stage"],
                "candidate_extraction",
            )
            self.assertIn(
                "screenshot_extraction_failed",
                by_id["CCH-02"]["failure_reason"],
            )
            self.assertGreater(len(list((cache / "partial-fixture" / "FULL" / "CCH-01").glob("*.jpg"))), 0)
            self.assertEqual(len(list((cache / "partial-fixture" / "FULL" / "CCH-02").glob("*.jpg"))), 0)
            runtime = assets["runtime"]
            self.assertEqual(runtime["video_download_count"], 1)
            for key in (
                "planning_duration_seconds",
                "tool_check_duration_seconds",
                "video_preparation_duration_seconds",
                "candidate_extraction_duration_seconds",
                "total_duration_seconds",
            ):
                self.assertIn(key, runtime)

    def test_ch01_ch08_and_video_scopes_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = (
                root / "cache",
                root / "output",
                root / "autosave",
            )
            ch01 = _result(source_chapter_id="CH-01")
            _write_candidates(cache, ch01)
            first = persist_selected_screenshot_package(
                ch01, "CCH-01", 2, cache, output, autosave
            )
            ch01_hash = _digest(first["image_path"])

            ch08 = _result(source_chapter_id="CH-08")
            _write_candidates(cache, ch08)
            second = persist_selected_screenshot_package(
                ch08, "CCH-01", 3, cache, output, autosave
            )
            self.assertEqual(_digest(first["image_path"]), ch01_hash)
            self.assertNotEqual(first["image_path"], second["image_path"])
            self.assertEqual(
                second["image_path"].relative_to(output.resolve()),
                Path("vI4RdXMSq8c/CH-08/CCH-01.jpg"),
            )

            other = _result(video_id="abcdefghijk", source_chapter_id="CH-01")
            _write_candidates(cache, other)
            third = persist_selected_screenshot_package(
                other, "CCH-01", 1, cache, output, autosave
            )
            self.assertEqual(
                third["image_path"].relative_to(output.resolve()),
                Path("abcdefghijk/CH-01/CCH-01.jpg"),
            )
            self.assertEqual(_digest(first["image_path"]), ch01_hash)

    def test_reselection_atomically_replaces_only_one_final_jpg(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result()
            _write_candidates(cache, result)
            first = persist_selected_screenshot_package(
                result,
                "CCH-01",
                2,
                cache,
                output,
                autosave,
                cleanup_candidates=False,
            )
            first_hash = _digest(first["image_path"])
            second = persist_selected_screenshot_package(
                first["saved_result"],
                "CCH-01",
                1,
                cache,
                output,
                autosave,
                cleanup_candidates=False,
            )
            self.assertNotEqual(first_hash, _digest(second["image_path"]))
            final_files = list(second["image_path"].parent.glob("*.jpg"))
            self.assertEqual([path.name for path in final_files], ["CCH-01.jpg"])
            self.assertFalse(any(path.name.startswith("candidate_") for path in final_files))

    def test_full_scope_packages_one_json_and_multiple_selected_images(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result(
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02"),
            )
            _write_candidates(cache, result)
            first = persist_selected_screenshot_package(
                result, "CCH-01", 1, cache, output, autosave
            )
            second = persist_selected_screenshot_package(
                first["saved_result"], "CCH-02", 2, cache, output, autosave
            )
            chapter_dir = output / "vI4RdXMSq8c" / "FULL"
            self.assertEqual(
                sorted(path.name for path in chapter_dir.iterdir()),
                ["CCH-01.jpg", "CCH-02.jpg", "FULL_preprocessed.json"],
            )
            packaged = json.loads(second["json_path"].read_text(encoding="utf-8"))
            selections = {
                item["content_chapter_id"]: item.get("selected_screenshot")
                for item in packaged["content_chapter_assets"]["items"]
            }
            self.assertEqual(selections["CCH-01"]["relative_path"], "CCH-01.jpg")
            self.assertEqual(selections["CCH-02"]["relative_path"], "CCH-02.jpg")

    def test_bulk_save_writes_three_images_and_one_current_json(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result(
                video_id="G0d9CHLpnnc",
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02", "CCH-03"),
            )
            result["source_title"] = "우리 디자인 시스템으로 바이브코딩 해봐요"
            _write_candidates(cache, result)
            with patch(
                "screenshot_runtime.atomic_write_json",
                wraps=__import__("screenshot_runtime").atomic_write_json,
            ) as write_json:
                package = persist_selected_screenshot_packages(
                    result,
                    {"CCH-01": 2, "CCH-02": 1, "CCH-03": 3},
                    cache,
                    output,
                    autosave,
                )
            self.assertEqual(package["success_count"], 3)
            self.assertEqual(package["failure_count"], 0)
            self.assertEqual(write_json.call_count, 1)
            chapter_dir = (
                output
                / "우리 디자인 시스템으로 바이브코딩 해봐요 [G0d9CHLpnnc]"
                / "FULL"
            )
            self.assertEqual(
                sorted(path.name for path in chapter_dir.iterdir()),
                [
                    "CCH-01.jpg",
                    "CCH-02.jpg",
                    "CCH-03.jpg",
                    "FULL_preprocessed.json",
                ],
            )
            packaged = json.loads(
                package["json_path"].read_text(encoding="utf-8")
            )
            selections = {
                item["content_chapter_id"]: item.get("selected_screenshot")
                for item in packaged["content_chapter_assets"]["items"]
            }
            self.assertEqual(
                {key: value["source_candidate_index"] for key, value in selections.items()},
                {"CCH-01": 2, "CCH-02": 1, "CCH-03": 3},
            )
            for chapter_id in ("CCH-01", "CCH-02", "CCH-03"):
                self.assertFalse(
                    (cache / "G0d9CHLpnnc" / "FULL" / chapter_id).exists()
                )

    def test_bulk_preflight_failure_preserves_other_results_and_failed_cache(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result(
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02", "CCH-03"),
            )
            _write_candidates(cache, result)
            missing = cache / scoped_candidate_relative_path(result, "CCH-02", 2)
            missing.unlink()
            old_failed_final = final_image_path(output, result, "CCH-02")
            old_failed_final.parent.mkdir(parents=True, exist_ok=True)
            old_failed_final.write_bytes(b"existing-final")
            old_hash = _digest(old_failed_final)
            package = persist_selected_screenshot_packages(
                result,
                {"CCH-01": 1, "CCH-02": 2, "CCH-03": 3},
                cache,
                output,
                autosave,
            )
            self.assertEqual(package["success_count"], 2)
            self.assertEqual(package["failure_count"], 1)
            self.assertEqual(
                package["failures"][0]["content_chapter_id"],
                "CCH-02",
            )
            self.assertEqual(
                package["failures"][0]["reason"],
                "selected_candidate_file_missing",
            )
            self.assertEqual(_digest(old_failed_final), old_hash)
            self.assertFalse(
                (cache / "vI4RdXMSq8c" / "FULL" / "CCH-01").exists()
            )
            self.assertTrue(
                (cache / "vI4RdXMSq8c" / "FULL" / "CCH-02").exists()
            )
            self.assertFalse(
                (cache / "vI4RdXMSq8c" / "FULL" / "CCH-03").exists()
            )

    def test_cache_cleanup_still_restores_final_selection(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result()
            _write_candidates(cache, result)
            package = persist_selected_screenshot_package(
                result, "CCH-01", 3, cache, output, autosave
            )
            self.assertFalse(
                (cache / "vI4RdXMSq8c/CH-01/CCH-01").exists()
            )
            view = build_screenshot_workflow_view(
                package["saved_result"], cache, output
            )
            self.assertTrue(view["items"][0]["selected_image_available"])
            self.assertEqual(
                view["items"][0]["selected_screenshot"]["relative_path"],
                "CCH-01.jpg",
            )
            self.assertTrue(view["items"][0]["final_selection_authoritative"])
            self.assertTrue(view["items"][0]["candidate_cache_retired"])
            self.assertEqual(view["items"][0]["candidates"], [])

    def test_regeneration_and_stale_state_preserve_existing_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result()
            _write_candidates(cache, result)
            package = persist_selected_screenshot_package(
                result, "CCH-01", 1, cache, output, autosave
            )
            old_hash = _digest(package["image_path"])
            regenerated = scope_candidate_assets(
                package["saved_result"],
                package["saved_result"]["content_chapter_assets"],
            )
            regenerated_result = copy.deepcopy(package["saved_result"])
            regenerated_result["content_chapter_assets"] = regenerated
            _write_candidates(cache, regenerated_result)
            self.assertEqual(_digest(package["image_path"]), old_hash)

            stale = copy.deepcopy(package["saved_result"])
            stale["content_chapters"][0]["title"] = "changed title"
            view = build_screenshot_workflow_view(stale, cache, output)
            self.assertTrue(view["items"][0]["stale"])
            self.assertIsNone(view["items"][0]["selected_screenshot"])
            self.assertIsNotNone(view["items"][0]["retained_selected_screenshot"])
            self.assertEqual(_digest(package["image_path"]), old_hash)

    def test_legacy_candidates_can_be_packaged_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result()
            item = result["content_chapter_assets"]["items"][0]
            for candidate in item["screenshot_candidates"]:
                candidate["relative_path"] = (
                    f"screenshots/CCH-01/candidate_{candidate['candidate_index']:02d}.jpg"
                )
                legacy = output / candidate["relative_path"]
                legacy.parent.mkdir(parents=True, exist_ok=True)
                legacy.write_bytes(f"legacy-{candidate['candidate_index']}".encode())
            legacy_hashes = {
                path.name: _digest(path)
                for path in (output / "screenshots/CCH-01").glob("*.jpg")
            }
            package = persist_selected_screenshot_package(
                result, "CCH-01", 2, cache, output, autosave
            )
            self.assertTrue(package["image_path"].is_file())
            self.assertEqual(
                legacy_hashes,
                {
                    path.name: _digest(path)
                    for path in (output / "screenshots/CCH-01").glob("*.jpg")
                },
            )

    def test_download_export_keeps_packaged_selection_state(self) -> None:
        from review_store import current_result, dataframe_from_draft

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache, output, autosave = root / "cache", root / "output", root / "autosave"
            result = _result()
            _write_candidates(cache, result)
            package = persist_selected_screenshot_package(
                result, "CCH-01", 2, cache, output, autosave
            )
            saved = package["saved_result"]
            downloaded = current_result(saved, dataframe_from_draft(saved))
            packaged = json.loads(package["json_path"].read_text(encoding="utf-8"))

            def selection(value: dict) -> dict:
                return value["content_chapter_assets"]["items"][0][
                    "selected_screenshot"
                ]

            self.assertEqual(selection(downloaded), selection(packaged))
            self.assertEqual(selection(downloaded)["relative_path"], "CCH-01.jpg")

    def test_streamlit_selection_smoke_shows_success_and_final_path(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache = root / "autosave" / "screenshot_candidates"
            output = root / "output"
            result = _result(
                video_id="G0d9CHLpnnc",
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02", "CCH-03"),
            )
            _write_candidates(cache, result)
            source = f'''\
import json
from pathlib import Path
import streamlit as st
from screenshot_ui import render_screenshot_workflow

if "preprocessing_draft" not in st.session_state:
    st.session_state["preprocessing_draft"] = json.loads({json.dumps(json.dumps(result, ensure_ascii=False))})
    st.session_state["source_data"] = {{
        "metadata": {{"title": "우리 디자인 시스템으로 바이브코딩 해봐요"}}
    }}
render_screenshot_workflow(
    st,
    st.session_state["preprocessing_draft"],
    st.session_state,
    Path({str(root)!r}),
    Path({str(root / "autosave")!r}),
)
'''
            ready = {
                "ready": True,
                "yt_dlp": {"available": True, "version": "fixture"},
                "ffmpeg": {"available": True, "path": "/fixture/ffmpeg"},
            }
            with patch("screenshot_ui.inspect_screenshot_tools", return_value=ready):
                app = AppTest.from_string(source).run(timeout=20)
                self.assertEqual(len(app.exception), 0)
                app.radio[0].set_value(2)
                app.radio[1].set_value(3)
                self.assertFalse(any(output.rglob("*.jpg")))
                self.assertFalse(
                    any(button.label == "선택 저장" for button in app.button)
                )
                next(
                    button
                    for button in app.button
                    if button.label == "선택한 대표 이미지 모두 저장"
                ).click()
                app.run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertIn(
                "대표 이미지 저장 완료: 3 / 3",
                [item.value for item in app.success],
            )
            self.assertTrue(
                any(
                    "output/우리 디자인 시스템으로 바이브코딩 해봐요 "
                    "[G0d9CHLpnnc]/FULL" in item.value
                    for item in app.caption
                )
            )
            final_dir = (
                output
                / "우리 디자인 시스템으로 바이브코딩 해봐요 [G0d9CHLpnnc]"
                / "FULL"
            )
            self.assertEqual(len(list(final_dir.glob("CCH-*.jpg"))), 3)
            self.assertFalse(
                any("candidate_cache_file_missing" in item.value for item in app.error)
            )
            packaged = json.loads(
                (final_dir / "FULL_preprocessed.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                packaged["source_title"],
                "우리 디자인 시스템으로 바이브코딩 해봐요",
            )

    def test_korean_full_content_chapters_show_ready_generation_button(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = _result(
                video_id="korean-full-fixture",
                source_chapter_id="FULL",
                content_chapter_ids=("CCH-01", "CCH-02"),
            )
            source = f'''\
import json
from pathlib import Path
import streamlit as st
from screenshot_ui import render_screenshot_workflow

result = json.loads({json.dumps(json.dumps(result, ensure_ascii=False))})
render_screenshot_workflow(st, result, st.session_state, Path({str(root)!r}), Path({str(root / "autosave")!r}))
'''
            ready = {
                "ready": True,
                "yt_dlp": {
                    "available": True,
                    "version": PINNED_YTDLP_VERSION,
                    "executable_path": "/fixture/yt-dlp",
                },
                "ffmpeg": {"available": True, "path": "/fixture/ffmpeg"},
            }
            with patch("screenshot_ui.inspect_screenshot_tools", return_value=ready):
                app = AppTest.from_string(source).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            button = next(
                item
                for item in app.button
                if item.label == "대표 스크린샷 후보 생성"
            )
            self.assertFalse(button.disabled)

    def test_planning_failure_reason_is_rendered_instead_of_generic_empty_state(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = _result(source_chapter_id="FULL")
            item = result["content_chapter_assets"]["items"][0]
            item.update(
                {
                    "status": "skipped",
                    "failure_stage": "candidate_planning",
                    "failure_reason": "utterance_outside_chapter_range:UT-00001",
                    "screenshot_candidates": [],
                    "warnings": ["utterance_outside_chapter_range:UT-00001"],
                }
            )
            source = f'''\
import json
from pathlib import Path
import streamlit as st
from screenshot_ui import render_screenshot_workflow

result = json.loads({json.dumps(json.dumps(result, ensure_ascii=False))})
render_screenshot_workflow(st, result, st.session_state, Path({str(root)!r}), Path({str(root / "autosave")!r}))
'''
            ready = {
                "ready": True,
                "yt_dlp": {
                    "available": True,
                    "version": PINNED_YTDLP_VERSION,
                    "executable_path": "/fixture/yt-dlp",
                },
                "ffmpeg": {"available": True, "path": "/fixture/ffmpeg"},
            }
            with patch("screenshot_ui.inspect_screenshot_tools", return_value=ready):
                app = AppTest.from_string(source).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            errors = [item.value for item in app.error]
            self.assertTrue(any("candidate_planning" in value for value in errors))
            self.assertTrue(any("UT-00001" in value for value in errors))

    def test_ytdlp_timeout_renders_failure_instead_of_checking_forever(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = _result(source_chapter_id="FULL")
            source = f'''\
import json
from pathlib import Path
import streamlit as st
from screenshot_ui import render_screenshot_workflow

result = json.loads({json.dumps(json.dumps(result, ensure_ascii=False))})
render_screenshot_workflow(st, result, st.session_state, Path({str(root)!r}), Path({str(root / "autosave")!r}))
'''
            unavailable = {
                "ready": False,
                "yt_dlp": {
                    "available": False,
                    "reason": "sidecar_version_check_timeout",
                    "timeout_seconds": TOOL_VERSION_CHECK_TIMEOUT_SECONDS,
                },
                "ffmpeg": {"available": True, "path": "/fixture/ffmpeg"},
            }
            with patch(
                "screenshot_ui.inspect_screenshot_tools",
                return_value=unavailable,
            ):
                app = AppTest.from_string(source).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(
                any("yt-dlp 버전 확인" in item.value for item in app.error)
            )
            button = next(
                item
                for item in app.button
                if item.label == "대표 스크린샷 후보 생성"
            )
            self.assertTrue(button.disabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
