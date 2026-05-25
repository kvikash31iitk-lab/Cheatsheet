#!/usr/bin/env bash
# Nightly DB backup → Backblaze B2 (or any rclone remote).
#
# Setup once on the VPS:
#   apt-get install -y rclone postgresql-client
#   rclone config            # add a remote called "b2" pointing at your bucket
#   crontab -e  (as root)
#   0 3 * * * /opt/video-notes-bot/scripts/backup-db.sh >> /var/log/cheatsheet-backup.log 2>&1
#
# Retains 30 days of nightly dumps locally + uploads each one to B2.
# Local dumps older than 30 days are pruned to keep disk light.
#
# Env knobs (set in /opt/video-notes-bot/.env or override per-run):
#   DATABASE_URL         postgresql+psycopg://user:pass@host:5432/dbname
#   BACKUP_DIR           /var/backups/cheatsheet  (default)
#   BACKUP_RCLONE_DEST   b2:cheatsheet-backups    (default, set to "" to skip upload)
#   BACKUP_RETENTION     30   (days)

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/video-notes-bot}"
if [[ -f "$INSTALL_DIR/.env" ]]; then
  set -a; . "$INSTALL_DIR/.env"; set +a
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/cheatsheet}"
RCLONE_DEST="${BACKUP_RCLONE_DEST:-b2:cheatsheet-backups}"
RETENTION="${BACKUP_RETENTION:-30}"

mkdir -p "$BACKUP_DIR"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[backup] DATABASE_URL not set — aborting" >&2
  exit 1
fi

# Strip the SQLAlchemy driver prefix so pg_dump understands the URL.
PG_URL=$(echo "$DATABASE_URL" | sed -E 's#^postgresql\+[a-z]+://#postgresql://#')

STAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT="$BACKUP_DIR/cheatsheet-$STAMP.sql.gz"

echo "[backup] dumping to $OUT ..."
pg_dump --no-owner --no-privileges "$PG_URL" | gzip > "$OUT"
BYTES=$(stat -c %s "$OUT")
echo "[backup] wrote $OUT ($BYTES bytes)"

if [[ -n "$RCLONE_DEST" ]] && command -v rclone >/dev/null 2>&1; then
  echo "[backup] uploading to $RCLONE_DEST ..."
  rclone copy --quiet "$OUT" "$RCLONE_DEST/"
  echo "[backup] uploaded."
else
  echo "[backup] skipping upload (no rclone or BACKUP_RCLONE_DEST unset)"
fi

# Prune anything older than $RETENTION days locally.
find "$BACKUP_DIR" -name 'cheatsheet-*.sql.gz' -mtime "+$RETENTION" -delete \
  && echo "[backup] pruned local dumps older than $RETENTION days"

echo "[backup] OK"
