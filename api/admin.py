"""Admin/developer endpoints. Mounted at ``/api/admin/*`` from main.

Auth model: a request is treated as admin when the resolved user's email
appears in the comma-separated ``ADMIN_EMAILS`` environment variable. We
deliberately don't grant admin via DB ``is_admin`` alone — making access
env-driven means rotating who has the keys doesn't require a DB write.

Every state-changing endpoint writes one ``AuditLog`` row before the
session is committed.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.cookie_files import (
    MAX_COOKIE_FILE_BYTES,
    CookieFileTooLarge,
    CookieFileValidationError,
    atomic_write_private,
    validate_cookie_file,
)
from api.db import get_session
from api.deps import is_admin_email, require_admin
from api.youtube_urls import validate_public_youtube_url
from api.models import (
    AppSetting,
    AuditLog,
    BlockRule,
    Broadcast,
    Generation,
    PromoCode,
    PromoRedemption,
    Transaction,
    User,
)
from api import settings as app_settings


router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- audit -----------------------------------------------------------------

async def _audit(
    s: AsyncSession,
    admin: User,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict | None = None,
) -> None:
    s.add(
        AuditLog(
            admin_email=admin.email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=json.dumps(payload, default=str) if payload else None,
        )
    )


# --- settings --------------------------------------------------------------

@router.get("/settings")
async def get_settings(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    return await app_settings.get_all(s)


class SettingsUpdate(BaseModel):
    free_cheatsheets_per_day: Optional[int] = Field(None, ge=0, le=100)
    free_books_per_day: Optional[int] = Field(None, ge=0, le=100)
    cost_paise_per_30min_cheatsheet: Optional[int] = Field(None, ge=0)
    cost_paise_per_30min_book: Optional[int] = Field(None, ge=0)
    min_topup_paise: Optional[int] = Field(None, ge=100)
    maintenance_mode: Optional[bool] = None
    maintenance_message: Optional[str] = None
    authoring_provider: Optional[Literal["claude_code", "groq", "openai", "anthropic"]] = None
    whisper_backend: Optional[Literal["local", "groq", "openai"]] = None
    max_generations_per_hour_per_user: Optional[int] = Field(None, ge=0)
    referral_credit_paise: Optional[int] = Field(None, ge=0)


@router.put("/settings")
async def update_settings(
    req: SettingsUpdate,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    before = await app_settings.get_all(s)
    for key, new_val in req.model_dump(exclude_unset=True).items():
        if new_val is None:
            continue
        if before.get(key) != new_val:
            changed[key] = {"from": before.get(key), "to": new_val}
            await app_settings.set_value(s, key, new_val, updated_by=admin.email)
    if changed:
        await _audit(s, admin, "settings.update", "settings", None, changed)
    await s.commit()
    return await app_settings.get_all(s)


# --- users -----------------------------------------------------------------

@router.get("/users")
async def list_users(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    q: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    base = select(User)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(
            or_(func.lower(User.email).like(like), func.lower(User.name).like(like))
        )
    total = (
        await s.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await s.execute(
            base.order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    # Daily usage + lifetime counts per user, computed in two grouped queries.
    user_ids = [u.id for u in rows]
    today_start = _ist_day_start_utc()
    today_rows = (
        await s.execute(
            select(Generation.user_id, Generation.kind, func.count())
            .where(Generation.user_id.in_(user_ids))
            .where(Generation.created_at >= today_start)
            .where(Generation.status != "error")
            .group_by(Generation.user_id, Generation.kind)
        )
        if user_ids
        else None
    )
    today_map: dict[tuple[str, str], int] = (
        {(uid, kind): int(c) for uid, kind, c in today_rows.all()} if today_rows else {}
    )

    total_rows = (
        await s.execute(
            select(Generation.user_id, func.count())
            .where(Generation.user_id.in_(user_ids))
            .group_by(Generation.user_id)
        )
        if user_ids
        else None
    )
    total_map: dict[str, int] = (
        {uid: int(c) for uid, c in total_rows.all()} if total_rows else {}
    )

    return {
        "total": int(total),
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "picture_url": u.picture_url,
                "wallet_balance_paise": u.wallet_balance_paise,
                "is_admin": is_admin_email(u.email),
                "is_banned": u.is_banned,
                "bypass_paid": u.bypass_paid,
                "daily_cheatsheets_override": u.daily_cheatsheets_override,
                "daily_books_override": u.daily_books_override,
                "today_cheatsheets": today_map.get((u.id, "cheatsheet"), 0),
                "today_books": today_map.get((u.id, "book"), 0),
                "total_generations": total_map.get(u.id, 0),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_seen_at": (
                    u.last_seen_at.isoformat() if u.last_seen_at else None
                ),
                "referral_code": u.referral_code,
            }
            for u in rows
        ],
    }


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    u = await s.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")

    txs = (
        await s.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    gens = (
        await s.execute(
            select(Generation)
            .where(Generation.user_id == user_id)
            .order_by(Generation.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    audit = (
        await s.execute(
            select(AuditLog)
            .where(and_(AuditLog.target_type == "user", AuditLog.target_id == user_id))
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        )
    ).scalars().all()

    return {
        "user": {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "picture_url": u.picture_url,
            "wallet_balance_paise": u.wallet_balance_paise,
            "is_admin": is_admin_email(u.email),
            "is_banned": u.is_banned,
            "bypass_paid": u.bypass_paid,
            "daily_cheatsheets_override": u.daily_cheatsheets_override,
            "daily_books_override": u.daily_books_override,
            "custom_prompt_cheatsheet": u.custom_prompt_cheatsheet,
            "custom_prompt_book": u.custom_prompt_book,
            "referral_code": u.referral_code,
            "referred_by_code": u.referred_by_code,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
        },
        "transactions": [
            {
                "id": tx.id,
                "kind": tx.kind,
                "amount_paise": tx.amount_paise,
                "status": tx.status,
                "note": tx.note,
                "generation_id": tx.generation_id,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx in txs
        ],
        "generations": [
            {
                "id": g.id,
                "kind": g.kind,
                "status": g.status,
                "title": g.title,
                "duration_seconds": g.duration_seconds,
                "cost_paise": g.cost_paise,
                "was_free": g.was_free,
                "error_message": g.error_message,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in gens
        ],
        "audit": [
            {
                "id": a.id,
                "admin_email": a.admin_email,
                "action": a.action,
                "payload": json.loads(a.payload_json) if a.payload_json else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in audit
        ],
    }


class UserUpdate(BaseModel):
    daily_cheatsheets_override: Optional[int] = Field(None, ge=0, le=10000)
    daily_books_override: Optional[int] = Field(None, ge=0, le=10000)
    bypass_paid: Optional[bool] = None
    is_banned: Optional[bool] = None
    custom_prompt_cheatsheet: Optional[str] = None
    custom_prompt_book: Optional[str] = None
    # Special sentinel: pass null in JSON to clear the override.
    clear_cheatsheets_override: Optional[bool] = None
    clear_books_override: Optional[bool] = None
    clear_custom_prompt_cheatsheet: Optional[bool] = None
    clear_custom_prompt_book: Optional[bool] = None


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdate,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    u = await s.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")

    changes: dict[str, Any] = {}

    def maybe_set(field: str, value: Any) -> None:
        current = getattr(u, field)
        if current != value:
            changes[field] = {"from": current, "to": value}
            setattr(u, field, value)

    if req.daily_cheatsheets_override is not None:
        maybe_set("daily_cheatsheets_override", req.daily_cheatsheets_override)
    if req.clear_cheatsheets_override:
        maybe_set("daily_cheatsheets_override", None)
    if req.daily_books_override is not None:
        maybe_set("daily_books_override", req.daily_books_override)
    if req.clear_books_override:
        maybe_set("daily_books_override", None)
    if req.bypass_paid is not None:
        maybe_set("bypass_paid", req.bypass_paid)
    if req.is_banned is not None:
        maybe_set("is_banned", req.is_banned)
    if req.custom_prompt_cheatsheet is not None:
        maybe_set("custom_prompt_cheatsheet", req.custom_prompt_cheatsheet)
    if req.clear_custom_prompt_cheatsheet:
        maybe_set("custom_prompt_cheatsheet", None)
    if req.custom_prompt_book is not None:
        maybe_set("custom_prompt_book", req.custom_prompt_book)
    if req.clear_custom_prompt_book:
        maybe_set("custom_prompt_book", None)

    if changes:
        await _audit(s, admin, "user.update", "user", user_id, changes)
    await s.commit()
    return {"ok": True, "changes": changes}


class CreditRequest(BaseModel):
    amount_paise: int = Field(..., description="Positive = credit, negative = debit.")
    reason: str = Field(..., min_length=1, max_length=200)


@router.post("/users/{user_id}/credit")
async def credit_user(
    user_id: str,
    req: CreditRequest,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    if req.amount_paise == 0:
        raise HTTPException(400, "Amount must be non-zero")
    u = await s.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    new_balance = u.wallet_balance_paise + req.amount_paise
    if new_balance < 0:
        raise HTTPException(400, "Would make wallet negative")
    u.wallet_balance_paise = new_balance
    s.add(
        Transaction(
            user_id=u.id,
            kind="topup" if req.amount_paise > 0 else "spend",
            amount_paise=req.amount_paise,
            status="success",
            note=f"Admin · {req.reason}",
        )
    )
    await _audit(
        s,
        admin,
        "user.credit",
        "user",
        user_id,
        {"amount_paise": req.amount_paise, "reason": req.reason, "new_balance": new_balance},
    )
    await s.commit()
    return {"ok": True, "new_balance_paise": new_balance}


# --- generations -----------------------------------------------------------

@router.get("/generations")
async def list_generations(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    status: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    base = select(Generation, User.email).join(User, User.id == Generation.user_id)
    if status:
        base = base.where(Generation.status == status)
    total = (
        await s.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await s.execute(
            base.order_by(Generation.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return {
        "total": int(total),
        "generations": [
            {
                "id": g.id,
                "user_id": g.user_id,
                "user_email": email,
                "kind": g.kind,
                "url": g.url,
                "video_id": g.video_id,
                "title": g.title,
                "channel": g.channel,
                "duration_seconds": g.duration_seconds,
                "status": g.status,
                "step": g.step,
                "progress": g.progress,
                "cost_paise": g.cost_paise,
                "was_free": g.was_free,
                "llm_cost_paise": g.llm_cost_paise,
                "transcription_cost_paise": g.transcription_cost_paise,
                "error_message": g.error_message,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "completed_at": (
                    g.completed_at.isoformat() if g.completed_at else None
                ),
            }
            for g, email in rows
        ],
    }


@router.post("/generations/{gen_id}/retry")
async def retry_generation(
    gen_id: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    from api.main import _run_job  # noqa: WPS433
    import asyncio

    g = await s.get(Generation, gen_id)
    if not g:
        raise HTTPException(404, "Generation not found")
    if g.status not in ("error", "done"):
        raise HTTPException(400, f"Cannot retry — status is {g.status}")

    g.status = "queued"
    g.step = "Re-queued by admin"
    g.progress = 0.0
    g.error_message = None
    g.completed_at = None
    await _audit(s, admin, "generation.retry", "generation", gen_id, None)
    await s.commit()

    asyncio.create_task(_run_job(gen_id))
    return {"ok": True}


# --- audit log -------------------------------------------------------------

@router.get("/audit")
async def audit_log(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    total = (await s.execute(select(func.count(AuditLog.id)))).scalar_one()
    rows = (
        await s.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "total": int(total),
        "entries": [
            {
                "id": a.id,
                "admin_email": a.admin_email,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "payload": json.loads(a.payload_json) if a.payload_json else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ],
    }


# --- overview / dashboard --------------------------------------------------

def _ist_day_start_utc() -> datetime:
    now_utc = datetime.now(timezone.utc)
    ist = now_utc + timedelta(hours=5, minutes=30)
    ist_day_start = ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return ist_day_start - timedelta(hours=5, minutes=30)


@router.get("/overview")
async def overview(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today_start = _ist_day_start_utc()
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    user_total = (await s.execute(select(func.count(User.id)))).scalar_one()
    user_today = (
        await s.execute(
            select(func.count(User.id)).where(User.created_at >= today_start)
        )
    ).scalar_one()
    user_week = (
        await s.execute(
            select(func.count(User.id)).where(User.created_at >= week_start)
        )
    ).scalar_one()

    gen_today = (
        await s.execute(
            select(func.count(Generation.id)).where(Generation.created_at >= today_start)
        )
    ).scalar_one()
    gen_week = (
        await s.execute(
            select(func.count(Generation.id)).where(Generation.created_at >= week_start)
        )
    ).scalar_one()
    gen_failed_week = (
        await s.execute(
            select(func.count(Generation.id))
            .where(Generation.created_at >= week_start)
            .where(Generation.status == "error")
        )
    ).scalar_one()
    gen_running = (
        await s.execute(
            select(func.count(Generation.id)).where(
                Generation.status.in_(("queued", "running"))
            )
        )
    ).scalar_one()

    rev_today = (
        await s.execute(
            select(func.coalesce(func.sum(Transaction.amount_paise), 0))
            .where(Transaction.kind == "topup")
            .where(Transaction.status == "success")
            .where(Transaction.created_at >= today_start)
        )
    ).scalar_one()
    rev_week = (
        await s.execute(
            select(func.coalesce(func.sum(Transaction.amount_paise), 0))
            .where(Transaction.kind == "topup")
            .where(Transaction.status == "success")
            .where(Transaction.created_at >= week_start)
        )
    ).scalar_one()
    rev_month = (
        await s.execute(
            select(func.coalesce(func.sum(Transaction.amount_paise), 0))
            .where(Transaction.kind == "topup")
            .where(Transaction.status == "success")
            .where(Transaction.created_at >= month_start)
        )
    ).scalar_one()
    wallet_total = (
        await s.execute(
            select(func.coalesce(func.sum(User.wallet_balance_paise), 0))
        )
    ).scalar_one()

    # Per-day generation counts for the last 30 days (used for the chart).
    by_day_rows = (
        await s.execute(
            select(
                func.date(Generation.created_at).label("d"),
                Generation.kind,
                func.count(),
            )
            .where(Generation.created_at >= month_start)
            .group_by("d", Generation.kind)
            .order_by("d")
        )
    ).all()
    series: dict[str, dict[str, int]] = {}
    for d, kind, count in by_day_rows:
        key = str(d)
        series.setdefault(key, {"cheatsheet": 0, "book": 0})
        series[key][kind] = int(count)

    return {
        "users": {"total": int(user_total), "today": int(user_today), "week": int(user_week)},
        "generations": {
            "today": int(gen_today),
            "week": int(gen_week),
            "failed_week": int(gen_failed_week),
            "running": int(gen_running),
        },
        "revenue_paise": {
            "today": int(rev_today),
            "week": int(rev_week),
            "month": int(rev_month),
        },
        "wallet_outstanding_paise": int(wallet_total),
        "daily_series": [
            {
                "date": d,
                "cheatsheet": series[d]["cheatsheet"],
                "book": series[d]["book"],
            }
            for d in sorted(series.keys())
        ],
    }


# --- disk / db usage -------------------------------------------------------

@router.get("/health/storage")
async def storage_health(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    from api.main import WORK_ROOT  # noqa: WPS433

    # Disk for the work dir.
    if WORK_ROOT.exists():
        total, used, free = shutil.disk_usage(WORK_ROOT)
        work_size = 0
        for path in WORK_ROOT.rglob("*"):
            if path.is_file():
                try:
                    work_size += path.stat().st_size
                except OSError:
                    pass
    else:
        total = used = free = work_size = 0

    user_count = (await s.execute(select(func.count(User.id)))).scalar_one()
    gen_count = (await s.execute(select(func.count(Generation.id)))).scalar_one()
    tx_count = (await s.execute(select(func.count(Transaction.id)))).scalar_one()
    audit_count = (await s.execute(select(func.count(AuditLog.id)))).scalar_one()

    return {
        "disk": {
            "total_bytes": int(total),
            "used_bytes": int(used),
            "free_bytes": int(free),
            "work_dir_bytes": int(work_size),
        },
        "rows": {
            "users": int(user_count),
            "generations": int(gen_count),
            "transactions": int(tx_count),
            "audit_log": int(audit_count),
        },
    }


# --- yt-dlp cookies refresh ------------------------------------------------

class CookiesUpload(BaseModel):
    cookies_txt: str


def _cookies_target() -> Path:
    configured = os.environ.get("YT_COOKIES_PATH", "").strip()
    if configured:
        return Path(configured)
    from api.main import PROJECT_ROOT  # noqa: WPS433

    return PROJECT_ROOT / "cookies.txt"


@router.post("/cookies")
async def upload_cookies(
    req: CookiesUpload,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    target = _cookies_target()
    try:
        summary = validate_cookie_file(req.cookies_txt)
    except CookieFileTooLarge as exc:
        raise HTTPException(413, str(exc)) from None
    except CookieFileValidationError as exc:
        raise HTTPException(400, str(exc)) from None

    try:
        atomic_write_private(target, summary.normalized_text)
    except OSError:
        raise HTTPException(500, "Could not store cookies securely") from None
    os.environ["YT_COOKIES_PATH"] = str(target)
    await _audit(
        s,
        admin,
        "cookies.upload",
        None,
        None,
        {
            "bytes": summary.size_bytes,
            "cookie_count": summary.cookie_count,
            "youtube_cookie_count": summary.youtube_cookie_count,
        },
    )
    await s.commit()
    return {
        "ok": True,
        "path": str(target),
        "bytes": summary.size_bytes,
        "cookie_count": summary.cookie_count,
        "youtube_cookie_count": summary.youtube_cookie_count,
    }


@router.get("/cookies/status")
async def cookies_status(
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    target = _cookies_target()
    proxy_configured = bool(
        os.environ.get("YTDLP_PROXY_POOL", "").strip()
        or os.environ.get("YTDLP_PROXY_URL", "").strip()
    )
    if not target.exists():
        return {"exists": False, "proxy_configured": proxy_configured}
    try:
        stat = target.stat()
    except OSError:
        return {"exists": False, "proxy_configured": proxy_configured}

    response: dict[str, Any] = {
        "exists": True,
        "proxy_configured": proxy_configured,
        "path": str(target),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
    try:
        if stat.st_size > MAX_COOKIE_FILE_BYTES:
            raise CookieFileTooLarge("Cookies file is too large")
        summary = validate_cookie_file(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, CookieFileValidationError):
        response.update(
            {
                "valid_netscape": False,
                "cookie_count": 0,
                "youtube_cookie_count": 0,
            }
        )
    else:
        response.update(
            {
                "valid_netscape": True,
                "cookie_count": summary.cookie_count,
                "youtube_cookie_count": summary.youtube_cookie_count,
            }
        )
    return response


class YouTubeProbeRequest(BaseModel):
    url: str = Field(..., min_length=20, max_length=2048)


@router.post("/youtube/probe")
async def youtube_probe(
    req: YouTubeProbeRequest,
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Probe the configured YouTube route without exposing private diagnostics."""

    try:
        url = validate_public_youtube_url(req.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    from scripts.transcribe_with_frames import fetch_metadata  # noqa: WPS433
    from scripts.ytdlp_client import YtDlpError, configured_proxies  # noqa: WPS433

    try:
        metadata = await asyncio.to_thread(fetch_metadata, url)
    except YtDlpError as exc:
        raise HTTPException(502, exc.public_message) from None
    except Exception:
        raise HTTPException(
            502, "Could not verify the YouTube download route. Please try again."
        ) from None

    return {
        "ok": True,
        "video_id": metadata["id"],
        "title": metadata["title"],
        "duration_seconds": metadata["duration"],
        "proxy_configured": bool(configured_proxies()),
    }

# --- broadcasts ------------------------------------------------------------

class BroadcastCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    channels: list[Literal["banner", "telegram"]] = Field(default_factory=lambda: ["banner"])
    expires_in_hours: Optional[int] = Field(None, ge=1, le=24 * 30)


@router.get("/broadcasts")
async def list_broadcasts(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    rows = (
        await s.execute(
            select(Broadcast).order_by(Broadcast.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return [
        {
            "id": b.id,
            "title": b.title,
            "body": b.body,
            "channels": b.channels.split(","),
            "active": b.active,
            "expires_at": b.expires_at.isoformat() if b.expires_at else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "created_by": b.created_by,
        }
        for b in rows
    ]


@router.post("/broadcasts")
async def create_broadcast(
    req: BroadcastCreate,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    expires_at = None
    if req.expires_in_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=req.expires_in_hours)
    b = Broadcast(
        title=req.title,
        body=req.body,
        channels=",".join(req.channels),
        expires_at=expires_at,
        created_by=admin.email,
    )
    s.add(b)
    await _audit(
        s,
        admin,
        "broadcast.create",
        "broadcast",
        None,
        {"title": req.title, "channels": req.channels},
    )
    await s.commit()
    await s.refresh(b)

    # Fan-out via Telegram in background if requested.
    if "telegram" in req.channels:
        import asyncio

        asyncio.create_task(_telegram_broadcast(b.id, req.title, req.body))

    return {"id": b.id}


@router.post("/broadcasts/{bid}/deactivate")
async def deactivate_broadcast(
    bid: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    b = await s.get(Broadcast, bid)
    if not b:
        raise HTTPException(404, "Not found")
    b.active = False
    await _audit(s, admin, "broadcast.deactivate", "broadcast", bid, None)
    await s.commit()
    return {"ok": True}


async def _telegram_broadcast(bid: str, title: str, body: str) -> None:
    """Best-effort fan-out to every user with a known Telegram chat. We use
    the bot token from env and hit Telegram directly to avoid pulling the
    whole bot worker into this process."""
    import asyncio

    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return

    # We don't persist per-user Telegram chat IDs yet — fall back to the
    # whitelisted group IDs from env so admins at least get the message.
    chat_ids_raw = os.environ.get("WHITELISTED_GROUP_IDS", "")
    chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]
    if not chat_ids:
        return

    text = f"*{title}*\n\n{body}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        for cid in chat_ids:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": cid,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                )
                await asyncio.sleep(0.1)  # avoid rate-limit
            except Exception:
                continue


# --- promo codes -----------------------------------------------------------

class PromoCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=32)
    credit_paise: int = Field(..., ge=100)
    max_redemptions: int = Field(0, ge=0)
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)


@router.get("/promos")
async def list_promos(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    rows = (
        await s.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
    ).scalars().all()
    return [
        {
            "id": p.id,
            "code": p.code,
            "credit_paise": p.credit_paise,
            "max_redemptions": p.max_redemptions,
            "times_redeemed": p.times_redeemed,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
            "active": p.active,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "created_by": p.created_by,
        }
        for p in rows
    ]


@router.post("/promos")
async def create_promo(
    req: PromoCreate,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    code = req.code.upper().strip()
    if not re.match(r"^[A-Z0-9_-]+$", code):
        raise HTTPException(400, "Code must be alphanumeric (plus _ or -)")
    existing = (
        await s.execute(select(PromoCode).where(PromoCode.code == code))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Code already exists")
    expires_at = None
    if req.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)
    p = PromoCode(
        code=code,
        credit_paise=req.credit_paise,
        max_redemptions=req.max_redemptions,
        expires_at=expires_at,
        created_by=admin.email,
    )
    s.add(p)
    await _audit(
        s,
        admin,
        "promo.create",
        "promo",
        code,
        {"credit_paise": req.credit_paise, "max_redemptions": req.max_redemptions},
    )
    await s.commit()
    await s.refresh(p)
    return {"id": p.id, "code": p.code}


@router.post("/promos/{pid}/deactivate")
async def deactivate_promo(
    pid: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    p = await s.get(PromoCode, pid)
    if not p:
        raise HTTPException(404, "Not found")
    p.active = False
    await _audit(s, admin, "promo.deactivate", "promo", p.code, None)
    await s.commit()
    return {"ok": True}


# --- block rules -----------------------------------------------------------

class BlockCreate(BaseModel):
    kind: Literal["channel", "keyword"]
    pattern: str = Field(..., min_length=1, max_length=255)
    reason: Optional[str] = None


@router.get("/blocks")
async def list_blocks(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    rows = (
        await s.execute(select(BlockRule).order_by(BlockRule.created_at.desc()))
    ).scalars().all()
    return [
        {
            "id": b.id,
            "kind": b.kind,
            "pattern": b.pattern,
            "reason": b.reason,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "created_by": b.created_by,
        }
        for b in rows
    ]


@router.post("/blocks")
async def create_block(
    req: BlockCreate,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    b = BlockRule(
        kind=req.kind,
        pattern=req.pattern.strip(),
        reason=req.reason,
        created_by=admin.email,
    )
    s.add(b)
    await _audit(
        s,
        admin,
        "block.create",
        "block",
        None,
        {"kind": req.kind, "pattern": req.pattern},
    )
    await s.commit()
    await s.refresh(b)
    return {"id": b.id}


@router.delete("/blocks/{bid}")
async def delete_block(
    bid: str,
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    b = await s.get(BlockRule, bid)
    if not b:
        raise HTTPException(404, "Not found")
    await s.delete(b)
    await _audit(s, admin, "block.delete", "block", bid, None)
    await s.commit()
    return {"ok": True}


# --- failed payments (Razorpay reconciliation view) ------------------------

@router.get("/payments/failed")
async def failed_payments(
    s: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = (
        await s.execute(
            select(Transaction, User.email)
            .join(User, User.id == Transaction.user_id)
            .where(Transaction.kind == "topup")
            .where(Transaction.status.in_(("pending", "failed")))
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": tx.id,
            "user_id": tx.user_id,
            "user_email": email,
            "amount_paise": tx.amount_paise,
            "status": tx.status,
            "razorpay_order_id": tx.razorpay_order_id,
            "razorpay_payment_id": tx.razorpay_payment_id,
            "note": tx.note,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }
        for tx, email in rows
    ]
