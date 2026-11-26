#!/bin/sh
# Copy the newest backups off this server, and shout if they are missing or old.
#
#   ./deploy/offsite.sh                      # run from the project folder, from cron (see below)
#
# Needs rclone on the server and a remote set up with `rclone config`. The backups hold people's
# email addresses and progress, so make the remote an rclone "crypt" remote (encrypts names and
# contents before upload) or use storage you trust with that data.
#
# Environment (put in the crontab line, or export):
#   OFFSITE_REMOTE      rclone destination, e.g. offsite:piano-backups   (required)
#   BACKUP_DIR          default ./backups
#   MAX_AGE_HOURS       newest backup must be younger than this, default 26
#   OFFSITE_PING_URL    optional: fetched (e.g. a healthchecks.io URL) only after a good run, so
#                       the monitor alerts you when this stops working
#
# Exit status is 0 only if a fresh backup exists AND the copy was verified.
set -eu
cd "$(dirname "$0")/.."
: "${OFFSITE_REMOTE:?set OFFSITE_REMOTE, e.g. offsite:piano-backups}"
: "${BACKUP_DIR:=./backups}"
: "${MAX_AGE_HOURS:=26}"

command -v rclone > /dev/null || { echo "rclone is not installed" >&2; exit 2; }

# 1. A backup exists and is recent. (Old backups copied happily would hide a broken backup job.)
fresh=$(find "$BACKUP_DIR" -maxdepth 1 -name 'piano-*.dump' -mmin -"$((MAX_AGE_HOURS * 60))" | head -n 1)
if [ -z "$fresh" ]; then
  echo "NO BACKUP in the last $MAX_AGE_HOURS hours in $BACKUP_DIR: the backup service is not working" >&2
  exit 1
fi

# 2. Copy what is new (files that are already there are skipped), then check every copied file
#    matches by size and hash.
rclone copy "$BACKUP_DIR" "$OFFSITE_REMOTE" --include 'piano-*.dump' --include 'piano-files-*.tar.gz' \
  --max-age "$((MAX_AGE_HOURS + 24))h"
rclone check "$BACKUP_DIR" "$OFFSITE_REMOTE" --include 'piano-*.dump' --include 'piano-files-*.tar.gz' \
  --max-age "$((MAX_AGE_HOURS + 24))h" --one-way

echo "offsite copy verified: $(basename "$fresh")"
if [ -n "${OFFSITE_PING_URL:-}" ]; then
  curl -fsS --max-time 10 "$OFFSITE_PING_URL" > /dev/null || echo "could not reach the ping URL" >&2
fi
