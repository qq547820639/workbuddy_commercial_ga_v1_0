#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
export WORKBUDDY_CONFIG_DIR="${WORKBUDDY_CONFIG_DIR:-$PWD/config}"
export WORKBUDDY_DATABASE_URL="${WORKBUDDY_DATABASE_URL:-sqlite:///$PWD/workbuddy.db}"
mkdir -p "${WORKBUDDY_OBJECT_STORE_DIR:-$PWD/var/objects}"
alembic upgrade head
workbuddy-seed
exec uvicorn workbuddy.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
