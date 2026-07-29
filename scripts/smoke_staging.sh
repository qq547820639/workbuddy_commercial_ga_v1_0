#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-${WORKBUDDY_PUBLIC_BASE_URL:-http://localhost:8000}}"
AUTH=()
if [[ -n "${WORKBUDDY_BEARER_TOKEN:-}" ]]; then AUTH=(-H "Authorization: Bearer $WORKBUDDY_BEARER_TOKEN"); fi
curl -fsS "$BASE/health/live" | python -m json.tool
curl -fsS "$BASE/health/ready" | python -m json.tool
curl -fsS "${AUTH[@]}" "$BASE/v1/ops/preflight" | python -m json.tool
curl -fsS "${AUTH[@]}" "$BASE/v1/ops/status" | python -m json.tool
