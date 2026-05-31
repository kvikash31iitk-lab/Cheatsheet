#!/usr/bin/env bash
# Deploy the Telegram video-notes bot on a fresh Ubuntu 22.04 / 24.04 VPS.
#
# Usage (run on the VPS as root or with sudo):
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy.sh | bash
#   - or -
#   scp deploy.sh root@vps:/tmp/ && ssh root@vps 'bash /tmp/deploy.sh'
#
# What it does:
#   1. Installs system dependencies (Python 3.12, ffmpeg, Node.js, deno).
#   2. Clones (or updates) this repo into /opt/video-notes-bot.
#   3. Installs Python deps from requirements.txt into a venv.
#   4. Installs Claude Code via npm (https://claude.com/claude-code).
#   5. Drops a systemd unit to run the bot on boot.
#
# What it does NOT do automatically (needs your hands afterwards):
#   - Authenticate Claude Code with your Max account.
#     run:   sudo -u botuser -i bash -c 'cd /opt/video-notes-bot && claude'
#     Open the URL it prints, log in, paste the code back. One-time.
#   - Create /opt/video-notes-bot/.env. Use .env.example as template; the
#     installer copies it for you on first run.
#
# Re-run-safe: skips installs that already succeeded. Use --force-reinstall to
# wipe the venv and start over.

set -euo pipefail
shopt -s extglob

REPO_URL="${REPO_URL:-https://github.com/kvikash31iitk-lab/Cheatsheet.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/video-notes-bot}"
SERVICE_NAME="video-notes-bot"
BOT_USER="${BOT_USER:-botuser}"

echo "==> deploy.sh"
echo "  install dir: $INSTALL_DIR"
echo "  bot user:    $BOT_USER"
echo "  repo:        $REPO_URL"

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: run as root or with sudo" >&2
  exit 1
fi

# --- 1. system packages ----------------------------------------------------

echo "==> installing system packages..."
apt-get update -qq
apt-get install -y -qq \
  python3.12 python3.12-venv python3-pip \
  ffmpeg curl ca-certificates git \
  build-essential

# Node.js 20 (for npm-based Claude Code install)
if ! command -v node >/dev/null 2>&1; then
  echo "==> installing Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

# Deno (for yt-dlp's JS-runtime requirement on YouTube)
if ! command -v deno >/dev/null 2>&1; then
  echo "==> installing deno (yt-dlp JS runtime)..."
  curl -fsSL https://deno.land/install.sh | sh -s -- -y
  ln -sf /root/.deno/bin/deno /usr/local/bin/deno || true
fi

# --- 2. unprivileged user ---------------------------------------------------

if ! id "$BOT_USER" >/dev/null 2>&1; then
  echo "==> creating user $BOT_USER..."
  useradd --create-home --shell /bin/bash "$BOT_USER"
fi

# --- 3. clone repo / pull updates ------------------------------------------

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "==> updating existing checkout..."
  sudo -u "$BOT_USER" git -C "$INSTALL_DIR" pull --rebase --autostash
else
  echo "==> cloning $REPO_URL..."
  install -d -o "$BOT_USER" -g "$BOT_USER" "$INSTALL_DIR"
  sudo -u "$BOT_USER" git clone "$REPO_URL" "$INSTALL_DIR"
fi

# --- 4. python venv + deps -------------------------------------------------

VENV="$INSTALL_DIR/.venv"
if [[ "${1:-}" == "--force-reinstall" ]]; then
  rm -rf "$VENV"
fi

if [[ ! -d "$VENV" ]]; then
  echo "==> creating venv..."
  sudo -u "$BOT_USER" python3.12 -m venv "$VENV"
fi
echo "==> installing Python deps..."
sudo -u "$BOT_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$BOT_USER" "$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# --- 5. Claude Code CLI ----------------------------------------------------

if ! sudo -u "$BOT_USER" -i bash -c 'command -v claude' >/dev/null 2>&1; then
  echo "==> installing Claude Code via npm (global, for $BOT_USER)..."
  sudo -u "$BOT_USER" -i bash -c 'mkdir -p ~/.npm-global && npm config set prefix ~/.npm-global'
  sudo -u "$BOT_USER" -i bash -c 'npm install -g @anthropic-ai/claude-code'
  # Add to PATH for the bot user
  if ! sudo -u "$BOT_USER" grep -q npm-global /home/"$BOT_USER"/.bashrc 2>/dev/null; then
    echo 'export PATH="$HOME/.npm-global/bin:$PATH"' \
      | sudo tee -a /home/"$BOT_USER"/.bashrc >/dev/null
  fi
fi

# --- 5b. Mermaid CLI for the diagram PDF feature --------------------------
# `mmdc` renders mermaid code-fence blocks (mindmaps + flowcharts) to PNG
# so the PDF builders can embed them. Puppeteer's post-install pulls
# Chromium into ~/.cache/puppeteer/ — so it MUST run as $BOT_USER (the
# systemd units run as $BOT_USER, and Puppeteer looks up Chrome under
# $HOME). Installing as root with `npm install -g` would land Chrome in
# /root/.cache/puppeteer/ and mmdc would fail with "Could not find Chrome"
# at runtime. (Burned a deploy cycle on this 2026-05-31 — leaving the note.)
#
# Chromium also pulls in a handful of shared libs that aren't part of the
# base Ubuntu image (libnss3, libgbm1, etc.). Install those first so the
# Chromium post-install download isn't dead-on-arrival.
echo "==> installing Chromium shared libs (mmdc's bundled Chrome needs these)..."
apt-get install -y -qq \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2t64 2>/dev/null || \
  apt-get install -y -qq \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2  # fallback name on 22.04

# The "is it installed?" check is the Chrome cache, NOT `command -v mmdc`:
# a previous deploy may have installed mmdc system-wide as root (putting
# Chrome in /root/.cache/puppeteer/), in which case mmdc IS on PATH for
# everyone but botuser can't read root's home and Puppeteer fails to find
# Chrome at runtime. The per-user cache dir is the actual marker of
# "ready to render."
if [[ ! -d "/home/$BOT_USER/.cache/puppeteer/chrome" ]]; then
  echo "==> installing @mermaid-js/mermaid-cli via npm (per-user, for $BOT_USER)..."
  sudo -u "$BOT_USER" -i bash -c 'npm install -g @mermaid-js/mermaid-cli'
  # Verify Chrome actually landed. Surface a clear error here rather than
  # have the first user-triggered render fail 6 hours from now.
  if [[ ! -d "/home/$BOT_USER/.cache/puppeteer/chrome" ]]; then
    echo "  WARN: Chrome cache STILL missing at /home/$BOT_USER/.cache/puppeteer/"
    echo "  WARN: mmdc will fail at render time. Recover manually with:"
    echo "    sudo -u $BOT_USER -i bash -c 'npx puppeteer browsers install chrome'"
  fi
fi

# --- 6. The /watch skill (transcribe pipeline depends on it) --------------

WATCH_DIR="/home/$BOT_USER/.claude/skills/watch"
if [[ ! -d "$WATCH_DIR/scripts" ]]; then
  echo "==> cloning bradautomates/claude-video into ~/.claude/skills/watch..."
  sudo -u "$BOT_USER" -H mkdir -p "/home/$BOT_USER/.claude/skills"
  sudo -u "$BOT_USER" -H git clone --depth 1 \
    https://github.com/bradautomates/claude-video.git "$WATCH_DIR"
fi
# (Skipping the Windows cp1252 patches — Linux has UTF-8 by default.)

# --- 7. .env scaffold ------------------------------------------------------

ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> writing $ENV_FILE.example (you must edit and copy to .env)..."
  cat > "$ENV_FILE.example" <<'EOF'
TELEGRAM_BOT_TOKEN=
WHITELISTED_GROUP_IDS=
GROQ_API_KEY=
AUTHORING_PROVIDER=claude_code
# 70b-versatile has a 131K context window — needed for real transcripts.
# The older 8b-instant default (6K TPM cap on the free tier) silently
# fails on anything longer than ~15 minutes of audio with a 413.
AUTHORING_MODEL=llama-3.3-70b-versatile
WHISPER_BACKEND=groq
DAILY_CAP_CHEATSHEETS=0
DAILY_CAP_BOOKS=0
CLAUDE_CODE_BIN=
EOF
  chown "$BOT_USER:$BOT_USER" "$ENV_FILE.example"
  chmod 600 "$ENV_FILE.example"
  echo "    cp $ENV_FILE.example $ENV_FILE"
  echo "    nano $ENV_FILE   # paste credentials"
fi

# Also configure Groq key in the watch skill's expected location.
WATCH_ENV="/home/$BOT_USER/.config/watch/.env"
if [[ ! -f "$WATCH_ENV" ]]; then
  sudo -u "$BOT_USER" -i mkdir -p "/home/$BOT_USER/.config/watch"
  sudo -u "$BOT_USER" -i bash -c "echo 'GROQ_API_KEY=' > '$WATCH_ENV' && chmod 600 '$WATCH_ENV'"
  echo "==> created $WATCH_ENV (paste your GROQ_API_KEY there too)"
fi

# --- 8. systemd service ----------------------------------------------------

UNIT="/etc/systemd/system/$SERVICE_NAME.service"
echo "==> writing systemd unit $UNIT..."
cat > "$UNIT" <<EOF
[Unit]
Description=Video Notes Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python -u -m bot.main
Restart=on-failure
RestartSec=15
Environment=PATH=$VENV/bin:/home/$BOT_USER/.npm-global/bin:/home/$BOT_USER/.deno/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

cat <<EOF

==> Done.

Next steps (manual):
  1. Edit credentials:
       sudo -u $BOT_USER nano $ENV_FILE          # bot keys + whitelist
       sudo -u $BOT_USER nano $WATCH_ENV         # GROQ_API_KEY=gsk_...

  2. Authenticate Claude Code (one-time, copy the URL it prints to your laptop browser):
       sudo -u $BOT_USER -i claude
       (log in with your Max account, then exit)

  3. Start the bot:
       sudo systemctl start $SERVICE_NAME
       sudo journalctl -u $SERVICE_NAME -f      # tail logs

  4. Verify in your Telegram group: send /cheat <youtube-url>
EOF
