"""Small, policy-driven wrapper around the :command:`yt-dlp` CLI.

The wrapper deliberately starts every logical operation without browser
cookies.  If (and only if) YouTube reports that authentication is required, it
retries once with the configured Netscape cookie file.  This avoids needlessly
sending account cookies with every request while still supporting restricted
videos.

Proxy configuration is provider agnostic:

* ``YTDLP_PROXY_POOL`` is a comma/newline-separated list.  Entries are selected
  round-robin, once per logical operation.
* ``YTDLP_PROXY_URL`` is the single-proxy fallback when the pool is empty.

Proxy URLs are passed directly to yt-dlp's ``--proxy`` option and are never
written to application logs.
"""
from __future__ import annotations

import itertools
import logging
import os
import re
import subprocess
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence


logger = logging.getLogger(__name__)

DEFAULT_COOKIES_PATH = "/home/botuser/cookies.txt"
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_HTTP_SLEEP_SECONDS = 0.75


class YtDlpFailureKind(str, Enum):
    """Stable failure categories callers may use without parsing yt-dlp text."""

    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    GEO_RESTRICTED = "geo_restricted"
    NETWORK = "network"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class YtDlpError(RuntimeError):
    """A yt-dlp failure with a user-safe message and private diagnostics.

    ``str(error)`` is intentionally concise and suitable for an API response.
    ``diagnostic`` contains the complete, credential-redacted stderr for
    server-side troubleshooting.
    """

    def __init__(
        self,
        *,
        operation: str,
        kind: YtDlpFailureKind,
        public_message: str,
        diagnostic: str,
        returncode: int | None,
    ) -> None:
        super().__init__(public_message)
        self.operation = operation
        self.kind = kind
        self.public_message = public_message
        self.diagnostic = diagnostic
        self.returncode = returncode


_proxy_counter = itertools.count()
_proxy_lock = threading.Lock()
_pace_lock = threading.Lock()
_last_request_started = 0.0


def configured_proxies(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return configured proxy URLs, with the pool taking precedence.

    Pool order is preserved and blank/duplicate entries are discarded.  Both
    commas and line breaks are accepted so multiline secret values work too.
    """

    source = os.environ if env is None else env
    raw_pool = source.get("YTDLP_PROXY_POOL", "")
    candidates = re.split(r"[,\r\n]+", raw_pool)
    pool = tuple(dict.fromkeys(item.strip() for item in candidates if item.strip()))
    if pool:
        return pool

    single = source.get("YTDLP_PROXY_URL", "").strip()
    return (single,) if single else ()


def _proxy_routes(env: Mapping[str, str] | None = None) -> tuple[str | None, ...]:
    """Return this call's routes, rotated to its round-robin start position."""

    proxies = configured_proxies(env)
    if not proxies:
        return (None,)
    with _proxy_lock:
        index = next(_proxy_counter)
    start = index % len(proxies)
    return proxies[start:] + proxies[:start]


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _pace_requests(env: Mapping[str, str] | None = None) -> None:
    """Keep starts of separate yt-dlp processes a modest distance apart."""

    global _last_request_started
    source = os.environ if env is None else env
    interval = _positive_float(
        source.get("YTDLP_REQUEST_INTERVAL_SECONDS"),
        DEFAULT_REQUEST_INTERVAL_SECONDS,
    )
    if interval <= 0:
        return

    with _pace_lock:
        now = time.monotonic()
        wait_for = interval - (now - _last_request_started)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_request_started = time.monotonic()


_CREDENTIAL_URL_RE = re.compile(
    r"(?i)\b((?:https?|socks(?:4a?|5h?))://)([^\s/@:]+):([^\s/@]+)@"
)


def _redact_sensitive(text: str, proxy: str | None = None) -> str:
    """Remove proxy credentials while retaining useful yt-dlp diagnostics."""

    safe = text or ""
    if proxy:
        safe = safe.replace(proxy, "<configured-proxy>")
    return _CREDENTIAL_URL_RE.sub(r"\1***:***@", safe)


def _classify_failure(output: str) -> YtDlpFailureKind:
    message = output.casefold()

    # A response can mention both cookies and rate limiting.  Rate limiting
    # takes precedence because resending account cookies cannot cure a 429.
    if any(
        marker in message
        for marker in (
            "http error 429",
            "http error 403",
            "request blocked",
            "request was blocked",
            "sign in to confirm you're not a bot",
            "sign in to confirm you’re not a bot",
            "too many requests",
            "rate limit",
            "rate-limit",
        )
    ):
        return YtDlpFailureKind.RATE_LIMITED

    if any(
        marker in message
        for marker in (
            "not available in your country",
            "not available in your region",
            "geo-restricted",
            "geographic restriction",
        )
    ):
        return YtDlpFailureKind.GEO_RESTRICTED

    if any(
        marker in message
        for marker in (
            "login required",
            "requires authentication",
            "use --cookies-from-browser or --cookies",
            "cookies for the authentication",
            "this video is private",
            "members-only content",
            "members only content",
            "confirm your age",
            "age-restricted",
        )
    ):
        return YtDlpFailureKind.AUTH_REQUIRED

    if any(
        marker in message
        for marker in (
            "video unavailable",
            "this video is unavailable",
            "has been removed",
            "copyright claim",
            "account associated with this video has been terminated",
            "unsupported url",
        )
    ):
        return YtDlpFailureKind.UNAVAILABLE

    if any(
        marker in message
        for marker in (
            "temporary failure in name resolution",
            "name or service not known",
            "connection refused",
            "connection reset",
            "connection timed out",
            "network is unreachable",
            "unable to connect",
            "proxyerror",
            "proxy error",
            "certificate verify failed",
            "http error 407",
            "http error 502",
            "http error 503",
            "http error 504",
            "proxy authentication required",
            "read timed out",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
    ):
        return YtDlpFailureKind.NETWORK

    return YtDlpFailureKind.UNKNOWN


def _public_message(kind: YtDlpFailureKind, operation: str) -> str:
    messages = {
        YtDlpFailureKind.AUTH_REQUIRED: (
            "YouTube requires sign-in for this video. Refresh the YouTube "
            "cookies and try again."
        ),
        YtDlpFailureKind.RATE_LIMITED: (
            "YouTube is temporarily rate-limiting this download route. "
            "Please try again shortly."
        ),
        YtDlpFailureKind.UNAVAILABLE: (
            "This YouTube video is unavailable, private, or restricted."
        ),
        YtDlpFailureKind.GEO_RESTRICTED: (
            "This YouTube video is not available from the configured region."
        ),
        YtDlpFailureKind.NETWORK: (
            "Could not reach YouTube through the configured download route. "
            "Please try again."
        ),
        YtDlpFailureKind.INVALID_RESPONSE: (
            "YouTube returned incomplete video information. Please try again."
        ),
        YtDlpFailureKind.UNKNOWN: (
            f"Could not {operation} from YouTube. Please try again."
        ),
    }
    return messages[kind]


def _cookies_path(env: Mapping[str, str] | None = None) -> Path | None:
    source = os.environ if env is None else env
    raw = source.get("YT_COOKIES_PATH", DEFAULT_COOKIES_PATH).strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _base_command(env: Mapping[str, str] | None = None) -> list[str]:
    source = os.environ if env is None else env
    http_sleep = _positive_float(
        source.get("YTDLP_HTTP_SLEEP_SECONDS"),
        DEFAULT_HTTP_SLEEP_SECONDS,
    )
    command = ["yt-dlp", "--ignore-config"]
    if http_sleep > 0:
        command += ["--sleep-requests", f"{http_sleep:g}"]
    return command


def _invoke(
    arguments: Sequence[str],
    *,
    operation: str,
    proxy: str | None,
    cookies: Path | None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = _base_command(env)
    if proxy:
        command += ["--proxy", proxy]
    if cookies is not None:
        command += ["--cookies", str(cookies)]
    command += list(arguments)

    route = "configured proxy" if proxy else "direct route"
    auth = "cookie retry" if cookies is not None else "anonymous"
    logger.info("Starting yt-dlp %s (%s, %s)", operation, route, auth)
    _pace_requests(env)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _diagnostic(process: subprocess.CompletedProcess[str], proxy: str | None) -> str:
    stderr = process.stderr or ""
    stdout = process.stdout or ""
    detail = stderr
    if stdout.strip():
        detail += ("\n[stdout]\n" if detail else "[stdout]\n") + stdout
    return _redact_sensitive(detail.rstrip(), proxy)


def _raise_failure(
    process: subprocess.CompletedProcess[str],
    *,
    operation: str,
    proxy: str | None,
) -> None:
    diagnostic = _diagnostic(process, proxy)
    kind = _classify_failure(diagnostic)
    logger.error(
        "yt-dlp %s failed (%s, exit=%s)\n%s",
        operation,
        kind.value,
        process.returncode,
        diagnostic,
    )
    raise YtDlpError(
        operation=operation,
        kind=kind,
        public_message=_public_message(kind, operation),
        diagnostic=diagnostic,
        returncode=process.returncode,
    )


def run_ytdlp(
    arguments: Sequence[str],
    *,
    operation: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one yt-dlp operation, failing over transient proxy-route errors.

    Every route starts anonymously. Cookies are tried only after an explicit
    authentication-required response, and only on that same route. Rate-limit
    and network failures move to the next configured pool route; content-level
    failures stop immediately.
    """

    cookies = _cookies_path(env)
    routes = _proxy_routes(env)
    retryable_route_failures = {
        YtDlpFailureKind.RATE_LIMITED,
        YtDlpFailureKind.NETWORK,
    }

    for route_index, proxy in enumerate(routes):
        process = _invoke(
            arguments,
            operation=operation,
            proxy=proxy,
            cookies=None,
            env=env,
        )
        if process.returncode == 0:
            return process

        diagnostic = _diagnostic(process, proxy)
        kind = _classify_failure(diagnostic)
        if kind is YtDlpFailureKind.AUTH_REQUIRED and cookies is not None:
            logger.warning(
                "Anonymous yt-dlp %s requires authentication; retrying with "
                "configured cookies. Full anonymous diagnostic:\n%s",
                operation,
                diagnostic,
            )
            process = _invoke(
                arguments,
                operation=operation,
                proxy=proxy,
                cookies=cookies,
                env=env,
            )
            if process.returncode == 0:
                return process
            diagnostic = _diagnostic(process, proxy)
            kind = _classify_failure(diagnostic)

        has_another_route = route_index + 1 < len(routes)
        if kind in retryable_route_failures and has_another_route:
            logger.warning(
                "yt-dlp %s route failed (%s); trying the next configured "
                "route. Full diagnostic:\n%s",
                operation,
                kind.value,
                diagnostic,
            )
            continue

        _raise_failure(process, operation=operation, proxy=proxy)

    raise AssertionError("yt-dlp route sequence was unexpectedly empty")


def invalid_response_error(operation: str, diagnostic: str) -> YtDlpError:
    """Build a typed failure for a successful command with malformed output."""

    safe_diagnostic = _redact_sensitive(diagnostic)
    logger.error("Invalid yt-dlp %s output\n%s", operation, safe_diagnostic)
    return YtDlpError(
        operation=operation,
        kind=YtDlpFailureKind.INVALID_RESPONSE,
        public_message=_public_message(YtDlpFailureKind.INVALID_RESPONSE, operation),
        diagnostic=safe_diagnostic,
        returncode=0,
    )


def _reset_runtime_state_for_tests() -> None:
    """Reset process-global rotation/pacing state (tests only)."""

    global _proxy_counter, _last_request_started
    with _proxy_lock:
        _proxy_counter = itertools.count()
    with _pace_lock:
        _last_request_started = 0.0
