#!/bin/sh
# Make one compressed backup of the database (and of the saved-files folder, if there is one)
# and delete backups older than BACKUP_KEEP_DAYS.
#
#   PGHOST=db PGUSER=piano PGPASSWORD=... PGDATABASE=piano BACKUP_DIR=/backups ./backup.sh
#
# The file is written under a temporary name and renamed only when pg_dump finished, so a crash
# never leaves a half-written file that looks like a good backup.
set -eu
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_KEEP_DAYS:=14}"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
tmp="$BACKUP_DIR/.piano-$stamp.dump.partial"
out="$BACKUP_DIR/piano-$stamp.dump"
pg_dump --format=custom --no-owner --no-privileges --file="$tmp"
# A dump we cannot list is not a backup.
pg_restore --list "$tmp" > /dev/null
mv "$tmp" "$out"
echo "backup ok: $out ($(du -h "$out" | cut -f1))"

# Saved files (My Library MIDI projects) live in a folder, not the database, so copy them too.
: "${STORAGE_DIR:=/storage}"
if [ -d "$STORAGE_DIR" ]; then
  tmp_files="$BACKUP_DIR/.piano-files-$stamp.tar.gz.partial"
  out_files="$BACKUP_DIR/piano-files-$stamp.tar.gz"
  tar -czf "$tmp_files" -C "$STORAGE_DIR" .
  tar -tzf "$tmp_files" > /dev/null   # an archive we cannot list is not a backup
  mv "$tmp_files" "$out_files"
  echo "files backup ok: $out_files ($(du -h "$out_files" | cut -f1))"
fi

find "$BACKUP_DIR" \( -name 'piano-*.dump' -o -name 'piano-files-*.tar.gz' \) -mtime +"$BACKUP_KEEP_DAYS" -delete
