"""Bot entry point. Run with:  python -m bot.main"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import sys

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import handlers, media_uploads, worker
from .config import TELEGRAM_BOT_TOKEN, WHITELISTED_GROUP_IDS, validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

# httpx includes the full Bot API URL in its INFO messages, and that URL
# contains the Telegram bot token. Keep request logging at WARNING and add a
# defensive root-handler filter so a future dependency cannot print the token
# accidentally.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        token = TELEGRAM_BOT_TOKEN
        if not token:
            return True

        def redact(value: object) -> object:
            if isinstance(value, str):
                return value.replace(token, "<redacted>")
            # httpx passes URL objects (not plain strings) as logging args.
            # Preserve ordinary values, but stringify and redact any object
            # whose rendered form contains the token.
            rendered = str(value)
            if token in rendered:
                return rendered.replace(token, "<redacted>")
            return value

        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: redact(value) for key, value in record.args.items()
            }
        return True


for _handler in logging.getLogger().handlers:
    _handler.addFilter(_SecretFilter())


_WORKER_TASK_KEY = "_worker_task"


async def post_init(app: Application) -> None:
    """Spin up the single-worker job loop alongside the bot."""
    media_uploads.cleanup_orphaned_staging()
    app.bot_data[_WORKER_TASK_KEY] = asyncio.create_task(
        worker.worker_loop(app.bot), name="video-notes-worker"
    )


async def post_stop(app: Application) -> None:
    """Cancel and await the worker before the polling event loop closes."""
    task = app.bot_data.pop(_WORKER_TASK_KEY, None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def main() -> None:
    problems = validate()
    if problems:
        for p in problems:
            print(f"[config] FATAL: {p}")
        sys.exit(1)

    print(f"[config] whitelist: {WHITELISTED_GROUP_IDS}")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("cheat", handlers.cmd_cheat))
    app.add_handler(CommandHandler("book", handlers.cmd_book))
    app.add_handler(CommandHandler("refresh", handlers.cmd_refresh))
    app.add_handler(CommandHandler("status", handlers.cmd_status))

    # Inline-keyboard flow: a bare YouTube URL message (no slash command)
    # triggers a reply with [Cheatsheet] [Book Notes] [Refresh] buttons.
    # Registered AFTER the slash CommandHandlers so /cheat <url> stays the
    # power-user path; this catches plain pasted links.
    # NOTE: We DO NOT pre-filter on filters.Regex(YOUTUBE_RE) here — the
    # YouTube-URL check is done inside on_youtube_link itself. That way
    # every non-command text message hits the handler (cheap), the
    # handler logs what it saw, and we never silently drop an update
    # because of an off-by-one in the filter regex. Without this we
    # spent a deploy cycle debugging "the bot doesn't reply to bare
    # URLs" without any logs to show what it was actually receiving.
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handlers.on_youtube_link,
    ))
    app.add_handler(MessageHandler(
        filters.AUDIO
        | filters.VIDEO
        | filters.VOICE
        | filters.VIDEO_NOTE
        | filters.Document.ALL,
        handlers.on_media_upload,
    ))
    app.add_handler(CallbackQueryHandler(
        handlers.on_choice_callback, pattern=r"^gen:"
    ))

    print("[bot] polling for updates...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
