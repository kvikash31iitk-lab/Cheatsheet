"""Strict validation for public YouTube URLs accepted by admin operations."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_PATH_ID_RE = re.compile(
    r"^/(?:embed|shorts|live)/([A-Za-z0-9_-]{11})(?:/|$)"
)


def validate_public_youtube_url(raw_url: str) -> str:
    """Return a trimmed HTTPS YouTube URL or raise a value-safe ``ValueError``."""

    url = raw_url.strip()
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise ValueError("Enter a valid public YouTube URL") from None

    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in _ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("Enter a valid public YouTube URL")

    video_id: str | None = None
    if host in {"youtu.be", "www.youtu.be"}:
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            video_id = path_parts[0]
    else:
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id is None:
            match = _PATH_ID_RE.match(parsed.path)
            if match:
                video_id = match.group(1)

    if not video_id or _VIDEO_ID_RE.fullmatch(video_id) is None:
        raise ValueError("Enter a valid public YouTube URL")
    return url
