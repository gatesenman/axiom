"""Import, diagnosis, what-if, versions, recommendation, and the share package."""

from __future__ import annotations

import base64
import io
import zipfile

from fastapi.testclient import TestClient
from openpyxl import Workbook

from axiom.analysis.service import compare_solutions, diagnose, recommend, what_if
from axiom.modeling import parse_aml
from tests.support import login

PRODUCT = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

INFEASIBLE = """
var x >= 0;
maximize obj: x;
subject to low: x >= 5;
subject to high: x <= 3;
"""

KNAPSACK = """
set I := {a, b};
param value[I] := {a: 3, b: 4};
param weight[I] := {a: 2, b: 3};
var take[I] binary;
maximize worth: sum {i in I} value[i] * take[i];
subject to cap: sum {i in I} weight[i] * take[i] <= 3;
"""


def test_infeasible_diagnosis_names_a_relaxation():
    report = diagnose(parse_aml(INFEASIBLE))
    assert report["feasible_without_slacks"] is False
    assert report["conflicts"]
    assert abs(report["total_violation"] - 2) < 1e-5
    text = report["message"]
    assert "冲突" in text
    assert report["conflicts"][0]["constraint"] in {"low", "high"}
    assert "放松" in report["conflicts"][0]["suggestion"]


def test_product_mix_needs_no_slack():
    report = diagnose(parse_aml(PRODUCT))
    assert report["feasible_without_slacks"] is True


def test_recommend_lp_and_mip():
    linear = recommend(parse_aml(PRODUCT))
    assert linear["solver"] == "highs"
    assert linear["family"] == "lp"
    assert "单纯形" in linear["reason_zh"]
    integer = recommend(parse_aml(KNAPSACK))
    assert integer["solver"] == "highs"
    assert integer["family"] == "mip"
    assert "分支切割" in integer["reason_zh"]


def test_what_if_changes_the_objective():
    report = what_if(parse_aml(PRODUCT), [{"target": "rhs", "name": "labor", "value": 200}], "highs")
    assert abs(report["baseline"]["objective"] - 11400 / 7) < 1e-3
    assert report["scenario"]["objective"] > report["baseline"]["objective"]


def test_compare_solutions_delta():
    diff = compare_solutions(
        {"objective": 10, "variables": {"x": 1, "y": 2}},
        {"objective": 14, "variables": {"x": 3, "z": 1}},
    )
    assert diff["objective_delta"] == 4
    rows = {row["name"]: row["delta"] for row in diff["rows"]}
    assert rows["x"] == 2
    assert rows["y"] is None


def test_csv_gb18030_and_xlsx_round_trip(client: TestClient):
    headers = login(client)
    raw = "工厂,产能\n一厂,10\n二厂,12\n".encode("gb18030")
    preview = client.post(
        "/api/tables/preview",
        headers=headers,
        json={"filename": "plants.csv", "content_base64": base64.b64encode(raw).decode()},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["encoding"] in {"gb18030", "gbk"}
    assert body["columns"] == ["工厂", "产能"]
    applied = client.post(
        "/api/tables/apply",
        headers=headers,
        json={"dsl": PRODUCT, "columns": body["columns"], "rows": body["rows"], "mapping": body["mapping"]},
    )
    assert applied.status_code == 200, applied.text
    aml = applied.json()["aml"]
    assert "一厂" in aml
    assert "set col" in aml

    book = Workbook()
    sheet = book.active
    sheet.title = "Sites"
    sheet.append(["site", "fixed"])
    sheet.append(["North", 8])
    sheet.append(["South", 5])
    buffer = io.BytesIO()
    book.save(buffer)
    xlsx = client.post(
        "/api/tables/preview",
        headers=headers,
        json={"filename": "sites.xlsx", "content_base64": base64.b64encode(buffer.getvalue()).decode(), "sheet": "Sites"},
    )
    assert xlsx.status_code == 200, xlsx.text
    grid = xlsx.json()
    assert grid["sheet"] == "Sites"
    assert grid["rows"][0][0] == "North"
    written = client.post(
        "/api/tables/apply",
        headers=headers,
        json={
            "dsl": "",
            "columns": grid["columns"],
            "rows": grid["rows"],
            "mapping": [
                {"column": "site", "role": "set", "name": "S"},
                {"column": "fixed", "role": "parameter", "name": "fixed", "indexes": ["site"]},
            ],
        },
    )
    assert written.status_code == 200, written.text
    model = parse_aml(written.json()["aml"])
    assert model.sets["S"].elements == ["North", "South"]
    assert model.parameters["fixed"].values[("North",)] == 8


def test_outline_edits_rhs_and_versions_and_package(client: TestClient):
    headers = login(client)
    edited = client.post("/api/model-data/apply", headers=headers, json={"dsl": PRODUCT, "rhs": [{"name": "labor", "value": 100}]})
    assert edited.status_code == 200
    assert "<= 100" in edited.json()["aml"]
    created = client.post("/api/projects", headers=headers, json={"title": "版本", "dsl": PRODUCT, "locale": "zh-CN"})
    project_id = created.json()["id"]
    saved = client.post(
        f"/api/projects/{project_id}/versions",
        headers=headers,
        json={"label": "手工", "dsl": edited.json()["aml"], "statement": "改过工时"},
    )
    assert saved.status_code == 200, saved.text
    listed = client.get(f"/api/projects/{project_id}/versions", headers=headers)
    assert listed.json()[0]["label"] == "手工"
    assert "<= 100" in listed.json()[0]["dsl"]
    started = client.post(
        f"/api/projects/{project_id}/runs",
        headers=headers,
        json={"dsl": PRODUCT, "statement": "产品组合", "solver": "highs", "auto_approve": True},
    )
    assert started.status_code == 200, started.text
    versions = client.get(f"/api/projects/{project_id}/versions", headers=headers).json()
    assert any(item["label"] == "求解前" for item in versions)
    advice = client.post("/api/recommend", headers=headers, json={"dsl": PRODUCT})
    assert "单纯形" in advice.json()["reason_zh"]
    package = client.get(f"/api/runs/{started.json()['id']}/report?format=zip", headers=headers)
    # The run may still be in progress; the package uses whatever is stored.
    assert package.status_code == 200, package.text
    archive = zipfile.ZipFile(io.BytesIO(package.content))
    names = set(archive.namelist())
    assert names == {"model.aml", "results.json", "report.md", "report.pdf"}
    pdf = archive.read("report.pdf")
    markdown = archive.read("report.md").decode()
    assert pdf.startswith(b"%PDF") and len(pdf) > 400
    assert "产品组合" in markdown or "Axiom" in markdown
