#!/usr/bin/env bash
# Deploy the web app (Next.js + FastAPI) onto a VPS that already runs the
# Telegram bot via deploy.sh. Re-run-safe.
#
# Usage (as root or sudo):
#   cd /opt/video-notes-bot && sudo bash deploy-web.sh
#

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/video-notes-bot}"
BOT_USER="${BOT_USER:-botuser}"
API_SVC="cheatsheet-api"
WEB_SVC="cheatsheet-web"
WEB_PORT="${WEB_PORT:-3000}"

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: run as root or with sudo" >&2
  exit 1
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  echo "ERROR: $INSTALL_DIR is not a git checkout — run deploy.sh first" >&2
  exit 1
fi

echo "==> pulling latest code..."
sudo -u "$BOT_USER" git -C "$INSTALL_DIR" pull --rebase --autostash

# --- 1. Python deps -------------------------------------------------------
echo "==> installing/upgrading Python deps..."
sudo -u "$BOT_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade   -r "$INSTALL_DIR/requirements.txt"

echo "==> packaging latest desktop release..."
sudo -u "$BOT_USER" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/package_desktop_release.py"

# Verify the downloader runtime before spending time on the frontend build.
echo "==> downloader runtime..."
sudo -u "$BOT_USER" "$INSTALL_DIR/.venv/bin/python" -m yt_dlp --version
DENO_BIN="$(command -v deno || true)"
if [[ -z "$DENO_BIN" && -x "/home/$BOT_USER/.deno/bin/deno" ]]; then
  DENO_BIN="/home/$BOT_USER/.deno/bin/deno"
fi
if [[ -z "$DENO_BIN" ]]; then
  echo "ERROR: deno not found - rerun deploy.sh before deploy-web.sh" >&2
  exit 1
fi
sudo -u "$BOT_USER" "$DENO_BIN" --version

# YouTube egress proxy check
MANAGED_PROXY_FILE="/home/$BOT_USER/.config/cheetsheet/ytdlp_proxy_url"
if { [[ -f "$INSTALL_DIR/.env" ]] && grep -Eq '^YTDLP_PROXY_(URL|POOL)=.+' "$INSTALL_DIR/.env"; }   || [[ -s "$MANAGED_PROXY_FILE" ]]; then
  echo "==> YouTube egress proxy: configured"
else
  echo "WARN: YouTube egress proxy is not configured; datacenter-IP blocks may persist." >&2
fi

# --- 2. Next.js build ---
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node not found — deploy.sh should have installed Node 20" >&2
  exit 1
fi

NEXT_BUILD_DIR="$INSTALL_DIR/web/.next"
if [[ -L "$NEXT_BUILD_DIR" ]]; then
  echo "ERROR: refusing to modify symlinked build directory: $NEXT_BUILD_DIR" >&2
  exit 1
fi
if [[ -d "$NEXT_BUILD_DIR" ]]; then
  echo "==> repairing .next ownership for $BOT_USER..."
  chown -R "$BOT_USER:$BOT_USER" "$NEXT_BUILD_DIR"
fi
echo "==> installing npm deps + building web/ (this takes ~1 min)..."
sudo -u "$BOT_USER" -H bash -c "
  set -e
  cd $INSTALL_DIR/web
  npm ci --no-audit --no-fund --silent
  npm run build
"

# --- 3. systemd units ---
ENV_FILE_DIRECTIVE=""
if [[ -f "$INSTALL_DIR/.env" ]]; then
  ENV_FILE_DIRECTIVE="EnvironmentFile=$INSTALL_DIR/.env"
fi

echo "==> writing $API_SVC.service..."
cat > "/etc/systemd/system/$API_SVC.service" <<EOF
[Unit]
Description=Cheatsheet FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
Group=$BOT_USER
WorkingDirectory=$INSTALL_DIR
$ENV_FILE_DIRECTIVE
ExecStart=$INSTALL_DIR/.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
KillMode=process
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

echo "==> writing $WEB_SVC.service..."
cat > "/etc/systemd/system/$WEB_SVC.service" <<EOF
[Unit]
Description=Cheatsheet Next.js frontend
After=network-online.target $API_SVC.service
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
Group=$BOT_USER
WorkingDirectory=$INSTALL_DIR/web
$ENV_FILE_DIRECTIVE
Environment=PORT=$WEB_PORT
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$API_SVC.service"
systemctl restart "$API_SVC.service"
systemctl enable --now "$WEB_SVC.service"
systemctl restart "$WEB_SVC.service"

echo "==> Deployment complete!"
