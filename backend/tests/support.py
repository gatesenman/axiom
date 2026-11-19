"""Shared HTTP helpers for studio tests."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


def login(client: TestClient, username: str = "demo", password: str = "demo1234") -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def wait_run(client: TestClient, headers: dict, run_id: int, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        current = client.get(f"/api/runs/{run_id}", headers=headers)
        assert current.status_code == 200, current.text
        payload = current.json()
        if payload["status"] in {"completed", "failed", "needs_input", "rejected"}:
            return payload
        time.sleep(0.4)
    return payload
