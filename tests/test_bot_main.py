from __future__ import annotations

import asyncio
import logging
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Production installs python-telegram-bot; these lifecycle units only need its
# import surface, so mirror the lightweight stubs used by the upload tests.
try:
    import telegram  # noqa: F401
except ModuleNotFoundError:
    telegram_stub = types.ModuleType("telegram")
    telegram_error_stub = types.ModuleType("telegram.error")
    telegram_constants_stub = types.ModuleType("telegram.constants")
    telegram_ext_stub = types.ModuleType("telegram.ext")

    class _TelegramError(Exception):
        pass

    class _RetryAfter(_TelegramError):
        retry_after = 0

    telegram_stub.Bot = object
    telegram_stub.InlineKeyboardButton = object
    telegram_stub.InlineKeyboardMarkup = object
    telegram_stub.Update = object
    telegram_error_stub.TelegramError = _TelegramError
    telegram_error_stub.BadRequest = _TelegramError
    telegram_error_stub.NetworkError = _TelegramError
    telegram_error_stub.TimedOut = _TelegramError
    telegram_error_stub.RetryAfter = _RetryAfter
    telegram_constants_stub.ParseMode = SimpleNamespace(HTML="HTML")
    telegram_ext_stub.Application = object
    telegram_ext_stub.CallbackQueryHandler = object
    telegram_ext_stub.CommandHandler = object
    telegram_ext_stub.MessageHandler = object
    telegram_ext_stub.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
    telegram_ext_stub.filters = SimpleNamespace()

    sys.modules["telegram"] = telegram_stub
    sys.modules["telegram.error"] = telegram_error_stub
    sys.modules["telegram.constants"] = telegram_constants_stub
    sys.modules["telegram.ext"] = telegram_ext_stub

from bot import main as bot_main


class _SecretBearingUrl:
    def __init__(self, token: str) -> None:
        self._token = token

    def __str__(self) -> str:
        return f"https://api.telegram.org/bot{self._token}/getMe"


class LoggingSafetyTests(unittest.TestCase):
    def test_http_client_request_logs_are_disabled_at_info(self) -> None:
        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)
        self.assertGreaterEqual(logging.getLogger("httpcore").level, logging.WARNING)

    def test_secret_filter_redacts_string_and_url_object_arguments(self) -> None:
        token = "123456:very-secret-token"
        record = logging.LogRecord(
            "httpx",
            logging.WARNING,
            __file__,
            1,
            "request %s failed: %s",
            (_SecretBearingUrl(token), f"token={token}"),
            None,
        )

        with patch.object(bot_main, "TELEGRAM_BOT_TOKEN", token):
            self.assertTrue(bot_main._SecretFilter().filter(record))

        rendered = record.getMessage()
        self.assertNotIn(token, rendered)
        self.assertIn("<redacted>", rendered)


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_stop_cancels_and_awaits_worker(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_worker(_bot: object) -> None:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        app = SimpleNamespace(bot=object(), bot_data={})
        with (
            patch.object(bot_main.media_uploads, "cleanup_orphaned_staging") as cleanup,
            patch.object(bot_main.worker, "worker_loop", new=fake_worker),
        ):
            await bot_main.post_init(app)
            task = app.bot_data[bot_main._WORKER_TASK_KEY]
            await asyncio.wait_for(started.wait(), timeout=1)
            await bot_main.post_stop(app)

        cleanup.assert_called_once_with()
        self.assertTrue(cancelled.is_set())
        self.assertTrue(task.done())
        self.assertNotIn(bot_main._WORKER_TASK_KEY, app.bot_data)

    async def test_post_stop_is_safe_when_worker_was_not_started(self) -> None:
        app = SimpleNamespace(bot=object(), bot_data={})
        await bot_main.post_stop(app)


if __name__ == "__main__":
    unittest.main()
