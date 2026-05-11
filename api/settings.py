"""Runtime-tunable configuration backed by the ``app_settings`` table.

Reads go through a 60-second in-process cache so the hot path (every
``/api/generate``, ``/api/me``, etc.) doesn't hit the DB. Writes invalidate
the cache and bump the per-key timestamp.

Defaults live in ``DEFAULTS`` — any key not yet stored returns the default,
which means a fresh DB just works without seeding.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import SyncSessionLocal
from api.models import AppSetting

# Default values. Update these when adding a new setting key.
DEFAULTS: dict[str, Any] = {
    # Free tier
    "free_cheatsheets_per_day": 3,
    "free_books_per_day": 1,
    # Pricing — paise per 30-minute slab
    "cost_paise_per_30min_cheatsheet": 100,
    "cost_paise_per_30min_book": 200,
    "min_topup_paise": 100 * 100,  # ₹100
    # Ops / maintenance
    "maintenance_mode": False,
    "maintenance_message": "Generation is paused for maintenance — back shortly.",
    # Tech toggles (read by the pipeline at job start)
    "authoring_provider": "claude_code",  # claude_code | groq | openai | anthropic
    "whisper_backend": "local",  # local | groq | openai
    # Rate limits (0 = unlimited)
    "max_generations_per_hour_per_user": 0,
    # Referral reward (paise credited to both inviter and invitee on signup)
    "referral_credit_paise": 100,
}

_CACHE_TTL_SECONDS = 60.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def _encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _decode(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return fallback


def get_sync(key: str) -> Any:
    """Synchronous getter — used by the pipeline worker thread."""
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    default = DEFAULTS.get(key)
    with SyncSessionLocal() as s:
        row = s.get(AppSetting, key)
        if row is None:
            value = default
        else:
            value = _decode(row.value_json, default)

    with _lock:
        _cache[key] = (now, value)
    return value


async def get(s: AsyncSession, key: str) -> Any:
    """Async getter — used inside request handlers."""
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    default = DEFAULTS.get(key)
    row = await s.get(AppSetting, key)
    value = default if row is None else _decode(row.value_json, default)
    with _lock:
        _cache[key] = (now, value)
    return value


async def get_many(s: AsyncSession, keys: list[str]) -> dict[str, Any]:
    """Bulk getter that issues a single query when keys aren't cached."""
    out: dict[str, Any] = {}
    missing: list[str] = []
    now = time.time()
    for k in keys:
        cached = _cache.get(k)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            out[k] = cached[1]
        else:
            missing.append(k)

    if missing:
        rows = (
            await s.execute(select(AppSetting).where(AppSetting.key.in_(missing)))
        ).scalars().all()
        present = {row.key: row for row in rows}
        with _lock:
            for k in missing:
                default = DEFAULTS.get(k)
                row = present.get(k)
                value = default if row is None else _decode(row.value_json, default)
                _cache[k] = (now, value)
                out[k] = value
    return out


async def set_value(
    s: AsyncSession,
    key: str,
    value: Any,
    *,
    updated_by: str | None = None,
) -> None:
    """Upsert one setting. Invalidates the per-key cache."""
    row = await s.get(AppSetting, key)
    if row is None:
        s.add(
            AppSetting(
                key=key, value_json=_encode(value), updated_by=updated_by
            )
        )
    else:
        row.value_json = _encode(value)
        row.updated_by = updated_by
    invalidate(key)


def invalidate(key: str | None = None) -> None:
    """Drop one key, or the whole cache when called with no argument."""
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


async def get_all(s: AsyncSession) -> dict[str, Any]:
    """Return every known setting merged with defaults — used by the admin UI."""
    rows = (await s.execute(select(AppSetting))).scalars().all()
    stored = {r.key: _decode(r.value_json, DEFAULTS.get(r.key)) for r in rows}
    return {**DEFAULTS, **stored}
