#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
export WORKBUDDY_CONFIG_DIR="${WORKBUDDY_CONFIG_DIR:-$PWD/config}"
export WORKBUDDY_DATABASE_URL="${WORKBUDDY_DATABASE_URL:-sqlite:///$PWD/workbuddy.db}"
exec workbuddy-worker
