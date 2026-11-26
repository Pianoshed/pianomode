#!/bin/sh
# Restore a database backup. DESTRUCTIVE: replaces what is in the target database.
# Saved files: extract the matching piano-files-*.tar.gz into the storage folder
# (tar -xzf piano-files-XXXX.tar.gz -C /path/to/storage).
#
#   PGHOST=db PGUSER=piano PGPASSWORD=... PGDATABASE=piano ./restore.sh /backups/piano-XXXX.dump
#
# Stop the api, worker and beat first, and try it on a copy before using it for real.
set -eu
[ $# -eq 1 ] || { echo "usage: restore.sh BACKUP_FILE" >&2; exit 2; }
pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction --dbname="$PGDATABASE" "$1"
echo "restore ok from $1"
