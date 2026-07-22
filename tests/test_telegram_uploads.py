from __future__ import annotations

import tempfile
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Production uses python-telegram-bot, but these units do not need a live
# Telegram dependency or network connection.
try:
    import telegram  # noqa: F401
except ModuleNotFoundError:
    telegram_stub = types.ModuleType('telegram')
    telegram_error_stub = types.ModuleType('telegram.error')
    telegram_constants_stub = types.ModuleType('telegram.constants')
    telegram_ext_stub = types.ModuleType('telegram.ext')

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
    telegram_constants_stub.ParseMode = SimpleNamespace(HTML='HTML')
    telegram_ext_stub.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)

    sys.modules['telegram'] = telegram_stub
    sys.modules['telegram.error'] = telegram_error_stub
    sys.modules['telegram.constants'] = telegram_constants_stub
    sys.modules['telegram.ext'] = telegram_ext_stub

from telegram.error import TimedOut

from bot import cache, handlers, media_uploads, worker


def attachment(**overrides):
    values = {
        "video": None,
        "video_note": None,
        "audio": None,
        "voice": None,
        "document": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def telegram_item(**overrides):
    values = {
        "file_id": "file-id",
        "file_unique_id": "unique-id",
        "file_name": None,
        "file_size": 123,
        "mime_type": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class UploadCacheIdTests(unittest.TestCase):
    def test_cache_id_is_stable_scoped_and_filesystem_safe(self):
        first = media_uploads.upload_cache_id(10, "same-file", "https://youtu.be/a")

        self.assertEqual(
            first,
            media_uploads.upload_cache_id(10, "same-file", "https://youtu.be/a"),
        )
        self.assertNotEqual(first, media_uploads.upload_cache_id(11, "same-file"))
        self.assertNotEqual(first, media_uploads.upload_cache_id(10, "other-file"))
        self.assertNotEqual(
            first,
            media_uploads.upload_cache_id(10, "same-file", "https://youtu.be/b"),
        )
        self.assertRegex(first, r"^tg_[0-9a-f]{32}$")

    def test_safe_media_suffix_is_allowlisted_and_case_insensitive(self):
        self.assertEqual(media_uploads.safe_media_suffix("lecture.MP4"), ".mp4")
        self.assertEqual(media_uploads.safe_media_suffix("voice.OpUs"), ".opus")
        self.assertEqual(media_uploads.safe_media_suffix("../payload.exe"), ".bin")
        self.assertEqual(media_uploads.safe_media_suffix(None), ".bin")

    def test_declared_size_boundary_is_enforced(self):
        with patch.object(media_uploads, "TELEGRAM_UPLOAD_MAX_BYTES", 10), patch.object(
            media_uploads, "TELEGRAM_UPLOAD_MAX_MB", 1
        ):
            media_uploads.check_size(None)
            media_uploads.check_size(10)
            with self.assertRaises(media_uploads.MediaTooLargeError) as raised:
                media_uploads.check_size(11)

        self.assertIn("smaller than 1 MB", str(raised.exception))

    def test_staging_cleanup_is_confined_to_upload_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "uploads"
            root.mkdir()
            outside = base / "upload-outside"
            outside.mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")

            with patch.object(media_uploads, "UPLOAD_ROOT", root):
                staged = media_uploads.create_staging_dir("tg_0123456789abcdef")
                (staged / "remove.txt").write_text("remove", encoding="utf-8")
                media_uploads.remove_staging_dir(staged)
                media_uploads.remove_staging_dir(outside)

            self.assertFalse(staged.exists())
            self.assertTrue((outside / "keep.txt").exists())

    def test_startup_cleanup_removes_only_orphan_upload_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orphan = root / "upload-stale"
            keep = root / "keep-cache"
            orphan.mkdir()
            keep.mkdir()
            (orphan / "partial.bin").write_bytes(b"partial")
            (keep / "important.bin").write_bytes(b"keep")

            with patch.object(media_uploads, "UPLOAD_ROOT", root):
                media_uploads.cleanup_orphaned_staging()

            self.assertFalse(orphan.exists())
            self.assertTrue((keep / "important.bin").exists())


class DownloadMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_is_atomic_and_uses_no_real_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "source.mp4"

            async def write_download(*, custom_path, **_kwargs):
                Path(custom_path).write_bytes(b"media-bytes")

            telegram_file = SimpleNamespace(
                file_size=len(b"media-bytes"),
                download_to_drive=AsyncMock(side_effect=write_download),
            )
            bot = SimpleNamespace(get_file=AsyncMock(return_value=telegram_file))

            with patch.object(media_uploads, "UPLOAD_ROOT", root), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MAX_BYTES", 100
            ), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MIN_FREE_BYTES", 10
            ), patch.object(
                media_uploads.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1_000),
            ):
                result = await media_uploads.download_media(
                    bot,
                    file_id="telegram-secret-id",
                    declared_size=11,
                    destination=destination,
                )

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"media-bytes")
            self.assertFalse((root / "source.mp4.part").exists())
            bot.get_file.assert_awaited_once()
            telegram_file.download_to_drive.assert_awaited_once()

    async def test_actual_oversize_file_is_rejected_and_partial_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "source.mp4"

            async def write_oversize(*, custom_path, **_kwargs):
                Path(custom_path).write_bytes(b"too-large")

            telegram_file = SimpleNamespace(
                file_size=None,
                download_to_drive=AsyncMock(side_effect=write_oversize),
            )
            bot = SimpleNamespace(get_file=AsyncMock(return_value=telegram_file))

            with patch.object(media_uploads, "UPLOAD_ROOT", root), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MAX_BYTES", 3
            ), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MAX_MB", 1
            ), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MIN_FREE_BYTES", 0
            ), patch.object(
                media_uploads.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1_000),
            ):
                with self.assertRaises(media_uploads.MediaTooLargeError):
                    await media_uploads.download_media(
                        bot,
                        file_id="file-id",
                        declared_size=None,
                        destination=destination,
                    )

            self.assertFalse(destination.exists())
            self.assertFalse((root / "source.mp4.part").exists())

    async def test_telegram_timeout_becomes_safe_error_and_cleans_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "source.mp4"
            bot = SimpleNamespace(get_file=AsyncMock(side_effect=TimedOut()))

            with patch.object(media_uploads, "UPLOAD_ROOT", root), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MIN_FREE_BYTES", 0
            ), patch.object(
                media_uploads.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1_000),
            ):
                with self.assertRaises(media_uploads.MediaUploadError) as raised:
                    await media_uploads.download_media(
                        bot,
                        file_id="sensitive-file-id",
                        declared_size=1,
                        destination=destination,
                    )

            self.assertEqual(
                str(raised.exception),
                "Telegram could not deliver this file. Please resend it and try again.",
            )
            self.assertNotIn("sensitive-file-id", str(raised.exception))
            self.assertFalse((root / "source.mp4.part").exists())

    async def test_runtime_download_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            telegram_file = SimpleNamespace(
                file_size=1,
                download_to_drive=AsyncMock(
                    side_effect=RuntimeError("private Telegram file path missing")
                ),
            )
            bot = SimpleNamespace(get_file=AsyncMock(return_value=telegram_file))

            with patch.object(media_uploads, "UPLOAD_ROOT", root), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MIN_FREE_BYTES", 0
            ), patch.object(
                media_uploads.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1_000),
            ):
                with self.assertRaises(media_uploads.MediaUploadError) as raised:
                    await media_uploads.download_media(
                        bot,
                        file_id="file-id",
                        declared_size=1,
                        destination=root / "source.mp4",
                    )

            self.assertNotIn("private Telegram", str(raised.exception))

    async def test_low_disk_rejects_before_requesting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bot = SimpleNamespace(get_file=AsyncMock())

            with patch.object(media_uploads, "UPLOAD_ROOT", root), patch.object(
                media_uploads, "TELEGRAM_UPLOAD_MIN_FREE_BYTES", 100
            ), patch.object(
                media_uploads.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=105),
            ):
                with self.assertRaises(media_uploads.MediaUploadError) as raised:
                    await media_uploads.download_media(
                        bot,
                        file_id="file-id",
                        declared_size=10,
                        destination=root / "source.mp4",
                    )

            self.assertIn("low on temporary storage", str(raised.exception))
            bot.get_file.assert_not_awaited()


class HandlerAttachmentParsingTests(unittest.TestCase):
    def test_video_attachment_uses_safe_defaults(self):
        media = handlers._extract_uploaded_media(
            attachment(video=telegram_item(file_name=None))
        )

        self.assertEqual(
            media,
            worker.TelegramMedia(
                file_id="file-id",
                file_unique_id="unique-id",
                file_name="telegram-video.mp4",
                file_size=123,
                is_video=True,
                title="telegram-video",
            ),
        )

    def test_audio_and_voice_are_not_marked_as_video(self):
        audio = handlers._extract_uploaded_media(
            attachment(audio=telegram_item(file_name="lesson.M4A"))
        )
        voice = handlers._extract_uploaded_media(
            attachment(voice=telegram_item())
        )

        self.assertFalse(audio.is_video)
        self.assertEqual(audio.title, "lesson")
        self.assertFalse(voice.is_video)
        self.assertEqual(voice.file_name, "telegram-voice.ogg")

    def test_document_accepts_media_mime_or_suffix_only(self):
        video = handlers._extract_uploaded_media(
            attachment(
                document=telegram_item(
                    file_name="recording.data", mime_type="video/mp4"
                )
            )
        )
        audio = handlers._extract_uploaded_media(
            attachment(
                document=telegram_item(
                    file_name="recording.FLAC", mime_type="application/octet-stream"
                )
            )
        )
        rejected = handlers._extract_uploaded_media(
            attachment(
                document=telegram_item(
                    file_name="notes.pdf", mime_type="application/pdf"
                )
            )
        )

        self.assertTrue(video.is_video)
        self.assertFalse(audio.is_video)
        self.assertIsNone(rejected)

    def test_attachment_without_both_telegram_ids_is_rejected(self):
        self.assertIsNone(
            handlers._extract_uploaded_media(
                attachment(video=telegram_item(file_id=""))
            )
        )
        self.assertIsNone(
            handlers._extract_uploaded_media(
                attachment(video=telegram_item(file_unique_id=None))
            )
        )

    def test_title_is_sanitized_and_bounded(self):
        item = telegram_item(file_name=("  unsafe\x00\n title  " + "x" * 140 + ".mp4"))

        media = handlers._extract_uploaded_media(attachment(video=item))

        self.assertNotIn("\x00", media.title)
        self.assertNotIn("\n", media.title)
        self.assertLessEqual(len(media.title), 120)

    def test_caption_format_supports_bot_mentions_and_boundaries(self):
        cases = {
            "/cheat": "cheat",
            "please /BOOK@CheetsheetBot now": "book",
            "before\n/CheAt\nafter": "cheat",
            None: None,
            "": None,
            "/cheater": None,
            "prefix/book": None,
            "/book-extra": None,
        }

        for caption, expected in cases.items():
            with self.subTest(caption=caption):
                self.assertEqual(handlers._caption_format(caption), expected)


class CacheKeyValidationTests(unittest.TestCase):
    def test_slot_accepts_youtube_and_generated_upload_ids(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            cache, "CACHE_ROOT", Path(directory)
        ):
            upload_id = media_uploads.upload_cache_id(1, "telegram-id")

            self.assertEqual(cache.slot("abcdefghijk"), Path(directory) / "abcdefghijk")
            self.assertEqual(cache.slot(upload_id), Path(directory) / upload_id)
            self.assertEqual(cache.slot("a" * 64), Path(directory) / ("a" * 64))

    def test_slot_rejects_traversal_and_malformed_ids(self):
        invalid = (
            "",
            "a" * 65,
            "../secret",
            "..\\secret",
            "nested/id",
            "dot.id",
            "has space",
            Path("abcdefghijk"),
            None,
        )

        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    cache.slot(value)


class CacheAdoptionTests(unittest.TestCase):
    def test_raw_frame_candidates_are_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_frames = root / "pipeline-frames"
            raw_frames = source_frames / "_raw"
            raw_frames.mkdir(parents=True)
            (raw_frames / "candidate.jpg").write_bytes(b"large-raw")
            (source_frames / "frame_00-00-01.jpg").write_bytes(b"final")
            frames_index = root / "frames.json"
            frames_index.write_text("[]", encoding="utf-8")
            cache_root = root / "cache"

            with patch.object(cache, "CACHE_ROOT", cache_root):
                cache.adopt_pipeline_outputs(
                    "tg_0123456789abcdef",
                    {
                        "title": "Upload",
                        "duration_seconds": 1.0,
                        "frames_dir": source_frames,
                        "frames_index": frames_index,
                    },
                )

            adopted = cache_root / "tg_0123456789abcdef" / "frames"
            self.assertTrue((adopted / "frame_00-00-01.jpg").exists())
            self.assertFalse((adopted / "_raw").exists())


class CallbackSubmissionTests(unittest.TestCase):
    def setUp(self):
        handlers._SUBMITTED_CALLBACKS.clear()

    def tearDown(self):
        handlers._SUBMITTED_CALLBACKS.clear()

    def test_generate_prompt_can_be_claimed_only_once(self):
        self.assertTrue(handlers._claim_submission(1, 2))
        self.assertFalse(handlers._claim_submission(1, 2))
        self.assertTrue(handlers._claim_submission(1, 3))
        handlers._release_submission(1, 2)
        self.assertTrue(handlers._claim_submission(1, 2))


class CallbackHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_rapid_double_submit_enqueues_upload_only_once(self):
        handlers._SUBMITTED_CALLBACKS.clear()
        uploader = SimpleNamespace(id=7, full_name="Uploader")
        original = attachment(
            video=telegram_item(file_name="lesson.mp4")
        )
        original.from_user = uploader
        callback_message = SimpleNamespace(
            chat_id=1,
            message_id=99,
            reply_to_message=original,
        )
        query = SimpleNamespace(
            data="gen:go:c:tg:0",
            message=callback_message,
            from_user=uploader,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=uploader,
            effective_chat=SimpleNamespace(id=1),
        )

        with patch.object(
            handlers, "WHITELISTED_GROUP_IDS", [1]
        ), patch.object(
            handlers, "_enqueue_media", new=AsyncMock(return_value=1)
        ) as enqueue_mock:
            await handlers.on_choice_callback(update, None)
            await handlers.on_choice_callback(update, None)

        self.assertEqual(enqueue_mock.await_count, 1)
        self.assertEqual(query.edit_message_text.await_count, 1)
        self.assertEqual(query.answer.await_count, 2)
        handlers._SUBMITTED_CALLBACKS.clear()


class JobSourceValidationTests(unittest.TestCase):
    @staticmethod
    def media() -> worker.TelegramMedia:
        return worker.TelegramMedia(
            file_id="file-id",
            file_unique_id="unique-id",
            file_name="video.mp4",
            file_size=123,
            is_video=True,
            title="video",
        )

    def test_valid_youtube_job_uses_default_source(self):
        job = worker.Job(
            chat_id=1,
            user_id=2,
            user_name="User",
            url="https://youtu.be/abcdefghijk",
            fmt="cheat",
        )

        self.assertEqual(job.source_kind, "youtube")
        self.assertIsNone(job.telegram_media)

    def test_valid_telegram_job_requires_media_metadata(self):
        media = self.media()

        job = worker.Job(
            chat_id=1,
            user_id=2,
            user_name="User",
            url="",
            fmt="book",
            source_kind="telegram",
            telegram_media=media,
        )

        self.assertIs(job.telegram_media, media)

    def test_youtube_job_without_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "YouTube jobs require a URL"):
            worker.Job(
                chat_id=1,
                user_id=2,
                user_name="User",
                url="",
                fmt="cheat",
            )

    def test_telegram_job_without_media_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Telegram jobs require media metadata"):
            worker.Job(
                chat_id=1,
                user_id=2,
                user_name="User",
                url="",
                fmt="cheat",
                source_kind="telegram",
            )

    def test_unknown_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown job source"):
            worker.Job(
                chat_id=1,
                user_id=2,
                user_name="User",
                url="https://example.com/video",
                fmt="cheat",
                source_kind="filesystem",
            )


if __name__ == "__main__":
    unittest.main()
