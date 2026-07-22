"""Configuration loaded once from .env at the project root."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _int_env(name: str, default: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _id_list(name: str) -> list[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    out: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            print(f"[config] WARN: ignoring non-integer ID in {name}: {tok!r}")
    return out


# === credentials =============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

# === access ==================================================================
WHITELISTED_GROUP_IDS: list[int] = _id_list("WHITELISTED_GROUP_IDS")

# === caps ====================================================================
DAILY_CAP_CHEATSHEETS = _int_env("DAILY_CAP_CHEATSHEETS", 0)  # 0 = unlimited
DAILY_CAP_BOOKS = _int_env("DAILY_CAP_BOOKS", 0)

# Telegram's hosted Bot API only lets bots download files up to 20 MB. Keep a
# little headroom so the rejection happens in our own preflight, with a useful
# message, rather than halfway through Telegram's getFile/download flow.
TELEGRAM_UPLOAD_MAX_MB = min(
    19, max(1, _int_env("TELEGRAM_UPLOAD_MAX_MB", 19))
)
TELEGRAM_UPLOAD_MAX_BYTES = TELEGRAM_UPLOAD_MAX_MB * 1024 * 1024
TELEGRAM_UPLOAD_MIN_FREE_MB = max(
    256, _int_env("TELEGRAM_UPLOAD_MIN_FREE_MB", 1024)
)
TELEGRAM_UPLOAD_MIN_FREE_BYTES = TELEGRAM_UPLOAD_MIN_FREE_MB * 1024 * 1024

# === backends ================================================================
WHISPER_BACKEND = os.environ.get("WHISPER_BACKEND", "groq").strip().lower()
AUTHORING_PROVIDER = os.environ.get("AUTHORING_PROVIDER", "groq").strip().lower()
AUTHORING_MODEL = os.environ.get("AUTHORING_MODEL", "llama-3.3-70b-versatile").strip()
# Path to Claude Code binary. Empty = "claude" on PATH (Linux VPS default).
CLAUDE_CODE_BIN = os.environ.get("CLAUDE_CODE_BIN", "").strip() or "claude"

# === paths ===================================================================
CACHE_ROOT = PROJECT_ROOT / "cache"
WORK_ROOT = PROJECT_ROOT / "work"
UPLOAD_ROOT = WORK_ROOT / "_telegram_uploads"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

CACHE_ROOT.mkdir(parents=True, exist_ok=True)
WORK_ROOT.mkdir(parents=True, exist_ok=True)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
try:
    # Uploaded media can be private. The bot service owns this directory on
    # Linux; Windows ignores POSIX permission bits during local development.
    UPLOAD_ROOT.chmod(0o700)
except OSError:
    pass


def validate() -> list[str]:
    """Return a list of fatal config errors. Empty list = ok to start."""
    problems: list[str] = []
    if not TELEGRAM_BOT_TOKEN:
        problems.append("TELEGRAM_BOT_TOKEN missing in .env")
    if not GROQ_API_KEY:
        problems.append("GROQ_API_KEY missing — needed for Whisper transcription")
    if AUTHORING_PROVIDER == "groq" and not GROQ_API_KEY:
        problems.append("AUTHORING_PROVIDER=groq but GROQ_API_KEY is empty")
    if AUTHORING_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        problems.append("AUTHORING_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty")
    if AUTHORING_PROVIDER == "openai" and not OPENAI_API_KEY:
        problems.append("AUTHORING_PROVIDER=openai but OPENAI_API_KEY is empty")
    if not WHITELISTED_GROUP_IDS:
        problems.append("WHITELISTED_GROUP_IDS is empty — bot would respond nowhere")
    return problems
