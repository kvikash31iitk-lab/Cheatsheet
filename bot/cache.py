"""Filesystem cache keyed by YouTube video ID.

Layout:
    cache/<video_id>/
        transcript.txt
        transcript.json
        frames.json            (only if frames extracted)
        frames/                (only if frames extracted)
        cheatsheet.md          (legacy / no-features default)
        cheatsheet.pdf
        cheatsheet.<hash>.md   (one per opt-in feature set)
        cheatsheet.<hash>.pdf
        book.md / book.pdf     (legacy / no-features default)
        book.<hash>.md
        book.<hash>.pdf
        meta.json              (title, duration, completed_at)

The ``<hash>`` is a short (5-char) sha1 of the sorted feature list — see
``FEATURE_ORDER`` and ``features_suffix``. Different feature toggles for the
same URL cache as separate PDFs so re-running with a different selection
doesn't clobber the previous result. The legacy bare ``book.pdf`` /
``cheatsheet.pdf`` paths are preserved exactly when no features are
requested, so any older code paths keep working unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .config import CACHE_ROOT


_CACHE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# Canonical order of opt-in PDF features. The bot bitmask, the cache hash,
# and the build_* scripts all rely on this ordering being stable, so ADD new
# entries at the END — never re-order or remove (would change every existing
# cache key).
FEATURE_ORDER: tuple[str, ...] = (
    "summary",   # cover-page summary card
    "tldr",      # `> [!tldr]` callout at the start of each section
    "qna",       # `## Self-Test` appendix with `> [!q]` Q&A callouts
    "mermaid",   # mindmap + flowchart pages, rendered via mmdc
    "chapters",  # chapter index page + QR code linking back to the video
)


def normalize_features(features: list[str] | None) -> list[str]:
    """Dedupe, drop unknowns, return in canonical FEATURE_ORDER so the cache
    hash is stable regardless of submission order. Empty list = legacy PDF.
    """
    if not features:
        return []
    seen = {f for f in features if f in FEATURE_ORDER}
    return [f for f in FEATURE_ORDER if f in seen]


def features_suffix(features: list[str] | None) -> str:
    """Return a path suffix for the feature set:
    - ``""`` for None / empty (preserves legacy bare ``book.pdf`` etc.)
    - ``".<hash>"`` otherwise — sha1 truncated to 5 hex chars
    Always normalises first so different orderings hash identically.
    """
    norm = normalize_features(features)
    if not norm:
        return ""
    digest = hashlib.sha1(",".join(norm).encode("utf-8")).hexdigest()
    return f".{digest[:5]}"


@dataclass
class CacheMeta:
    video_id: str
    title: str
    duration_seconds: float
    transcribed_at: Optional[float] = None
    cheatsheet_at: Optional[float] = None
    book_at: Optional[float] = None


def slot(video_id: str) -> Path:
    if not isinstance(video_id, str) or _CACHE_ID_RE.fullmatch(video_id) is None:
        raise ValueError("Invalid cache identifier")
    return CACHE_ROOT / video_id


def has_transcript(video_id: str) -> bool:
    return (slot(video_id) / "transcript.txt").exists()


def has_frames(video_id: str) -> bool:
    return (slot(video_id) / "frames.json").exists()


def has_cheatsheet_pdf(video_id: str, features: list[str] | None = None) -> bool:
    return cheatsheet_pdf_path(video_id, features).exists()


def has_book_pdf(video_id: str, features: list[str] | None = None) -> bool:
    return book_pdf_path(video_id, features).exists()


def cheatsheet_pdf_path(
    video_id: str, features: list[str] | None = None
) -> Path:
    return slot(video_id) / f"cheatsheet{features_suffix(features)}.pdf"


def cheatsheet_md_path(
    video_id: str, features: list[str] | None = None
) -> Path:
    return slot(video_id) / f"cheatsheet{features_suffix(features)}.md"


def book_pdf_path(video_id: str, features: list[str] | None = None) -> Path:
    return slot(video_id) / f"book{features_suffix(features)}.pdf"


def book_md_path(video_id: str, features: list[str] | None = None) -> Path:
    return slot(video_id) / f"book{features_suffix(features)}.md"


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
        # _raw contains scene/grid candidates that were already distilled into
        # final frames. Persisting it duplicates hundreds of large JPEGs.
        shutil.copytree(
            fd, dst_dir, ignore=shutil.ignore_patterns("_raw")
        )
    # Meta
    meta_fields = {
        "title": pipeline_result.get("title", ""),
        "duration_seconds": pipeline_result.get("duration_seconds", 0.0),
    }
    if pipeline_result.get("transcript_txt"):
        meta_fields["transcribed_at"] = time.time()
    update_meta(video_id, **meta_fields)


def invalidate(video_id: str) -> None:
    """Wipe the entire cache slot for /refresh."""
    s = slot(video_id)
    if s.exists():
        shutil.rmtree(s)
