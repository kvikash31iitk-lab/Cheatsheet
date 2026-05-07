"""Database engine + session factory.

DATABASE_URL examples:
  - sqlite+aiosqlite:///./web_work/app.db        (local dev)
  - postgresql+asyncpg://user:pass@host:5432/db  (production)

Both share the same SQLAlchemy 2.x async API, so models and queries don't
need to know which backend is in use.

A small synchronous engine (``sync_engine``) is also exposed so the worker
thread that runs the pipeline can write progress updates without crossing
the async boundary on every tick.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{PROJECT_ROOT / 'web_work' / 'app.db'}",
)


def _sync_url(async_url: str) -> str:
    """Convert an async URL to its sync equivalent for the worker thread."""
    return (
        async_url.replace("+asyncpg", "+psycopg")
        .replace("+aiosqlite", "")
        .replace("postgresql://", "postgresql+psycopg://")
    )


class Base(DeclarativeBase):
    """Common declarative base."""


# Async engine — used by FastAPI request handlers.
async_engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


# Sync engine — used by the pipeline worker thread to push progress updates.
# Falls back to the same SQLite/Postgres file via the sync driver. We default
# to using the standard ``sqlite3`` and ``psycopg`` drivers when sync.
sync_engine = create_engine(_sync_url(DATABASE_URL), echo=False, future=True)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
