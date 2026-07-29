#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export WORKBUDDY_CONFIG_DIR="$ROOT/config"

printf '\n[1/12] Python compilation\n'
python -m compileall -q src migrations scripts

printf '\n[2/12] Automated tests\n'
pytest -q -p no:cacheprovider

printf '\n[3/12] Empty-database migrations 0001-0019\n'
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" /tmp/workbuddy_ga_ui.js' EXIT
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/migration.db" alembic upgrade head
[[ "$(WORKBUDDY_DATABASE_URL="sqlite:///$TMP/migration.db" alembic current)" == *"0019_attestation_signing"* ]]

printf '\n[4/12] Generate and validate OpenAPI\n'
python scripts/generate_openapi.py
python - <<'PY'
from pathlib import Path
text=Path('api/openapi.yaml').read_text(encoding='utf-8')
for endpoint in [
    '/v1/agent-runs/{run_id}/execute', '/v1/connectors/graph/webhook',
    '/v1/pilot-programs/{program_id}/go-no-go', '/v1/ops/preflight',
    '/v1/commercial/subscriptions', '/v1/commercial/usage', '/v1/commercial/invoices',
    '/v1/commercial/onboardings', '/v1/support/tickets', '/v1/compliance/documents',
    '/v1/ga/programs/{program_id}/go-no-go',
    '/v1/commercial/pricing-approvals', '/v1/commercial/model-agreements',
    '/v1/commercial/pentest-reports', '/v1/compliance/documents/{document_id}/legal-review',
    '/v1/oncall/schedules', '/v1/oncall/escalation-policies',
    '/v1/ga/programs/{program_id}/observation-window/start',
    '/v1/commercial/billing/webhook',
]:
    assert endpoint in text, endpoint
PY

printf '\n[5/12] Front-end safety and JavaScript syntax\n'
python - <<'PY'
from pathlib import Path
html=Path('src/workbuddy/web/index.html').read_text(encoding='utf-8')
assert 'localStorage' not in html
assert 'https://fonts' not in html
assert 'COMMERCIAL GA' in html
assert '商用与 GA' in html
js=html.split('<script>',1)[1].split('</script>',1)[0]
Path('/tmp/workbuddy_ga_ui.js').write_text(js,encoding='utf-8')
PY
if command -v node >/dev/null 2>&1; then node --check /tmp/workbuddy_ga_ui.js; else echo 'node unavailable; JavaScript syntax check skipped'; fi

printf '\n[6/12] Declarative config and deployment YAML\n'
python - <<'PY'
from pathlib import Path
import json, yaml
for root in ['config','deploy']:
    for path in Path(root).rglob('*.yaml'):
        docs=list(yaml.safe_load_all(path.read_text(encoding='utf-8')))
        assert docs and all(x is None or isinstance(x, dict) for x in docs), path
for path in Path('config').rglob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
PY

printf '\n[7/12] Full deterministic expert-team golden path\n'
(
  cd "$TMP"
  PYTHONPATH="$ROOT/src" WORKBUDDY_CONFIG_DIR="$ROOT/config" python "$ROOT/scripts/demo_flow.py"
)

printf '\n[8/12] Production Pilot honest-gate flow\n'
PYTHONPATH=src python scripts/pilot_demo_flow.py

printf '\n[9/12] Commercial bootstrap and honest GA gate\n'
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/commercial.db" PYTHONPATH=src python scripts/commercial_bootstrap.py
set +e
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/commercial.db" PYTHONPATH=src python scripts/ga_check.py > "$TMP/ga-report.json"
GA_RC=$?
set -e
[[ "$GA_RC" -eq 1 ]]
grep -q 'NO_GO' "$TMP/ga-report.json"

printf '\n[10/12] Invoice draft and tenant-exit export\n'
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/commercial.db" PYTHONPATH=src python scripts/generate_invoice.py > "$TMP/invoice.json"
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/commercial.db" PYTHONPATH=src python scripts/tenant_exit_export.py --output "$TMP/tenant-exit.json"
test -s "$TMP/invoice.json" && test -s "$TMP/tenant-exit.json"

printf '\n[11/12] Local production preflight and gate report\n'
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/migration.db" PYTHONPATH=src python -m workbuddy.services.seed
WORKBUDDY_DATABASE_URL="sqlite:///$TMP/migration.db" \
WORKBUDDY_APP_SECRET='verification-secret-with-more-than-32-characters' \
WORKBUDDY_TOKEN_ENCRYPTION_KEY='local-verification-key' \
WORKBUDDY_BACKUP_BUCKET='local-test-bucket' \
WORKBUDDY_ALERT_WEBHOOK_URL='https://alerts.invalid/test' \
PYTHONPATH=src python scripts/production_preflight.py
PYTHONPATH=src python scripts/gate_check.py

printf '\n[12/12] Container and Kubernetes syntax\n'
if command -v docker >/dev/null 2>&1 && timeout 10 docker compose version >/dev/null 2>&1; then timeout 20 docker compose config >/dev/null; else echo 'docker compose unavailable; compose runtime check skipped'; fi
if command -v kubectl >/dev/null 2>&1; then timeout 20 kubectl kustomize deploy/k8s >/dev/null; else echo 'kubectl unavailable; kustomize render skipped'; fi

printf '\nAll WorkBuddy Commercial GA v1.0 code-scope verification checks passed.\n'
