#!/usr/bin/env bash
set -euo pipefail
: "${WORKBUDDY_DATABASE_URL:?WORKBUDDY_DATABASE_URL is required}"
FILE="${1:?usage: restore_postgres.sh backup.dump}"
sha256sum -c "$FILE.sha256"
case "$WORKBUDDY_DATABASE_URL" in
  postgresql*) pg_restore --clean --if-exists --no-owner --no-acl --dbname "$WORKBUDDY_DATABASE_URL" "$FILE" ;;
  *) echo "Refusing restore: production restore script requires PostgreSQL" >&2; exit 2 ;;
esac
