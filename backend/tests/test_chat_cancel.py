"""Chat replies and stopping a run that is waiting for approval."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.support import login

ZH = (
    "一家工厂生产产品A和产品B。产品A单位利润40元，产品B单位利润30元。"
    "生产一件A需要2小时机器时间和3公斤原料，生产一件B需要3小时机器时间和1公斤原料。"
    "每周机器时间不超过120小时，原料不超过90公斤。请制定利润最大的生产计划。"
)


def test_mock_chat_returns_a_formulation(client: TestClient):
    headers = login(client)
    denied = client.post("/api/chat", json={"messages": [{"role": "user", "content": ZH}]})
    assert denied.status_code == 401
    reply = client.post("/api/chat", json={"messages": [{"role": "user", "content": ZH}]}, headers=headers)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["provider"] == "mock"
    assert body["role"] == "assistant"
    assert "x_A" in body["content"]
    assert "```aml" in body["content"]


def test_cancel_stops_a_run_waiting_for_approval(client: TestClient):
    headers = login(client)
    project = client.post("/api/projects", json={"title": "停止校验", "statement": ZH, "locale": "zh-CN"}, headers=headers)
    assert project.status_code == 200, project.text
    started = client.post(
        f"/api/projects/{project.json()['id']}/runs",
        json={"statement": ZH, "dsl": "", "auto_approve": False, "solver": "highs"},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]
    deadline = time.time() + 60
    status = ""
    while time.time() < deadline:
        current = client.get(f"/api/runs/{run_id}", headers=headers)
        status = current.json()["status"]
        if status == "awaiting_approval":
            break
        assert status in {"queued", "running", "awaiting_approval"}
        time.sleep(0.3)
    assert status == "awaiting_approval"
    cancelled = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    time.sleep(0.8)
    again = client.get(f"/api/runs/{run_id}", headers=headers)
    assert again.json()["status"] == "cancelled"
    finished = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
    assert finished.status_code == 409
