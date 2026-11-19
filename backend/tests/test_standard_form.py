"""Standard-form equations for LP and MIP, and the gate before a solve."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from axiom.errors import AxiomError
from axiom.modeling import parse_aml, standard_form
from axiom.reports.build import markdown_report, pdf_report
from axiom.solvers.registry import solve_model
from tests.support import login, wait_run

PRODUCT = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

KNAPSACK = """
set I := {1, 2, 3, 4};
param v[I] := {1: 16, 2: 19, 3: 23, 4: 28};
param w[I] := {1: 2, 2: 3, 3: 4, 4: 5};
param W := 7;
var x[I] binary;
maximize value: sum {i in I} v[i] * x[i];
subject to cap: sum {i in I} w[i] * x[i] <= W;
"""

ROSEN = """
var x >= -2 <= 2;
var y >= -2 <= 2;
minimize rosenbrock: (1 - x)^2 + 100 * (y - x^2)^2;
"""


def test_product_mix_standard_form_is_lp_with_slacks():
    form = standard_form(parse_aml(PRODUCT))
    assert form["ok"] is True
    assert form["kind"] == "lp"
    assert form["sense"] == "maximize"
    assert form["c"]["xA"] == 40
    assert form["c"]["xB"] == 30
    labor = next(row for row in form["rows"] if row["name"] == "labor")
    material = next(row for row in form["rows"] if row["name"] == "material")
    assert labor["sense"] == "<="
    assert labor["rhs"] == 120
    assert labor["coeffs"] == {"xA": 2.0, "xB": 3.0}
    assert material["coeffs"]["xA"] == 3
    assert material["coeffs"]["xB"] == 1
    assert material["rhs"] == 90
    canonical = form["canonical"]
    assert canonical["applicable"] is True
    labor_eq = next(row for row in canonical["equations"] if row["constraint"] == "labor")
    assert labor_eq["sense"] == "="
    assert labor_eq["coeffs"]["s_labor"] == 1
    assert labor_eq["rhs"] == 120
    assert "s_labor" in canonical["nonnegative"]
    assert "s_material" in canonical["nonnegative"]
    assert "xA" in canonical["nonnegative"]
    linked = {item["constraint"] for item in form["maps"]}
    assert linked == {"labor", "material"}
    assert r"\le" in form["latex"]
    assert "labor" in form["plain"]
    assert "s_labor" in form["plain"]
    assert form["mathml"].startswith("<math")
    assert form["integers"] == []
    assert form["binaries"] == []


def test_knapsack_standard_form_marks_binaries():
    form = standard_form(parse_aml(KNAPSACK))
    assert form["kind"] == "milp"
    assert form["sense"] == "maximize"
    assert set(form["binaries"]) == {"x[1]", "x[2]", "x[3]", "x[4]"}
    cap = next(row for row in form["rows"] if row["name"] == "cap")
    assert cap["sense"] == "<="
    assert cap["rhs"] == 7
    assert cap["coeffs"]["x[1]"] == 2
    assert cap["coeffs"]["x[4]"] == 5
    slack = next(row for row in form["canonical"]["equations"] if row["constraint"] == "cap")
    assert slack["coeffs"]["s_cap"] == 1
    assert any(row["kind"] == "equality" and "s_ub_" in "".join(row["coeffs"]) for row in form["canonical"]["equations"])
    assert r"\mathcal{B}" in form["latex"] or r"\{0,1\}" in form["latex"]
    assert any(item["constraint"] == "cap" for item in form["maps"])
    indexed = standard_form(
        parse_aml(
            "set I := {A, B};\nvar x[I] >= 0;\nminimize cost: sum {i in I} x[i];\nsubject to cover[i in I]: x[i] >= 1;\n"
        )
    )
    assert {row["key"] for row in indexed["rows"]} == {"cover[A]", "cover[B]"}
    assert indexed["indexed"][0]["constraint"] == "cover"
    assert "i in I" in indexed["indexed"][0]["plain"]


def test_nonlinear_skips_slack_form():
    form = standard_form(parse_aml(ROSEN))
    assert form["kind"] == "nlp"
    assert form["canonical"]["applicable"] is False
    assert "rosenbrock" in form["plain"]
    assert "x" in form["latex"]


def test_solve_still_requires_a_standard_form_and_keeps_the_optimum():
    result = solve_model(parse_aml(PRODUCT), "highs")
    assert result.status == "optimal"
    assert result.objective == pytest.approx(11400 / 7, rel=1e-4)

    with pytest.raises(AxiomError) as caught:
        solve_model(parse_aml("var x >= 0;"), "highs")
    assert caught.value.code == "no_objective"


def test_reports_include_standard_equations():
    form = standard_form(parse_aml(PRODUCT))
    run = {
        "title": "产品组合",
        "statement": "利润最大",
        "status": "optimal",
        "solver": "highs",
        "objective": 1628.571,
        "dsl": PRODUCT,
        "variables": {"xA": 21.4, "xB": 25.7},
        "standard_form": form,
    }
    markdown = markdown_report(run, "zh-CN")
    assert "## 标准方程" in markdown
    assert "s_labor" in markdown
    assert r"\max" in markdown or "maximize" in markdown
    pdf = pdf_report(run, "zh-CN")
    assert pdf[:4] == b"%PDF"


def test_api_standard_form_and_solver_does_not_start_when_it_fails(client: TestClient, monkeypatch):
    headers = login(client)
    product = client.post("/api/standard-form", json={"dsl": PRODUCT}, headers=headers)
    assert product.status_code == 200, product.text
    body = product.json()
    assert body["kind"] == "lp"
    assert body["rows"][0]["name"] == "labor"
    knapsack = client.post("/api/standard-form", json={"dsl": KNAPSACK}, headers=headers)
    assert knapsack.json()["kind"] == "milp"
    empty = client.post("/api/standard-form", json={"dsl": "var x >= 0;"}, headers=headers)
    assert empty.json()["ok"] is False

    def boom(_model):
        raise AxiomError("标准方程生成失败。", "Standard form failed.", code="standard_form")

    monkeypatch.setattr("axiom.agents.orchestrator.standard_form", boom)
    created = client.post("/api/projects", json={"title": "方程闸门", "statement": "产品组合", "dsl": PRODUCT}, headers=headers)
    assert created.status_code == 200, created.text
    started = client.post(
        f"/api/projects/{created.json()['id']}/runs",
        json={"statement": "产品组合", "dsl": PRODUCT, "auto_approve": True, "solver": "highs"},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    payload = wait_run(client, headers, started.json()["id"], timeout=60)
    assert payload["status"] == "failed", payload
    assert "标准方程" in (payload.get("error") or "")
    events = client.get(f"/api/runs/{started.json()['id']}/events", headers=headers).json()
    assert not any(item["kind"] == "race" for item in events)
    assert any(item["title"] == "标准方程未能生成" for item in events)
