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
_raw_groq = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_API_KEYS = [k.strip() for k in (os.environ.get("GROQ_API_KEYS", "") or _raw_groq).split(",") if k.strip()]
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
def _valid_gemini_key(k: str) -> bool:
    return bool(k and len(k) > 10)

_raw_gemini = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
_raw_keys = [k.strip() for k in (os.environ.get("GEMINI_API_KEYS", "") or _raw_gemini).split(",") if k.strip()]
GEMINI_API_KEYS = [k for k in _raw_keys if _valid_gemini_key(k)]
if not GEMINI_API_KEYS and os.environ.get("CTTS_KEY", "").strip():
    GEMINI_API_KEYS = [os.environ.get("CTTS_KEY", "").strip()]
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""


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
_DEFAULT_AUTHORING_MODEL = (
    "qwen2.5:7b" if AUTHORING_PROVIDER == "ollama" else "llama-3.3-70b-versatile"
)
AUTHORING_MODEL = os.environ.get(
    "AUTHORING_MODEL", _DEFAULT_AUTHORING_MODEL
).strip()
GROQ_FALLBACK_MODELS = tuple(
    model.strip()
    for model in os.environ.get(
        "GROQ_FALLBACK_MODELS",
        "qwen/qwen3.8-27b,qwen/qwen3.6-27b,openai/gpt-oss-20b",
    ).split(",")
    if model.strip()
)
OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
).strip().rstrip("/")
# Path to Claude Code binary. Empty = "claude" on PATH (Linux VPS default).
CLAUDE_CODE_BIN = os.environ.get("CLAUDE_CODE_BIN", "").strip() or "claude"
CODEX_CLI_BIN = os.environ.get("CODEX_CLI_BIN", "").strip() or "codex"

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
    if WHISPER_BACKEND == "groq" and not GROQ_API_KEY:
        problems.append("GROQ_API_KEY missing — needed for Whisper transcription")
    if AUTHORING_PROVIDER == "groq" and not GROQ_API_KEY:
        problems.append("AUTHORING_PROVIDER=groq but GROQ_API_KEY is empty")
    if AUTHORING_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        problems.append("AUTHORING_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty")
    if AUTHORING_PROVIDER == "openai" and not OPENAI_API_KEY:
        problems.append("AUTHORING_PROVIDER=openai but OPENAI_API_KEY is empty")
    if AUTHORING_PROVIDER == "gemini" and not GEMINI_API_KEY:
        problems.append("AUTHORING_PROVIDER=gemini but GEMINI_API_KEY is empty")
    if not WHITELISTED_GROUP_IDS:
        problems.append("WHITELISTED_GROUP_IDS is empty — bot would respond nowhere")
    return problems
