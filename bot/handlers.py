"""Telegram slash command handlers + whitelist enforcement."""
from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from .config import WHITELISTED_GROUP_IDS
from . import worker

URL_RE = re.compile(r"https?://\S+")


def _whitelisted(chat_id: int) -> bool:
    return chat_id in WHITELISTED_GROUP_IDS


def _extract_url(text: str) -> str | None:
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(0) if m else None


async def _drop(update: Update) -> bool:
    """Reject if the chat is not whitelisted. Returns True iff dropped."""
    chat = update.effective_chat
    if chat is None:
        return True
    if not _whitelisted(chat.id):
        print(f"[reject] chat_id={chat.id} title={chat.title!r} - not whitelisted")
        return True
    return False


async def _enqueue(update: Update, fmt: str, refresh: bool = False) -> None:
    msg = update.effective_message
    if msg is None:
        return
    text = (msg.text or "").strip()
    # Strip the slash command itself
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        text = parts[1] if len(parts) > 1 else ""
    url = _extract_url(text)
    if not url:
        await msg.reply_text(
            f"Usage: /{fmt} <youtube-url>", quote=True)
        return

    user = update.effective_user
    job = worker.Job(
        chat_id=update.effective_chat.id,
        user_id=user.id if user else 0,
        user_name=(user.full_name if user else "unknown"),
        url=url,
        fmt=fmt,
        refresh=refresh,
    )
    position = await worker.queue.put(job)
    if position > 1:
        await msg.reply_text(
            f"Queued (position {position}).", quote=True)


# === handlers ==============================================================

async def cmd_cheat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _drop(update):
        return
    await _enqueue(update, fmt="cheat", refresh=False)


async def cmd_book(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _drop(update):
        return
    await _enqueue(update, fmt="book", refresh=False)


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _drop(update):
        return
    text = (update.effective_message.text or "")
    fmt = "book" if "/book" in text else "cheat"
    await _enqueue(update, fmt=fmt, refresh=True)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _drop(update):
        return
    s = worker.queue.status()
    if s["current"] is None and not s["queued"]:
        await update.effective_message.reply_text("Idle. No jobs running.")
        return
    lines = []
    if s["current"]:
        cur = s["current"]
        lines.append(f"Running: /{cur.fmt} {cur.url} (by {cur.user_name})")
    for i, j in enumerate(s["queued"], 1):
        lines.append(f"  {i}. /{j.fmt} {j.url} (by {j.user_name})")
    await update.effective_message.reply_text("\n".join(lines))
