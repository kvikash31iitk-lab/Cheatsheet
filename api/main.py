"""FastAPI service that wraps the bot pipeline.

Phase 1 (this version):
  - Generations are persisted to a SQL DB (SQLite locally, Postgres in prod).
  - User identity is read from the ``X-User-ID`` header injected by the
    Next.js middleware after a NextAuth Google session is established.
    During development the header is allowed to be missing — the API falls
    back to a hardcoded "anonymous" user so the pipeline can still be
    smoke-tested without going through the OAuth flow.
  - Free-tier quota (5 cheatsheets, 2 book notes) is enforced on
    ``POST /api/generate``.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Make the existing bot modules importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- PATH augmentation (Windows dev convenience) ---------------------------

def _augment_path() -> None:
    extra: list[str] = []
    if sys.platform == "win32":
        appdata_scripts = Path(os.environ.get("APPDATA", "")) / "Python"
        for sub in appdata_scripts.glob("Python*/Scripts"):
            extra.append(str(sub))
        for cand in [
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        ]:
            if Path(cand).exists():
                extra.append(cand)
        winget_pkgs = Path(
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
        )
        for bin_dir in winget_pkgs.glob("Gyan.FFmpeg_*/ffmpeg-*/bin"):
            extra.append(str(bin_dir))
        for deno_pkg in winget_pkgs.glob("DenoLand.Deno_*"):
            if (deno_pkg / "deno.exe").exists():
                extra.append(str(deno_pkg))
    if extra:
        os.environ["PATH"] = (
            os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")
        )


_augment_path()

# Wire the project's cookies.txt to yt-dlp.
_local_cookies = PROJECT_ROOT / "cookies.txt"
if _local_cookies.exists() and "YT_COOKIES_PATH" not in os.environ:
    os.environ["YT_COOKIES_PATH"] = str(_local_cookies)

# Load the project .env so the existing pipeline picks up keys.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


# --- pipeline imports (after PATH/env setup) -------------------------------

from scripts.transcribe_with_frames import fetch_metadata, run_pipeline  # noqa: E402
from scripts.build_cheatsheet import build as build_cheatsheet  # noqa: E402
from scripts.build_illustrated_book import build as build_book  # noqa: E402
from bot.author import author_book, author_cheatsheet  # noqa: E402

from api.db import (  # noqa: E402
    AsyncSessionLocal,
    Base,
    SyncSessionLocal,
    async_engine,
    get_session,
)
from api.models import Generation, User  # noqa: E402

WORK_ROOT = PROJECT_ROOT / "web_work"
WORK_ROOT.mkdir(exist_ok=True)

INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
ANON_USER_EMAIL = "anonymous@local.dev"

# Free-tier limits (lifetime, per user)
FREE_CHEATSHEETS = 5
FREE_BOOKS = 2


# --- FastAPI app -----------------------------------------------------------

app = FastAPI(title="Cheatsheet API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed the anonymous user for dev so /api/generate works without auth.
    async with AsyncSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == ANON_USER_EMAIL))
        if result.scalar_one_or_none() is None:
            s.add(User(email=ANON_USER_EMAIL, name="Anonymous"))
            await s.commit()


# --- auth dependency -------------------------------------------------------

async def current_user(
    request: Request,
    s: AsyncSession = Depends(get_session),
    x_user_id: Optional[str] = Header(default=None),
    x_internal_token: Optional[str] = Header(default=None),
) -> User:
    """Resolve the active user.

    In production the Next.js middleware sets ``X-User-ID`` after validating
    the NextAuth session, plus an ``X-Internal-Token`` shared secret so this
    API doesn't trust headers from arbitrary clients.

    During development (no token configured), or when the headers are missing,
    we fall back to the anonymous user so curl / browser pokes still work.
    """
    if x_user_id and INTERNAL_API_TOKEN and x_internal_token == INTERNAL_API_TOKEN:
        result = await s.execute(select(User).where(User.id == x_user_id))
        u = result.scalar_one_or_none()
        if u:
            u.last_seen_at = datetime.now(timezone.utc)
            await s.commit()
            return u

    # Dev fallback: anonymous user.
    result = await s.execute(select(User).where(User.email == ANON_USER_EMAIL))
    return result.scalar_one()


# --- routes ----------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"ok": "yes"}


class UpsertUserRequest(BaseModel):
    email: str
    name: Optional[str] = None
    picture_url: Optional[str] = None
    google_sub: Optional[str] = None


@app.post("/api/auth/upsert-user")
async def upsert_user(
    req: UpsertUserRequest,
    s: AsyncSession = Depends(get_session),
    x_internal_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Called by Next.js after a successful OAuth sign-in.

    Trusted via the shared ``INTERNAL_API_TOKEN`` since FastAPI binds to
    127.0.0.1 and only Next.js can reach it. Returns the user row.
    """
    if not INTERNAL_API_TOKEN or x_internal_token != INTERNAL_API_TOKEN:
        raise HTTPException(401, "missing or invalid internal token")

    result = await s.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=req.email,
            name=req.name,
            picture_url=req.picture_url,
            google_sub=req.google_sub,
        )
        s.add(user)
    else:
        if req.name and req.name != user.name:
            user.name = req.name
        if req.picture_url and req.picture_url != user.picture_url:
            user.picture_url = req.picture_url
        if req.google_sub and not user.google_sub:
            user.google_sub = req.google_sub
    user.last_seen_at = datetime.now(timezone.utc)
    await s.commit()
    await s.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
    }


@app.get("/api/me")
async def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "is_admin": user.is_admin,
        "free_cheatsheets_left": max(0, FREE_CHEATSHEETS - user.free_cheatsheets_used),
        "free_books_left": max(0, FREE_BOOKS - user.free_books_used),
        "wallet_balance_paise": user.wallet_balance_paise,
    }


@app.get("/api/library")
async def library(
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    result = await s.execute(
        select(Generation)
        .where(Generation.user_id == user.id)
        .order_by(Generation.created_at.desc())
        .limit(100)
    )
    rows = result.scalars().all()
    return [_serialize(g) for g in rows]


class CreateRequest(BaseModel):
    url: str = Field(..., min_length=10)
    kind: Literal["cheatsheet", "book"]


@app.post("/api/generate")
async def create_generation(
    req: CreateRequest,
    bg: BackgroundTasks,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    # Quota check
    if req.kind == "cheatsheet" and user.free_cheatsheets_used >= FREE_CHEATSHEETS \
            and user.wallet_balance_paise <= 0:
        raise HTTPException(402, "Free cheatsheet quota exhausted. Top up your wallet.")
    if req.kind == "book" and user.free_books_used >= FREE_BOOKS \
            and user.wallet_balance_paise <= 0:
        raise HTTPException(402, "Free book-notes quota exhausted. Top up your wallet.")

    gen = Generation(
        id=uuid.uuid4().hex,
        user_id=user.id,
        kind=req.kind,
        url=req.url,
        status="queued",
        progress=0.0,
        was_free=True,  # Phase 1: every generation is free until Razorpay lands
    )
    s.add(gen)
    await s.commit()
    await s.refresh(gen)

    bg.add_task(_run_job, gen.id)
    return {"id": gen.id}


@app.get("/api/jobs/{job_id}")
async def get_job(
    job_id: str,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await s.execute(select(Generation).where(Generation.id == job_id))
    gen = result.scalar_one_or_none()
    if not gen:
        raise HTTPException(404, "job not found")
    if gen.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "not your job")
    return _serialize(gen)


@app.get("/api/files/{job_id}/pdf")
async def get_pdf(
    job_id: str,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> FileResponse:
    result = await s.execute(select(Generation).where(Generation.id == job_id))
    gen = result.scalar_one_or_none()
    if not gen:
        raise HTTPException(404, "job not found")
    if gen.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "not your job")
    if not gen.pdf_path or not Path(gen.pdf_path).exists():
        raise HTTPException(404, "pdf not ready")
    safe = "".join(c if c.isalnum() or c in " ._-" else "_" for c in (gen.title or ""))
    safe = safe.strip()[:80] or "cheatsheet"
    return FileResponse(
        gen.pdf_path, media_type="application/pdf", filename=f"{safe}.pdf"
    )


# --- background runner -----------------------------------------------------

def _serialize(gen: Generation) -> dict[str, Any]:
    """Shape a Generation row into the JSON the frontend expects."""
    base = {
        "id": gen.id,
        "kind": gen.kind,
        "url": gen.url,
        "created_at": gen.created_at.isoformat() if gen.created_at else None,
        "meta": {
            "video_id": gen.video_id or "",
            "title": gen.title or "",
            "duration_seconds": gen.duration_seconds or 0,
            "channel": gen.channel or "",
            "thumbnail_url": gen.thumbnail_url or "",
        }
        if gen.video_id
        else None,
    }
    if gen.status in ("queued", "running"):
        base["status"] = {
            "state": gen.status,
            "step": gen.step or "",
            "progress": gen.progress,
        }
    elif gen.status == "done":
        base["status"] = {
            "state": "done",
            "pdf_url": f"/api/files/{gen.id}/pdf",
            "markdown": gen.markdown or "",
            "meta": base["meta"] or {},
        }
    elif gen.status == "error":
        base["status"] = {"state": "error", "message": gen.error_message or "unknown"}
    return base


def _update_sync(job_id: str, **fields: Any) -> None:
    """Apply a partial update to a Generation row from a worker thread."""
    with SyncSessionLocal() as s:
        gen = s.get(Generation, job_id)
        if not gen:
            return
        for k, v in fields.items():
            setattr(gen, k, v)
        s.commit()


async def _run_job(job_id: str) -> None:
    progress_state = {"p": 0.05, "step": "Starting"}

    def emit(step: str, p: float | None = None) -> None:
        if p is not None:
            progress_state["p"] = max(progress_state["p"], min(0.95, p))
        progress_state["step"] = step
        _update_sync(
            job_id,
            status="running",
            step=step,
            progress=round(progress_state["p"], 3),
        )

    def on_pipeline(msg: str) -> None:
        m = msg.lower()
        bumps = [
            ("download", 0.12),
            ("encode", 0.18),
            ("scene", 0.22),
            ("sampling fallback", 0.28),
            ("dedup", 0.32),
            ("splitting", 0.40),
            ("transcrib", 0.45),
        ]
        for kw, p in bumps:
            if kw in m:
                emit(msg, max(progress_state["p"], p))
                return
        if "chunk" in m and "/" in m:
            try:
                ratio = msg.split("chunk")[1].split("...")[0].strip()
                a, b = ratio.split("/")
                p = 0.45 + 0.25 * (int(a) / int(b))
                emit(msg, p)
                return
            except Exception:
                pass
        emit(msg)

    work = WORK_ROOT / job_id
    work.mkdir(parents=True, exist_ok=True)

    # Look up the kind/url from DB (avoids race where user mutated something).
    with SyncSessionLocal() as s:
        gen = s.get(Generation, job_id)
        if not gen:
            return
        kind = gen.kind
        url = gen.url

    try:
        emit("Fetching video metadata", 0.05)
        meta = await asyncio.to_thread(fetch_metadata, url)
        _update_sync(
            job_id,
            video_id=meta["id"],
            title=meta["title"],
            duration_seconds=meta["duration"],
            thumbnail_url=f"https://i.ytimg.com/vi/{meta['id']}/hqdefault.jpg",
        )

        extract_frames = kind == "book"
        result = await asyncio.to_thread(
            run_pipeline,
            url,
            work,
            extract_frames=extract_frames,
            on_progress=on_pipeline,
        )

        emit("Authoring notes", 0.72)
        if kind == "cheatsheet":
            md_text = await asyncio.to_thread(
                author_cheatsheet,
                result["transcript_txt"],
                title_hint=meta["title"],
                duration_seconds=meta["duration"],
                on_progress=lambda m: emit(m, max(progress_state["p"], 0.72)),
            )
        else:
            md_text = await asyncio.to_thread(
                author_book,
                result["transcript_with_frames"],
                result["frames_index"],
                title_hint=meta["title"],
                duration_seconds=meta["duration"],
                on_progress=lambda m: emit(m, max(progress_state["p"], 0.72)),
            )

        md_path = work / "output.md"
        md_path.write_text(md_text, encoding="utf-8")

        emit("Rendering PDF", 0.92)
        pdf_path = work / "output.pdf"
        if kind == "cheatsheet":
            await asyncio.to_thread(build_cheatsheet, md_path, pdf_path, meta["title"])
        else:
            await asyncio.to_thread(
                build_book,
                md_path,
                pdf_path,
                meta["title"],
                result["frames_dir"],
                None,
            )

        # Mark done + bump quota counter.
        with SyncSessionLocal() as s:
            gen = s.get(Generation, job_id)
            if gen:
                gen.status = "done"
                gen.step = "done"
                gen.progress = 1.0
                gen.markdown = md_text
                gen.pdf_path = str(pdf_path)
                gen.completed_at = datetime.now(timezone.utc)
                user = s.get(User, gen.user_id)
                if user and gen.was_free:
                    if kind == "cheatsheet":
                        user.free_cheatsheets_used += 1
                    else:
                        user.free_books_used += 1
                s.commit()

    except Exception as exc:
        _update_sync(
            job_id,
            status="error",
            error_message=f"{type(exc).__name__}: {exc}",
            completed_at=datetime.now(timezone.utc),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)
