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

# === backends ================================================================
WHISPER_BACKEND = os.environ.get("WHISPER_BACKEND", "groq").strip().lower()
AUTHORING_PROVIDER = os.environ.get("AUTHORING_PROVIDER", "groq").strip().lower()
AUTHORING_MODEL = os.environ.get("AUTHORING_MODEL", "llama-3.3-70b-versatile").strip()
# Path to Claude Code binary. Empty = "claude" on PATH (Linux VPS default).
CLAUDE_CODE_BIN = os.environ.get("CLAUDE_CODE_BIN", "").strip() or "claude"

# === paths ===================================================================
CACHE_ROOT = PROJECT_ROOT / "cache"
WORK_ROOT = PROJECT_ROOT / "work"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

CACHE_ROOT.mkdir(parents=True, exist_ok=True)
WORK_ROOT.mkdir(parents=True, exist_ok=True)


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
