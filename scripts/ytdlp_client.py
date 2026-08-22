"""Small, policy-driven wrapper around the :command:`yt-dlp` CLI.

The wrapper deliberately starts every logical operation without browser
cookies. If YouTube reports that authentication is required, or the final
available route returns an explicit anti-bot sign-in challenge, it retries once
with the configured Netscape cookie file. This avoids needlessly sending
account cookies with every request while still supporting restricted videos.

Proxy configuration is provider agnostic:

* ``YTDLP_PROXY_POOL`` is a comma/newline-separated list.  Entries are selected
  round-robin, once per logical operation.
* ``YTDLP_PROXY_URL`` is the single-proxy fallback when the pool is empty.

Proxy URLs are passed directly to yt-dlp's ``--proxy`` option and are never
written to application logs.
"""
from __future__ import annotations

import ipaddress
import itertools
import logging
import os
import re
import subprocess
import stat
import sys
import threading
import time

from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)

DEFAULT_COOKIES_PATH = "/home/botuser/cookies.txt"
DEFAULT_PROXY_FILE = "/home/botuser/.config/cheetsheet/ytdlp_proxy_url"
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_HTTP_SLEEP_SECONDS = 0.75
DEFAULT_SOCKET_TIMEOUT_SECONDS = 20.0
DEFAULT_NETWORK_RETRY_DELAYS_SECONDS = (12.0, 24.0, 48.0)
DEFAULT_CLIENT_PROFILES = (
    "default",
    "android",
    "android_vr",
    "web_embedded",
    "tv",
)
MAX_PROXY_FILE_BYTES = 2048

_CLIENT_PROFILE_ARGS: dict[str, tuple[str, ...]] = {
    "default": (),
    "android": ("--extractor-args", "youtube:player_client=android"),
    "android_vr": ("--extractor-args", "youtube:player_client=android_vr"),
    "web_embedded": ("--extractor-args", "youtube:player_client=web_embedded"),
    "tv": ("--extractor-args", "youtube:player_client=tv"),
}


class YtDlpFailureKind(str, Enum):
    """Stable failure categories callers may use without parsing yt-dlp text."""

    AUTH_REQUIRED = "auth_required"
    MEMBERS_ONLY = "members_only"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    GEO_RESTRICTED = "geo_restricted"
    NETWORK = "network"
    CONFIGURATION = "configuration"
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


ALLOWED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})
_MALFORMED_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_DNS_LABEL_RE = re.compile(
    r"(?i)^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _is_valid_proxy_hostname(hostname: str) -> bool:
    """Validate a literal IP address or an IDNA-compatible DNS hostname."""

    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass

    # Reject malformed dotted-numeric hosts rather than interpreting them as
    # DNS names after strict IPv4 parsing fails.
    if "." in hostname and all(
        character.isdigit() or character == "." for character in hostname
    ):
        return False
    if hostname.startswith(".") or hostname.endswith("."):
        return False
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    labels = ascii_hostname.split(".")
    return all(_DNS_LABEL_RE.fullmatch(label) is not None for label in labels)


def is_valid_proxy_url(value: str) -> bool:
    """Return whether *value* is a supported, unambiguous proxy URL.

    This helper is safe for the admin upload boundary as well as the runtime
    reader. It never logs or returns any part of the supplied credential.
    """

    if not isinstance(value, str) or not value:
        return False
    if _MALFORMED_PERCENT_RE.search(value):
        return False
    if any(
        character == "," or character.isspace() or ord(character) < 32
        or ord(character) == 127
        for character in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() in ALLOWED_PROXY_SCHEMES
        and parsed.hostname
        and _is_valid_proxy_hostname(parsed.hostname)
        and port is not None
        and 0 < port <= 65535
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )

_PROXY_FILE_ERROR_CODES = frozenset(
    {
        "stat_failed",
        "symlink",
        "not_regular_file",
        "insecure_permissions",
        "changed_during_read",
        "read_failed",
        "too_large",
        "invalid_encoding",
        "invalid_format",
        "unknown",
    }
)


def _proxy_configuration_error(reason: str) -> YtDlpError:
    """Create a fail-closed error without exposing a path or file contents."""

    code = reason if reason in _PROXY_FILE_ERROR_CODES else "unknown"
    diagnostic = f"proxy_file:{code}"
    logger.error("yt-dlp proxy secret file is unusable (%s)", code)
    return YtDlpError(
        operation="configure YouTube download proxy",
        kind=YtDlpFailureKind.CONFIGURATION,
        public_message=(
            "The YouTube download proxy is unavailable. Contact an administrator."
        ),
        diagnostic=diagnostic,
        returncode=None,
    )


def _proxy_from_secret_file(source: Mapping[str, str]) -> tuple[str, ...]:
    """Read one private proxy URL, fresh for each logical yt-dlp operation."""

    if "YTDLP_PROXY_FILE" in source:
        raw_path = source.get("YTDLP_PROXY_FILE", "")
        if not raw_path.strip():
            return ()
    else:
        raw_path = DEFAULT_PROXY_FILE
    path = Path(raw_path.strip())

    try:
        file_info = path.lstat()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise _proxy_configuration_error("stat_failed") from exc

    if stat.S_ISLNK(file_info.st_mode):
        raise _proxy_configuration_error("symlink")
    if not stat.S_ISREG(file_info.st_mode):
        raise _proxy_configuration_error("not_regular_file")
    if os.name != "nt" and stat.S_IMODE(file_info.st_mode) & 0o077:
        raise _proxy_configuration_error("insecure_permissions")

    try:
        with path.open("rb") as handle:
            opened_info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_info.st_mode)
                or opened_info.st_dev != file_info.st_dev
                or opened_info.st_ino != file_info.st_ino
            ):
                raise _proxy_configuration_error("changed_during_read")
            raw = handle.read(MAX_PROXY_FILE_BYTES + 1)
    except FileNotFoundError as exc:
        raise _proxy_configuration_error("changed_during_read") from exc
    except OSError as exc:
        raise _proxy_configuration_error("read_failed") from exc

    if len(raw) > MAX_PROXY_FILE_BYTES:
        raise _proxy_configuration_error("too_large")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _proxy_configuration_error("invalid_encoding") from exc

    if decoded.endswith("\r\n"):
        proxy = decoded[:-2]
    elif decoded.endswith("\n"):
        proxy = decoded[:-1]
    else:
        proxy = decoded
    if (
        not proxy
        or proxy != proxy.strip()
        or not is_valid_proxy_url(proxy)
    ):
        raise _proxy_configuration_error("invalid_format")
    return (proxy,)


def configured_proxies(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return proxy routes in env-pool, env-URL, private-file precedence.

    Pool order is preserved and blank/duplicate entries are discarded.  Both
    commas and line breaks are accepted so multiline environment secrets work.
    The private file is consulted only when neither environment route is set.
    """

    source = os.environ if env is None else env
    raw_pool = source.get("YTDLP_PROXY_POOL", "")
    candidates = re.split(r"[,\r\n]+", raw_pool)
    pool = tuple(dict.fromkeys(item.strip() for item in candidates if item.strip()))
    if pool:
        return pool

    single = source.get("YTDLP_PROXY_URL", "").strip()
    if single:
        return (single,)
    return _proxy_from_secret_file(source)


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


def _network_retry_delays(
    env: Mapping[str, str] | None = None,
) -> tuple[float, ...]:
    """Return bounded delays for retrying a temporarily unavailable route."""

    source = os.environ if env is None else env
    if "YTDLP_NETWORK_RETRY_DELAYS_SECONDS" not in source:
        return DEFAULT_NETWORK_RETRY_DELAYS_SECONDS

    values: list[float] = []
    for item in source.get("YTDLP_NETWORK_RETRY_DELAYS_SECONDS", "").split(","):
        try:
            delay = float(item.strip())
        except ValueError:
            continue
        if 0 <= delay <= 120:
            values.append(delay)
    return tuple(values[:3]) or DEFAULT_NETWORK_RETRY_DELAYS_SECONDS


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
            "members-only content",
            "members only content",
            "members-only video",
            "members only video",
            "join this channel to get access",
            "available to channel members",
            "member-only",
            "member only",
            "available to this channel's members",
            "available to this channel?s members",
            "membership level",
        )
    ):
        return YtDlpFailureKind.MEMBERS_ONLY

    if any(
        marker in message
        for marker in (
            "login required",
            "requires authentication",
            "use --cookies-from-browser or --cookies",
            "cookies for the authentication",
            "this video is private",
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


def _is_explicit_bot_challenge(output: str) -> bool:
    """Return whether YouTube explicitly asks this client to sign in as human."""

    message = output.casefold()
    return any(
        marker in message
        for marker in (
            "sign in to confirm you're not a bot",
            "sign in to confirm you are not a bot",
            "sign in to confirm youâ€™re not a bot",
        )
    )


def _public_message(kind: YtDlpFailureKind, operation: str) -> str:
    messages = {
        YtDlpFailureKind.AUTH_REQUIRED: (
            "YouTube requires sign-in for this video. Refresh the YouTube "
            "cookies and try again."
        ),
        YtDlpFailureKind.MEMBERS_ONLY: (
            "This YouTube video is members-only. The configured YouTube account "
            "must be a paid member of this channel. Refresh the cookies only if "
            "that account has access."
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
        YtDlpFailureKind.CONFIGURATION: (
            "The YouTube download proxy is unavailable. Contact an administrator."
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
    # Prefer venv-relative yt-dlp binary if running inside virtualenv
    executable = "yt-dlp"
    venv_ytdlp = Path(sys.executable).parent / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    if venv_ytdlp.exists():
        executable = str(venv_ytdlp)

    command = [executable, "--ignore-config"]

    # Current YouTube extraction requires an external JS runtime plus the EJS
    # solver component. Node 22+ is supported and already part of the local
    # engine setup; an empty value explicitly disables this option.
    js_runtime = source.get("YTDLP_JS_RUNTIME", "node").strip()
    if js_runtime:
        command += ["--js-runtimes", js_runtime]
    if http_sleep > 0:
        command += ["--sleep-requests", f"{http_sleep:g}"]
    socket_timeout = _positive_float(
        source.get("YTDLP_SOCKET_TIMEOUT_SECONDS"),
        DEFAULT_SOCKET_TIMEOUT_SECONDS,
    )
    if socket_timeout > 0:
        command += ["--socket-timeout", f"{socket_timeout:g}"]
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
    and network failures move to the next configured pool route. When only one
    route remains, transient network failures are retried after a delay so an
    SSH relay has time to reconnect. Content-level failures stop immediately.
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
        has_another_route = route_index + 1 < len(routes)

        if kind is YtDlpFailureKind.NETWORK and not has_another_route:
            for delay in _network_retry_delays(env):
                logger.warning(
                    "yt-dlp %s route is temporarily unavailable; retrying "
                    "the same route in %.1fs. Full diagnostic:\n%s",
                    operation,
                    delay,
                    diagnostic,
                )
                time.sleep(delay)
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
                if kind is not YtDlpFailureKind.NETWORK:
                    break

        cookie_retry_allowed = kind in {
            YtDlpFailureKind.AUTH_REQUIRED,
            YtDlpFailureKind.MEMBERS_ONLY,
        } or (
            kind is YtDlpFailureKind.RATE_LIMITED
            and not has_another_route
            and _is_explicit_bot_challenge(diagnostic)
        )
        if cookie_retry_allowed and cookies is not None:
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


def youtube_client_profiles(
    env: Mapping[str, str] | None = None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return the bounded YouTube extractor-client fallback sequence."""

    source = os.environ if env is None else env
    raw = source.get("YTDLP_CLIENT_PROFILES", "").strip()
    names = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not names:
        names = list(DEFAULT_CLIENT_PROFILES)
    ordered = tuple(dict.fromkeys(name for name in names if name in _CLIENT_PROFILE_ARGS))
    if not ordered:
        ordered = ("default",)
    return tuple((name, _CLIENT_PROFILE_ARGS[name]) for name in ordered)


def run_ytdlp_profiles(
    arguments: Sequence[str],
    *,
    operation: str,
    env: Mapping[str, str] | None = None,
    on_profile=None,
) -> subprocess.CompletedProcess[str]:
    """Try safe extractor clients after a playback-route 403/429 failure.

    Proxy/cookie handling remains inside :func:`run_ytdlp`. Content-level
    failures stop immediately; only failures that another client can plausibly
    repair advance to the next profile.
    """

    profiles = youtube_client_profiles(env)
    last_error: YtDlpError | None = None
    retryable = {
        YtDlpFailureKind.RATE_LIMITED,
        YtDlpFailureKind.INVALID_RESPONSE,
        YtDlpFailureKind.UNKNOWN,
    }
    for index, (name, profile_args) in enumerate(profiles, 1):
        if on_profile is not None:
            on_profile(name, index, len(profiles))
        try:
            return run_ytdlp(
                [*profile_args, *arguments],
                operation=f"{operation} ({name} client)",
                env=env,
            )
        except YtDlpError as exc:
            last_error = exc
            if exc.kind not in retryable or index >= len(profiles):
                raise
            logger.warning(
                "yt-dlp %s failed with %s client (%s); trying the next "
                "extractor client",
                operation,
                name,
                exc.kind.value,
            )
    assert last_error is not None
    raise last_error


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
