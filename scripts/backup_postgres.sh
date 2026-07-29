#!/usr/bin/env bash
set -euo pipefail
: "${WORKBUDDY_DATABASE_URL:?WORKBUDDY_DATABASE_URL is required}"
OUT="${1:-var/backups/workbuddy-$(date -u +%Y%m%dT%H%M%SZ).dump}"
mkdir -p "$(dirname "$OUT")"
case "$WORKBUDDY_DATABASE_URL" in
  postgresql*) pg_dump --format=custom --no-owner --no-acl "$WORKBUDDY_DATABASE_URL" > "$OUT" ;;
  *) echo "Refusing backup: production backup script requires PostgreSQL" >&2; exit 2 ;;
esac
sha256sum "$OUT" > "$OUT.sha256"
echo "$OUT"
