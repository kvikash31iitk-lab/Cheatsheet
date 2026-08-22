#!/usr/bin/env python3
"""Run batch playlist processing to generate individual and consolidated cheatsheets.

Features:
- Extracts all video URLs and metadata from a YouTube playlist URL via yt-dlp.
- Maintains state in `playlist_manifest.json` for full resumability.
- Processes each video using `scripts.run_local_job.run_url_job`.
- Merges markdown outputs into a master consolidated markdown and renders a unified PDF.
- Manages rate limits with configurable delays and retry backoff.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_cheatsheet import build as build_cheatsheet
from scripts.build_illustrated_book import build as build_book
from scripts.run_local_job import (
    DEFAULT_RUN_ROOT,
    _atomic_write_json,
    _normalize_features,
    _utc_now,
    run_url_job,
)
from scripts.ytdlp_client import run_ytdlp


def extract_playlist_info(playlist_url: str) -> tuple[list[dict[str, Any]], str | None]:
    """Use yt-dlp to extract flat playlist metadata without downloading media."""
    cmd = [
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        playlist_url,
    ]
    proc = run_ytdlp(cmd, operation="extract_playlist_info")
    stdout = proc.stdout
    videos = []
    index = 1
    found_playlist_title = None

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if not found_playlist_title:
                found_playlist_title = item.get("playlist_title") or item.get("playlist")
            v_id = item.get("id")
            v_title = item.get("title")
            # Skip hidden, deleted, or unavailable video placeholders in playlist
            if not v_title or v_title.strip() in {"[Private video]", "[Deleted video]", "[Unavailable video]"}:
                continue
            v_url = item.get("url") or item.get("webpage_url") or (f"https://www.youtube.com/watch?v={v_id}" if v_id else None)
            if not v_url:
                continue
            videos.append({
                "playlist_index": index,
                "video_id": v_id,
                "url": v_url,
                "title": v_title or f"Video {index}",
                "duration_seconds": item.get("duration"),
            })
            index += 1
        except json.JSONDecodeError:
            continue
    return videos, found_playlist_title




def load_playlist_manifest(manifest_path: Path, playlist_url: str) -> dict[str, Any]:
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    now = _utc_now()
    return {
        "schema_version": 1,
        "playlist_url": playlist_url,
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "items": {},
    }


import re

def _extract_episode_number(title: str) -> float | None:
    """Extract class/episode/part number from video title (e.g. 'Class-8' -> 8.0, 'Part-1' -> 1.0, 'Lec-28' -> 28.0)."""
    if not title:
        return None

    # Priority 1: Match explicit keyword prefixes (e.g., 'Part-1', 'Part 1', 'Class-8', 'Lec-28', 'Lec 28', 'Lecture 5', 'Ep 3', '#4')
    match = re.search(r'\b(?:class|ep|episode|part|lecture|lec|vol|v|#)[-:\s]*(\d+(?:\.\d+)?)\b', title, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    # Priority 2: Match trailing 'Class 26' or numbers after hyphen/pipe separators (e.g. 'Class 26 EPFO Complete Course' -> 26.0)
    match_sec = re.search(r'\b(?:class|part|lec|lecture)[-:\s]*(\d+)', title, re.IGNORECASE)
    if match_sec:
        try:
            return float(match_sec.group(1))
        except ValueError:
            pass

    # Priority 3: Fallback standalone number if near 'Class' or at end of title segment
    match_num = re.search(r'(?:class|part)\s*(\d+)', title, re.IGNORECASE)
    if match_num:
        try:
            return float(match_num.group(1))
        except ValueError:
            pass

def _extract_topic_key(title: str) -> str:
    """Extract specific subject/sub-topic chunk from title (e.g. 'Audit', 'Cost Accounting', 'Bills of Exchange').
    
    In titles like:
      'UPSC EPFO AO/EO & APFC | General Accounting Principles | Audit | Part-1 | Lec- 28 | By Anurag Sir'
    We split by delimiters (| , - , :) and find the distinctive topic segment.
    """
    if not title:
        return ""
    
    segments = re.split(r'[|–—]', title)
    # Common generic prefix/suffix phrases to ignore
    ignore_phrases = {
        "upsc", "epfo", "apfc", "ao", "eo", "exam", "general accounting principles",
        "complete course", "by anurag sir", "anurag sir", "target upsc",
    }
    
    for seg in segments:
        s = seg.strip()
        if not s:
            continue
        # Remove part/lecture/class numbers from segment
        cleaned_seg = re.sub(r'\b(?:class|ep|episode|part|lecture|lec|vol|v|#)[-:\s]*\d+(?:\.\d+)?\b', '', s, flags=re.IGNORECASE).strip()
        cleaned_norm = re.sub(r'\s+', ' ', cleaned_seg.lower())
        
        if len(cleaned_norm) >= 3 and cleaned_norm not in ignore_phrases and not re.fullmatch(r'[\d\s]+', cleaned_norm):
            return cleaned_norm

    # Fallback: token-based
    cleaned = re.sub(r'\b(?:class|ep|episode|part|lecture|lec|vol|v|#)[-:\s]*\d+(?:\.\d+)?\b', '', title, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\d_|\-–—:]+', ' ', cleaned)
    tokens = [w.lower() for w in cleaned.split() if len(w) > 3 and w.lower() not in {"upsc", "epfo", "apfc", "general", "accounting", "principles", "anurag", "complete", "course"}]
    return tokens[0] if tokens else ""


def consolidate_markdowns(
    items_results: list[dict[str, Any]],
    playlist_title: str = "Playlist Summary",
) -> str:
    """Combine individual video markdowns into a master consolidated markdown, grouped by sub-topic and sorted by episode number."""
    # Find the earliest playlist index for each distinct sub-topic
    topic_first_seen: dict[str, int] = {}
    for item in items_results:
        t_key = _extract_topic_key(item.get("title", ""))
        idx = int(item.get("playlist_index", 0))
        if t_key and t_key not in topic_first_seen:
            topic_first_seen[t_key] = idx

    def sort_key(item: dict[str, Any]) -> tuple[int, float, int]:
        title = item.get("title", "")
        t_key = _extract_topic_key(title)
        topic_order = topic_first_seen.get(t_key, 999)
        ep = _extract_episode_number(title)
        
        if ep is not None:
            return (topic_order, ep, int(item.get("playlist_index", 0)))
        return (topic_order, 999.0, int(item.get("playlist_index", 0)))

    sorted_items = sorted(items_results, key=sort_key)



    lines = [
        f"# {playlist_title}",
        "",
        "> **Consolidated Course & Playlist Summary**",
        "",
        "## Table of Contents",
        "",
    ]

    for display_idx, item in enumerate(sorted_items, start=1):
        idx = item.get("playlist_index", display_idx)
        title = item.get("title") or f"Module {display_idx}"
        anchor = f"module-{display_idx}-{item.get('video_id', '')}"
        lines.append(f"{display_idx}. [{title}](#{anchor})")

    lines.append("")
    lines.append("---")
    lines.append("")

    for display_idx, item in enumerate(sorted_items, start=1):
        title = item.get("title") or f"Module {display_idx}"
        anchor = f"module-{display_idx}-{item.get('video_id', '')}"
        md_path_str = item.get("markdown_path")

        lines.append(f"<a id='{anchor}'></a>")
        lines.append(f"# Module {display_idx}: {title}")
        lines.append("")
        if item.get("url"):
            lines.append(f"**Source Video**: [{item['url']}]({item['url']})")
            lines.append("")

        if md_path_str and Path(md_path_str).is_file():
            content = Path(md_path_str).read_text(encoding="utf-8", errors="replace").strip()
            adjusted_lines = []
            for line in content.splitlines():
                if line.lstrip().startswith("#"):
                    adjusted_lines.append("#" + line)
                else:
                    adjusted_lines.append(line)
            lines.append("\n".join(adjusted_lines))
        else:
            lines.append("*Notes unavailable for this module.*")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)



def run_playlist_job(
    playlist_url: str,
    *,
    kind: str = "cheatsheet",
    out_dir: Path | None = None,
    delay_seconds: float = 2.0,
    max_videos: int | None = None,
    concurrency: int = 3,
    features: list[str] | None = None,
    continue_on_error: bool = True,
    clean_temp: bool = False,
    progress: bool = True,
) -> dict[str, Any]:
    import concurrent.futures
    import threading

    def emit(msg: str) -> None:
        if progress:
            print(f"[playlist-job] {msg}", flush=True)

    feats = _normalize_features(features or [])
    root_dir = Path(out_dir) if out_dir else (DEFAULT_RUN_ROOT / "playlists" / "run")
    root_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = root_dir / "playlist_manifest.json"
    manifest = load_playlist_manifest(manifest_path, playlist_url)

    emit(f"Extracting playlist info from: {playlist_url}")
    playlist_items, found_title = extract_playlist_info(playlist_url)
    if not playlist_items:
        raise RuntimeError(f"No videos found in playlist or playlist is private/invalid: {playlist_url}")

    if max_videos and max_videos > 0:
        playlist_items = playlist_items[:max_videos]

    emit(f"Found {len(playlist_items)} videos to process with {concurrency} parallel workers.")
    manifest["total_videos"] = len(playlist_items)
    if found_title:
        manifest["playlist_title"] = found_title
    _atomic_write_json(manifest_path, manifest)

    manifest_lock = threading.Lock()
    successful_results: list[dict[str, Any]] = []

    # Pre-collect already completed items
    pending_items: list[dict[str, Any]] = []
    for item in playlist_items:
        idx = item["playlist_index"]
        v_id = item["video_id"]
        item_key = f"{idx:03d}_{v_id}"
        item_manifest = manifest.setdefault("items", {}).setdefault(item_key, {})
        if item_manifest.get("status") == "complete" and item_manifest.get("result"):
            res = item_manifest["result"]
            res["playlist_index"] = idx
            res["title"] = item.get("title", res.get("title"))
            successful_results.append(res)
            emit(f"Skipping video [{idx}/{len(playlist_items)}] (already completed): {item['title']}")
        else:
            pending_items.append(item)

    def process_video_worker(item: dict[str, Any]) -> dict[str, Any] | None:
        # Check if job was stopped by user
        if manifest_path.is_file():
            try:
                cur_m = json.loads(manifest_path.read_text(encoding="utf-8"))
                if cur_m.get("status") == "stopped":
                    return None
            except Exception:
                pass

        v_id = item["video_id"]
        v_url = item["url"]
        idx = item["playlist_index"]
        item_key = f"{idx:03d}_{v_id}"

        with manifest_lock:
            item_manifest = manifest.setdefault("items", {}).setdefault(item_key, {})
            item_manifest["status"] = "running"
            item_manifest["started_at"] = _utc_now()
            item_manifest["current_subtask"] = "Starting ingestion..."
            _atomic_write_json(manifest_path, manifest)

        emit(f"[Worker] Starting video [{idx}/{len(playlist_items)}]: {item['title']}")
        video_out_dir = root_dir / f"{idx:03d}_{v_id}"

        def handle_subtask_progress(subtask_msg: str) -> None:
            with manifest_lock:
                if manifest_path.is_file():
                    try:
                        cur_m = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if cur_m.get("status") == "stopped":
                            return
                    except Exception:
                        pass
                item_manifest["current_subtask"] = subtask_msg
                _atomic_write_json(manifest_path, manifest)
            emit(f"[{idx}/{len(playlist_items)}] {subtask_msg}")

        # Retry loop for transient rate limits (3 attempts)
        max_retries = 3
        last_exception = None
        res = None

        for attempt in range(1, max_retries + 1):
            try:
                res = run_url_job(
                    v_url,
                    kind=kind,
                    work_root=video_out_dir,
                    features=feats,
                    progress=progress,
                    on_progress=handle_subtask_progress,
                )
                break
            except Exception as exc:
                last_exception = exc
                err_str = str(exc).lower()
                is_rate_limit = "429" in err_str or "quota" in err_str or "rate limit" in err_str
                if is_rate_limit and attempt < max_retries:
                    backoff = attempt * 8.0
                    emit(f"Rate limit on video {idx}, backing off {backoff}s...")
                    time.sleep(backoff)
                else:
                    break

        with manifest_lock:
            if res is not None:
                res["playlist_index"] = idx
                res["title"] = item.get("title", res.get("title"))
                successful_results.append(res)

                item_manifest["status"] = "complete"
                item_manifest["current_subtask"] = "Completed"
                item_manifest["finished_at"] = _utc_now()
                item_manifest["result"] = res
                _atomic_write_json(manifest_path, manifest)

                if clean_temp and video_out_dir.exists():
                    for sub in video_out_dir.glob("*.tmp*"):
                        try:
                            if sub.is_file():
                                sub.unlink()
                            elif sub.is_dir():
                                shutil.rmtree(sub)
                        except Exception:
                            pass
                return res
            else:
                err_msg = f"{type(last_exception).__name__}: {last_exception}"
                emit(f"Error on video {idx} ({v_id}): {err_msg}")
                item_manifest["status"] = "failed"
                item_manifest["finished_at"] = _utc_now()
                item_manifest["error"] = err_msg
                _atomic_write_json(manifest_path, manifest)
                return None

    # Execute all pending items concurrently in thread pool
    if pending_items:
        workers_count = max(1, min(concurrency, len(pending_items)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as executor:
            future_to_item = {executor.submit(process_video_worker, item): item for item in pending_items}
            for future in concurrent.futures.as_completed(future_to_item):
                try:
                    future.result()
                except Exception as exc:
                    emit(f"Worker exception: {exc}")

    # Check if job was marked stopped
    if manifest_path.is_file():
        try:
            cur_m = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cur_m.get("status") == "stopped":
                manifest["status"] = "stopped"
                manifest.pop("active_video", None)
                _atomic_write_json(manifest_path, manifest)
                return {"total_videos": len(playlist_items), "successful_videos": len(successful_results), "status": "stopped"}
        except Exception:
            pass

    # Consolidation stage
    emit("Starting consolidation of individual cheatsheets...")
    consolidated_dir = root_dir / "Consolidated"
    consolidated_dir.mkdir(parents=True, exist_ok=True)

    master_md_text = consolidate_markdowns(
        successful_results,
        playlist_title=f"Playlist Summary ({len(successful_results)} modules)",
    )
    master_md_path = consolidated_dir / "master_cheatsheet.md"
    master_md_path.write_text(master_md_text, encoding="utf-8")
    emit(f"Master markdown written to: {master_md_path}")

    master_pdf_path = consolidated_dir / "master_cheatsheet.pdf"
    emit(f"Rendering master PDF to: {master_pdf_path}")


    if kind == "cheatsheet":
        build_cheatsheet(
            master_md_path,
            master_pdf_path,
            title="Master Consolidated Cheatsheet",
            features=feats,
            source_url=playlist_url,
        )
    else:
        build_book(
            master_md_path,
            master_pdf_path,
            title="Master Consolidated Book",
            work_dir=root_dir,
            features=feats,
            source_url=playlist_url,
        )

    summary_result = {
        "playlist_url": playlist_url,
        "total_videos": len(playlist_items),
        "successful_videos": len(successful_results),
        "root_dir": str(root_dir),
        "master_markdown_path": str(master_md_path),
        "master_pdf_path": str(master_pdf_path),
        "manifest_path": str(manifest_path),
    }

    manifest["status"] = "complete"
    manifest["updated_at"] = _utc_now()
    manifest["summary"] = summary_result
    _atomic_write_json(manifest_path, manifest)

    emit(f"Playlist batch processing finished! Master PDF: {master_pdf_path}")
    return summary_result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run batch YouTube playlist → individual & consolidated cheatsheets."
    )
    parser.add_argument("playlist_url", help="YouTube playlist URL")
    parser.add_argument(
        "--kind",
        choices=("cheatsheet", "book"),
        default="cheatsheet",
        help="Output type for each video and master PDF",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output folder to store all runs, manifests, and consolidated files",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=5.0,
        help="Delay in seconds between processing videos (default: 5.0)",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Limit processing to first N videos from the playlist",
    )
    parser.add_argument(
        "--features",
        default="",
        help="Comma-separated feature toggles (summary,tldr,qna,mermaid,chapters)",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Halt execution if any video fails instead of skipping to the next",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        run_playlist_job(
            args.playlist_url,
            kind=args.kind,
            out_dir=Path(args.out_dir) if args.out_dir else None,
            delay_seconds=args.delay_seconds,
            max_videos=args.max_videos,
            features=_normalize_features(args.features),
            continue_on_error=not args.stop_on_error,
        )
    except KeyboardInterrupt:
        print("\n[playlist-job] Interrupted by user. Run again with same --out-dir to resume.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"\n[playlist-job] Batch run failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
