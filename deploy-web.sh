#!/usr/bin/env bash
# Deploy the web app (Next.js + FastAPI) onto a VPS that already runs the
# Telegram bot via deploy.sh. Re-run-safe.
#
# Usage (as root or sudo):
#   cd /opt/video-notes-bot && sudo bash deploy-web.sh
#
# What it does:
#   1. Pulls latest code from the repo.
#   2. Installs new Python deps (fastapi, uvicorn, pydantic) into the venv.
#   3. Runs `npm ci` + `npm run build` in web/ as the bot user.
#   4. Drops two systemd units:
#        cheatsheet-api.service   (FastAPI on 127.0.0.1:8000)
#        cheatsheet-web.service   (Next.js on 0.0.0.0:3000)
#   5. Opens UFW port 3000 if UFW is active.
#   6. Prints the URL to visit.
#
# After running, the app is reachable at http://<VPS-IP>:3000 — no auth, no
# SSL. Stick a shared secret or nginx + TLS in front before sharing widely.

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
sudo -u "$BOT_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade \
  -r "$INSTALL_DIR/requirements.txt"

# --- 2. Next.js build (as bot user, with login shell so PATH has node) ---
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node not found — deploy.sh should have installed Node 20" >&2
  exit 1
fi

echo "==> installing npm deps + building web/ (this takes ~1 min)..."
sudo -u "$BOT_USER" -H bash -c "
  set -e
  cd $INSTALL_DIR/web
  npm ci --no-audit --no-fund --silent
  npm run build
"

# --- 3. systemd units -----------------------------------------------------

echo "==> writing $API_SVC.service..."
cat > "/etc/systemd/system/$API_SVC.service" <<EOF
[Unit]
Description=Cheatsheet FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10
Environment=PATH=$INSTALL_DIR/.venv/bin:/home/$BOT_USER/.npm-global/bin:/home/$BOT_USER/.deno/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=YT_COOKIES_PATH=/home/$BOT_USER/cookies.txt
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "==> writing $WEB_SVC.service..."
cat > "/etc/systemd/system/$WEB_SVC.service" <<EOF
[Unit]
Description=Cheatsheet Next.js frontend
After=network-online.target $API_SVC.service

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$INSTALL_DIR/web
ExecStart=/usr/bin/node $INSTALL_DIR/web/node_modules/next/dist/bin/next start -p $WEB_PORT -H 0.0.0.0
Restart=on-failure
RestartSec=10
Environment=NODE_ENV=production
Environment=PORT=$WEB_PORT
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$API_SVC" "$WEB_SVC"

# --- 4. firewall ----------------------------------------------------------

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  echo "==> opening UFW port $WEB_PORT/tcp..."
  ufw allow "$WEB_PORT/tcp" || true
fi

# --- 5. Summary -----------------------------------------------------------

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "<your-vps-ip>")

cat <<EOF

==> Done.

App URL:     http://$IP:$WEB_PORT
API URL:     http://127.0.0.1:8000  (proxied by Next.js at /api/*)

Tail logs:
  sudo journalctl -u $API_SVC -f
  sudo journalctl -u $WEB_SVC -f

Service control:
  sudo systemctl restart $API_SVC $WEB_SVC
  sudo systemctl status  $API_SVC $WEB_SVC

Re-deploy after a code change:
  cd $INSTALL_DIR && sudo bash deploy-web.sh

EOF
