"""Telegram slash command handlers + whitelist enforcement.

There are two ways to kick off a generation:

  1. Slash command — ``/cheat <url>`` or ``/book <url>``. Power-user path,
     unchanged since the bot's inception.

  2. Inline-keyboard flow — paste a YouTube URL (no command, just the
     link) and the bot replies with [Cheatsheet] [Book Notes] [Refresh]
     buttons. Tap one and the job is queued. Saves typing in mobile chats.
     See ``on_youtube_link`` and ``on_choice_callback`` below.

Both paths funnel through ``_enqueue_url`` which builds the Job and puts
it on ``worker.queue``. The Job dataclass and queue itself are unchanged.
"""
from __future__ import annotations

import os
import re

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from .config import WHITELISTED_GROUP_IDS
from . import worker

URL_RE = re.compile(r"https?://\S+")

# Only fire the inline-button flow on actual YouTube links. Matches:
#   https://youtu.be/<id>
#   https://www.youtube.com/watch?v=<id>
#   https://youtube.com/shorts/<id>
# Tracking-param suffixes (?si=..., &t=..., #...) are allowed because the
# regex doesn't anchor at end-of-string.
YOUTUBE_RE = re.compile(
    r"https?://(?:youtu\.be/|(?:www\.)?youtube\.com/(?:watch\?v=|shorts/))"
    r"[A-Za-z0-9_-]+",
    re.IGNORECASE,
)

# Pull the 11-char video id out of a YouTube URL. Same patterns as above but
# captures the id itself. Used to keep ``callback_data`` short — Telegram
# caps callback_data at 64 bytes; an 11-char id leaves plenty of headroom
# for our "gen:<action>:" prefix.
_VIDEO_ID_RE = re.compile(r"(?:youtu\.be/|v=|/shorts/)([A-Za-z0-9_-]{11})")

INTERNAL_API_BASE = os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:8000")
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")


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


async def _enqueue_url(update: Update, fmt: str, url: str,
                       refresh: bool) -> int:
    """Build a Job for ``url``/``fmt`` and put it on the worker queue.
    Returns the 1-based queue position. Shared by every entry point
    (slash commands AND the inline-keyboard callback)."""
    user = update.effective_user
    chat = update.effective_chat
    job = worker.Job(
        chat_id=chat.id,
        user_id=user.id if user else 0,
        user_name=(user.full_name if user else "unknown"),
        url=url,
        fmt=fmt,
        refresh=refresh,
    )
    return await worker.queue.put(job)


async def _enqueue(update: Update, fmt: str, refresh: bool = False) -> None:
    """Slash-command path. Parse URL from message text, then ``_enqueue_url``."""
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
    position = await _enqueue_url(update, fmt, url, refresh)
    if position > 1:
        await msg.reply_text(
            f"Queued (position {position}).", quote=True)


# === handlers ==============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/start``. With a ``link_<token>`` deep-link argument, bind
    this Telegram chat to the user's cheetsheet.tech account so they
    receive "your cheatsheet is ready" pings."""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return

    args = ctx.args or []
    if args and args[0].startswith("link_"):
        token = args[0][5:]  # strip "link_" prefix
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{INTERNAL_API_BASE}/api/telegram/link",
                    json={"token": token, "chat_id": str(chat.id)},
                    headers={"X-Internal-Token": INTERNAL_API_TOKEN},
                    timeout=10.0,
                )
            if r.status_code == 200:
                data = r.json()
                who = data.get("email") or data.get("name") or "your account"
                await msg.reply_text(
                    f"✓ Linked to {who}.\n\n"
                    "You'll get a ping here when each generation is ready. "
                    "Manage from /wallet on the web app."
                )
            else:
                detail = r.text[:200] if r.text else f"HTTP {r.status_code}"
                await msg.reply_text(
                    f"Couldn't link: {detail}\n\n"
                    "The token may have expired (10-min window). "
                    "Generate a fresh link from /wallet on the web app."
                )
        except Exception as exc:
            await msg.reply_text(f"Couldn't reach the API: {exc}")
        return

    # Bare /start with no deep-link arg.
    await msg.reply_text(
        "Hi! I'm the Cheatsheet bot.\n\n"
        "• Generate notes at https://cheetsheet.tech\n"
        "• Or in an authorised group: /cheat <url> or /book <url>\n"
        "• To get notified here when your web generations finish, "
        "open /wallet on the web app and tap 'Link Telegram'."
    )


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


# === inline-keyboard flow ===================================================

async def on_youtube_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered by any non-command message whose text contains a YouTube URL
    (filter is configured in bot/main.py). Replies with three inline buttons
    so the user can pick a format without typing a slash command.

    The video id is encoded into each button's ``callback_data`` so the bot
    can survive a restart between the URL being posted and the user tapping
    a button — there's no server-side state to lose.
    """
    if await _drop(update):
        return
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    m = YOUTUBE_RE.search(msg.text)
    if not m:
        return
    url = m.group(0)
    id_match = _VIDEO_ID_RE.search(url)
    if not id_match:
        return  # regex matched the URL shape but not the id — bail silently
    vid = id_match.group(1)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📄 Cheatsheet", callback_data=f"gen:cheat:{vid}"),
            InlineKeyboardButton(
                "📕 Book Notes", callback_data=f"gen:book:{vid}"),
        ],
        [
            InlineKeyboardButton(
                "↻ Refresh from scratch", callback_data=f"gen:refresh:{vid}"),
        ],
    ])
    await msg.reply_text(
        "Which format?", reply_markup=keyboard, quote=True)


async def on_choice_callback(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the inline-keyboard buttons we emit from
    :func:`on_youtube_link`. callback_data shape: ``gen:<action>:<video_id>``.

    Actions:
      cheat / book   — enqueue that format, fresh from cache
      refresh        — re-prompt the user for format, but mark the job to
                       bust the cache (turns into rcheat/rbook)
      rcheat / rbook — same as cheat/book but refresh=True
    """
    q = update.callback_query
    if q is None or q.message is None:
        return
    if not _whitelisted(q.message.chat_id):
        await q.answer("Not authorised here.", show_alert=False)
        return
    data = q.data or ""
    try:
        _prefix, action, vid = data.split(":", 2)
    except ValueError:
        await q.answer()
        return
    if _prefix != "gen" or not vid:
        await q.answer()
        return
    url = f"https://youtu.be/{vid}"

    if action == "refresh":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "↻ Cheatsheet (rebuild)",
                    callback_data=f"gen:rcheat:{vid}"),
                InlineKeyboardButton(
                    "↻ Book Notes (rebuild)",
                    callback_data=f"gen:rbook:{vid}"),
            ],
        ])
        await q.answer()
        await q.edit_message_text(
            "Force fresh rebuild — which format?", reply_markup=keyboard)
        return

    fmt_map = {
        "cheat":  ("cheat", False),
        "book":   ("book",  False),
        "rcheat": ("cheat", True),
        "rbook":  ("book",  True),
    }
    pick = fmt_map.get(action)
    if pick is None:
        await q.answer("Unknown choice", show_alert=False)
        return
    fmt, refresh = pick

    position = await _enqueue_url(update, fmt, url, refresh)
    await q.answer(f"Queued · {fmt}{' · refresh' if refresh else ''}")

    # Wipe the keyboard from the prompt and replace it with a record of
    # what was chosen — so the chat history reads naturally and the buttons
    # can't be tapped a second time.
    label = "Cheatsheet" if fmt == "cheat" else "Book Notes"
    suffix = " (rebuild)" if refresh else ""
    body = f"→ {label}{suffix}"
    if position > 1:
        body += f"\nQueue position: {position}"
    try:
        await q.edit_message_text(body)
    except Exception:
        # Same content / unchanged markup / message too old — ignore.
        pass
