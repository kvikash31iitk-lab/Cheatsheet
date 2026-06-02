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
import shutil
import threading
import uuid
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.deps import require_admin
from api.models import AuditLog, UpscIssue, User

# Where input newspaper PDFs land. The pipeline reads from here.
UPSC_UPLOADS = Path(__file__).resolve().parent.parent / "web_work" / "upsc_uploads"
UPSC_UPLOADS.mkdir(parents=True, exist_ok=True)


router = APIRouter(tags=["upsc"])


STYLE_CHOICES = ("academic", "dense", "dense_tight", "coaching", "magazine")


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
    }
    if include_markdown:
        out["markdown"] = row.markdown
    return out


def _kick_pipeline(issue_id: str) -> None:
    """Background task wrapper — runs the pipeline in a thread so the request
    handler returns immediately. ``process_issue`` does its own DB session
    management via SyncSessionLocal, so no event-loop interaction here."""
    def _run():
        from scripts.upsc_pipeline import process_issue
        try:
            process_issue(issue_id)
        except Exception as exc:
            # process_issue already records error_message on the row.
            print(f"[upsc] pipeline crashed for {issue_id}: {exc}")
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
    limit: int = 30,
    offset: int = 0,
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
                B.RUNNING_HEADER = "UPSC CHEETSHEET"
                B.RUNNING_RIGHT = row.issue_date.strftime("%d %b %Y").lstrip("0")
                issue_url = f"https://cheetsheet.tech/upsc/{row.issue_date.isoformat()}"
                t0 = time.monotonic()
                B.build(
                    src=md_path, out=output_pdf, title=row.title,
                    subtitle=f"{row.source} - {row.issue_date.strftime('%d %B %Y').lstrip('0')}",
                    features=["summary", "tldr", "qna", "chapters"],
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
# Public: list / get / pdf / thumb
# =============================================================================

@router.get("/api/public/upsc/issues")
async def public_list(
    s: AsyncSession = Depends(get_session),
    limit: int = 30,
    offset: int = 0,
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
