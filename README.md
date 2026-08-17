# Video Notes Bot

Telegram bot that turns YouTube videos into PDF cheatsheets and illustrated study books.

- **`/cheat <url>`** — 2-3 page condensed cheatsheet
- **`/book <url>`** — full chapter-by-chapter illustrated book with embedded screenshots
- **`/refresh <url>`** — bust cache, regenerate from scratch
- **`/status`** — show queue position

If YouTube blocks the VPS route, send the actual audio/video file to the bot
and use the buttons attached to that upload. Hosted Bot API uploads are capped
at 19 MB and this local-media path never contacts YouTube.

For bare links and media posted in a group, either make the bot a group admin
or use BotFather → Bot Settings → Group Privacy → Turn off, then remove and
re-add the bot to the group. Otherwise Telegram delivers commands but may hide
ordinary group messages and uploads from the bot.

## Architecture

```
Telegram link/upload → bot/main.py (long-poll) → bot/worker.py (single-worker queue)
              │
              ▼
        scripts/transcribe_with_frames.py
        (links: yt-dlp; uploads: local file only; then ffmpeg + Whisper)
              │
              ▼
        bot/author.py  (Claude Code or Groq Llama writes markdown)
              │
              ▼
        scripts/build_cheatsheet.py / build_illustrated_book.py  (ReportLab → PDF)
              │
              ▼
        Telegram sendDocument
```

Cache is keyed by YouTube video ID; same URL twice serves the cached PDF instantly. `/refresh` busts it.

## Local quick-start (Windows / Linux)

```bash
# 1. System deps (Linux/Ubuntu)
sudo apt install -y ffmpeg python3-venv

# 2. The /watch skill (transcript pipeline depends on it)
git clone https://github.com/bradautomates/claude-video.git ~/.claude/skills/watch

# 3. Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Credentials
cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, GROQ_API_KEY, WHITELISTED_GROUP_IDS

# 5. Run
python -m bot.main
```

### One-paste local generator (Windows)

Copy a YouTube link, then double-click `Generate YTSummary.cmd`. If the
clipboard does not contain a link, the launcher asks you to paste one. The
validated PDF is saved as `output/pdf/YTsummary-<video_id>.pdf`.
When `.env` selects Ollama, the launcher starts the local Ollama service if it
is stopped and pulls the configured model once if it is missing.

The ingestion ladder is:

1. reuse a completed transcript/PDF from cache;
2. fetch a human or auto-generated caption track through the transcript API;
3. fetch caption JSON through several supported yt-dlp YouTube clients;
4. download resumable audio through the same client ladder and run Whisper;
5. use a configured proxy/cookie route only when one is explicitly available.

Each run records `data/local-runs/<video_id>/job.manifest.json`. A retry resumes
from reusable artifacts. Markdown and PDF quality gates reject empty, corrupt,
or leaked-reasoning output before the final PDF path is reported.

PowerShell/terminal equivalents:

```powershell
.\Generate-YTSummary.ps1 "https://youtu.be/<VIDEO_ID>"
python scripts/one_click_youtube.py "https://youtu.be/<VIDEO_ID>"
```

### Local end-to-end job runner (debug mode)

You can bypass Telegram and execute the whole URL pipeline directly:

```bash
python scripts/run_local_job.py https://www.youtube.com/watch?v=<VIDEO_ID> \
  --kind cheatsheet
# or
python scripts/run_local_job.py https://www.youtube.com/watch?v=<VIDEO_ID> \
  --kind book --features summary,mermaid --out-pdf data/local-runs/notes.pdf
```

Options:
- `--work-dir`: base folder for working files (`data/local-runs` by default)
- `--features`: comma-separated feature toggles (`summary`, `tldr`, `qna`, `mermaid`, `chapters`)
- `--force`: re-run transcript/frame stage even if cached artifacts are available
- `--json`: print result metadata as JSON (including `pdf_path` and `markdown_path`)
- `--no-progress`: quieter output

This is useful when you want to inspect or override individual stages. The
normal clipboard launcher above is the recommended path.

## VPS deployment

`deploy.sh` is a one-shot installer for fresh Ubuntu 22.04/24.04. See the script header for details. Run as root:

```bash
sudo bash deploy.sh
```

After installation, finish three manual steps:

1. Edit `/opt/video-notes-bot/.env` with your tokens.
2. Authenticate Claude Code interactively as the bot user (`sudo -u botuser -i claude`).
3. `sudo systemctl start video-notes-bot`.

## Config (`.env`)

See `.env.example`. Key knobs:

| Variable | Default | Note |
|---|---|---|
| `AUTHORING_PROVIDER` | `claude_code` | Or `codex_cli`/`ollama`/`groq`/`openai`/`anthropic`. `codex_cli` and `claude_code` use signed-in CLIs; both can fall back to Groq for expired CLI auth. |
| `AUTHORING_MODEL` | provider-specific | Use `qwen2.5:7b` with the local Ollama provider. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama API endpoint. |
| `WHISPER_BACKEND` | `groq` | Free-tier Whisper. Falls back to queuing on rate limits. |
| `WHITELISTED_GROUP_IDS` | (required) | Comma-separated Telegram chat IDs. Bot ignores everyone else. |
| `DAILY_CAP_CHEATSHEETS` | `0` | 0 = unlimited |
| `DAILY_CAP_BOOKS` | `0` | 0 = unlimited |
| `YTDLP_PROXY_URL` | (empty) | Authenticated production egress proxy used when YouTube blocks the VPS IP. URL-encode reserved characters in credentials. |
| `YTDLP_PROXY_POOL` | (empty) | Optional comma-separated proxy failover pool; takes precedence over `YTDLP_PROXY_URL`. |
| `YTDLP_NETWORK_RETRY_DELAYS_SECONDS` | `12,24,48` | Retry delays for a single proxy route when the failure looks transient network-related. |
| `YTDLP_PROXY_FILE` | `/home/botuser/.config/cheetsheet/ytdlp_proxy_url` | Private mode-0600 fallback containing one proxy URL. The admin UI can save/remove it when the environment proxy settings are empty. |
| `YT_COOKIES_PATH` | `/home/botuser/cookies.txt` | Netscape cookies file used only for videos that genuinely require sign-in. Cookies do not bypass an IP-level HTTP 429 block. |

Proxy precedence is `YTDLP_PROXY_POOL`, then `YTDLP_PROXY_URL`, then `YTDLP_PROXY_FILE`. Environment-managed proxies cannot be replaced from the admin UI, and the stored file URL is never returned by the API.

## Project layout

```
bot/             Telegram bot package (config, handlers, worker, author, cache, progress)
scripts/         Standalone-runnable pipeline scripts (also imported by the bot)
output/          Generated PDFs and markdown
work/            Per-video working dirs (gitignored)
cache/           Persistent cache by video ID (gitignored)
deploy.sh        Ubuntu VPS installer
```
