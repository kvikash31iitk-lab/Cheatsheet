# Video Notes Bot

Telegram bot that turns YouTube videos into PDF cheatsheets and illustrated study books.

- **`/cheat <url>`** — 2-3 page condensed cheatsheet
- **`/book <url>`** — full chapter-by-chapter illustrated book with embedded screenshots
- **`/refresh <url>`** — bust cache, regenerate from scratch
- **`/status`** — show queue position

## Architecture

```
Telegram → bot/main.py (long-poll) → bot/worker.py (single-worker queue)
              │
              ▼
        scripts/transcribe_with_frames.py   (yt-dlp + ffmpeg + Groq Whisper)
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
| `AUTHORING_PROVIDER` | `claude_code` | Or `groq`/`openai`/`anthropic`. `claude_code` uses your Max sub via the headless CLI, no extra cost. |
| `WHISPER_BACKEND` | `groq` | Free-tier Whisper. Falls back to queuing on rate limits. |
| `WHITELISTED_GROUP_IDS` | (required) | Comma-separated Telegram chat IDs. Bot ignores everyone else. |
| `DAILY_CAP_CHEATSHEETS` | `0` | 0 = unlimited |
| `DAILY_CAP_BOOKS` | `0` | 0 = unlimited |
| `YTDLP_PROXY_URL` | (empty) | Authenticated production egress proxy used when YouTube blocks the VPS IP. URL-encode reserved characters in credentials. |
| `YTDLP_PROXY_POOL` | (empty) | Optional comma-separated proxy failover pool; takes precedence over `YTDLP_PROXY_URL`. |
| `YT_COOKIES_PATH` | `/home/botuser/cookies.txt` | Netscape cookies file used only for videos that genuinely require sign-in. Cookies do not bypass an IP-level HTTP 429 block. |

## Project layout

```
bot/             Telegram bot package (config, handlers, worker, author, cache, progress)
scripts/         Standalone-runnable pipeline scripts (also imported by the bot)
output/          Generated PDFs and markdown
work/            Per-video working dirs (gitignored)
cache/           Persistent cache by video ID (gitignored)
deploy.sh        Ubuntu VPS installer
```
