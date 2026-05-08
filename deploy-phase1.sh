#!/usr/bin/env bash
# Phase 1 deploy: Postgres + nginx + Let's Encrypt + Auth env vars.
#
# Run on the VPS as root, after deploy-web.sh has succeeded:
#
#   sudo bash /opt/video-notes-bot/deploy-phase1.sh
#
# PREREQUISITES (do these in the Hostinger panel / Google Console first):
#   1. Hostinger panel firewall: open inbound 80/tcp and 443/tcp.
#   2. Google Cloud Console > Clients > Cheatsheet Web > add this redirect URI:
#        https://srv1622345.hstgr.cloud/auth/callback/google
#   3. Edit /opt/video-notes-bot/.env on the VPS to include the Google client
#      ID and secret you got from Google Console:
#        AUTH_GOOGLE_ID=xxxxxxxxxxxxx.apps.googleusercontent.com
#        AUTH_GOOGLE_SECRET=GOCSPX-xxxxxxxxxxxxx
#
# WHAT THIS DOES
#   1. Installs Postgres + nginx + certbot if not already present.
#   2. Creates a `cheatsheet` Postgres role+db with an auto-generated password.
#   3. Configures nginx as TLS-terminating reverse proxy in front of :3000.
#   4. Runs certbot --nginx to issue and install a Let's Encrypt cert.
#   5. Generates AUTH_SECRET and INTERNAL_API_TOKEN (idempotent — kept across runs).
#   6. Writes/updates /opt/video-notes-bot/.env with the prod values.
#   7. Installs psycopg into the venv (sync Postgres driver used by the worker).
#   8. Adds EnvironmentFile= directives to both systemd units.
#   9. Rebuilds web/ (npm ci + npm run build) and restarts both services.
#
# Re-run-safe. Keeps existing secrets (.dbpass, .auth_secret, .internal_token).

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/video-notes-bot}"
BOT_USER="${BOT_USER:-botuser}"
DOMAIN="${DOMAIN:-srv1622345.hstgr.cloud}"
EMAIL_FOR_LE="${EMAIL_FOR_LE:-admin@$DOMAIN}"
DB_NAME="cheatsheet"
DB_USER="cheatsheet"
ENV_FILE="$INSTALL_DIR/.env"
WEB_ENV="$INSTALL_DIR/web/.env.local"

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: run as root (use sudo)" >&2
  exit 1
fi

# Sanity check — Phase 0 must already be installed.
if [[ ! -d "$INSTALL_DIR/web/node_modules" ]]; then
  echo "ERROR: $INSTALL_DIR/web/node_modules not found — run deploy-web.sh first" >&2
  exit 1
fi

if ! grep -q "^AUTH_GOOGLE_ID=" "$ENV_FILE" 2>/dev/null \
   || ! grep -q "^AUTH_GOOGLE_SECRET=" "$ENV_FILE" 2>/dev/null; then
  echo "ERROR: $ENV_FILE missing AUTH_GOOGLE_ID and/or AUTH_GOOGLE_SECRET." >&2
  echo "Add them with values from Google Cloud Console first, then re-run." >&2
  exit 1
fi

# --- 1. Postgres ----------------------------------------------------------

if ! command -v psql >/dev/null 2>&1; then
  echo "==> installing Postgres..."
  apt-get update -qq
  apt-get install -y -qq postgresql postgresql-contrib
fi

DB_PASS_FILE="$INSTALL_DIR/.dbpass"
if [[ ! -f "$DB_PASS_FILE" ]]; then
  openssl rand -hex 16 > "$DB_PASS_FILE"
  chown "$BOT_USER:$BOT_USER" "$DB_PASS_FILE"
  chmod 600 "$DB_PASS_FILE"
fi
DB_PASS="$(cat "$DB_PASS_FILE")"

echo "==> ensuring Postgres role + database..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<EOF >/dev/null
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS';
  ELSE
    ALTER ROLE $DB_USER WITH PASSWORD '$DB_PASS';
  END IF;
END \$\$;
EOF
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" \
  | grep -q 1 \
  || sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" >/dev/null

# --- 2. nginx + certbot ---------------------------------------------------

if ! command -v nginx >/dev/null 2>&1; then
  echo "==> installing nginx + certbot..."
  apt-get install -y -qq nginx certbot python3-certbot-nginx
fi

# HTTP-only bootstrap config so certbot's HTTP-01 challenge can succeed.
# After certbot issues the cert we rewrite the file to add the HTTPS server
# block ourselves — relying on `certbot --nginx` to mutate the file is
# fragile when other server blocks already exist with default_server / *
# wildcards, which we've seen on this VPS (the bot's "grid" config).
NGINX_CONF=/etc/nginx/sites-available/cheatsheet
write_http_only_conf() {
  cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    client_max_body_size 50M;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
}

write_full_conf() {
  cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
EOF
}

mkdir -p /var/www/certbot
rm -f /etc/nginx/sites-enabled/default

if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  # No cert yet: bootstrap with HTTP-only config first so certbot's
  # HTTP challenge has a path to land on.
  write_http_only_conf
  ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/cheatsheet
  nginx -t && systemctl reload nginx
fi

ufw allow 80/tcp 2>/dev/null || true
ufw allow 443/tcp 2>/dev/null || true

# --- 3. TLS via certbot ---------------------------------------------------

if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  echo "==> requesting Let's Encrypt cert for $DOMAIN..."
  # Use the webroot plugin instead of --nginx so certbot doesn't try to
  # mutate our nginx config (which can fail silently when the VPS has
  # pre-existing server blocks with default_server flags).
  certbot certonly --webroot -w /var/www/certbot \
    -d "$DOMAIN" \
    --non-interactive --agree-tos \
    --email "$EMAIL_FOR_LE"
else
  echo "==> cert for $DOMAIN already exists, skipping certbot..."
fi

# Now write the full HTTP+HTTPS config and reload.
write_full_conf
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/cheatsheet
nginx -t && systemctl reload nginx

# --- 4. App secrets (idempotent: kept across runs) ------------------------

ensure_var () {
  local file="$1" key="$2" value="$3"
  if grep -q "^$key=" "$file" 2>/dev/null; then
    sed -i "s|^$key=.*|$key=$value|" "$file"
  else
    echo "$key=$value" >> "$file"
  fi
}

INTERNAL_TOKEN_FILE="$INSTALL_DIR/.internal_token"
[[ -f "$INTERNAL_TOKEN_FILE" ]] || {
  openssl rand -hex 32 > "$INTERNAL_TOKEN_FILE"
  chown "$BOT_USER:$BOT_USER" "$INTERNAL_TOKEN_FILE"
  chmod 600 "$INTERNAL_TOKEN_FILE"
}
INTERNAL_TOKEN="$(cat "$INTERNAL_TOKEN_FILE")"

AUTH_SECRET_FILE="$INSTALL_DIR/.auth_secret"
[[ -f "$AUTH_SECRET_FILE" ]] || {
  openssl rand -base64 32 > "$AUTH_SECRET_FILE"
  chown "$BOT_USER:$BOT_USER" "$AUTH_SECRET_FILE"
  chmod 600 "$AUTH_SECRET_FILE"
}
AUTH_SECRET="$(cat "$AUTH_SECRET_FILE")"

echo "==> updating $ENV_FILE..."
ensure_var "$ENV_FILE" "DATABASE_URL" \
  "postgresql+asyncpg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
ensure_var "$ENV_FILE" "AUTH_SECRET" "$AUTH_SECRET"
ensure_var "$ENV_FILE" "AUTH_URL" "https://$DOMAIN"
ensure_var "$ENV_FILE" "AUTH_TRUST_HOST" "true"
ensure_var "$ENV_FILE" "INTERNAL_API_TOKEN" "$INTERNAL_TOKEN"
ensure_var "$ENV_FILE" "INTERNAL_API_BASE" "http://127.0.0.1:8000"
chown "$BOT_USER:$BOT_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Mirror the file for Next.js (it reads .env.local from web/).
sudo -u "$BOT_USER" cp "$ENV_FILE" "$WEB_ENV"
chmod 600 "$WEB_ENV"

# --- 5. Python deps (psycopg for sync Postgres) ---------------------------

echo "==> installing/upgrading Python deps..."
sudo -u "$BOT_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade \
  -r "$INSTALL_DIR/requirements.txt"

# Pre-download the Whisper model when WHISPER_BACKEND=local so the first
# user request doesn't pay a 10-minute model download. Must cd into the
# project root so Python can resolve the `scripts` package.
if grep -q "^WHISPER_BACKEND=local" "$ENV_FILE" 2>/dev/null; then
  WHISPER_MODEL=$(grep "^WHISPER_MODEL=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
  WHISPER_MODEL="${WHISPER_MODEL:-small}"
  echo "==> warming up faster-whisper '$WHISPER_MODEL' model (one-time download)..."
  sudo -u "$BOT_USER" -H bash -c "
    cd $INSTALL_DIR && \
    WHISPER_MODEL='$WHISPER_MODEL' .venv/bin/python -c \
      'from scripts.whisper_local import warmup; warmup()'
  " || echo "WARN: model warmup failed; first request will retry"
fi

# --- 6. systemd unit refresh ----------------------------------------------

for svc in cheatsheet-api cheatsheet-web; do
  unit="/etc/systemd/system/$svc.service"
  if [[ -f "$unit" ]]; then
    sed -i "/^EnvironmentFile=/d" "$unit"
    sed -i "/^\[Service\]/a EnvironmentFile=$ENV_FILE" "$unit"
  fi
done
systemctl daemon-reload

# --- 7. Rebuild Next.js + restart -----------------------------------------

echo "==> rebuilding web/..."
sudo -u "$BOT_USER" -H bash -c "
  set -e
  cd $INSTALL_DIR/web
  npm ci --no-audit --no-fund --silent
  npm run build
"

echo "==> restarting services..."
systemctl restart cheatsheet-api cheatsheet-web

cat <<EOF

==> Phase 1 deploy done.

Visit:  https://$DOMAIN

If sign-in fails with "redirect_uri_mismatch", verify the Google Cloud
Console > Clients > Cheatsheet Web has this Authorized redirect URI:
   https://$DOMAIN/auth/callback/google

Logs:
  sudo journalctl -u cheatsheet-api -f
  sudo journalctl -u cheatsheet-web -f

Re-run after a code change:
  cd $INSTALL_DIR && sudo bash deploy-web.sh        # rebuild + restart only
  cd $INSTALL_DIR && sudo bash deploy-phase1.sh     # this script (idempotent)

EOF
