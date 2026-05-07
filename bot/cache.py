"""Filesystem cache keyed by YouTube video ID.

Layout:
    cache/<video_id>/
        transcript.txt
        transcript.json
        frames.json            (only if frames extracted)
        frames/                (only if frames extracted)
        cheatsheet.md
        cheatsheet.pdf
        book.md
        book.pdf
        meta.json              (title, duration, completed_at)
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .config import CACHE_ROOT


@dataclass
class CacheMeta:
    video_id: str
    title: str
    duration_seconds: float
    transcribed_at: Optional[float] = None
    cheatsheet_at: Optional[float] = None
    book_at: Optional[float] = None


def slot(video_id: str) -> Path:
    return CACHE_ROOT / video_id


def has_transcript(video_id: str) -> bool:
    return (slot(video_id) / "transcript.txt").exists()


def has_frames(video_id: str) -> bool:
    return (slot(video_id) / "frames.json").exists()


def has_cheatsheet_pdf(video_id: str) -> bool:
    return (slot(video_id) / "cheatsheet.pdf").exists()


def has_book_pdf(video_id: str) -> bool:
    return (slot(video_id) / "book.pdf").exists()


def cheatsheet_pdf_path(video_id: str) -> Path:
    return slot(video_id) / "cheatsheet.pdf"


def book_pdf_path(video_id: str) -> Path:
    return slot(video_id) / "book.pdf"


def transcript_path(video_id: str) -> Path:
    return slot(video_id) / "transcript.txt"


def frames_index_path(video_id: str) -> Path:
    return slot(video_id) / "frames.json"


def frames_dir_path(video_id: str) -> Path:
    return slot(video_id) / "frames"


def load_meta(video_id: str) -> Optional[CacheMeta]:
    f = slot(video_id) / "meta.json"
    if not f.exists():
        return None
    return CacheMeta(**json.loads(f.read_text(encoding="utf-8")))


def save_meta(meta: CacheMeta) -> None:
    s = slot(meta.video_id)
    s.mkdir(parents=True, exist_ok=True)
    (s / "meta.json").write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")


def update_meta(video_id: str, **fields) -> None:
    meta = load_meta(video_id)
    if meta is None:
        # Creating fresh — caller should pass title and duration
        meta = CacheMeta(
            video_id=video_id,
            title=fields.get("title", ""),
            duration_seconds=fields.get("duration_seconds", 0.0),
        )
    for k, v in fields.items():
        if hasattr(meta, k):
            setattr(meta, k, v)
    save_meta(meta)


def adopt_pipeline_outputs(video_id: str, pipeline_result: dict) -> None:
    """Copy/move transcript + frames produced by run_pipeline into the cache slot."""
    s = slot(video_id)
    s.mkdir(parents=True, exist_ok=True)
    # Transcripts
    for src_key, dst_name in [
        ("transcript_txt", "transcript.txt"),
        ("transcript_json", "transcript.json"),
        ("transcript_with_frames", "transcript_with_frames.txt"),
    ]:
        src = pipeline_result.get(src_key)
        if src and Path(src).exists():
            shutil.copy2(src, s / dst_name)
    # Frames
    fi = pipeline_result.get("frames_index")
    if fi and Path(fi).exists():
        shutil.copy2(fi, s / "frames.json")
    fd = pipeline_result.get("frames_dir")
    if fd and Path(fd).exists():
        dst_dir = s / "frames"
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(fd, dst_dir)
    # Meta
    update_meta(
        video_id,
        title=pipeline_result.get("title", ""),
        duration_seconds=pipeline_result.get("duration_seconds", 0.0),
        transcribed_at=time.time(),
    )


def invalidate(video_id: str) -> None:
    """Wipe the entire cache slot for /refresh."""
    s = slot(video_id)
    if s.exists():
        shutil.rmtree(s)
