#!/usr/bin/env bash
set -euo pipefail
ARCHIVE=${1:?usage: restore-test.sh backup.age}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
age -d -i "$BACKUP_AGE_IDENTITY" "$ARCHIVE" | tar -C "$TMP" -xzf -
(cd "$TMP" && sha256sum -c SHA256SUMS)
createdb magnotherm_restore_test
pg_restore --exit-on-error --clean --if-exists --dbname=magnotherm_restore_test "$TMP/neon.dump"
psql magnotherm_restore_test -c 'select count(*) from parts' >/dev/null
dropdb magnotherm_restore_test
echo "Restore test passed: $ARCHIVE"
