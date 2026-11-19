"""Natural language, simulation, analysis, reports, and the HTTP studio."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from axiom.analysis.service import diagnose, monte_carlo, present, scenarios, sensitivity, statistics
from axiom.modeling import parse_aml
from axiom.nl.formulate import formulate
from axiom.reports.build import excel_report, markdown_report, pdf_report
from axiom.simulation.des import simulate_queue
from tests.support import login, wait_run

PRODUCT = """
model ProductMix;
var x_A >= 0;
var x_B >= 0;
maximize profit: 40 * x_A + 30 * x_B;
subject to labor: 2 * x_A + 3 * x_B <= 120;
subject to material: 3 * x_A + 1 * x_B <= 90;
"""

ZH = (
    "一家工厂生产产品A和产品B。产品A单位利润40元，产品B单位利润30元。"
    "生产一件A需要2小时机器时间和3公斤原料，生产一件B需要3小时机器时间和1公斤原料。"
    "每周机器时间不超过120小时，原料不超过90公斤。请制定利润最大的生产计划。"
)

EN = (
    "Maximize profit. The unit profit of A is 40 and the unit profit of B is 30. "
    "Producing one A requires 2 hours and 3 kg. Producing one B requires 3 hours and 1 kg. "
    "Machine time limit is at most 120. Material limit is at most 90."
)


def test_chinese_and_english_product_mix():
    chinese = formulate(ZH)
    english = formulate(EN)
    assert chinese.aml and "x_A" in chinese.aml and "x_B" in chinese.aml
    assert english.aml and "x_A" in english.aml
    assert chinese.confidence > 0.8
    assert formulate("帮我看看").kind == "clarification"
    queue = formulate("请做排队仿真，到达率 6，服务率 9，服务台 2，仿真 4")
    assert queue.kind == "simulation"
    assert queue.simulation["servers"] == 2


def test_queue_and_analysis_are_numeric():
    result = simulate_queue(arrival_rate=8, service_rate=10, servers=1, horizon=6, seed=3)
    assert result["served"] > 0
    assert 0 <= result["utilization"] <= 2
    model = parse_aml(PRODUCT)
    solved_view = present(model, {"x_A": 150 / 7, "x_B": 180 / 7}, 11400 / 7)
    assert solved_view["bars"]
    stats = statistics({"x_A": 21.4, "x_B": 25.7}, [{"binding": True, "violated": False}])
    assert stats["variable_count"] == 2
    sens = sensitivity(model, "highs", widths=(-0.1, 0.1))
    assert sens["rows"]
    cases = scenarios(model, [{"name": "基准"}, {"name": "宽松", "rhs_scale": {"labor": 1.2, "material": 1.2}}])
    assert cases[0]["status"] == "optimal"
    assert cases[1]["objective"] >= cases[0]["objective"] - 1e-6
    sample = monte_carlo(model, samples=6, cv=0.05, seed=2)
    assert sample["samples"] >= 5
    diagnosis = diagnose(model)
    assert diagnosis["feasible_without_slacks"] is True


def test_reports_include_the_objective():
    run = {
        "title": "产品组合",
        "statement": ZH,
        "status": "optimal",
        "solver": "highs",
        "objective": 1628.571,
        "dsl": PRODUCT,
        "variables": {"x_A": 21.4286, "x_B": 25.7143},
        "constraints": [{"name": "labor", "sense": "<=", "lhs": 120, "rhs": 120, "slack": 0, "binding": True}],
        "summary": "利润最大。",
        "sensitivity": {"rows": [{"name": "rhs:labor", "low": 1, "base": 2, "high": 3, "span": 2}]},
    }
    markdown = markdown_report(run, "zh-CN")
    assert "x_A" in markdown and "1628" in markdown
    assert excel_report(run)[:2] == b"PK"
    assert pdf_report(run, "zh-CN")[:4] == b"%PDF"


def test_api_product_mix_run(client: TestClient):
    headers = login(client)
    created = client.post("/api/projects", json={"title": "周计划", "statement": ZH, "locale": "zh-CN"}, headers=headers)
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    started = client.post(f"/api/projects/{project_id}/runs", json={"statement": ZH, "auto_approve": True, "solver": "highs"}, headers=headers)
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]
    payload = wait_run(client, headers, run_id)
    assert payload["status"] == "completed", payload.get("error") or payload
    objective = float(payload["objective"])
    assert objective == pytest.approx(1628.571428, rel=1e-3)
    assert payload["result"]["verification"]["ok"] is True
    variable_names = [
        key
        for key in payload["result"]["variables"]
        if not key.startswith("_") and not key.startswith("s_")
    ]
    bars = payload["result"]["views"]["bars"]
    assert [row["name"] for row in bars] == variable_names[:16]
    for row in bars:
        assert row["value"] == pytest.approx(payload["result"]["variables"][row["name"]], rel=1e-6)
    scenario_rows = payload["result"]["scenarios"]
    scenario_objectives = [row["objective"] for row in scenario_rows]
    assert scenario_rows[0]["name"] == "基准"
    assert scenario_objectives[0] == pytest.approx(objective, rel=1e-4)
    assert scenario_objectives[1] > scenario_objectives[0] > scenario_objectives[2]
    assert min(scenario_objectives) > 1000
    for row in payload["result"]["sensitivity"]["rows"]:
        assert row["span"] == pytest.approx(row["high"] - row["low"], abs=1e-4)
        assert row["low"] <= row["base"] + 1e-3
        assert row["high"] + 1e-3 >= row["base"]
        assert row["span"] < abs(objective)
    assert "pyomo" in payload["result"]["translations"]
    assert "lp" in payload["result"]["translations"]
    assert payload["result"]["standard_form"]["ok"] is True
    assert payload["result"]["standard_form"]["kind"] == "lp"
    events = client.get(f"/api/runs/{run_id}/events", headers=headers).json()
    agents = {item["agent"] for item in events}
    assert {"analyst", "modeler", "solver", "verifier", "report"} <= agents
    report = client.get(f"/api/runs/{run_id}/report", params={"format": "md"}, headers=headers)
    assert report.status_code == 200
    assert "x_A" in report.text
    assert "标准方程" in report.text
    excel = client.get(f"/api/runs/{run_id}/report", params={"format": "xlsx"}, headers=headers)
    assert excel.status_code == 200 and excel.content[:2] == b"PK"
    pdf = client.get(f"/api/runs/{run_id}/report", params={"format": "pdf"}, headers=headers)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    audit = client.get("/api/audit", headers=headers)
    assert audit.status_code == 200 and any(item["action"] == "run.start" for item in audit.json())
    solvers = client.get("/api/solvers", headers=headers).json()
    names = {item["name"] for item in solvers if item["available"]}
    assert {"highs", "cbc", "glpk"} <= names


def test_api_workspace_user_and_import(client: TestClient):
    headers = login(client)
    denied = client.get("/api/projects")
    assert denied.status_code == 401
    workspace = client.post("/api/workspaces", json={"name": "计划组"}, headers=headers)
    assert workspace.status_code == 200
    created = client.post(
        "/api/users",
        json={"username": "lin", "password": "secret1", "display_name": "林工", "role": "member"},
        headers=headers,
    )
    assert created.status_code == 200
    added = client.post(f"/api/workspaces/{workspace.json()['id']}/members", json={"username": "lin"}, headers=headers)
    assert any(member["username"] == "lin" for member in added.json()["members"])
    imported = client.post(
        "/api/import",
        json={"format": "lp", "text": "Maximize\n obj: 40 x_A + 30 x_B\nSubject To\n labor: 2 x_A + 3 x_B <= 120\nBounds\n x_A >= 0\n x_B >= 0\nEnd\n"},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    assert "x_A" in imported.json()["aml"]
    settings = client.put("/api/settings", json={"provider": "mock", "model": "offline"}, headers=headers)
    assert settings.json()["provider"] == "mock"
    probe = client.post("/api/settings/test-llm", headers=headers)
    assert probe.json()["ok"] is True
    me = client.patch("/api/auth/me", json={"locale": "en", "theme": "dark"}, headers=headers)
    assert me.json()["locale"] == "en"
    os.environ["AXIOM_SKIP_EXAMPLE"] = "1"
