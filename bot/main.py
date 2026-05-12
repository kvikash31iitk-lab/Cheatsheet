"""Bot entry point. Run with:  python -m bot.main"""
from __future__ import annotations

import asyncio
import logging
import sys

from telegram.ext import Application, CommandHandler

from . import handlers, worker
from .config import TELEGRAM_BOT_TOKEN, WHITELISTED_GROUP_IDS, validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")


async def post_init(app: Application) -> None:
    """Spin up the single-worker job loop alongside the bot."""
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
    app.add_handler(CommandHandler("cheat", handlers.cmd_cheat))
    app.add_handler(CommandHandler("book", handlers.cmd_book))
    app.add_handler(CommandHandler("refresh", handlers.cmd_refresh))
    app.add_handler(CommandHandler("status", handlers.cmd_status))

    print("[bot] polling for updates...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
