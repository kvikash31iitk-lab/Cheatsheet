"""Secure storage and source reporting for the managed yt-dlp proxy URL."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Literal, Mapping, TypedDict

from api.cookie_files import atomic_write_private
from scripts.ytdlp_client import (
    DEFAULT_PROXY_FILE,
    MAX_PROXY_FILE_BYTES,
    is_valid_proxy_url,
)


DEFAULT_MANAGED_PROXY_FILE = Path(DEFAULT_PROXY_FILE)
MAX_PROXY_URL_BYTES = MAX_PROXY_FILE_BYTES
SAFE_PROXY_VALIDATION_MESSAGE = (
    "Enter a valid http, https, socks5, or socks5h proxy URL with an explicit port."
)


class ProxyConfigurationError(ValueError):
    """A public-safe managed proxy configuration error."""


class ProxyManagedByEnvironment(ProxyConfigurationError):
    """Environment variables, rather than the admin file, own proxy state."""


class ProxyFileManagementDisabled(ProxyConfigurationError):
    """The deployment explicitly disabled managed proxy-file lookup."""


class ProxyStatus(TypedDict):
    proxy_configured: bool
    proxy_source: Literal["environment", "admin", "none"]


def environment_proxy_configured(env: Mapping[str, str] | None = None) -> bool:
    """Return whether a nonempty pool or single URL is configured in env."""

    source = os.environ if env is None else env
    pool_entries = re.split(r"[,\r\n]+", source.get("YTDLP_PROXY_POOL", ""))
    if any(entry.strip() for entry in pool_entries):
        return True
    return bool(source.get("YTDLP_PROXY_URL", "").strip())


def managed_proxy_file(env: Mapping[str, str] | None = None) -> Path | None:
    """Resolve the managed secret path; an explicitly blank override disables it."""

    source = os.environ if env is None else env
    if "YTDLP_PROXY_FILE" in source:
        configured = source.get("YTDLP_PROXY_FILE", "").strip()
        if not configured:
            return None
        return Path(configured)
    return DEFAULT_MANAGED_PROXY_FILE


def validate_proxy_url(proxy_url: str) -> str:
    """Validate a proxy URL without ever including it in an exception."""

    try:
        encoded_size = len(proxy_url.encode("utf-8"))
    except (AttributeError, UnicodeError):
        raise ProxyConfigurationError(SAFE_PROXY_VALIDATION_MESSAGE) from None
    if encoded_size == 0 or encoded_size > MAX_PROXY_URL_BYTES:
        raise ProxyConfigurationError(SAFE_PROXY_VALIDATION_MESSAGE)
    if not is_valid_proxy_url(proxy_url):
        raise ProxyConfigurationError(SAFE_PROXY_VALIDATION_MESSAGE)
    return proxy_url


def _read_valid_managed_proxy(target: Path) -> str | None:
    """Read a private managed file, returning no diagnostics or secret values."""

    try:
        if target.is_symlink() or not target.is_file():
            return None
        file_stat = target.stat()
        if file_stat.st_size <= 0 or file_stat.st_size > MAX_PROXY_URL_BYTES:
            return None
        if os.name != "nt" and stat.S_IMODE(file_stat.st_mode) & 0o077:
            return None
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    try:
        return validate_proxy_url(text)
    except ProxyConfigurationError:
        return None


def managed_proxy_status(env: Mapping[str, str] | None = None) -> ProxyStatus:
    """Return only whether a proxy is configured and its non-secret source."""

    if environment_proxy_configured(env):
        return {"proxy_configured": True, "proxy_source": "environment"}

    target = managed_proxy_file(env)
    if target is not None and _read_valid_managed_proxy(target) is not None:
        return {"proxy_configured": True, "proxy_source": "admin"}
    return {"proxy_configured": False, "proxy_source": "none"}



def _prepare_managed_proxy_parent(target: Path) -> None:
    """Create and lock down only the dedicated proxy-secret directory."""

    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise OSError("Managed proxy directory is not a private directory")
    if os.name != "nt" and parent.name == "cheetsheet":
        os.chmod(parent, 0o700)


def save_managed_proxy(
    proxy_url: str,
    env: Mapping[str, str] | None = None,
) -> ProxyStatus:
    """Validate and atomically save one private proxy URL."""

    if environment_proxy_configured(env):
        raise ProxyManagedByEnvironment(
            "Proxy configuration is managed by the server environment."
        )
    target = managed_proxy_file(env)
    if target is None:
        raise ProxyFileManagementDisabled(
            "Admin-managed proxy storage is disabled by the server environment."
        )

    validated = validate_proxy_url(proxy_url)
    _prepare_managed_proxy_parent(target)
    atomic_write_private(target, validated)
    return managed_proxy_status(env)


def remove_managed_proxy(
    env: Mapping[str, str] | None = None,
) -> ProxyStatus:
    """Atomically remove the admin-managed secret when environment allows it."""

    if environment_proxy_configured(env):
        raise ProxyManagedByEnvironment(
            "Proxy configuration is managed by the server environment."
        )
    target = managed_proxy_file(env)
    if target is not None:
        target.unlink(missing_ok=True)
    return managed_proxy_status(env)
