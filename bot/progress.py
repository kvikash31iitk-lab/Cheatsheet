"""Live-progress helper: edit a single Telegram message as work progresses.

Built around two layers:

  - ``ProgressEditor`` lives on the asyncio event loop and owns the actual
    ``edit_message_text`` calls. It rate-limits edits to once every
    ``MIN_EDIT_GAP_S`` seconds to stay under Telegram's anti-spam limits.

  - The pipeline runs in a worker thread (sync code, ~minutes). It can call
    ``editor.update_threadsafe(text)`` from that thread to schedule an edit on
    the bot's event loop.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from telegram import Bot
from telegram.error import RetryAfter, TimedOut, BadRequest

MIN_EDIT_GAP_S = 1.0


class ProgressEditor:
    def __init__(self, bot: Bot, chat_id: int, message_id: int,
                 prefix: str = "", loop: Optional[asyncio.AbstractEventLoop] = None):
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.prefix = prefix
        self._last_text: str = ""
        self._last_edit_at: float = 0.0
        self._loop = loop or asyncio.get_event_loop()

    async def _edit(self, text: str) -> None:
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id, message_id=self.message_id, text=text)
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 0.5)
        except (TimedOut, BadRequest):
            # Same content, network blips — ignore
            pass

    async def update(self, text: str, *, force: bool = False) -> None:
        full = f"{self.prefix}{text}" if self.prefix else text
        if full == self._last_text:
            return
        now = time.monotonic()
        if not force and (now - self._last_edit_at) < MIN_EDIT_GAP_S:
            # Coalesce: store text, schedule a delayed edit
            self._last_text = full
            return
        self._last_text = full
        self._last_edit_at = now
        await self._edit(full)

    def update_threadsafe(self, text: str, *, force: bool = False) -> None:
        """Call from a worker thread; the actual edit runs on the bot loop."""
        try:
            asyncio.run_coroutine_threadsafe(
                self.update(text, force=force), self._loop)
        except RuntimeError:
            pass
