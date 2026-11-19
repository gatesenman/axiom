"""Multi-agent runs against a local OpenAI-compatible server and against mock mode."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.support import login, wait_run

ZH = (
    "一家工厂生产产品A和产品B。产品A单位利润40元，产品B单位利润30元。"
    "生产一件A需要2小时机器时间和3公斤原料，生产一件B需要3小时机器时间和1公斤原料。"
    "每周机器时间不超过120小时，原料不超过90公斤。请制定利润最大的生产计划。"
)

FROM_LLM = """```aml
model FromLLM;
var x >= 0;
maximize profit: 5 * x;
subject to cap: x <= 4;
```"""

INVALID = """```aml
this is not a model
```"""


class _Endpoint:
    def __init__(self, content: str) -> None:
        self.calls = 0
        self.content = content
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self.send_error(404)
                    return
                outer.calls += 1
                body = json.dumps(
                    {"id": "cmpl-test", "choices": [{"message": {"role": "assistant", "content": outer.content}}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A002
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self) -> None:
        self._httpd.shutdown()
        self._thread.join(timeout=5)


def _run(client, headers, statement: str) -> dict:
    created = client.post("/api/projects", json={"title": "llm", "statement": statement, "locale": "zh-CN"}, headers=headers)
    assert created.status_code == 200, created.text
    started = client.post(
        f"/api/projects/{created.json()['id']}/runs",
        json={"statement": statement, "dsl": "", "auto_approve": True, "solver": "highs"},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    payload = wait_run(client, headers, started.json()["id"])
    assert payload["status"] == "completed", payload.get("error") or payload
    return payload


def test_openai_compatible_formulation_is_solved(client):
    endpoint = _Endpoint(FROM_LLM)
    try:
        headers = login(client)
        saved = client.put(
            "/api/settings",
            json={"provider": "openai-compatible", "base_url": endpoint.base_url, "model": "test-model", "api_key": "sk-test"},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        probe = client.post("/api/settings/test-llm", headers=headers)
        assert probe.json()["ok"] is True
        payload = _run(client, headers, ZH)
        assert endpoint.calls >= 2
        assert "FromLLM" in payload["dsl"]
        assert float(payload["objective"]) == pytest.approx(20, rel=1e-3)
        events = client.get(f"/api/runs/{payload['id']}/events", headers=headers).json()
        assert any(item["kind"] == "llm" and "采用" in item["title"] for item in events)
    finally:
        endpoint.close()


def test_invalid_llm_output_falls_back_to_rules(client):
    endpoint = _Endpoint(INVALID)
    try:
        headers = login(client)
        client.put(
            "/api/settings",
            json={"provider": "openai-compatible", "base_url": endpoint.base_url, "model": "test-model", "api_key": "sk-test"},
            headers=headers,
        )
        payload = _run(client, headers, ZH)
        assert endpoint.calls >= 1
        assert "x_A" in payload["dsl"]
        assert float(payload["objective"]) == pytest.approx(1628.571428, rel=1e-3)
        events = client.get(f"/api/runs/{payload['id']}/events", headers=headers).json()
        assert any("未通过校验" in item["title"] for item in events)
    finally:
        endpoint.close()


def test_mock_mode_does_not_call_the_model_server(client):
    endpoint = _Endpoint(FROM_LLM)
    try:
        headers = login(client)
        saved = client.put(
            "/api/settings",
            json={"provider": "mock", "base_url": endpoint.base_url, "model": "offline", "api_key": "sk-test"},
            headers=headers,
        )
        assert saved.json()["provider"] == "mock"
        payload = _run(client, headers, ZH)
        assert endpoint.calls == 0
        assert "x_A" in payload["dsl"]
        assert float(payload["objective"]) == pytest.approx(1628.571428, rel=1e-3)
    finally:
        endpoint.close()
