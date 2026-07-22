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
from pathlib import Path

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from .config import WHITELISTED_GROUP_IDS
from . import cache, worker


# === feature-toggle encoding ===============================================
# The opt-in PDF features are exposed in the bot as a second-step inline
# keyboard. Telegram caps callback_data at 64 bytes, so we encode the
# selection as a bitmask (one bit per feature in cache.FEATURE_ORDER) and
# pack it into the callback string as a hex digit. With 5 features we fit
# easily — worst-case callback_data ends up around 25 bytes.
#
# Wire format (all prefixed with `gen:` so the existing CallbackQueryHandler
# pattern still catches them):
#   gen:cheat:<vid>                — open toggle screen for cheat
#   gen:book:<vid>                 — open toggle screen for book
#   gen:rcheat:<vid>               — open toggle screen for cheat + refresh
#   gen:rbook:<vid>                — open toggle screen for book + refresh
#   gen:tog:<fmt>:<vid>:<mask>:<b> — flip bit <b> in <mask>
#   gen:go:<fmt>:<vid>:<mask>      — submit with the decoded features
#
# <fmt> is a 1-2 char code so the callback data stays under 64B:
#   c = cheat, cr = cheat+refresh, b = book, br = book+refresh
_FMT_CODE: dict[tuple[str, bool], str] = {
    ("cheat", False): "c",
    ("cheat", True):  "cr",
    ("book",  False): "b",
    ("book",  True):  "br",
}
_CODE_FMT: dict[str, tuple[str, bool]] = {v: k for k, v in _FMT_CODE.items()}

# Short labels for the toggle buttons — must stay short so the keyboard
# fits Telegram's narrow rendering on mobile (target ≤16 chars total
# including the ✅/⬜ icon).
_FEATURE_LABELS: dict[str, str] = {
    "summary":  "Summary",
    "tldr":     "TL;DRs",
    "qna":      "Self-Test",
    "mermaid":  "Diagrams",
    "chapters": "Index+QR",
}


def _features_from_mask(mask: int) -> list[str]:
    """Decode a bitmask into the canonical feature list."""
    return [f for i, f in enumerate(cache.FEATURE_ORDER) if mask & (1 << i)]


def _toggle_keyboard(fmt_code: str, vid: str, mask: int) -> InlineKeyboardMarkup:
    """Render the feature-toggle keyboard. Each feature gets a ✅/⬜ button
    that flips its bit; a final "Generate" button submits the current mask.
    """
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for bit, feat in enumerate(cache.FEATURE_ORDER):
        on = bool(mask & (1 << bit))
        icon = "✅" if on else "⬜"
        label = _FEATURE_LABELS.get(feat, feat)
        row.append(InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"gen:tog:{fmt_code}:{vid}:{mask:x}:{bit}",
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    n_on = bin(mask).count("1")
    if n_on == 0:
        gen_label = "🚀 Generate (no extras)"
    elif n_on == 1:
        gen_label = "🚀 Generate (1 extra)"
    else:
        gen_label = f"🚀 Generate ({n_on} extras)"
    rows.append([InlineKeyboardButton(
        gen_label,
        callback_data=f"gen:go:{fmt_code}:{vid}:{mask:x}",
    )])
    return InlineKeyboardMarkup(rows)

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
_SUBMITTED_CALLBACKS: dict[tuple[int, int], None] = {}
_MAX_SUBMITTED_CALLBACKS = 4096


def _claim_submission(chat_id: int, message_id: int) -> bool:
    """Atomically consume one Generate prompt for this bot process."""

    key = (chat_id, message_id)
    if key in _SUBMITTED_CALLBACKS:
        return False
    if len(_SUBMITTED_CALLBACKS) >= _MAX_SUBMITTED_CALLBACKS:
        oldest = next(iter(_SUBMITTED_CALLBACKS))
        _SUBMITTED_CALLBACKS.pop(oldest, None)
    _SUBMITTED_CALLBACKS[key] = None
    return True


def _release_submission(chat_id: int, message_id: int) -> None:
    _SUBMITTED_CALLBACKS.pop((chat_id, message_id), None)


def _whitelisted(chat_id: int) -> bool:
    return chat_id in WHITELISTED_GROUP_IDS


def _extract_url(text: str) -> str | None:
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(0) if m else None


_VIDEO_SUFFIXES = frozenset({".mp4", ".mkv", ".mov", ".webm", ".m4v"})
_AUDIO_SUFFIXES = frozenset(
    {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac"}
)


def _clean_media_title(file_name: str | None, *, is_video: bool) -> str:
    stem = Path(file_name or "").stem
    stem = re.sub(r"[\x00-\x1f\x7f]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:120] or ("Uploaded video" if is_video else "Uploaded audio")


def _extract_uploaded_media(message) -> worker.TelegramMedia | None:
    """Return a safe immutable media descriptor without downloading anything."""

    item = None
    file_name = None
    is_video = False

    if getattr(message, "video", None) is not None:
        item = message.video
        file_name = getattr(item, "file_name", None) or "telegram-video.mp4"
        is_video = True
    elif getattr(message, "video_note", None) is not None:
        item = message.video_note
        file_name = "telegram-video-note.mp4"
        is_video = True
    elif getattr(message, "audio", None) is not None:
        item = message.audio
        file_name = getattr(item, "file_name", None) or "telegram-audio.m4a"
    elif getattr(message, "voice", None) is not None:
        item = message.voice
        file_name = "telegram-voice.ogg"
    elif getattr(message, "document", None) is not None:
        item = message.document
        file_name = getattr(item, "file_name", None) or ""
        mime = (getattr(item, "mime_type", None) or "").casefold()
        suffix = Path(file_name).suffix.casefold()
        is_video = mime.startswith("video/") or suffix in _VIDEO_SUFFIXES
        is_audio = mime.startswith("audio/") or suffix in _AUDIO_SUFFIXES
        if not is_video and not is_audio:
            return None
    else:
        return None

    file_id = getattr(item, "file_id", None)
    unique_id = getattr(item, "file_unique_id", None)
    if not file_id or not unique_id:
        return None
    return worker.TelegramMedia(
        file_id=file_id,
        file_unique_id=unique_id,
        file_name=file_name or ("video.mp4" if is_video else "audio.m4a"),
        file_size=getattr(item, "file_size", None),
        is_video=is_video,
        title=_clean_media_title(file_name, is_video=is_video),
    )


def _caption_format(caption: str | None) -> str | None:
    match = re.search(
        r"(?:^|\s)/(cheat|book)(?:@[A-Za-z0-9_]+)?(?:\s|$)",
        caption or "",
        flags=re.IGNORECASE,
    )
    return match.group(1).casefold() if match else None


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
                       refresh: bool,
                       features: list[str] | None = None) -> int:
    """Build a Job for ``url``/``fmt`` and put it on the worker queue.
    Returns the 1-based queue position. Shared by every entry point
    (slash commands AND the inline-keyboard callback).

    ``features`` — opt-in PDF enhancements. None / [] = legacy PDF (the
    default for slash commands, since those have no toggle UI). The inline
    multi-step button flow passes a populated list.
    """
    user = update.effective_user
    chat = update.effective_chat
    job = worker.Job(
        chat_id=chat.id,
        user_id=user.id if user else 0,
        user_name=(user.full_name if user else "unknown"),
        url=url,
        fmt=fmt,
        refresh=refresh,
        features=list(features) if features else [],
    )
    return await worker.queue.put(job)


async def _enqueue_media(
    update: Update,
    fmt: str,
    media: worker.TelegramMedia,
    *,
    features: list[str] | None = None,
) -> int:
    """Build a local-media Job without placing its file id in callback data."""

    user = update.effective_user
    chat = update.effective_chat
    job = worker.Job(
        chat_id=chat.id,
        user_id=user.id if user else 0,
        user_name=(user.full_name if user else "unknown"),
        url="",
        fmt=fmt,
        features=list(features) if features else [],
        source_kind="telegram",
        telegram_media=media,
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
            f"Usage: /{fmt} <youtube-url>", do_quote=True)
        return
    position = await _enqueue_url(update, fmt, url, refresh)
    if position > 1:
        await msg.reply_text(
            f"Queued (position {position}).", do_quote=True)


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


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _drop(update):
        return
    await update.effective_message.reply_text(
        "Send a YouTube link, or upload an audio/video file under 19 MB.\n\n"
        "Commands:\n"
        "/cheat <youtube-url>\n"
        "/book <youtube-url>\n"
        "/status\n\n"
        "For an uploaded file, use the buttons I attach to it. "
        "Book Notes requires video because it extracts screenshots."
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
        source = ("uploaded media" if cur.source_kind == "telegram" else cur.url)
        lines.append(f"Running: /{cur.fmt} {source} (by {cur.user_name})")
    for i, j in enumerate(s["queued"], 1):
        source = ("uploaded media" if j.source_kind == "telegram" else j.url)
        lines.append(f"  {i}. /{j.fmt} {source} (by {j.user_name})")
    await update.effective_message.reply_text("\n".join(lines))


async def on_media_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Offer the normal format/options flow for an uploaded audio/video file."""

    if await _drop(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    media = _extract_uploaded_media(msg)
    if media is None:
        return
    from .media_uploads import MediaTooLargeError, check_size
    try:
        check_size(media.file_size)
    except MediaTooLargeError as exc:
        await msg.reply_text(str(exc), do_quote=True)
        return

    requested = _caption_format(msg.caption)
    if requested == "book" and not media.is_video:
        await msg.reply_text(
            "Book Notes needs video for screenshots. "
            "Choose Cheatsheet for this audio file.",
            do_quote=True,
        )
        return

    if requested in {"cheat", "book"}:
        fmt_code = _FMT_CODE[(requested, False)]
        label = "Cheatsheet" if requested == "cheat" else "Book Notes"
        await msg.reply_text(
            f"<b>{label}</b> — pick any extras then tap Generate.\n"
            "This upload will be processed without contacting YouTube.",
            reply_markup=_toggle_keyboard(fmt_code, "tg", 0),
            parse_mode="HTML",
            do_quote=True,
        )
        return

    rows = [[
        InlineKeyboardButton(
            "📄 Cheatsheet", callback_data="gen:cheat:tg"),
        InlineKeyboardButton(
            "📕 Book Notes", callback_data="gen:book:tg"),
    ]]
    await msg.reply_text(
        "Uploaded media detected. What should I create?\n"
        "This path does not contact YouTube.",
        reply_markup=InlineKeyboardMarkup(rows),
        do_quote=True,
    )


# === inline-keyboard flow ===================================================

async def on_youtube_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered by any non-command text message in a whitelisted chat.
    We do the YouTube-URL regex match inside the handler (not as a
    MessageHandler filter) so that even non-matching messages produce a
    debug-log line — that makes it possible to tell, after the fact,
    whether (a) the message wasn't received, (b) was received but didn't
    look like a YouTube URL, or (c) was processed normally. Cheap and
    avoids the class of bugs where a filter silently swallows updates.

    Replies with three inline buttons so the user can pick a format
    without typing a slash command. video id is encoded into each
    button's ``callback_data`` so the bot can survive a restart between
    the URL being posted and the user tapping a button — there's no
    server-side state to lose.
    """
    if await _drop(update):
        return
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    text = msg.text
    print(
        f"[on_youtube_link] chat={msg.chat_id} text={text[:120]!r}",
        flush=True,
    )
    m = YOUTUBE_RE.search(text)
    if not m:
        print("[on_youtube_link] no YouTube URL in message — ignoring",
              flush=True)
        return
    url = m.group(0)
    id_match = _VIDEO_ID_RE.search(url)
    if not id_match:
        print(f"[on_youtube_link] URL matched but no video id: {url!r}",
              flush=True)
        return
    vid = id_match.group(1)
    print(f"[on_youtube_link] matched url={url!r} vid={vid!r}", flush=True)

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
        "Which format?", reply_markup=keyboard, do_quote=True)


async def on_choice_callback(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the inline-keyboard buttons we emit from
    :func:`on_youtube_link`. Dispatches by action prefix on a ``gen:``-
    prefixed callback_data — see the wire-format comment above
    ``_FMT_CODE`` for the full schema.

    Three logical flows:

    1. **Format pick** (``cheat`` / ``book`` / ``refresh`` / ``rcheat`` /
       ``rbook``) — opens the feature-toggle screen (or, for plain
       ``refresh``, the cheat-vs-book sub-prompt first).
    2. **Toggle a bit** (``tog``) — flips a single feature bit and re-
       renders the same keyboard with the new state.
    3. **Submit** (``go``) — decodes the bitmask into a feature list and
       enqueues the job.
    """
    q = update.callback_query
    if q is None or q.message is None:
        return
    if not _whitelisted(q.message.chat_id):
        await q.answer("Not authorised here.", show_alert=False)
        return
    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "gen":
        await q.answer()
        return
    action = parts[1]

    # Upload callbacks use the sentinel 'tg'. The keyboard message is a reply
    # to the original media, so Telegram carries the file state across bot
    # restarts and no file id is exposed in callback_data.
    callback_media = None
    identifier = None
    if action in {"tog", "go"} and len(parts) >= 4:
        identifier = parts[3]
    elif len(parts) >= 3:
        identifier = parts[2]
    if identifier == "tg":
        original = getattr(q.message, "reply_to_message", None)
        callback_media = (
            _extract_uploaded_media(original) if original is not None else None
        )
        if callback_media is None:
            await q.answer("Please upload the file again.", show_alert=True)
            return
        uploader = getattr(original, "from_user", None)
        clicker = q.from_user
        if uploader is None:
            await q.answer(
                "Anonymous or channel uploads are not supported. "
                "Please upload from your own account.",
                show_alert=True,
            )
            return
        if clicker is None or uploader.id != clicker.id:
            await q.answer(
                "Only the person who uploaded this file can start it.",
                show_alert=True,
            )
            return

    # --- action: tog (flip a feature bit) -----------------------------------
    if action == "tog":
        # gen:tog:<fmt_code>:<vid>:<mask_hex>:<bit>
        if len(parts) != 6:
            await q.answer(); return
        _, _, fmt_code, vid, mask_hex, bit_str = parts
        if fmt_code not in _CODE_FMT or not vid:
            await q.answer(); return
        try:
            mask = int(mask_hex, 16)
            bit = int(bit_str)
        except ValueError:
            await q.answer(); return
        if not (0 <= bit < len(cache.FEATURE_ORDER)):
            await q.answer(); return
        new_mask = mask ^ (1 << bit)
        try:
            await q.edit_message_reply_markup(
                reply_markup=_toggle_keyboard(fmt_code, vid, new_mask))
        except Exception:
            # Same markup / message too old / network — drop quietly so a
            # double-tap doesn't surface a scary error.
            pass
        await q.answer()
        return

    # --- action: go (submit) ------------------------------------------------
    if action == "go":
        # gen:go:<fmt_code>:<vid>:<mask_hex>
        if len(parts) != 5:
            await q.answer(); return
        _, _, fmt_code, vid, mask_hex = parts
        pick = _CODE_FMT.get(fmt_code)
        if pick is None or not vid:
            await q.answer(); return
        fmt, refresh = pick
        try:
            mask = int(mask_hex, 16)
        except ValueError:
            await q.answer(); return
        features = _features_from_mask(mask)
        if vid == "tg":
            if callback_media is None:
                await q.answer("Please upload the file again.", show_alert=True)
                return
            if fmt == "book" and not callback_media.is_video:
                await q.answer(
                    "Book Notes needs video for screenshots. Choose Cheatsheet.",
                    show_alert=True,
                )
                return
        submission_chat_id = q.message.chat_id
        submission_message_id = q.message.message_id
        if not _claim_submission(submission_chat_id, submission_message_id):
            await q.answer("Already queued.", show_alert=False)
            return
        try:
            if vid == "tg":
                position = await _enqueue_media(
                    update, fmt, callback_media, features=features
                )
            else:
                url = f"https://youtu.be/{vid}"
                position = await _enqueue_url(
                    update, fmt, url, refresh, features=features
                )
        except Exception:
            _release_submission(submission_chat_id, submission_message_id)
            raise
        await q.answer(
            f"Queued · {fmt}{' · refresh' if refresh else ''}"
            + (f" · {len(features)} extras" if features else ""))

        # Replace the keyboard with a one-line confirmation so the chat
        # history reads naturally and the buttons can't be re-tapped.
        label = "Cheatsheet" if fmt == "cheat" else "Book Notes"
        suffix = " (rebuild)" if refresh else ""
        body = f"→ {label}{suffix}"
        if features:
            extras = ", ".join(_FEATURE_LABELS.get(f, f).lower() for f in features)
            body += f"\nExtras: {extras}"
        if position > 1:
            body += f"\nQueue position: {position}"
        try:
            await q.edit_message_text(body)
        except Exception:
            pass
        return

    # --- action: refresh sub-prompt -----------------------------------------
    # Reaches here only for the bare "↻ Refresh" button that asks the user
    # which kind of rebuild they want before opening the toggle screen.
    if action == "refresh":
        if len(parts) != 3:
            await q.answer(); return
        vid = parts[2]
        if not vid:
            await q.answer(); return
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

    # --- action: cheat / book / rcheat / rbook (open toggle screen) ---------
    # Decode (fmt, refresh) from the action verb, then render the feature
    # toggle keyboard with an empty mask (all features off — the default).
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
    if len(parts) != 3:
        await q.answer(); return
    vid = parts[2]
    if not vid:
        await q.answer(); return
    fmt, refresh = pick
    if vid == "tg" and fmt == "book":
        if callback_media is None or not callback_media.is_video:
            await q.answer(
                "Book Notes needs video for screenshots. Choose Cheatsheet.",
                show_alert=True,
            )
            return
    fmt_code = _FMT_CODE[(fmt, refresh)]

    label = "Cheatsheet" if fmt == "cheat" else "Book Notes"
    suffix = " (rebuild)" if refresh else ""
    prompt = (
        f"<b>{label}{suffix}</b> — pick any extras then tap Generate.\n"
        + (
            "This upload will be processed without contacting YouTube."
            if vid == "tg"
            else "All extras start OFF (default = the bare PDF)."
        )
    )
    await q.answer()
    try:
        await q.edit_message_text(
            prompt,
            reply_markup=_toggle_keyboard(fmt_code, vid, 0),
            parse_mode="HTML",
        )
    except Exception:
        pass
