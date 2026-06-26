"""UPSC Cheetsheet REST routes — admin upload + processing + public reads.

Admin endpoints live at ``/api/admin/upsc/*`` (gated by ``require_admin``);
public endpoints at ``/api/public/upsc/*`` (unauthenticated, browser-cached).
Both are registered through this single router which ``main.py`` mounts.

Pipeline integration: a successful upload inserts an ``UpscIssue`` row and
queues ``scripts.upsc_pipeline.process_issue`` on ``BackgroundTasks``. The
pipeline updates ``status`` after each stage so the admin preview page can
poll.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api import settings as app_settings
from api.db import get_session
from api.deps import require_admin
from api.models import AuditLog, ScriptJob, UpscIssue, User, _utcnow

# Where input newspaper PDFs land. The pipeline reads from here.
UPSC_UPLOADS = Path(__file__).resolve().parent.parent / "web_work" / "upsc_uploads"
UPSC_UPLOADS.mkdir(parents=True, exist_ok=True)


router = APIRouter(tags=["upsc"])

# Issue IDs whose pipeline thread is currently alive in this process.
# main.py reads this to detect orphans in the periodic sweep.
_upsc_in_flight: set[str] = set()

STYLE_CHOICES = ("academic", "dense", "dense_tight", "coaching", "magazine")

# --- Narrated-video pipeline constants ---------------------------------------
VIDEO_ENGINES = ("gemini", "chirp")
VIDEO_LANGS = ("hi", "en")
SLIDE_STYLES = ("digest", "clean", "animated")
PRIVACY_CHOICES = ("public", "unlisted", "private")

# The app_settings key holding the persisted VideoDefaults blob. Read/written
# through the same api.settings helper every other setting uses, so it lives in
# the app_settings table and rides the 60s cache.
VIDEO_DEFAULTS_KEY = "video_defaults"

# Server-side fallback used when no defaults row has been saved yet. The UI
# pre-fills new issues from this. Kept here (not in api/settings.DEFAULTS, which
# we do not own) so reads/writes stay inside this file's contract.
VIDEO_DEFAULTS_FALLBACK: dict[str, Any] = {
    "engine": "chirp",
    "voice": "hi-IN-Chirp3-HD-Alnilam",
    "lang": "hi",
    "slide_style": "clean",
    "theme": "amber",
    "privacy": "unlisted",
    "auto_publish": False,
    "auto_generate_on_upload": False,
    "title_template": "UPSC Daily Digest — {date}",
    "description_template": (
        "Exam-relevant current affairs from {source}, {date}.\n\n"
        "Subscribe for a fresh UPSC digest every day."
    ),
}

# QC band: a valid digest video should sit between a few seconds and ~40 min.
QC_MIN_DURATION = 1.0
QC_MAX_DURATION = 40 * 60.0


# =============================================================================
# Shared helpers
# =============================================================================

def _issue_dict(row: UpscIssue, *, include_markdown: bool = False) -> dict[str, Any]:
    """Serialise an UpscIssue for JSON responses. ``markdown`` is large so we
    only include it on the single-issue endpoint, never on listings."""
    out: dict[str, Any] = {
        "id": row.id,
        "issue_date": row.issue_date.isoformat(),
        "source": row.source,
        "title": row.title,
        "style": row.style,
        "status": row.status,
        "error_message": row.error_message,
        "article_count": row.article_count,
        "summary": row.summary,
        "has_output_pdf": bool(row.output_pdf_path),
        "has_cover_thumb": bool(row.cover_thumb_path),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "llm_tokens_in": row.llm_tokens_in,
        "llm_tokens_out": row.llm_tokens_out,
        "llm_cost_paise": row.llm_cost_paise,
        "extract_seconds": row.extract_seconds,
        "classify_seconds": row.classify_seconds,
        "author_seconds": row.author_seconds,
        "render_seconds": row.render_seconds,
        # Narrated-video pipeline fields (all nullable; mirror the model).
        "video_status": row.video_status,
        "video_progress": row.video_progress,
        "video_path": row.video_path,
        "has_video": bool(row.video_path),
        "youtube_id": row.youtube_id,
        "youtube_url": row.youtube_url,
        "narration_script": row.narration_script,
        "script_confirmed": bool(row.script_confirmed),
        "video_config": row.video_config,
    }
    if include_markdown:
        out["markdown"] = row.markdown
    return out


def _kick_pipeline(issue_id: str) -> None:
    """Background task wrapper — runs the pipeline in a thread so the request
    handler returns immediately. ``process_issue`` does its own DB session
    management via SyncSessionLocal, so no event-loop interaction here."""
    _upsc_in_flight.add(issue_id)
    def _run():
        from scripts.upsc_pipeline import process_issue
        try:
            process_issue(issue_id)
        except Exception as exc:
            # process_issue already records error_message on the row.
            print(f"[upsc] pipeline crashed for {issue_id}: {exc}")
        finally:
            _upsc_in_flight.discard(issue_id)
    threading.Thread(target=_run, daemon=True).start()


def _kick_pyq_reseed(years: str, stages: list[str]) -> None:
    """Background runner for the PYQ corpus seed. Same fire-and-forget pattern."""
    def _run():
        from scripts.seed_pyq_corpus import (
            parse_year_range, PRELIMS_URLS, discover_mains_year,
            download_pdf, process_pdf,
        )
        try:
            year_list = parse_year_range(years)
            targets = []
            for y in year_list:
                if "prelims" in stages and y in PRELIMS_URLS:
                    targets.append((y, "prelims", "GS-1", PRELIMS_URLS[y]))
                if "mains" in stages:
                    for paper, url in discover_mains_year(y).items():
                        targets.append((y, "mains", paper, url))
            print(f"[pyq-reseed] {len(targets)} PDFs to process")
            for (year, stage, paper, url) in targets:
                try:
                    pdf_path = download_pdf(url)
                    process_pdf(pdf_path=pdf_path, year=year, exam_stage=stage,
                                paper=paper, source_url=url, do_tag=True)
                except Exception as exc:
                    print(f"[pyq-reseed] {year} {paper} failed: {exc}")
        except Exception as exc:
            print(f"[pyq-reseed] crashed: {exc}")
    threading.Thread(target=_run, daemon=True).start()


async def _audit(
    s: AsyncSession, admin: User, action: str, target_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    s.add(AuditLog(
        admin_email=admin.email, action=action,
        target_type="upsc_issue" if action.startswith("upsc.") else None,
        target_id=target_id,
        payload_json=json.dumps(payload, default=str) if payload else None,
    ))


# =============================================================================
# Admin: upload
# =============================================================================

@router.post("/api/admin/upsc/upload")
async def admin_upload(
    pdf: UploadFile = File(..., description="The newspaper PDF to digest"),
    issue_date: str = Form(..., description="Issue date as YYYY-MM-DD"),
    source: str = Form(..., description="Newspaper name (free-form)"),
    title: Optional[str] = Form(None, description="Optional override; default 'UPSC Cheetsheet - {date}'"),
    style: str = Form("dense_tight", description="One of the renderer styles"),
    background: BackgroundTasks = None,  # type: ignore[assignment]
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Multipart upload. Validates inputs, stores the PDF, inserts an issue
    row in status=uploaded, and kicks the pipeline. Returns the issue dict."""
    if style not in STYLE_CHOICES:
        raise HTTPException(400, f"style must be one of {list(STYLE_CHOICES)}")
    try:
        the_date = date_cls.fromisoformat(issue_date)
    except ValueError:
        raise HTTPException(400, "issue_date must be YYYY-MM-DD")
    if pdf.content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        # octet-stream is the lenient fallback some browsers send
        raise HTTPException(400, f"expected a PDF, got {pdf.content_type}")
    # Bound against the column widths (source VARCHAR(64), title VARCHAR(255)) so
    # an over-length value can't raise StringDataRightTruncation on the insert.
    if len(source.strip()) > 64:
        raise HTTPException(400, "source must be at most 64 characters")
    if title and len(title.strip()) > 255:
        raise HTTPException(400, "title must be at most 255 characters")

    # Unique key — only one published digest per date for now (admin can
    # delete + re-upload if they need to redo a day).
    existing = await s.execute(
        select(UpscIssue).where(UpscIssue.issue_date == the_date)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            409, f"An issue for {issue_date} already exists. Delete it first or PATCH."
        )

    issue_id = uuid.uuid4().hex
    issue_dir = UPSC_UPLOADS / issue_id
    issue_dir.mkdir(parents=True, exist_ok=True)
    input_pdf_path = issue_dir / "input.pdf"
    with input_pdf_path.open("wb") as fh:
        shutil.copyfileobj(pdf.file, fh)

    row = UpscIssue(
        id=issue_id,
        issue_date=the_date,
        source=source.strip(),
        # Human-readable default; URL still uses ISO date for routing.
        title=(title or f"UPSC Cheetsheet - {the_date.strftime('%d %B %Y')}").strip(),
        style=style,
        status="uploaded",
        input_pdf_path=str(input_pdf_path),
    )
    s.add(row)
    await _audit(s, admin, "upsc.upload", target_id=issue_id, payload={
        "issue_date": issue_date, "source": source, "style": style,
        "input_bytes": input_pdf_path.stat().st_size,
    })
    await s.commit()
    await s.refresh(row)

    # Fire pipeline now (after commit so the worker thread can read the row).
    _kick_pipeline(issue_id)

    return _issue_dict(row)


# =============================================================================
# Admin: list / get / edit / publish / delete
# =============================================================================

@router.get("/api/admin/upsc/issues")
async def admin_list(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    q = (select(UpscIssue)
         .order_by(desc(UpscIssue.issue_date))
         .limit(limit).offset(offset))
    rows = (await s.execute(q)).scalars().all()
    return {"issues": [_issue_dict(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/api/admin/upsc/issues/{issue_id}")
async def admin_get(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    return _issue_dict(row, include_markdown=True)


class IssuePatch(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    style: Optional[str] = None
    markdown: Optional[str] = None  # admin-edited markdown -> triggers re-render
    source: Optional[str] = Field(None, max_length=64)


@router.patch("/api/admin/upsc/issues/{issue_id}")
async def admin_patch(
    issue_id: str,
    patch: IssuePatch,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Edit issue fields. If ``markdown`` or ``style`` changes, re-render is
    auto-triggered (status flips to ``rendering`` -> ``preview``)."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if patch.style and patch.style not in STYLE_CHOICES:
        raise HTTPException(400, f"style must be one of {list(STYLE_CHOICES)}")

    needs_rerender = False
    if patch.title is not None and patch.title.strip() != row.title:
        row.title = patch.title.strip()
        needs_rerender = True  # cover page bakes the title in
    if patch.source is not None and patch.source.strip() != row.source:
        row.source = patch.source.strip()
        needs_rerender = True  # subtitle "<source> - <date>" is on the cover
    if patch.style is not None and patch.style != row.style:
        row.style = patch.style
        needs_rerender = True
    if patch.markdown is not None and patch.markdown != row.markdown:
        row.markdown = patch.markdown
        needs_rerender = True
    await _audit(s, admin, "upsc.patch", target_id=issue_id, payload={
        "rerender": needs_rerender, **patch.model_dump(exclude_none=True),
    })
    await s.commit()
    await s.refresh(row)

    if needs_rerender:
        # Reset to a re-render state; pipeline will pick up the edited markdown.
        row.status = "rendering"
        await s.commit()
        _kick_rerender(issue_id)
    return _issue_dict(row, include_markdown=True)


def _kick_rerender(issue_id: str) -> None:
    """Render-only re-run (skip extract + classify + author, use the existing
    markdown on the row). Used after admin edits."""
    def _run():
        import time
        from scripts import upsc_pipeline
        try:
            with upsc_pipeline.SyncSessionLocal() as session:
                row = session.get(UpscIssue, issue_id)
                if row is None or not row.markdown:
                    return
                issue_dir = upsc_pipeline.WORK_ROOT / issue_id
                issue_dir.mkdir(parents=True, exist_ok=True)
                output_pdf = issue_dir / "digest.pdf"
                cover_thumb = issue_dir / "cover.png"
                md_path = output_pdf.with_suffix(".md")
                md_path.write_text(row.markdown, encoding="utf-8")
                # Re-render with the chosen style
                from scripts.digest_styles import STYLES
                import scripts.build_illustrated_book as B
                STYLES[row.style]()
                B.MASTHEAD_PATH = Path(__file__).resolve().parent.parent / "assets" / "brand" / "masthead_full.png"
                B.RUNNING_HEADER = "UPSC CHEETSHEET"
                B.RUNNING_RIGHT = row.issue_date.strftime("%d %b %Y").lstrip("0")
                issue_url = f"https://cheetsheet.tech/upsc/{row.issue_date.isoformat()}"
                t0 = time.monotonic()
                B.build(
                    src=md_path, out=output_pdf, title=row.title,
                    subtitle=f"{row.source} - {row.issue_date.strftime('%d %B %Y').lstrip('0')}",
                    features=["summary", "tldr", "qna", "qr"],
                    source_url=issue_url,
                )
                import fitz
                doc = fitz.open(output_pdf)
                pix = doc[0].get_pixmap(dpi=120)
                pix.save(cover_thumb)
                doc.close()
                row.render_seconds = time.monotonic() - t0
                row.output_pdf_path = str(output_pdf)
                row.cover_thumb_path = str(cover_thumb)
                row.status = "preview"
                row.error_message = None
                session.commit()
        except Exception as exc:
            print(f"[upsc] rerender failed for {issue_id}: {exc}")
            with upsc_pipeline.SyncSessionLocal() as session:
                row = session.get(UpscIssue, issue_id)
                if row is not None:
                    row.status = "error"
                    row.error_message = str(exc)
                    session.commit()
    threading.Thread(target=_run, daemon=True).start()


# =============================================================================
# Narrated-video helpers (QC gate + defaults + the _kick_video daemon)
# =============================================================================

def _ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_BIN", "").strip() or "ffprobe"


def _qc_video(video_path: str) -> tuple[bool, str, float]:
    """QC gate before any YouTube upload. ffprobe the MP4 and require:
    file exists, a decodable audio stream is present, and duration is inside
    the expected band. Returns ``(ok, reason, duration)`` — ``reason`` is empty
    when ok. Never raises; a missing/broken ffprobe is reported as a failure so
    we fail closed (no publish) rather than open."""
    if not video_path or not Path(video_path).exists():
        return False, "video file missing on disk", 0.0
    try:
        proc = subprocess.run(
            [
                _ffprobe_bin(), "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                video_path,
            ],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return False, "ffprobe not found — cannot QC video", 0.0
    except Exception as exc:  # noqa: BLE001
        return False, f"ffprobe failed: {exc}", 0.0
    if proc.returncode != 0:
        return False, f"ffprobe error: {(proc.stderr or '').strip()[:200]}", 0.0
    try:
        info = json.loads(proc.stdout or "{}")
    except Exception:  # noqa: BLE001
        return False, "ffprobe returned unparseable output", 0.0

    streams = info.get("streams") or []
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    has_video = any(s.get("codec_type") == "video" for s in streams)
    if not has_video:
        return False, "no video stream", 0.0
    if not has_audio:
        return False, "no audio stream (narration missing)", 0.0

    duration = 0.0
    try:
        duration = float((info.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration < QC_MIN_DURATION:
        return False, f"duration too short ({duration:.1f}s)", duration
    if duration > QC_MAX_DURATION:
        return False, f"duration too long ({duration:.1f}s)", duration
    return True, "", duration


def _set_video_status(
    issue_id: str, *, status: Optional[str] = None,
    progress: Optional[str] = None, error: Optional[str] = None,
    **fields: Any,
) -> None:
    """Write video_status/video_progress (and any extra row fields) from inside
    the worker thread, using the pipeline's sync session like _kick_rerender."""
    from scripts import upsc_pipeline
    try:
        with upsc_pipeline.SyncSessionLocal() as session:
            row = session.get(UpscIssue, issue_id)
            if row is None:
                return
            if status is not None:
                row.video_status = status
            if progress is not None:
                row.video_progress = progress
            if error is not None:
                row.error_message = error
            for k, v in fields.items():
                setattr(row, k, v)
            # Clamp width-limited columns so an over-length label can never raise
            # StringDataRightTruncation on Postgres and silently lose the write
            # (SQLite ignores VARCHAR length, which hid this in dev). video_progress
            # is VARCHAR(32), youtube_id VARCHAR(20); error_message is Text (free).
            if row.video_progress and len(row.video_progress) > 32:
                row.video_progress = row.video_progress[:32]
            if row.youtube_id and len(row.youtube_id) > 20:
                row.youtube_id = row.youtube_id[:20]
            session.commit()
    except Exception as exc:  # noqa: BLE001
        # LOUD: a swallowed terminal status write leaves the row stuck in-flight
        # (videoBusy locks the whole Slides/Voice UI) until a reaper fires. Make
        # it greppable rather than a quiet print.
        print(f"[ERROR] _set_video_status write FAILED for {issue_id}: {exc}", flush=True)


def _kick_video(issue_id: str) -> None:
    """Fire-and-forget video build for an issue. Mirrors _kick_rerender's
    thread + SyncSessionLocal shape. Lazy-imports the scripts.* engine modules
    (built to the shared contract by sibling agents) inside the thread so the
    request handler never depends on the TTS/google libs being importable.

    Pipeline: (generate script if not confirmed/empty) -> build_video ->
    QC gate -> optional YouTube upload (when config.auto_publish + privacy).
    Status flows none/queued -> rendering -> uploading -> ready | error."""
    _upsc_in_flight.add(issue_id)

    def _run() -> None:
        from scripts import upsc_pipeline
        try:
            # ---- Load the row + chosen config -----------------------------
            with upsc_pipeline.SyncSessionLocal() as session:
                row = session.get(UpscIssue, issue_id)
                if row is None:
                    return
                try:
                    config = json.loads(row.video_config) if row.video_config else {}
                except Exception:  # noqa: BLE001
                    config = {}
                script_confirmed = bool(row.script_confirmed)
                raw_script = row.narration_script

            lang = (config.get("lang") or "hi")

            # ---- Script: reuse the confirmed/edited one, else generate -----
            _set_video_status(issue_id, status="rendering",
                              progress="preparing script", error=None)
            sections: list[dict] = []
            if raw_script:
                try:
                    parsed = json.loads(raw_script)
                    if isinstance(parsed, list):
                        sections = parsed
                except Exception:  # noqa: BLE001
                    sections = []
            if not sections:
                from scripts import upsc_narration
                sections = upsc_narration.generate_script(issue_id, lang=lang)
                # Persist the freshly generated script so the UI can show it.
                _set_video_status(
                    issue_id,
                    narration_script=json.dumps(sections, ensure_ascii=False),
                )

            # ---- Sample mode: intro + first story only, for a quick preview --
            if config.get("sample") and len(sections) > 2:
                sections = sections[:2]

            # ---- Build the video (engine updates progress as it goes) ------
            _set_video_status(issue_id, status="rendering",
                              progress="rendering slides + narration")
            from scripts import upsc_video
            result = upsc_video.build_video(issue_id, config, sections)
            video_path = result["video_path"]
            _set_video_status(
                issue_id, status="ready", progress="video ready",
                video_path=video_path, error=None,
            )

            # ---- Optional auto-publish to YouTube (behind the QC gate) -----
            privacy = (config.get("privacy") or "").strip().lower()
            auto_publish = bool(config.get("auto_publish"))
            if auto_publish and privacy in PRIVACY_CHOICES:
                ok, reason, _dur = _qc_video(video_path)
                if not ok:
                    _set_video_status(
                        issue_id, status="error",
                        progress=f"QC failed: {reason}",
                        error=f"QC gate blocked publish: {reason}",
                    )
                    return
                _set_video_status(issue_id, status="uploading",
                                  progress="uploading to YouTube")
                meta = _youtube_meta_from_config(issue_id, config)
                from scripts import youtube_upload
                up = youtube_upload.upload(video_path, meta)
                _set_video_status(
                    issue_id, status="ready", progress="published to YouTube",
                    youtube_id=up.get("youtube_id"),
                    youtube_url=up.get("youtube_url"),
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[upsc-video] build failed for {issue_id}: {exc}")
            _set_video_status(
                issue_id, status="error", progress="error",
                error=str(exc)[:500],
            )
        finally:
            _upsc_in_flight.discard(issue_id)

    threading.Thread(target=_run, daemon=True).start()


def _youtube_meta_from_config(issue_id: str, config: dict) -> dict[str, Any]:
    """Build YouTube upload metadata from saved defaults templates + the issue.
    Runs inside the worker thread (sync session). Templates support {date},
    {source}, {title} placeholders."""
    from scripts import upsc_pipeline
    defaults = app_settings.get_sync(VIDEO_DEFAULTS_KEY) or {}
    if not isinstance(defaults, dict):
        defaults = {}
    title_tpl = config.get("title_template") or defaults.get(
        "title_template") or VIDEO_DEFAULTS_FALLBACK["title_template"]
    desc_tpl = config.get("description_template") or defaults.get(
        "description_template") or VIDEO_DEFAULTS_FALLBACK["description_template"]
    date_str = source = title = ""
    with upsc_pipeline.SyncSessionLocal() as session:
        row = session.get(UpscIssue, issue_id)
        if row is not None:
            source = row.source or ""
            title = row.title or ""
            try:
                date_str = row.issue_date.strftime("%d %B %Y").lstrip("0")
            except Exception:  # noqa: BLE001
                date_str = ""
    subst = {"date": date_str, "source": source, "title": title}

    def _fmt(tpl: str) -> str:
        try:
            return tpl.format(**subst)
        except Exception:  # noqa: BLE001
            return tpl

    return {
        "title": _fmt(title_tpl) or title or "UPSC Daily Digest",
        "description": _fmt(desc_tpl),
        "tags": ["UPSC", "current affairs", "daily digest"],
        "privacy": (config.get("privacy") or "unlisted"),
    }


@router.post("/api/admin/upsc/issues/{issue_id}/reauthor")
async def admin_reauthor(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Re-run the full pipeline from scratch on this issue. Useful when the
    first authoring pass produced a bad article."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    row.status = "uploaded"
    row.error_message = None
    row.markdown = None
    row.output_pdf_path = None
    row.cover_thumb_path = None
    row.article_count = 0
    await _audit(s, admin, "upsc.reauthor", target_id=issue_id)
    await s.commit()
    _kick_pipeline(issue_id)
    return _issue_dict(row)


@router.post("/api/admin/upsc/issues/{issue_id}/publish")
async def admin_publish(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if row.status not in ("preview", "published"):
        raise HTTPException(400, f"cannot publish from status={row.status}")
    if not row.output_pdf_path:
        raise HTTPException(400, "no output PDF — cannot publish")
    row.status = "published"
    row.published_at = datetime.now(timezone.utc)
    await _audit(s, admin, "upsc.publish", target_id=issue_id)
    await s.commit()
    await s.refresh(row)
    return _issue_dict(row)


@router.post("/api/admin/upsc/issues/{issue_id}/unpublish")
async def admin_unpublish(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if row.status != "published":
        raise HTTPException(400, f"cannot unpublish from status={row.status}")
    row.status = "preview"
    row.published_at = None
    await _audit(s, admin, "upsc.unpublish", target_id=issue_id)
    await s.commit()
    await s.refresh(row)
    return _issue_dict(row)


@router.delete("/api/admin/upsc/issues/{issue_id}")
async def admin_delete(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    # Best-effort cleanup of files; ignore if missing.
    for p in (row.input_pdf_path, row.output_pdf_path, row.cover_thumb_path):
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
    # Try to remove the issue directory if it's now empty.
    for parent_path in (UPSC_UPLOADS / issue_id,
                        Path(__file__).resolve().parent.parent / "web_work" / "upsc" / issue_id):
        try:
            if parent_path.exists():
                shutil.rmtree(parent_path, ignore_errors=True)
        except Exception:
            pass
    await _audit(s, admin, "upsc.delete", target_id=issue_id, payload={
        "issue_date": row.issue_date.isoformat(),
    })
    await s.delete(row)
    await s.commit()
    return {"deleted": issue_id}


# =============================================================================
# Admin: PYQ reseed (idempotent, fire-and-forget)
# =============================================================================

class PyqReseed(BaseModel):
    years: str = Field(..., description="Year or range like '2024' or '2013-2025'")
    stages: list[str] = Field(default_factory=lambda: ["prelims"],
                              description="Subset of ['prelims', 'mains']")


@router.post("/api/admin/upsc/pyq/reseed")
async def admin_pyq_reseed(
    body: PyqReseed,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    for st in body.stages:
        if st not in ("prelims", "mains"):
            raise HTTPException(400, f"unknown stage: {st}")
    await _audit(s, admin, "upsc.pyq_reseed", payload=body.model_dump())
    await s.commit()
    _kick_pyq_reseed(body.years, body.stages)
    return {"queued": "ok", "years": body.years, "stages": ",".join(body.stages)}


# =============================================================================
# Admin: narrated-video studio (voices, script, make-video, youtube, defaults)
# =============================================================================

@router.get("/api/admin/upsc/voices")
async def admin_voices(
    engine: str = "chirp",
    lang: str = "hi",
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Ranked voice catalogue for an engine+language. Also reports whether the
    Gemini engine is currently usable so the UI can badge the fallback."""
    engine = (engine or "chirp").lower()
    lang = (lang or "hi").lower()
    if engine not in VIDEO_ENGINES:
        raise HTTPException(400, f"engine must be one of {list(VIDEO_ENGINES)}")
    if lang not in VIDEO_LANGS:
        raise HTTPException(400, f"lang must be one of {list(VIDEO_LANGS)}")
    from scripts import upsc_video
    try:
        voices = upsc_video.list_voices(engine, lang)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"could not list voices: {exc}")
    try:
        gemini_active = bool(upsc_video.gemini_billing_active())
    except Exception:  # noqa: BLE001
        gemini_active = False
    return {
        "engine": engine,
        "lang": lang,
        "voices": voices,
        "gemini_billing_active": gemini_active,
    }


class VoicePreview(BaseModel):
    engine: str = "chirp"
    voice: str
    lang: str = "hi"
    text: Optional[str] = Field(None, max_length=600)


@router.post("/api/admin/upsc/voice-preview")
async def admin_voice_preview(
    body: VoicePreview,
    admin: User = Depends(require_admin),
) -> Response:
    """Synthesize one sample sentence in the chosen engine/voice/lang and return
    the WAV bytes inline for the UI to play."""
    engine = (body.engine or "chirp").lower()
    lang = (body.lang or "hi").lower()
    if engine not in VIDEO_ENGINES:
        raise HTTPException(400, f"engine must be one of {list(VIDEO_ENGINES)}")
    if lang not in VIDEO_LANGS:
        raise HTTPException(400, f"lang must be one of {list(VIDEO_LANGS)}")
    if not body.voice or not body.voice.strip():
        raise HTTPException(400, "voice is required")
    from scripts import upsc_video
    import anyio
    # CRITICAL: preview_voice() does blocking network I/O and, on a TTS 429,
    # honours the server's escalating "retry in Ns" hint with time.sleep() —
    # which on this single-worker uvicorn would FREEZE the whole event loop
    # (every other request hangs -> "socket hang up"). Run it in a worker thread.
    try:
        wav = await anyio.to_thread.run_sync(
            upsc_video.preview_voice, engine, body.voice.strip(), lang, body.text
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"voice preview failed: {exc}")
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


def _run_script_job(job_id: str) -> None:
    """Background worker for ONE script-generation job. Daemon thread (same
    pattern as ``_kick_video``). It:
      * claims the job atomically under a row lock (``SELECT ... FOR UPDATE``) —
        IDEMPOTENT: a duplicate kick or a re-run sees status != 'pending' and
        skips, so Groq is never called twice for the same job;
      * runs the slow SEQUENTIAL Groq rewrite (``upsc_narration.generate_script``
        does exactly one Groq call per article, in order — no concurrency);
      * catches EVERYTHING so a Groq error marks the job 'failed' and the worker
        thread never crashes;
      * writes the result to the job row AND mirrors it onto the issue's
        ``narration_script`` so the existing video-build/hydrate flow keeps working.
    """
    from scripts import upsc_pipeline

    # 1. Claim the job (row lock) — idempotent.
    with upsc_pipeline.SyncSessionLocal() as s:
        job = s.execute(
            select(ScriptJob).where(ScriptJob.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if job is None:
            print(f"[script-job] {job_id}: not found", flush=True)
            return
        if job.status != "pending":
            print(f"[script-job] {job_id}: already '{job.status}' "
                  f"(started_at={job.started_at}) — skipping (idempotent)", flush=True)
            s.rollback()
            return
        job.status = "processing"
        job.started_at = _utcnow()
        digest_id, lang = job.digest_id, job.language
        s.commit()  # releases the FOR UPDATE lock; the claim is now durable

    print(f"[script-job] {job_id}: processing digest={digest_id} lang={lang}", flush=True)

    # 2. Slow SEQUENTIAL Groq rewrite — never let it crash the worker.
    try:
        from scripts import upsc_narration
        sections = upsc_narration.generate_script(digest_id, lang=lang)
    except Exception as exc:  # noqa: BLE001
        with upsc_pipeline.SyncSessionLocal() as s:
            j = s.get(ScriptJob, job_id)
            if j is not None:
                j.status = "failed"
                j.error = str(exc)[:500]
                j.completed_at = _utcnow()
                s.commit()
        print(f"[script-job] {job_id}: FAILED — {exc}", flush=True)
        return

    # 3. Persist result + keep the issue's narration_script in sync.
    with upsc_pipeline.SyncSessionLocal() as s:
        j = s.get(ScriptJob, job_id)
        if j is not None:
            j.status = "done"
            j.result = json.dumps({"sections": sections}, ensure_ascii=False)
            j.completed_at = _utcnow()
        issue = s.get(UpscIssue, digest_id)
        if issue is not None:
            issue.narration_script = json.dumps(sections, ensure_ascii=False)
            issue.script_confirmed = False
        s.commit()
    print(f"[script-job] {job_id}: DONE ({len(sections)} sections)", flush=True)


def _kick_script_job(job_id: str) -> None:
    """Fire the script worker in a daemon thread (same pattern as _kick_video)."""
    threading.Thread(target=_run_script_job, args=(job_id,), daemon=True).start()


@router.post("/api/admin/upsc/issues/{issue_id}/script")
async def admin_generate_script(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Kick BOTH an English and a Hindi script-generation job and return both
    job ids IMMEDIATELY. The UI polls both
    (``GET /api/admin/upsc/script/{job_id}``) and lets the user toggle between
    the two finished scripts — English = pure English, Hindi = Hinglish in
    Devanagari. Each job's slow sequential-Groq rewrite runs in its own
    background ``_run_script_job`` worker, which logs its language and mirrors
    its result onto the issue's ``narration_script`` when saved.

    Returns ``{en_job_id, hi_job_id, status:"pending"}``. The per-language
    partial-unique index ux_script_jobs_active lets an en and a hi job coexist
    for one issue while still blocking duplicate same-language jobs."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if not row.markdown or not row.markdown.strip():
        raise HTTPException(400, "issue has no authored markdown yet")

    async def _ensure_job(language: str) -> str:
        """Return a live (pending/processing) job id for this issue+language —
        reusing an existing one (idempotency) or creating a fresh job. Race-safe:
        a SAVEPOINT around the insert means an IntegrityError from the
        ux_script_jobs_active backstop rolls back ONLY this insert, never the
        sibling job already created earlier in the same request."""
        live = (await s.execute(
            select(ScriptJob).where(
                ScriptJob.digest_id == issue_id,
                ScriptJob.language == language,
                ScriptJob.status.in_(("pending", "processing")),
            ).order_by(desc(ScriptJob.created_at))
        )).scalars().first()
        if live is not None:
            return live.id
        job = ScriptJob(digest_id=issue_id, language=language, status="pending")
        try:
            async with s.begin_nested():  # savepoint — isolates a race failure
                s.add(job)
                await s.flush()
        except IntegrityError:
            winner = (await s.execute(
                select(ScriptJob).where(
                    ScriptJob.digest_id == issue_id,
                    ScriptJob.language == language,
                    ScriptJob.status.in_(("pending", "processing")),
                ).order_by(desc(ScriptJob.created_at))
            )).scalars().first()
            if winner is not None:
                return winner.id
            raise HTTPException(409, "could not create script job; please retry")
        return job.id

    en_id = await _ensure_job("en")
    hi_id = await _ensure_job("hi")
    await _audit(s, admin, "upsc.script_generate", target_id=issue_id,
                 payload={"en_job_id": en_id, "hi_job_id": hi_id})
    await s.commit()

    _kick_script_job(en_id)
    _kick_script_job(hi_id)
    return {"en_job_id": en_id, "hi_job_id": hi_id, "status": "pending"}


@router.get("/api/admin/upsc/script/{job_id}")
async def admin_get_script_job(
    job_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Poll one script-generation job (read-only). Locked contract shape:
    ``{status, progress, result, error}``.

    * ``status``   — pending | processing | done | failed
    * ``progress`` — coarse by design (the worker exposes no per-article detail):
                     0 pending, 50 processing, 100 done/failed.
    * ``result``   — ``{"sections": [...]}`` on success, else null. NOTE the
                     narration is structured *sections* (what the editor renders,
                     and what POST used to return), not a single ``script``
                     string — so result carries ``sections`` rather than ``script``.
    * ``error``    — failure message when status == 'failed', else null.

    Returns 404 for an unknown job id."""
    job = await s.get(ScriptJob, job_id)
    if job is None:
        raise HTTPException(404, "script job not found")
    progress = {"pending": 0, "processing": 50, "done": 100, "failed": 100}.get(job.status, 0)
    result = None
    if job.status == "done" and job.result:
        try:
            result = json.loads(job.result)
        except Exception:  # noqa: BLE001
            result = None
    return {
        "status": job.status,
        "progress": progress,
        "result": result,
        "error": job.error,
    }


class ScriptSection(BaseModel):
    section_id: str
    label: str = ""
    text: str = ""
    est_seconds: float = 0.0


class ScriptPatch(BaseModel):
    sections: list[ScriptSection]
    confirmed: bool = False


@router.patch("/api/admin/upsc/issues/{issue_id}/script")
async def admin_save_script(
    issue_id: str,
    patch: ScriptPatch,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Save the edited narration script + confirmed flag. TTS will not run
    until ``confirmed`` is true (the make-video endpoint enforces this)."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    sections = [sec.model_dump() for sec in patch.sections]
    row.narration_script = json.dumps(sections, ensure_ascii=False)
    row.script_confirmed = bool(patch.confirmed)
    await _audit(s, admin, "upsc.script_save", target_id=issue_id, payload={
        "sections": len(sections), "confirmed": bool(patch.confirmed),
    })
    await s.commit()
    return {"ok": True}


class MakeVideoConfig(BaseModel):
    engine: Literal["gemini", "chirp"] = "chirp"
    voice: str
    lang: Literal["hi", "en"] = "hi"
    slide_style: Literal["digest", "clean", "animated"] = "clean"
    theme: str = "amber"
    privacy: Literal["public", "unlisted", "private"] = "unlisted"
    auto_publish: bool = False
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    sample: bool = False  # quick preview: intro + first story only


class MakeVideoRequest(BaseModel):
    config: MakeVideoConfig


@router.post("/api/admin/upsc/issues/{issue_id}/make-video")
async def admin_make_video(
    issue_id: str,
    body: MakeVideoRequest,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Persist the chosen variant config and kick the video build daemon.
    Requires a confirmed script (the TTS confirm gate). Mirrors admin_publish's
    guard + audit + commit shape, then fires _kick_video like _kick_rerender."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if not row.markdown or not row.markdown.strip():
        raise HTTPException(400, "issue has no authored markdown — cannot make a video")
    if not row.script_confirmed:
        raise HTTPException(400, "confirm the narration script before generating the video")
    if row.video_status in ("queued", "rendering", "uploading"):
        raise HTTPException(409, f"a video job is already in progress (status={row.video_status})")

    config = body.config.model_dump()
    row.video_config = json.dumps(config, ensure_ascii=False)
    row.video_status = "queued"
    row.video_progress = "queued"
    row.error_message = None
    # Clear the previous render's artifacts so a re-render never serves the OLD
    # mp4 (or shows a stale YouTube link) as if current — they're set again only
    # on success. NOTE: re-rendering un-links a previously-published video; the
    # new render supersedes it and must be re-published to get a fresh link.
    row.video_path = None
    row.youtube_id = None
    row.youtube_url = None
    await _audit(s, admin, "upsc.make_video", target_id=issue_id, payload=config)
    await s.commit()
    await s.refresh(row)

    _kick_video(issue_id)
    return _issue_dict(row)


@router.get("/api/admin/upsc/video/{issue_id}")
async def admin_video(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> FileResponse:
    """Stream the rendered MP4 for inline preview. FileResponse natively honors
    HTTP Range requests, so the <video> element can seek."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if not row.video_path:
        raise HTTPException(404, "no rendered video yet")
    video = Path(row.video_path)
    if not video.exists():
        raise HTTPException(410, "video missing from disk")
    return FileResponse(video, media_type="video/mp4", filename=f"upsc-{issue_id}.mp4")


class YoutubePublish(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=5000)
    tags: list[str] = Field(default_factory=list)
    privacy: Literal["public", "unlisted", "private"] = "unlisted"


@router.post("/api/admin/upsc/issues/{issue_id}/youtube")
async def admin_youtube(
    issue_id: str,
    body: YoutubePublish,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Manually publish the rendered video to YouTube. Runs the QC gate first
    and blocks (surfacing the reason) if the MP4 is invalid / silent / out of
    band. The upload itself runs in a thread (network-bound, slow)."""
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if not row.video_path:
        raise HTTPException(400, "no rendered video to publish")
    video_path = row.video_path
    if not Path(video_path).exists():
        raise HTTPException(410, "video missing from disk")

    # QC gate — fail closed, surface the reason. Block any publish if it fails.
    ok, reason, _dur = _qc_video(video_path)
    if not ok:
        raise HTTPException(422, f"QC gate blocked publish: {reason}")

    meta = {
        "title": body.title.strip(),
        "description": body.description,
        "tags": body.tags,
        "privacy": body.privacy,
    }

    import anyio

    def _do_upload() -> dict:
        from scripts import youtube_upload
        return youtube_upload.upload(video_path, meta)

    try:
        result = await anyio.to_thread.run_sync(_do_upload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"YouTube upload failed: {exc}")

    row.youtube_id = result.get("youtube_id")
    row.youtube_url = result.get("youtube_url")
    row.video_status = "ready"
    row.video_progress = "published to YouTube"
    await _audit(s, admin, "upsc.youtube_publish", target_id=issue_id, payload={
        "youtube_url": row.youtube_url, "privacy": body.privacy,
    })
    await s.commit()
    return {"youtube_url": row.youtube_url, "youtube_id": row.youtube_id}


def _merged_video_defaults(stored: Any) -> dict[str, Any]:
    """Overlay the stored defaults blob on the fallback so every key is present
    even when only a subset was saved."""
    out = dict(VIDEO_DEFAULTS_FALLBACK)
    if isinstance(stored, dict):
        out.update({k: v for k, v in stored.items() if v is not None})
    return out


@router.get("/api/admin/upsc/video-defaults")
async def admin_get_video_defaults(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Read the persisted VideoDefaults from app_settings (merged with the
    server fallback so the UI always gets a complete object)."""
    stored = await app_settings.get(s, VIDEO_DEFAULTS_KEY)
    return _merged_video_defaults(stored)


class VideoDefaultsBody(BaseModel):
    engine: Literal["gemini", "chirp"] = "chirp"
    voice: str = "hi-IN-Chirp3-HD-Alnilam"
    lang: Literal["hi", "en"] = "hi"
    slide_style: Literal["digest", "clean", "animated"] = "clean"
    theme: str = "amber"
    privacy: Literal["public", "unlisted", "private"] = "unlisted"
    auto_publish: bool = False
    auto_generate_on_upload: bool = False
    title_template: str = VIDEO_DEFAULTS_FALLBACK["title_template"]
    description_template: str = VIDEO_DEFAULTS_FALLBACK["description_template"]


class VideoDefaultsRequest(BaseModel):
    defaults: VideoDefaultsBody


@router.put("/api/admin/upsc/video-defaults")
async def admin_put_video_defaults(
    body: VideoDefaultsRequest,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Persist the VideoDefaults blob into app_settings (one JSON row, same
    path every other setting uses). New issues pre-fill from this."""
    value = body.defaults.model_dump()
    await app_settings.set_value(s, VIDEO_DEFAULTS_KEY, value, updated_by=admin.email)
    await _audit(s, admin, "upsc.video_defaults", payload=value)
    await s.commit()
    return {"ok": True}


# =============================================================================
# Public: list / get / pdf / thumb
# =============================================================================

@router.get("/api/public/upsc/issues")
async def public_list(
    s: AsyncSession = Depends(get_session),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    q = (select(UpscIssue)
         .where(UpscIssue.status == "published")
         .order_by(desc(UpscIssue.issue_date))
         .limit(limit).offset(offset))
    rows = (await s.execute(q)).scalars().all()
    return {
        "issues": [{
            "date": r.issue_date.isoformat(),
            "title": r.title,
            "source": r.source,
            "summary": r.summary,
            "article_count": r.article_count,
            "published_at": r.published_at.isoformat() if r.published_at else None,
        } for r in rows],
        "limit": limit, "offset": offset,
    }


@router.get("/api/public/upsc/issues/{issue_date}")
async def public_get(
    issue_date: str,
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        the_date = date_cls.fromisoformat(issue_date)
    except ValueError:
        raise HTTPException(400, "issue_date must be YYYY-MM-DD")
    row = (await s.execute(
        select(UpscIssue).where(UpscIssue.issue_date == the_date)
    )).scalar_one_or_none()
    if row is None or row.status != "published":
        raise HTTPException(404, "issue not found or not published")
    return {
        "date": row.issue_date.isoformat(),
        "title": row.title,
        "source": row.source,
        "summary": row.summary,
        "article_count": row.article_count,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "pdf_url": f"/api/public/upsc/pdf/{the_date.isoformat()}",
        "thumb_url": f"/api/public/upsc/thumb/{the_date.isoformat()}",
    }


@router.get("/api/public/upsc/pdf/{issue_date}")
async def public_pdf(
    issue_date: str,
    s: AsyncSession = Depends(get_session),
) -> FileResponse:
    try:
        the_date = date_cls.fromisoformat(issue_date)
    except ValueError:
        raise HTTPException(400, "issue_date must be YYYY-MM-DD")
    row = (await s.execute(
        select(UpscIssue).where(UpscIssue.issue_date == the_date)
    )).scalar_one_or_none()
    if row is None or row.status != "published" or not row.output_pdf_path:
        raise HTTPException(404, "PDF not found")
    pdf_path = Path(row.output_pdf_path)
    if not pdf_path.exists():
        raise HTTPException(410, "PDF was removed from disk")
    fname = f"upsc-cheetsheet-{the_date.isoformat()}.pdf"
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=fname,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/public/upsc/thumb/{issue_date}")
async def public_thumb(
    issue_date: str,
    s: AsyncSession = Depends(get_session),
) -> FileResponse:
    try:
        the_date = date_cls.fromisoformat(issue_date)
    except ValueError:
        raise HTTPException(400, "issue_date must be YYYY-MM-DD")
    row = (await s.execute(
        select(UpscIssue).where(UpscIssue.issue_date == the_date)
    )).scalar_one_or_none()
    if row is None or row.status != "published" or not row.cover_thumb_path:
        raise HTTPException(404, "thumbnail not found")
    thumb = Path(row.cover_thumb_path)
    if not thumb.exists():
        raise HTTPException(410, "thumbnail was removed from disk")
    return FileResponse(
        thumb, media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# =============================================================================
# Admin-only: stream the in-preview PDF (so admin can preview pre-publish)
# =============================================================================

@router.get("/api/admin/upsc/issues/{issue_id}/pdf")
async def admin_pdf(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> FileResponse:
    row = await s.get(UpscIssue, issue_id)
    if row is None:
        raise HTTPException(404, "issue not found")
    if not row.output_pdf_path:
        raise HTTPException(404, "no rendered PDF yet")
    pdf_path = Path(row.output_pdf_path)
    if not pdf_path.exists():
        raise HTTPException(410, "PDF missing from disk")
    return FileResponse(pdf_path, media_type="application/pdf")


@router.get("/api/admin/upsc/issues/{issue_id}/thumb")
async def admin_thumb(
    issue_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> FileResponse:
    row = await s.get(UpscIssue, issue_id)
    if row is None or not row.cover_thumb_path:
        raise HTTPException(404, "no thumbnail yet")
    thumb = Path(row.cover_thumb_path)
    if not thumb.exists():
        raise HTTPException(410, "thumbnail missing")
    return FileResponse(thumb, media_type="image/png")
