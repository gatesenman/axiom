"""Isolated API client. Each test gets its own SQLite directory."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AXIOM_SKIP_EXAMPLE", "1")
    from axiom.db.session import reset_engine

    reset_engine()
    from axiom.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    reset_engine()
