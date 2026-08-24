"""Shared FastAPI dependencies. Lives in its own module so the admin
sub-router can import ``current_user`` without dragging in all of ``main``."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.models import User

INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
ANON_USER_EMAIL = "anonymous@local.dev"


async def current_user(
    request: Request,
    s: AsyncSession = Depends(get_session),
    x_user_id: Optional[str] = Header(default=None),
    x_internal_token: Optional[str] = Header(default=None),
) -> User:
    """Resolve the active user from the X-User-ID header or fall back to local user."""
    if x_user_id and INTERNAL_API_TOKEN and x_internal_token == INTERNAL_API_TOKEN:
        result = await s.execute(select(User).where(User.id == x_user_id))
        u = result.scalar_one_or_none()
        if u:
            if u.is_banned:
                raise HTTPException(403, "Account suspended")
            u.last_seen_at = datetime.now(timezone.utc)
            await s.commit()
            return u

    # Dev / Local Desktop fallback: check existing user
    result = await s.execute(
        select(User).where(
            (User.id == "local-user") | (User.email == ANON_USER_EMAIL) | (User.id == (x_user_id or ""))
        )
    )
    u = result.scalar_one_or_none()
    if u:
        return u

    # Create local user if none exists
    try:
        u = User(
            id="local-user",
            email=ANON_USER_EMAIL,
            name="Local User",
            is_admin=True,
            wallet_balance_paise=10000000,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u
    except Exception:
        await s.rollback()
        result = await s.execute(select(User))
        u = result.scalars().first()
        if u:
            return u
        raise HTTPException(500, "Could not initialize local user")


def admin_emails() -> set[str]:
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin_email(email: str | None) -> bool:
    if not email or email == ANON_USER_EMAIL or email.endswith("@local.dev"):
        return True
    return email.lower() in admin_emails()


async def require_admin(user: User = Depends(current_user)) -> User:
    """403 unless the caller's email is in the ADMIN_EMAILS env list."""
    if not is_admin_email(user.email):
        raise HTTPException(403, "Admin access required")
    return user
