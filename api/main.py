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
import math
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
from api.models import Generation, Transaction, User  # noqa: E402

WORK_ROOT = PROJECT_ROOT / "web_work"
WORK_ROOT.mkdir(exist_ok=True)

INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
ANON_USER_EMAIL = "anonymous@local.dev"

# Free tier — daily cap, resets at midnight IST
FREE_CHEATSHEETS_PER_DAY = 3
FREE_BOOKS_PER_DAY = 1

# Pricing — paise per 30-minute slab (rounded up). 30 min cheatsheet = ₹1,
# 30 min book = ₹2, 90 min cheatsheet = ₹3 etc.
COST_PAISE_PER_30MIN: dict[str, int] = {
    "cheatsheet": 100,
    "book": 200,
}
MIN_TOPUP_PAISE = 100 * 100  # ₹100

# Razorpay test/live credentials. Live values come from .env / systemd env.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")


def _ist_day_start_utc() -> datetime:
    """UTC datetime for the start of the current IST calendar day. Used to
    bound the daily-quota query."""
    now_utc = datetime.now(timezone.utc)
    ist = now_utc + timedelta(hours=5, minutes=30)
    ist_day_start = ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return ist_day_start - timedelta(hours=5, minutes=30)


def _calc_cost_paise(duration_seconds: float, kind: str) -> int:
    """Cost in paise, rounded up to the next 30-minute slab. Minimum one slab."""
    slabs = max(1, math.ceil(max(1.0, duration_seconds) / (30 * 60)))
    return slabs * COST_PAISE_PER_30MIN[kind]


async def _daily_used(s: AsyncSession, user_id: str) -> tuple[int, int]:
    """Free-tier generations consumed today (cheatsheets, books)."""
    start = _ist_day_start_utc()
    result = await s.execute(
        select(Generation.kind, func.count())
        .where(Generation.user_id == user_id)
        .where(Generation.created_at >= start)
        .where(Generation.was_free.is_(True))
        .where(Generation.status != "error")
        .group_by(Generation.kind)
    )
    counts = {kind: int(c) for kind, c in result.all()}
    return counts.get("cheatsheet", 0), counts.get("book", 0)


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
async def me(
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cheats_today, books_today = await _daily_used(s, user.id)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "is_admin": user.is_admin,
        "free_cheatsheets_left": max(0, FREE_CHEATSHEETS_PER_DAY - cheats_today),
        "free_books_left": max(0, FREE_BOOKS_PER_DAY - books_today),
        "free_cheatsheets_per_day": FREE_CHEATSHEETS_PER_DAY,
        "free_books_per_day": FREE_BOOKS_PER_DAY,
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


class PreviewRequest(BaseModel):
    url: str = Field(..., min_length=10)


# Tiny in-memory cache so refreshing the page or trying multiple kinds for the
# same URL doesn't re-spawn yt-dlp every time. Keyed by URL, capped at 256.
_PREVIEW_CACHE: dict[str, dict[str, Any]] = {}


@app.post("/api/preview")
async def preview(
    req: PreviewRequest,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Cheap metadata lookup for a YouTube URL — used by the generate UI to
    show a thumbnail + title + duration + cost preview BEFORE the user
    commits to a generation.
    """
    if req.url in _PREVIEW_CACHE:
        out = dict(_PREVIEW_CACHE[req.url])
    else:
        try:
            meta = await asyncio.to_thread(fetch_metadata, req.url)
        except Exception as exc:
            raise HTTPException(400, f"Could not read URL: {exc}")
        out = {
            "video_id": meta["id"],
            "title": meta["title"],
            "duration_seconds": meta["duration"],
            "thumbnail_url": f"https://i.ytimg.com/vi/{meta['id']}/hqdefault.jpg",
        }
        if len(_PREVIEW_CACHE) > 256:
            _PREVIEW_CACHE.clear()
        _PREVIEW_CACHE[req.url] = out

    # Annotate with what it would cost if the user is past today's free tier.
    out["cost_paise"] = {
        "cheatsheet": _calc_cost_paise(out["duration_seconds"], "cheatsheet"),
        "book": _calc_cost_paise(out["duration_seconds"], "book"),
    }
    return out


@app.post("/api/generate")
async def create_generation(
    req: CreateRequest,
    bg: BackgroundTasks,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    # Resolve duration up-front so we can price + decide free vs paid.
    cached = _PREVIEW_CACHE.get(req.url)
    if cached:
        duration = float(cached.get("duration_seconds") or 0)
    else:
        try:
            meta = await asyncio.to_thread(fetch_metadata, req.url)
        except Exception as exc:
            raise HTTPException(400, f"Could not read URL: {exc}")
        duration = float(meta["duration"])
        _PREVIEW_CACHE[req.url] = {
            "video_id": meta["id"],
            "title": meta["title"],
            "duration_seconds": meta["duration"],
            "thumbnail_url": f"https://i.ytimg.com/vi/{meta['id']}/hqdefault.jpg",
        }

    cheats_today, books_today = await _daily_used(s, user.id)
    if req.kind == "cheatsheet":
        within_free = cheats_today < FREE_CHEATSHEETS_PER_DAY
    else:
        within_free = books_today < FREE_BOOKS_PER_DAY

    cost_paise = 0
    if within_free:
        was_free = True
    else:
        cost_paise = _calc_cost_paise(duration, req.kind)
        if user.wallet_balance_paise < cost_paise:
            mins = math.ceil(duration / 60)
            raise HTTPException(
                402,
                f"Today's free {req.kind}s are used. "
                f"This {mins}-min video would cost ₹{cost_paise / 100:.0f} "
                f"but your wallet has ₹{user.wallet_balance_paise / 100:.2f}. "
                f"Top up to continue.",
            )
        was_free = False

    gen = Generation(
        id=uuid.uuid4().hex,
        user_id=user.id,
        kind=req.kind,
        url=req.url,
        status="queued",
        progress=0.0,
        was_free=was_free,
        cost_paise=cost_paise,
    )
    s.add(gen)

    # Deduct + log spend transaction now (refunded automatically if the job
    # later errors out — see _run_job).
    if cost_paise > 0:
        user.wallet_balance_paise -= cost_paise
        s.add(
            Transaction(
                user_id=user.id,
                kind="spend",
                amount_paise=-cost_paise,
                generation_id=gen.id,
                status="success",
                note=f"{req.kind} · {math.ceil(duration / 60)}min",
            )
        )

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


# --- wallet -----------------------------------------------------------------

class TopupOrderRequest(BaseModel):
    amount_paise: int = Field(..., ge=MIN_TOPUP_PAISE)


def _razorpay_client():
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(503, "Wallet payments are not configured yet.")
    import razorpay  # type: ignore
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


@app.post("/api/wallet/order")
async def wallet_create_order(
    req: TopupOrderRequest,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    client = _razorpay_client()
    order = await asyncio.to_thread(
        client.order.create,
        {
            "amount": req.amount_paise,
            "currency": "INR",
            "notes": {"user_id": user.id, "user_email": user.email},
        },
    )
    s.add(
        Transaction(
            user_id=user.id,
            kind="topup",
            amount_paise=req.amount_paise,
            razorpay_order_id=order["id"],
            status="pending",
        )
    )
    await s.commit()
    return {
        "order_id": order["id"],
        "amount_paise": req.amount_paise,
        "key_id": RAZORPAY_KEY_ID,
        "currency": "INR",
    }


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@app.post("/api/wallet/verify")
async def wallet_verify(
    req: VerifyRequest,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    client = _razorpay_client()
    try:
        await asyncio.to_thread(
            client.utility.verify_payment_signature,
            {
                "razorpay_order_id": req.razorpay_order_id,
                "razorpay_payment_id": req.razorpay_payment_id,
                "razorpay_signature": req.razorpay_signature,
            },
        )
    except Exception:
        raise HTTPException(400, "Invalid payment signature")

    result = await s.execute(
        select(Transaction).where(
            Transaction.razorpay_order_id == req.razorpay_order_id,
            Transaction.user_id == user.id,
        )
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Order not found")
    if tx.status == "success":
        return {"balance_paise": user.wallet_balance_paise, "already": True}

    tx.razorpay_payment_id = req.razorpay_payment_id
    tx.status = "success"
    user.wallet_balance_paise += tx.amount_paise
    await s.commit()
    return {"balance_paise": user.wallet_balance_paise, "credited": tx.amount_paise}


@app.get("/api/wallet/transactions")
async def wallet_transactions(
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    result = await s.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc())
        .limit(100)
    )
    rows = result.scalars().all()
    return [
        {
            "id": tx.id,
            "kind": tx.kind,
            "amount_paise": tx.amount_paise,
            "status": tx.status,
            "note": tx.note,
            "generation_id": tx.generation_id,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }
        for tx in rows
    ]


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

        # Mark done. Daily usage is derived from generations rows so there's
        # no per-user counter to bump here.
        with SyncSessionLocal() as s:
            gen = s.get(Generation, job_id)
            if gen:
                gen.status = "done"
                gen.step = "done"
                gen.progress = 1.0
                gen.markdown = md_text
                gen.pdf_path = str(pdf_path)
                gen.completed_at = datetime.now(timezone.utc)
                s.commit()

    except Exception as exc:
        # Refund the wallet for paid jobs that fail mid-pipeline.
        with SyncSessionLocal() as s:
            gen = s.get(Generation, job_id)
            if gen:
                gen.status = "error"
                gen.error_message = f"{type(exc).__name__}: {exc}"
                gen.completed_at = datetime.now(timezone.utc)
                if gen.cost_paise and not gen.was_free:
                    user_row = s.get(User, gen.user_id)
                    if user_row:
                        user_row.wallet_balance_paise += gen.cost_paise
                        s.add(
                            Transaction(
                                user_id=user_row.id,
                                kind="refund",
                                amount_paise=gen.cost_paise,
                                generation_id=gen.id,
                                status="success",
                                note="Auto-refund: generation failed",
                            )
                        )
                s.commit()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)
