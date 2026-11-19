"""The documented desktop account signs in on a fresh database."""

from __future__ import annotations


def test_demo_seed_accepts_documented_password(client):
    response = client.post("/api/auth/login", json={"username": "demo", "password": "demo1234"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "demo"
    assert body["token"]


def test_demo_wrong_password_is_not_a_server_error(client):
    response = client.post("/api/auth/login", json={"username": "demo", "password": "not-the-demo"})
    assert response.status_code == 401
    assert "不正确" in response.json()["message"]
