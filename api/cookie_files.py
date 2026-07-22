"""Validation and secure storage helpers for yt-dlp Netscape cookies files."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


NETSCAPE_COOKIE_HEADER = "# Netscape HTTP Cookie File"
MAX_COOKIE_FILE_BYTES = 2 * 1024 * 1024


class CookieFileValidationError(ValueError):
    """The supplied text is not a usable Netscape YouTube cookie file."""


class CookieFileTooLarge(CookieFileValidationError):
    """The supplied cookie file exceeds the upload limit."""


@dataclass(frozen=True)
class CookieFileSummary:
    normalized_text: str
    size_bytes: int
    cookie_count: int
    youtube_cookie_count: int


def validate_cookie_file(
    raw_text: str,
    *,
    max_bytes: int = MAX_COOKIE_FILE_BYTES,
) -> CookieFileSummary:
    """Validate and normalize an exported Netscape cookies.txt file.

    Cookie values are deliberately never copied into exceptions or metadata.
    ``#HttpOnly_`` lines are cookie rows in this format, not comments.
    """

    raw_size = len(raw_text.encode("utf-8"))
    if raw_size > max_bytes:
        raise CookieFileTooLarge(
            f"Cookies file is too large (maximum {max_bytes // 1024} KB)"
        )
    if "\x00" in raw_text:
        raise CookieFileValidationError("Cookies file contains invalid data")

    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized.removeprefix("\ufeff")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != NETSCAPE_COOKIE_HEADER:
        raise CookieFileValidationError(
            f"Cookies file must start with '{NETSCAPE_COOKIE_HEADER}'"
        )
    lines[0] = NETSCAPE_COOKIE_HEADER

    cookie_count = 0
    youtube_cookie_count = 0
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        is_http_only = line.startswith("#HttpOnly_")
        if line.startswith("#") and not is_http_only:
            continue

        fields = line.split("\t")
        if len(fields) != 7:
            raise CookieFileValidationError(
                f"Invalid Netscape cookie row at line {line_number}"
            )
        domain, include_subdomains, path, secure, expires, name, _value = fields
        if is_http_only:
            domain = domain.removeprefix("#HttpOnly_")
        if not domain or include_subdomains.upper() not in {"TRUE", "FALSE"}:
            raise CookieFileValidationError(
                f"Invalid Netscape cookie row at line {line_number}"
            )
        if not path.startswith("/") or secure.upper() not in {"TRUE", "FALSE"}:
            raise CookieFileValidationError(
                f"Invalid Netscape cookie row at line {line_number}"
            )
        if not expires.isdigit() or not name:
            raise CookieFileValidationError(
                f"Invalid Netscape cookie row at line {line_number}"
            )

        cookie_count += 1
        normalized_domain = domain.casefold().lstrip(".").rstrip(".")
        if normalized_domain == "youtube.com" or normalized_domain.endswith(
            ".youtube.com"
        ):
            youtube_cookie_count += 1

    if cookie_count == 0:
        raise CookieFileValidationError("Cookies file does not contain any cookie rows")
    if youtube_cookie_count == 0:
        raise CookieFileValidationError(
            "Cookies file must contain at least one youtube.com cookie"
        )

    normalized = "\n".join(lines).rstrip("\n") + "\n"
    return CookieFileSummary(
        normalized_text=normalized,
        size_bytes=len(normalized.encode("utf-8")),
        cookie_count=cookie_count,
        youtube_cookie_count=youtube_cookie_count,
    )


def atomic_write_private(target: Path, text: str) -> None:
    """Atomically replace ``target`` with a UTF-8 file private to its owner."""

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except Exception:
        if fd >= 0:
            os.close(fd)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
