#!/usr/bin/env bash
# Disk hygiene for web_work/. Each generation leaves audio chunks, frames,
# and a final PDF behind. Without pruning, disk fills in ~weeks at modest
# traffic.
#
# Setup once on the VPS:
#   crontab -e  (as root)
#   30 3 * * * /opt/video-notes-bot/scripts/cleanup-workdir.sh >> /var/log/cheatsheet-cleanup.log 2>&1
#
# Policy (all defaults; override via env):
#   WORK_DIR=/opt/video-notes-bot/web_work
#   KEEP_DAYS=30        Keep the final PDF (output.pdf) for this many days.
#   CHUNK_DAYS=3        Delete intermediate audio chunks / frames after this many days.
#
# Files matched (relative to web_work/<job-id>/):
#   chunks/*.m4a, chunks/*.mp3, chunks/*.wav   -> pruned at CHUNK_DAYS
#   frames/*.jpg, frames/*.png                 -> pruned at CHUNK_DAYS
#   audio.m4a, audio.mp3                       -> pruned at CHUNK_DAYS
#   output.md                                  -> kept (small)
#   output.pdf                                 -> pruned at KEEP_DAYS
#
# After deleting an output.pdf, we DO NOT touch the DB; the API already
# returns 404 from /api/files/{id}/pdf when the file is missing, and the
# library page shows "pdf not ready". A future cleanup of stale DB rows
# can be added if desired.

set -euo pipefail

WORK_DIR="${WORK_DIR:-/opt/video-notes-bot/web_work}"
KEEP_DAYS="${KEEP_DAYS:-30}"
CHUNK_DAYS="${CHUNK_DAYS:-3}"

if [[ ! -d "$WORK_DIR" ]]; then
  echo "[cleanup] $WORK_DIR does not exist — nothing to do"
  exit 0
fi

before=$(du -sb "$WORK_DIR" 2>/dev/null | awk '{print $1}')

# Intermediates (chunks, frames, raw audio) — short retention.
find "$WORK_DIR" -mindepth 2 -type d \( -name chunks -o -name frames \) \
  -prune -exec find {} -type f -mtime "+$CHUNK_DAYS" -delete \;

find "$WORK_DIR" -mindepth 2 -maxdepth 2 -type f \
  \( -name 'audio.*' -o -name '*.m4a' -o -name '*.wav' -o -name '*.opus' \) \
  -mtime "+$CHUNK_DAYS" -delete

# Final PDFs — longer retention.
find "$WORK_DIR" -mindepth 2 -maxdepth 2 -type f -name 'output.pdf' \
  -mtime "+$KEEP_DAYS" -delete

# Empty job dirs that have nothing left.
find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d -empty -delete

after=$(du -sb "$WORK_DIR" 2>/dev/null | awk '{print $1}')
freed=$(( before - after ))
echo "[cleanup] before=${before}B after=${after}B freed=${freed}B"
