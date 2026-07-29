#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from workbuddy.api.main import create_app

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner", "X-Roles": "owner product_owner security_owner operations_owner privacy_owner platform_owner it_admin ai_platform_owner business_owner"}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(f"sqlite:///{tmp}/pilot.db", auto_seed=True)
        with TestClient(app) as client:
            program = client.post("/v1/pilot-programs", headers=HEADERS, json={"name": "Deterministic Production Pilot", "scope": {"max_users": 20}, "targets": {}})
            assert program.status_code == 201, program.text
            pid = program.json()["id"]
            report = client.get(f"/v1/pilot-programs/{pid}/go-no-go", headers=HEADERS)
            assert report.status_code == 200
            assert report.json()["decision"] == "NO_GO"
            assert report.json()["blockers"]
            print("Production Pilot evidence gate correctly remains NO_GO without live evidence.")


if __name__ == "__main__":
    main()
