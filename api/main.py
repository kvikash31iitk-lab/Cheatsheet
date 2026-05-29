"""FastAPI service that wraps the bot pipeline.

Generations are persisted to a SQL DB (SQLite locally, Postgres in prod).
User identity is read from the ``X-User-ID`` header injected by the
Next.js middleware after a NextAuth Google session is established. During
development the header is allowed to be missing — the API falls back to
a hardcoded "anonymous" user so the pipeline can still be smoke-tested
without going through the OAuth flow.

Free-tier quota, pricing, maintenance mode, and other knobs are pulled
from the ``app_settings`` table via ``api.settings`` (cached). Admin
endpoints live on ``api.admin`` and are mounted below.
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

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update as sa_update
from sqlalchemy.exc import IntegrityError
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
from api.deps import (  # noqa: E402
    ANON_USER_EMAIL,
    INTERNAL_API_TOKEN,
    current_user,
    is_admin_email,
)
from api.models import (  # noqa: E402
    BlockRule,
    Broadcast,
    Generation,
    PromoCode,
    PromoRedemption,
    Transaction,
    User,
)
from api import settings as app_settings  # noqa: E402
from api.admin import router as admin_router  # noqa: E402

WORK_ROOT = PROJECT_ROOT / "web_work"
WORK_ROOT.mkdir(exist_ok=True)

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


def _calc_cost_paise_for(
    duration_seconds: float, kind: str, per_30min: dict[str, int]
) -> int:
    """Cost in paise, rounded up to the next 30-minute slab. Minimum one slab.

    ``per_30min`` is passed in (not read from settings here) so callers can
    fetch the value once per request instead of per-call."""
    slabs = max(1, math.ceil(max(1.0, duration_seconds) / (30 * 60)))
    return slabs * per_30min[kind]


# What each provider/backend ACTUALLY costs us (paise). These power the cost
# tracker on /admin/generations — not the user's billing (that's the slab rate).
# USD→INR conversion baked at ~₹85/USD; tweak if FX moves materially.
LLM_RATES_PAISE_PER_MTOK = {
    "claude_code": {"in": 0, "out": 0},          # subsidized by Max subscription
    "groq":        {"in": 0, "out": 0},          # free tier
    "openai":      {"in": 1275, "out": 5100},    # gpt-4o-mini @ $0.15 / $0.60
    "anthropic":   {"in": 25500, "out": 127500}, # sonnet @ $3 / $15
}
WHISPER_RATES_PAISE_PER_MIN = {
    "local":  0,
    "groq":   0,
    "openai": 51,  # $0.006/min @ ₹85/$
}


def _llm_cost_paise(provider: str, tokens_in: int, tokens_out: int) -> int:
    rates = LLM_RATES_PAISE_PER_MTOK.get(provider, {"in": 0, "out": 0})
    return (tokens_in * rates["in"] + tokens_out * rates["out"]) // 1_000_000


def _whisper_cost_paise(backend: str, duration_seconds: float) -> int:
    rate = WHISPER_RATES_PAISE_PER_MIN.get(backend, 0)
    return int(rate * (duration_seconds / 60))


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


async def _free_limits_for(s: AsyncSession, user: User) -> tuple[int, int]:
    """Per-day free quota for ``user`` — honouring admin overrides."""
    cfg = await app_settings.get_many(
        s, ["free_cheatsheets_per_day", "free_books_per_day"]
    )
    cheats = (
        user.daily_cheatsheets_override
        if user.daily_cheatsheets_override is not None
        else int(cfg["free_cheatsheets_per_day"])
    )
    books = (
        user.daily_books_override
        if user.daily_books_override is not None
        else int(cfg["free_books_per_day"])
    )
    return cheats, books


# --- FastAPI app -----------------------------------------------------------

app = FastAPI(title="Cheatsheet API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, sql type). Boolean defaults use the placeholder
    # ``__BOOL_FALSE__`` which is swapped per-dialect at apply time
    # (`0` for SQLite, `FALSE` for Postgres) so the ALTER works on both.
    ("users", "daily_cheatsheets_override", "INTEGER"),
    ("users", "daily_books_override", "INTEGER"),
    ("users", "bypass_paid", "BOOLEAN NOT NULL DEFAULT __BOOL_FALSE__"),
    ("users", "is_banned", "BOOLEAN NOT NULL DEFAULT __BOOL_FALSE__"),
    ("users", "custom_prompt_cheatsheet", "TEXT"),
    ("users", "custom_prompt_book", "TEXT"),
    ("users", "referral_code", "VARCHAR(16)"),
    ("users", "referred_by_code", "VARCHAR(16)"),
    ("generations", "llm_tokens_in", "INTEGER NOT NULL DEFAULT 0"),
    ("generations", "llm_tokens_out", "INTEGER NOT NULL DEFAULT 0"),
    ("generations", "llm_cost_paise", "INTEGER NOT NULL DEFAULT 0"),
    ("generations", "transcription_cost_paise", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "telegram_chat_id", "VARCHAR(64)"),
]


# Idempotent index additions. Each entry: (index_name, CREATE statement).
# Wrapped in `IF NOT EXISTS` so re-runs are no-ops on both backends.
_INDEX_MIGRATIONS: list[tuple[str, str]] = [
    (
        "ux_promo_redemptions_promo_user",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_promo_redemptions_promo_user "
        "ON promo_redemptions (promo_id, user_id)",
    ),
]


async def _migrate_columns() -> None:
    """Idempotent ALTER TABLE / CREATE INDEX for schema additions made after
    the initial release.

    Each statement runs in its **own** transaction so one failure doesn't
    poison the rest — Postgres aborts the whole transaction after the first
    error and rejects every subsequent statement otherwise.
    """
    from sqlalchemy import inspect, text

    dialect = async_engine.dialect.name  # "sqlite" or "postgresql"
    bool_false = "FALSE" if dialect == "postgresql" else "0"

    def _check(sync_conn: Any) -> list[tuple[str, str, str]]:
        insp = inspect(sync_conn)
        existing: dict[str, set[str]] = {}
        for table, _col, _spec in _MIGRATIONS:
            if table not in existing:
                try:
                    existing[table] = {c["name"] for c in insp.get_columns(table)}
                except Exception:
                    existing[table] = set()
        return [
            (t, c, s) for (t, c, s) in _MIGRATIONS if c not in existing.get(t, set())
        ]

    async with async_engine.connect() as conn:
        missing = await conn.run_sync(_check)

    for table, col, spec in missing:
        spec = spec.replace("__BOOL_FALSE__", bool_false)
        try:
            async with async_engine.begin() as conn:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {spec}"))
            print(f"[migrate] added {table}.{col}")
        except Exception as exc:
            print(f"[migrate] skip {table}.{col}: {exc}")

    for name, sql in _INDEX_MIGRATIONS:
        try:
            async with async_engine.begin() as conn:
                await conn.execute(text(sql))
            print(f"[migrate] ensured index {name}")
        except Exception as exc:
            print(f"[migrate] skip index {name}: {exc}")


async def _recover_stuck_jobs() -> None:
    """Mark long-stuck queued/running rows as error and auto-refund the user.

    Runs on every API boot. Any job left in ``queued``/``running`` for more
    than 30 minutes is presumed orphaned (the previous process died mid-job),
    so we flip it to ``error`` and credit back the paise we deducted up-front.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with AsyncSessionLocal() as s:
        stuck = (
            await s.execute(
                select(Generation)
                .where(Generation.status.in_(("queued", "running")))
                .where(Generation.created_at < cutoff)
            )
        ).scalars().all()
        if not stuck:
            return
        for g in stuck:
            g.status = "error"
            g.error_message = "Server restarted mid-job — auto-recovered"
            g.completed_at = datetime.now(timezone.utc)
            if g.cost_paise > 0 and not g.was_free:
                user_row = await s.get(User, g.user_id)
                if user_row:
                    user_row.wallet_balance_paise += g.cost_paise
                    s.add(
                        Transaction(
                            user_id=user_row.id,
                            kind="refund",
                            amount_paise=g.cost_paise,
                            generation_id=g.id,
                            status="success",
                            note="Auto-refund: stuck job recovered on restart",
                        )
                    )
        await s.commit()
        print(f"[recovery] reset {len(stuck)} stuck job(s)", flush=True)


@app.on_event("startup")
async def startup() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_columns()
    await _recover_stuck_jobs()
    # Seed the anonymous user for dev so /api/generate works without auth.
    async with AsyncSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == ANON_USER_EMAIL))
        if result.scalar_one_or_none() is None:
            s.add(User(email=ANON_USER_EMAIL, name="Anonymous"))
            await s.commit()


app.include_router(admin_router)


# --- routes ----------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"ok": "yes"}


class UpsertUserRequest(BaseModel):
    email: str
    name: Optional[str] = None
    picture_url: Optional[str] = None
    google_sub: Optional[str] = None
    referral_code: Optional[str] = None


def _gen_referral_code() -> str:
    """Short, URL-safe, human-readable code (no ambiguous chars)."""
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


@app.post("/api/auth/upsert-user")
async def upsert_user(
    req: UpsertUserRequest,
    s: AsyncSession = Depends(get_session),
    x_internal_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Called by Next.js after a successful OAuth sign-in.

    Trusted via the shared ``INTERNAL_API_TOKEN`` since FastAPI binds to
    127.0.0.1 and only Next.js can reach it. Returns the user row.

    On a *new* user, if ``referral_code`` matches an existing user's code,
    both inviter and invitee receive ``referral_credit_paise`` from settings.
    """
    if not INTERNAL_API_TOKEN or x_internal_token != INTERNAL_API_TOKEN:
        raise HTTPException(401, "missing or invalid internal token")

    result = await s.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    is_new = user is None

    if user is None:
        user = User(
            email=req.email,
            name=req.name,
            picture_url=req.picture_url,
            google_sub=req.google_sub,
            referral_code=_gen_referral_code(),
        )
        # Mirror admin status into the User row so the UI can branch on
        # `me.is_admin` without re-reading the env.
        if is_admin_email(req.email):
            user.is_admin = True
        s.add(user)
        await s.flush()  # so we have user.id before applying referral

        if req.referral_code:
            code = req.referral_code.strip().upper()
            inviter = (
                await s.execute(
                    select(User).where(User.referral_code == code)
                )
            ).scalar_one_or_none()
            if inviter and inviter.id != user.id:
                credit = int(await app_settings.get(s, "referral_credit_paise"))
                if credit > 0:
                    inviter.wallet_balance_paise += credit
                    user.wallet_balance_paise += credit
                    user.referred_by_code = code
                    s.add_all(
                        [
                            Transaction(
                                user_id=inviter.id,
                                kind="topup",
                                amount_paise=credit,
                                status="success",
                                note=f"Referral · invited {user.email}",
                            ),
                            Transaction(
                                user_id=user.id,
                                kind="topup",
                                amount_paise=credit,
                                status="success",
                                note=f"Referral · joined via {inviter.email}",
                            ),
                        ]
                    )
    else:
        if req.name and req.name != user.name:
            user.name = req.name
        if req.picture_url and req.picture_url != user.picture_url:
            user.picture_url = req.picture_url
        if req.google_sub and not user.google_sub:
            user.google_sub = req.google_sub
        if is_admin_email(req.email) and not user.is_admin:
            user.is_admin = True
        if not user.referral_code:
            user.referral_code = _gen_referral_code()
    user.last_seen_at = datetime.now(timezone.utc)
    await s.commit()
    await s.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "is_new": is_new,
    }


@app.get("/api/me")
async def me(
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cheats_today, books_today = await _daily_used(s, user.id)
    free_cheats, free_books = await _free_limits_for(s, user)
    cfg = await app_settings.get_many(
        s,
        [
            "maintenance_mode",
            "maintenance_message",
            "cost_paise_per_30min_cheatsheet",
            "cost_paise_per_30min_book",
            "min_topup_paise",
        ],
    )
    # Active banner broadcast.
    now = datetime.now(timezone.utc)
    banner_row = (
        await s.execute(
            select(Broadcast)
            .where(Broadcast.active.is_(True))
            .where(Broadcast.channels.like("%banner%"))
            .where(or_(Broadcast.expires_at.is_(None), Broadcast.expires_at > now))
            .order_by(Broadcast.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    banner = (
        {"id": banner_row.id, "title": banner_row.title, "body": banner_row.body}
        if banner_row
        else None
    )

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "is_admin": user.is_admin or is_admin_email(user.email),
        "free_cheatsheets_left": max(0, free_cheats - cheats_today),
        "free_books_left": max(0, free_books - books_today),
        "free_cheatsheets_per_day": free_cheats,
        "free_books_per_day": free_books,
        "wallet_balance_paise": user.wallet_balance_paise,
        "referral_code": user.referral_code,
        "bypass_paid": user.bypass_paid,
        "cost_paise_per_30min": {
            "cheatsheet": int(cfg["cost_paise_per_30min_cheatsheet"]),
            "book": int(cfg["cost_paise_per_30min_book"]),
        },
        "min_topup_paise": int(cfg["min_topup_paise"]),
        "maintenance": {
            "active": bool(cfg["maintenance_mode"]),
            "message": str(cfg["maintenance_message"]),
        },
        "banner": banner,
    }


class RedeemPromoRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=32)


@app.post("/api/promos/redeem")
async def redeem_promo(
    req: RedeemPromoRequest,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    code = req.code.strip().upper()
    p = (
        await s.execute(select(PromoCode).where(PromoCode.code == code))
    ).scalar_one_or_none()
    if not p or not p.active:
        raise HTTPException(404, "Invalid or inactive code")
    if p.expires_at and p.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "This code has expired")
    if p.max_redemptions and p.times_redeemed >= p.max_redemptions:
        raise HTTPException(400, "This code has reached its redemption limit")
    # Race-safe insert: rely on the unique (promo_id, user_id) index to
    # prevent double-redemption when two requests land simultaneously.
    s.add(
        PromoRedemption(
            promo_id=p.id, user_id=user.id, credit_paise=p.credit_paise
        )
    )
    try:
        await s.flush()
    except IntegrityError:
        await s.rollback()
        raise HTTPException(400, "You have already redeemed this code")

    user.wallet_balance_paise += p.credit_paise
    p.times_redeemed += 1
    s.add(
        Transaction(
            user_id=user.id,
            kind="topup",
            amount_paise=p.credit_paise,
            status="success",
            note=f"Promo · {p.code}",
        )
    )
    await s.commit()
    return {
        "ok": True,
        "credited_paise": p.credit_paise,
        "new_balance_paise": user.wallet_balance_paise,
    }


# --- Telegram link + notifications -----------------------------------------

import base64
import hashlib
import hmac

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "")
TELEGRAM_LINK_TTL_SECONDS = 600  # link expires 10 min after generation
WEB_PUBLIC_URL = os.environ.get("WEB_PUBLIC_URL", "https://cheetsheet.tech")


def _sign_link_token(user_id: str, expires_at: int) -> str:
    """Token = base64url(user_id|expires_at|hmac). HMAC uses INTERNAL_API_TOKEN
    as the key so it can't be forged without server-side access."""
    msg = f"{user_id}|{expires_at}".encode()
    sig = hmac.new(INTERNAL_API_TOKEN.encode(), msg, hashlib.sha256).hexdigest()[:24]
    raw = f"{user_id}|{expires_at}|{sig}".encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _verify_link_token(token: str) -> str | None:
    """Returns user_id if valid + unexpired, else None."""
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding).decode()
        user_id, exp_str, sig = raw.split("|")
        expires_at = int(exp_str)
    except Exception:
        return None
    if expires_at < int(datetime.now(timezone.utc).timestamp()):
        return None
    msg = f"{user_id}|{expires_at}".encode()
    expected = hmac.new(
        INTERNAL_API_TOKEN.encode(), msg, hashlib.sha256
    ).hexdigest()[:24]
    if not hmac.compare_digest(expected, sig):
        return None
    return user_id


@app.get("/api/telegram/link-url")
async def telegram_link_url(
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Return a t.me deep-link the user can click to bind their Telegram chat
    to this account. Signed and expires in 10 min."""
    if not TELEGRAM_BOT_USERNAME:
        raise HTTPException(503, "Telegram link not configured on server")
    expires_at = int(datetime.now(timezone.utc).timestamp()) + TELEGRAM_LINK_TTL_SECONDS
    token = _sign_link_token(user.id, expires_at)
    url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start=link_{token}"
    return {
        "url": url,
        "expires_in_seconds": TELEGRAM_LINK_TTL_SECONDS,
        "currently_linked": bool(user.telegram_chat_id),
    }


class TelegramLinkRequest(BaseModel):
    token: str
    chat_id: str


@app.post("/api/telegram/link")
async def telegram_link(
    req: TelegramLinkRequest,
    s: AsyncSession = Depends(get_session),
    x_internal_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Called by the bot when a user runs ``/start link_<token>``. Verifies
    the signed token and binds the chat to the user."""
    if not INTERNAL_API_TOKEN or x_internal_token != INTERNAL_API_TOKEN:
        raise HTTPException(401, "missing or invalid internal token")

    raw_token = req.token
    if raw_token.startswith("link_"):
        raw_token = raw_token[5:]
    user_id = _verify_link_token(raw_token)
    if not user_id:
        raise HTTPException(400, "Invalid or expired link token")

    u = await s.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    u.telegram_chat_id = str(req.chat_id)
    await s.commit()
    return {"ok": True, "email": u.email, "name": u.name}


@app.post("/api/telegram/unlink")
async def telegram_unlink(
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Let the user remove the Telegram link from the web app."""
    user.telegram_chat_id = None
    await s.commit()
    return {"ok": True}


def _send_telegram_message(chat_id: str, text: str) -> None:
    """Fire-and-forget Telegram notification. Logs and swallows errors so the
    notification can never break a generation."""
    if not (TELEGRAM_BOT_TOKEN and chat_id):
        return
    import httpx as _httpx
    try:
        r = _httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10.0,
        )
        if r.status_code != 200:
            print(f"[telegram] notify failed: {r.status_code} {r.text[:200]}",
                  flush=True)
    except Exception as exc:
        print(f"[telegram] notify exception: {exc}", flush=True)


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


async def _check_block_rules(
    s: AsyncSession, title: str | None, channel: str | None
) -> None:
    """Raise 403 if the video matches an active block rule. Channel matching
    is case-insensitive exact; keyword matching is case-insensitive substring."""
    rules = (await s.execute(select(BlockRule))).scalars().all()
    title_l = (title or "").lower()
    channel_l = (channel or "").lower()
    for r in rules:
        pat = (r.pattern or "").lower().strip()
        if not pat:
            continue
        if r.kind == "channel" and channel_l and pat == channel_l:
            raise HTTPException(403, f"Channel is blocked: {r.reason or 'policy'}")
        if r.kind == "keyword" and pat in title_l:
            raise HTTPException(
                403, f"Title matches a blocked keyword: {r.reason or 'policy'}"
            )


async def _cost_table(s: AsyncSession) -> dict[str, int]:
    cfg = await app_settings.get_many(
        s, ["cost_paise_per_30min_cheatsheet", "cost_paise_per_30min_book"]
    )
    return {
        "cheatsheet": int(cfg["cost_paise_per_30min_cheatsheet"]),
        "book": int(cfg["cost_paise_per_30min_book"]),
    }


@app.post("/api/preview")
async def preview(
    req: PreviewRequest,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cheap metadata lookup for a YouTube URL — used by the generate UI to
    show a thumbnail + title + duration + cost preview BEFORE the user
    commits to a generation."""
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
            "channel": meta.get("channel") or meta.get("uploader") or "",
            "thumbnail_url": f"https://i.ytimg.com/vi/{meta['id']}/hqdefault.jpg",
        }
        if len(_PREVIEW_CACHE) > 256:
            _PREVIEW_CACHE.clear()
        _PREVIEW_CACHE[req.url] = out

    await _check_block_rules(s, out.get("title"), out.get("channel"))

    table = await _cost_table(s)
    out["cost_paise"] = {
        "cheatsheet": _calc_cost_paise_for(out["duration_seconds"], "cheatsheet", table),
        "book": _calc_cost_paise_for(out["duration_seconds"], "book", table),
    }
    return out


@app.post("/api/generate")
async def create_generation(
    req: CreateRequest,
    bg: BackgroundTasks,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Accept a job in <50ms and return the id immediately.

    All slow work — metadata fetch, block-rule check, cost calc, atomic wallet
    debit — is deferred to the background worker (``_run_job``). The frontend
    polls ``/api/jobs/{id}`` for status; if pricing or block-rule fails, the
    job lands in ``error`` state with a helpful message instead of blocking
    the user on a spinning POST.
    """
    # Maintenance mode — admins are allowed through.
    if not (user.is_admin or is_admin_email(user.email)):
        if bool(await app_settings.get(s, "maintenance_mode")):
            msg = await app_settings.get(s, "maintenance_message")
            raise HTTPException(503, str(msg))

    # Per-user rate limit (last 1 hour).
    hourly_cap = int(await app_settings.get(s, "max_generations_per_hour_per_user"))
    if hourly_cap > 0:
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = (
            await s.execute(
                select(func.count(Generation.id))
                .where(Generation.user_id == user.id)
                .where(Generation.created_at >= hour_ago)
            )
        ).scalar_one()
        if int(recent) >= hourly_cap:
            raise HTTPException(
                429,
                f"Rate limit: max {hourly_cap} generations per hour. Try later.",
            )

    gen = Generation(
        id=uuid.uuid4().hex,
        user_id=user.id,
        kind=req.kind,
        url=req.url,
        status="queued",
        progress=0.0,
        was_free=False,   # placeholder — re-evaluated inside _run_job
        cost_paise=0,     # placeholder — atomic debit happens in _run_job
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


# --- wallet -----------------------------------------------------------------

class TopupOrderRequest(BaseModel):
    amount_paise: int = Field(..., ge=100)  # absolute floor; real min in settings


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
    min_topup = int(await app_settings.get(s, "min_topup_paise"))
    if req.amount_paise < min_topup:
        raise HTTPException(
            400, f"Minimum top-up is ₹{min_topup / 100:.0f}"
        )
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


def _check_block_rules_sync(
    s: Any, title: str | None, channel: str | None
) -> None:
    """Sync equivalent of `_check_block_rules` for the worker thread.

    Raises ``ValueError`` instead of ``HTTPException`` since this runs after
    the request has already returned 200. The exception bubbles up to the
    ``_run_job`` ``except`` block which marks the row as ``error``.
    """
    rules = s.execute(select(BlockRule)).scalars().all()
    title_l = (title or "").lower()
    channel_l = (channel or "").lower()
    for r in rules:
        pat = (r.pattern or "").lower().strip()
        if not pat:
            continue
        if r.kind == "channel" and channel_l and pat == channel_l:
            raise ValueError(f"Channel is blocked: {r.reason or 'policy'}")
        if r.kind == "keyword" and pat in title_l:
            raise ValueError(
                f"Title matches a blocked keyword: {r.reason or 'policy'}"
            )


def _daily_used_sync(s: Any, user_id: str) -> tuple[int, int]:
    """Sync equivalent of `_daily_used`."""
    start = _ist_day_start_utc()
    result = s.execute(
        select(Generation.kind, func.count())
        .where(Generation.user_id == user_id)
        .where(Generation.created_at >= start)
        .where(Generation.was_free.is_(True))
        .where(Generation.status != "error")
        .group_by(Generation.kind)
    )
    counts = {kind: int(c) for kind, c in result.all()}
    return counts.get("cheatsheet", 0), counts.get("book", 0)


def _free_limits_for_sync(user_row: User) -> tuple[int, int]:
    """Sync equivalent of `_free_limits_for`, reading from the cached
    settings module instead of an async DB session."""
    cheats = (
        user_row.daily_cheatsheets_override
        if user_row.daily_cheatsheets_override is not None
        else int(app_settings.get_sync("free_cheatsheets_per_day"))
    )
    books = (
        user_row.daily_books_override
        if user_row.daily_books_override is not None
        else int(app_settings.get_sync("free_books_per_day"))
    )
    return cheats, books


def _cost_table_sync() -> dict[str, int]:
    return {
        "cheatsheet": int(app_settings.get_sync("cost_paise_per_30min_cheatsheet")),
        "book": int(app_settings.get_sync("cost_paise_per_30min_book")),
    }


def _price_and_charge(job_id: str, kind: str, duration_seconds: float,
                     title: str | None, channel: str | None) -> None:
    """Run after metadata fetch. Applies block rules, computes cost, and
    performs the atomic wallet debit. On failure, raises an exception so
    `_run_job`'s except block marks the row as error and refunds anything
    we charged (which, on insufficient balance, is nothing)."""
    with SyncSessionLocal() as s:
        _check_block_rules_sync(s, title, channel)

        user_row = s.get(User, _user_id_for_job(s, job_id))
        if user_row is None:
            raise ValueError("user not found")

        free_cheats, free_books = _free_limits_for_sync(user_row)
        cheats_today, books_today = _daily_used_sync(s, user_row.id)
        if kind == "cheatsheet":
            within_free = cheats_today < free_cheats
        else:
            within_free = books_today < free_books

        if user_row.bypass_paid or within_free:
            cost_paise = 0
            was_free = True
        else:
            table = _cost_table_sync()
            cost_paise = _calc_cost_paise_for(duration_seconds, kind, table)
            # Atomic decrement with balance precondition.
            result = s.execute(
                sa_update(User)
                .where(User.id == user_row.id)
                .where(User.wallet_balance_paise >= cost_paise)
                .values(
                    wallet_balance_paise=User.wallet_balance_paise - cost_paise
                )
                .returning(User.wallet_balance_paise)
            )
            new_balance = result.scalar_one_or_none()
            if new_balance is None:
                raise ValueError(
                    f"Insufficient wallet balance. "
                    f"This {kind} would cost ₹{cost_paise / 100:.0f}; "
                    f"top up at /wallet."
                )
            was_free = False
            s.add(
                Transaction(
                    user_id=user_row.id,
                    kind="spend",
                    amount_paise=-cost_paise,
                    generation_id=job_id,
                    status="success",
                    note=f"{kind} · {math.ceil(duration_seconds / 60)}min",
                )
            )

        gen = s.get(Generation, job_id)
        if gen:
            gen.cost_paise = cost_paise
            gen.was_free = was_free
        s.commit()


def _user_id_for_job(s: Any, job_id: str) -> str | None:
    gen = s.get(Generation, job_id)
    return gen.user_id if gen else None


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

    # Sync runtime-tunable tech toggles into process env so the pipeline picks
    # them up. We do this per-job since admins can swap providers via /admin.
    for env_key, settings_key in (
        ("AUTHORING_PROVIDER", "authoring_provider"),
        ("WHISPER_BACKEND", "whisper_backend"),
    ):
        val = app_settings.get_sync(settings_key)
        if val:
            os.environ[env_key] = str(val)

    # Look up the kind/url/user from DB (avoids race where user mutated
    # something). The user lookup also pulls the per-user prompt overrides.
    with SyncSessionLocal() as s:
        gen = s.get(Generation, job_id)
        if not gen:
            return
        kind = gen.kind
        url = gen.url
        user_row = s.get(User, gen.user_id)
        custom_prompt_cheat = (
            user_row.custom_prompt_cheatsheet if user_row else None
        )
        custom_prompt_book = user_row.custom_prompt_book if user_row else None

    cost_sink: dict[str, int] = {"tokens_in": 0, "tokens_out": 0}

    try:
        emit("Fetching video metadata", 0.05)
        meta = await asyncio.to_thread(fetch_metadata, url)
        channel = meta.get("channel") or meta.get("uploader") or ""
        _update_sync(
            job_id,
            video_id=meta["id"],
            title=meta["title"],
            duration_seconds=meta["duration"],
            channel=channel,
            thumbnail_url=f"https://i.ytimg.com/vi/{meta['id']}/hqdefault.jpg",
        )

        # Block rules + cost calc + atomic wallet debit. Raises ValueError if
        # the user can't afford or the video is blocked — caught below, marks
        # the row error with the message we set here.
        emit("Reserving wallet credit", 0.08)
        await asyncio.to_thread(
            _price_and_charge,
            job_id,
            kind,
            float(meta["duration"]),
            meta.get("title"),
            channel,
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
                system_override=custom_prompt_cheat,
                cost_sink=cost_sink,
            )
        else:
            md_text = await asyncio.to_thread(
                author_book,
                result["transcript_with_frames"],
                result["frames_index"],
                title_hint=meta["title"],
                duration_seconds=meta["duration"],
                on_progress=lambda m: emit(m, max(progress_state["p"], 0.72)),
                system_override=custom_prompt_book,
                cost_sink=cost_sink,
            )

        md_path = work / "output.md"
        md_path.write_text(md_text, encoding="utf-8")

        emit("Rendering PDF", 0.92)
        pdf_path = work / "output.pdf"
        if kind == "cheatsheet":
            await asyncio.to_thread(build_cheatsheet, md_path, pdf_path, meta["title"])
        else:
            # image_base must be the PARENT of the frames/ dir, because the
            # BOOK_SYSTEM prompt forces the LLM to write `![..](frames/<name>.jpg)`
            # and make_image_flowable resolves to IMAGE_BASE / path. Passing the
            # frames dir itself produced "frames/frames/<name>.jpg" lookups and
            # `[missing image: ...]` placeholders in every book PDF — caught
            # 2026-05-29 from a user-reported PDF. bot/worker.py already does
            # the right thing (`cache.slot(video_id)`); only the API path was
            # off-by-one.
            await asyncio.to_thread(
                build_book,
                md_path,
                pdf_path,
                meta["title"],
                Path(result["frames_dir"]).parent,
                None,
            )

        # Mark done. Daily usage is derived from generations rows so there's
        # no per-user counter to bump here.
        provider = str(app_settings.get_sync("authoring_provider") or "claude_code")
        backend = str(app_settings.get_sync("whisper_backend") or "local")
        tokens_in = int(cost_sink.get("tokens_in", 0))
        tokens_out = int(cost_sink.get("tokens_out", 0))
        llm_cost = _llm_cost_paise(provider, tokens_in, tokens_out)
        transcription_cost = _whisper_cost_paise(backend, float(meta["duration"]))
        notify_chat_id: str | None = None
        notify_title: str = ""
        with SyncSessionLocal() as s:
            gen = s.get(Generation, job_id)
            if gen:
                gen.status = "done"
                gen.step = "done"
                gen.progress = 1.0
                gen.markdown = md_text
                gen.pdf_path = str(pdf_path)
                gen.completed_at = datetime.now(timezone.utc)
                gen.llm_tokens_in = tokens_in
                gen.llm_tokens_out = tokens_out
                gen.llm_cost_paise = llm_cost
                gen.transcription_cost_paise = transcription_cost
                s.commit()
                user_row = s.get(User, gen.user_id)
                notify_chat_id = (
                    user_row.telegram_chat_id if user_row else None
                )
                notify_title = gen.title or "your video"

        if notify_chat_id:
            label = "Cheatsheet" if kind == "cheatsheet" else "Book Notes"
            text = (
                f"*{label} ready* ✓\n"
                f"_{notify_title}_\n\n"
                f"Open: {WEB_PUBLIC_URL}/library"
            )
            await asyncio.to_thread(_send_telegram_message, notify_chat_id, text)

    except Exception as exc:
        # Refund the wallet for paid jobs that fail mid-pipeline.
        notify_chat_id = None
        notify_err = f"{type(exc).__name__}: {exc}"
        with SyncSessionLocal() as s:
            gen = s.get(Generation, job_id)
            if gen:
                gen.status = "error"
                gen.error_message = notify_err
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
                user_row = s.get(User, gen.user_id)
                notify_chat_id = (
                    user_row.telegram_chat_id if user_row else None
                )

        if notify_chat_id:
            short = notify_err[:200]
            await asyncio.to_thread(
                _send_telegram_message,
                notify_chat_id,
                f"*Generation failed* ✗\n`{short}`\n\nWallet auto-refunded if paid.",
            )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)
