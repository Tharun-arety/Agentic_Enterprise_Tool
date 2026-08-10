#!/usr/bin/env bash
set -euo pipefail
umask 077
BACKUP_ROOT=${BACKUP_ROOT:?set BACKUP_ROOT to the separate backup disk}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$BACKUP_ROOT/daily/$STAMP"
mkdir -p "$DEST"
pg_dump "$DATABASE_URL" --format=custom --file="$DEST/neon.dump"
docker compose exec -T mariadb mariadb-dump -uroot -p"$MYSQL_ROOT_PASSWORD" --all-databases --single-transaction > "$DEST/erpnext.sql"
docker run --rm --network magnotherm_default -v magnotherm_minio-data:/source:ro -v "$DEST:/backup" alpine:3.22 tar -C /source -czf /backup/minio.tar.gz .
sha256sum "$DEST"/* > "$DEST/SHA256SUMS"
tar -C "$DEST" -czf - . | age -r "$BACKUP_AGE_RECIPIENT" -o "$DEST.age"
rm -rf "$DEST"
find "$BACKUP_ROOT/daily" -maxdepth 1 -type f -name '*.age' -mtime +7 -delete
if [ "$(date -u +%u)" = 7 ]; then mkdir -p "$BACKUP_ROOT/weekly"; cp "$DEST.age" "$BACKUP_ROOT/weekly/"; find "$BACKUP_ROOT/weekly" -type f -mtime +28 -delete; fi
