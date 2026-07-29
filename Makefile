.PHONY: install test verify run worker migrate openapi preflight pilot commercial ga invoice tenant-exit
install:
	python -m pip install -e '.[dev]'
test:
	pytest -q
verify:
	./scripts/verify.sh
run:
	./scripts/run_local.sh
worker:
	./scripts/run_worker.sh
migrate:
	alembic upgrade head
openapi:
	PYTHONPATH=src python scripts/generate_openapi.py
preflight:
	PYTHONPATH=src python scripts/production_preflight.py
pilot:
	PYTHONPATH=src python scripts/pilot_bootstrap.py --activate
commercial:
	PYTHONPATH=src python scripts/commercial_bootstrap.py
ga:
	PYTHONPATH=src python scripts/ga_check.py
invoice:
	PYTHONPATH=src python scripts/generate_invoice.py
tenant-exit:
	PYTHONPATH=src python scripts/tenant_exit_export.py
