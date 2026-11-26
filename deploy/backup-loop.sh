#!/bin/sh
# Runs backup.sh every day at BACKUP_HOUR_UTC (default 02) and keeps running if one attempt fails.
set -u
: "${BACKUP_HOUR_UTC:=2}"
while true; do
  now=$(date -u +%s)
  next=$(date -u -d "today ${BACKUP_HOUR_UTC}:00" +%s)
  [ "$next" -le "$now" ] && next=$(date -u -d "tomorrow ${BACKUP_HOUR_UTC}:00" +%s)
  sleep $((next - now))
  /deploy/backup.sh || echo "BACKUP FAILED at $(date -u)" >&2
done
