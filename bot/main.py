"""Bot entry point. Run with:  python -m bot.main"""
from __future__ import annotations

import asyncio
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


async def post_init(app: Application) -> None:
    """Spin up the single-worker job loop alongside the bot."""
    media_uploads.cleanup_orphaned_staging()
    asyncio.create_task(worker.worker_loop(app.bot))


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
