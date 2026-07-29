from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workbuddy.api.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Use repository config files even when tests run in a temporary working directory.
    monkeypatch.setenv("WORKBUDDY_CONFIG_DIR", str(__import__('pathlib').Path(__file__).resolve().parents[1] / "config"))
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}", auto_seed=True)
    with TestClient(app) as c:
        yield c
