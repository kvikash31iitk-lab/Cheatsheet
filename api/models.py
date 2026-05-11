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

    # Admin overrides. Null = use global setting from AppSettings.
    daily_cheatsheets_override: Mapped[Optional[int]] = mapped_column(Integer)
    daily_books_override: Mapped[Optional[int]] = mapped_column(Integer)
    bypass_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_prompt_cheatsheet: Mapped[Optional[str]] = mapped_column(Text)
    custom_prompt_book: Mapped[Optional[str]] = mapped_column(Text)

    # Referral system. ``referral_code`` is what *this* user shares;
    # ``referred_by_code`` is the code they signed up under (if any).
    referral_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True)
    referred_by_code: Mapped[Optional[str]] = mapped_column(String(16))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    generations: Mapped[list["Generation"]] = relationship(
        "Generation", back_populates="user", cascade="all, delete-orphan"
    )


class Transaction(Base):
    """Wallet ledger entry. ``amount_paise`` is positive for credits
    (top-ups, refunds) and negative for debits (spends)."""

    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # topup | spend | refund

    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)

    # For spend/refund: which generation this relates to.
    generation_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("generations.id", ondelete="SET NULL")
    )

    # For topups: Razorpay identifiers.
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success"
    )  # pending | success | failed
    note: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
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

    # Cost tracking (admin observability — what we spent on LLM + transcription).
    llm_tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_cost_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transcription_cost_paise: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User", back_populates="generations")


class AppSetting(Base):
    """Single source of truth for runtime-tunable config. Read with the cached
    settings helper in `api.settings`. Admins write through `/api/admin/settings`.

    Value is stored as JSON-encoded text so booleans, numbers, strings, and
    small lists all round-trip cleanly.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(320))  # admin email


class AuditLog(Base):
    """Append-only log of every admin action."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    admin_email: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(32))  # user | settings | promo | broadcast
    target_id: Mapped[Optional[str]] = mapped_column(String(64))
    payload_json: Mapped[Optional[str]] = mapped_column(Text)  # before/after snapshot
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class PromoCode(Base):
    """Redeemable promo code. Credits the redeemer's wallet by ``credit_paise``
    and counts toward a global ``max_redemptions`` cap (0 = unlimited)."""

    __tablename__ = "promo_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    credit_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    max_redemptions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    times_redeemed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(320))


class PromoRedemption(Base):
    """Tracks who redeemed which promo code, so each user can only use a given
    code once."""

    __tablename__ = "promo_redemptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    promo_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    credit_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Broadcast(Base):
    """Banner / push message sent by admin to users."""

    __tablename__ = "broadcasts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[str] = mapped_column(
        String(64), nullable=False, default="banner"
    )  # comma-separated: banner,telegram
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(320))


class BlockRule(Base):
    """Content moderation rules. ``kind`` is ``channel`` (match channel name
    case-insensitive) or ``keyword`` (match against video title)."""

    __tablename__ = "block_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # channel | keyword
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(320))


# Indexes
Index("ix_generations_user_created", Generation.user_id, Generation.created_at.desc())
Index("ix_generations_status", Generation.status)
Index("ix_generations_created", Generation.created_at.desc())
Index("ix_transactions_user_created", Transaction.user_id, Transaction.created_at.desc())
Index("ix_users_created", User.created_at.desc())
Index("ix_audit_log_created", AuditLog.created_at.desc())
Index("ix_audit_log_target", AuditLog.target_type, AuditLog.target_id)
Index("ix_promo_redemptions_user", PromoRedemption.user_id)
Index("ix_promo_redemptions_promo", PromoRedemption.promo_id)
