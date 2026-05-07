"""SQLAlchemy ORM models for the web app.

Schema is small enough to keep in one file:

    User           one row per signed-in user
    Generation     one row per /api/generate job

Money is stored in **paise** (1 INR = 100 paise) as integers — never floats.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    google_sub: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(255))
    picture_url: Mapped[Optional[str]] = mapped_column(Text)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    free_cheatsheets_used: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    free_books_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wallet_balance_paise: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    generations: Mapped[list["Generation"]] = relationship(
        "Generation", back_populates="user", cascade="all, delete-orphan"
    )


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # cheatsheet | book
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Video metadata (filled in once yt-dlp returns)
    video_id: Mapped[Optional[str]] = mapped_column(String(20))
    title: Mapped[Optional[str]] = mapped_column(Text)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    channel: Mapped[Optional[str]] = mapped_column(String(255))
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text)

    # Live state
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued"
    )  # queued | running | done | error
    step: Mapped[Optional[str]] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Final outputs
    pdf_path: Mapped[Optional[str]] = mapped_column(Text)
    markdown: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Billing
    cost_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    was_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User", back_populates="generations")


# Indexes
Index("ix_generations_user_created", Generation.user_id, Generation.created_at.desc())
Index("ix_generations_status", Generation.status)
