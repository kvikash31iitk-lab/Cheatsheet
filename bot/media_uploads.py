"""Security-conscious helpers for Telegram media ingestion.

The hosted Telegram Bot API is intentionally treated as a small-file fallback:
it has a hard 20 MB bot-download limit. Files are staged privately, downloaded
atomically, checked against declared and actual sizes, and removed after the
pipeline adopts their outputs.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError

from .config import (
    TELEGRAM_UPLOAD_MAX_BYTES,
    TELEGRAM_UPLOAD_MAX_MB,
    TELEGRAM_UPLOAD_MIN_FREE_BYTES,
    UPLOAD_ROOT,
)


class MediaUploadError(RuntimeError):
    """An upload failure whose message is safe to show to the user."""


class MediaTooLargeError(MediaUploadError):
    pass


def upload_cache_id(
    chat_id: int, file_unique_id: str, source_url: str = ""
) -> str:
    """Return a private, filesystem-safe cache key for one Telegram file.

    Scoping by chat prevents a cross-chat cache hit from revealing that two
    users uploaded the same private media. The optional source URL keeps PDFs
    with source-link features from colliding.
    """

    material = f"{chat_id}\0{file_unique_id}\0{source_url}".encode("utf-8")
    return "tg_" + hashlib.sha256(material).hexdigest()[:32]


_SAFE_SUFFIXES = frozenset(
    {
        ".mp4", ".mkv", ".mov", ".webm", ".m4v",
        ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac",
    }
)


def safe_media_suffix(file_name: str | None) -> str:
    suffix = Path(file_name or "").suffix.casefold()
    return suffix if suffix in _SAFE_SUFFIXES else ".bin"


def create_staging_dir(cache_id: str) -> Path:
    prefix = "upload-" + cache_id[-10:] + "-"
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=UPLOAD_ROOT))
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def remove_staging_dir(path: Path | None) -> None:
    if path is None:
        return
    try:
        resolved = Path(path).resolve()
        root = UPLOAD_ROOT.resolve()
        if resolved.parent == root and resolved.name.startswith("upload-"):
            shutil.rmtree(resolved, ignore_errors=True)
    except OSError:
        pass


def cleanup_orphaned_staging() -> None:
    """Remove private upload directories left behind by a killed process."""

    try:
        children = list(UPLOAD_ROOT.iterdir())
    except OSError:
        return
    for child in children:
        if not child.name.startswith("upload-"):
            continue
        try:
            if child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                remove_staging_dir(child)
        except OSError:
            continue


def check_size(size: int | None) -> None:
    if size is not None and size > TELEGRAM_UPLOAD_MAX_BYTES:
        raise MediaTooLargeError(
            f"This file is too large for Telegram's hosted bot download. "
            f"Send a file smaller than {TELEGRAM_UPLOAD_MAX_MB} MB."
        )


async def download_media(
    bot: Bot,
    *,
    file_id: str,
    declared_size: int | None,
    destination: Path,
) -> Path:
    """Download one Telegram file atomically into a private staging folder."""

    check_size(declared_size)
    expected = max(0, declared_size or 0)
    try:
        free = shutil.disk_usage(UPLOAD_ROOT).free
    except OSError as exc:
        raise MediaUploadError(
            "Storage is temporarily unavailable. Please try again later."
        ) from exc
    if free - expected < TELEGRAM_UPLOAD_MIN_FREE_BYTES:
        raise MediaUploadError(
            "The server is low on temporary storage. Please try again later."
        )

    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    destination.unlink(missing_ok=True)
    try:
        telegram_file = await bot.get_file(
            file_id,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30,
        )
        check_size(getattr(telegram_file, "file_size", None))
        await telegram_file.download_to_drive(
            custom_path=partial,
            read_timeout=300,
            write_timeout=300,
            connect_timeout=30,
            pool_timeout=30,
        )
        actual = partial.stat().st_size
        if actual <= 0:
            raise MediaUploadError("Telegram returned an empty media file.")
        check_size(actual)
        os.chmod(partial, 0o600)
        partial.replace(destination)
        return destination
    except MediaUploadError:
        raise
    except (TelegramError, RuntimeError) as exc:
        raise MediaUploadError(
            "Telegram could not deliver this file. Please resend it and try again."
        ) from exc
    except OSError as exc:
        raise MediaUploadError(
            "The uploaded file could not be stored safely. Please try again."
        ) from exc
    finally:
        partial.unlink(missing_ok=True)
