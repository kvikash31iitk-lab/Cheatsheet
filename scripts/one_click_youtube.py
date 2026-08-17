#!/usr/bin/env python3
"""Clipboard/paste entry point for the complete local YouTube-to-PDF job."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_local_job import run_url_job  # noqa: E402
from scripts.transcribe_with_frames import extract_video_id  # noqa: E402
from bot import config as bot_config  # noqa: E402


URL_RE = re.compile(r"https://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)
DEFAULT_FEATURES = ["summary", "tldr", "qna", "chapters"]


def _ollama_models() -> set[str]:
    endpoint = f"{bot_config.OLLAMA_BASE_URL}/api/tags"
    request = Request(endpoint, headers={"User-Agent": "YTsummary/1.0"})
    with urlopen(request, timeout=3) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    return {
        str(item.get("name") or "")
        for item in payload.get("models") or []
        if isinstance(item, dict)
    }


def _ensure_authoring_ready() -> None:
    """Start the configured local authoring service when possible."""

    if bot_config.AUTHORING_PROVIDER != "ollama":
        return
    try:
        models = _ollama_models()
    except Exception:
        executable = shutil.which("ollama")
        if not executable:
            raise RuntimeError(
                "Ollama is required by .env but is not installed or on PATH"
            ) from None
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        subprocess.Popen(
            [executable, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        for _ in range(30):
            time.sleep(1)
            try:
                models = _ollama_models()
                break
            except Exception:
                continue
        else:
            raise RuntimeError("Ollama did not become ready within 30 seconds")

    model = bot_config.AUTHORING_MODEL
    if model in models or any(name.split("@", 1)[0] == model for name in models):
        return
    executable = shutil.which("ollama")
    if not executable:
        raise RuntimeError(f"Ollama model {model!r} is not installed")
    print(f"First-time setup: downloading Ollama model {model}...")
    subprocess.run([executable, "pull", model], check=True)


def _clipboard_text() -> str:
    if sys.platform != "win32":
        return ""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-Clipboard -Raw",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _choose_url(explicit: str | None) -> str:
    candidate = explicit or _clipboard_text()
    match = URL_RE.search(candidate or "")
    if match:
        return match.group(0).rstrip(")]}>.,;\"'")
    if sys.stdin.isatty():
        entered = input("Paste a YouTube link and press Enter: ").strip()
        match = URL_RE.search(entered)
        if match:
            return match.group(0).rstrip(")]}>.,;\"'")
    raise ValueError("No public YouTube link was supplied or found on the clipboard")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read a YouTube URL from the argument or clipboard and create a PDF."
    )
    parser.add_argument("url", nargs="?", help="Optional URL; clipboard is used if omitted")
    parser.add_argument(
        "--kind", choices=("cheatsheet", "book"), default="cheatsheet"
    )
    parser.add_argument(
        "--features",
        default=",".join(DEFAULT_FEATURES),
        help="Comma-separated output extras",
    )
    parser.add_argument(
        "--force", action="store_true", help="Ignore the shared transcript cache"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        url = _choose_url(args.url)
        video_id = extract_video_id(url)
        _ensure_authoring_ready()
        output_dir = PROJECT_ROOT / "output"
        pdf_dir = output_dir / "pdf"
        markdown_dir = output_dir / "markdown"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        markdown_dir.mkdir(parents=True, exist_ok=True)
        features = [item.strip() for item in args.features.split(",") if item.strip()]
        result = run_url_job(
            url,
            kind=args.kind,
            output_pdf=pdf_dir / f"YTsummary-{video_id}.pdf",
            output_md=markdown_dir / f"YTsummary-{video_id}.md",
            features=features,
            use_cached_pipeline=not args.force,
            progress=True,
        )
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nYTsummary failed: {exc}", file=sys.stderr)
        print(
            "The completed stages remain cached; run the same link again to resume.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("\nPDF READY")
    print(result["pdf_path"])
    print(f"Pages: {result['pdf_pages']} | source: {result['transcript_provider']}")


if __name__ == "__main__":
    main()
