"""Algorithm catalog, SOS1, piecewise linearization, audits, and workspace isolation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from axiom.analysis.algorithms import CATALOG, choose
from axiom.errors import AxiomError
from axiom.modeling import parse_aml
from axiom.solvers.registry import solve_model
from tests.support import login

PRODUCT = """
model mix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + 1 * xB <= 90;
"""

SOS = """
var xA >= 0 <= 5;
var xB >= 0 <= 5;
maximize profit: 3 * xA + 4 * xB;
sos1 pick: xA, xB;
"""

PIECE = """
var x >= 0;
minimize obj: cost;
subject to demand: x >= 10;
piecewise cost on x: (0, 0), (10, 5), (20, 30);
"""


def test_catalog_covers_the_requested_families():
    ids = {item["id"] for item in CATALOG}
    assert {
        "auto",
        "dual-simplex",
        "primal-simplex",
        "barrier",
        "branch-and-cut",
        "cbc-branch-and-cut",
        "scip-mip",
        "cp-sat",
        "slsqp",
        "ipopt",
        "weighted-sum",
        "local-search",
        "row-generation",
    } <= ids


def test_choose_matches_structure():
    linear = choose(parse_aml(PRODUCT))
    assert linear["id"] == "dual-simplex"
    assert "单纯形" in linear["reason_zh"]
    integer = choose(parse_aml("var x binary; minimize obj: x; subject to c: x >= 0;"))
    assert integer["id"] == "branch-and-cut"
    assert "分支切割" in integer["reason_zh"]
    quadratic = choose(parse_aml("var x >= 0; minimize obj: x ^ 2;"))
    assert quadratic["id"] == "osqp"
    nonlinear = choose(parse_aml("var x >= -2 <= 2; minimize obj: (1 - x) ^ 2 + (x ^ 2) ^ 2;"))
    assert nonlinear["id"] == "slsqp"
    weighted = choose(parse_aml("var x >= 0 <= 1; minimize a: x; maximize b: x;"))
    assert weighted["id"] == "weighted-sum"


def test_sos1_picks_the_better_member():
    result = solve_model(parse_aml(SOS), "highs")
    assert result.status == "optimal"
    assert result.objective == pytest.approx(20, abs=1e-4)
    assert result.variables["xA"] == pytest.approx(0, abs=1e-4)
    assert result.variables["xB"] == pytest.approx(5, abs=1e-4)


def test_piecewise_sits_on_the_cheapest_feasible_breakpoint():
    result = solve_model(parse_aml(PIECE), "highs")
    assert result.status == "optimal"
    assert result.variables["x"] == pytest.approx(10, abs=1e-4)
    assert result.variables["cost"] == pytest.approx(5, abs=1e-4)


def test_row_generation_matches_the_full_product_mix():
    result = solve_model(parse_aml(PRODUCT), "highs", {"algorithm": "row-generation"})
    assert result.status == "optimal"
    assert result.objective == pytest.approx(1628.571, abs=1e-3)


def test_simplex_and_barrier_keep_the_product_mix_optimum():
    for algorithm in ("dual-simplex", "primal-simplex", "barrier"):
        result = solve_model(parse_aml(PRODUCT), "highs", {"algorithm": algorithm})
        assert result.status == "optimal"
        assert result.objective == pytest.approx(1628.571, abs=1e-2)
        assert result.duals


def test_local_search_enumerates_a_tiny_binary():
    model = parse_aml("var x binary; var y binary; maximize obj: 3 * x + y; subject to c: x + y <= 1;")
    result = solve_model(model, "local")
    assert result.status == "optimal"
    assert result.objective == pytest.approx(3, abs=1e-6)
    wide = parse_aml("var x integer >= 0 <= 20; minimize obj: x; subject to c: x >= 0;")
    skipped = solve_model(wide, "local")
    assert skipped.status == "not_applicable"


def test_index_offset_names_the_set():
    model = parse_aml(
        """
        set P := {a, b};
        var x[P] >= 0;
        minimize obj: sum {i in P} x[i];
        subject to link[i in P]: x[i+1] <= 1;
        """
    )
    with pytest.raises(AxiomError) as caught:
        solve_model(model, "highs")
    assert "超出集合" in caught.value.message
    assert "共 2 个元素" in caught.value.message


def test_rate_limit_is_a_429():
    from axiom.limit import check_rate, reset_limits

    reset_limits()
    for _ in range(3):
        check_rate("algorithms-test", limit=3, window=60)
    with pytest.raises(AxiomError) as caught:
        check_rate("algorithms-test", limit=3, window=60)
    assert caught.value.status == 429


def test_algorithms_route_and_audits(client: TestClient):
    headers = login(client)
    catalog = client.get("/api/algorithms", headers=headers)
    assert catalog.status_code == 200
    assert any(item["id"] == "dual-simplex" and item["label_zh"] == "对偶单纯形" for item in catalog.json())
    imported = client.post(
        "/api/import",
        json={"format": "aml", "text": PRODUCT},
        headers=headers,
    )
    assert imported.status_code == 200
    edited = client.post(
        "/api/model-data/apply",
        json={"dsl": PRODUCT, "rhs": [{"name": "labor", "value": 100}]},
        headers=headers,
    )
    assert edited.status_code == 200
    assert "100" in edited.json()["aml"]
    applied = client.post(
        "/api/tables/apply",
        json={
            "dsl": "param price default 1 := 1;\nvar x >= 0;\nmaximize obj: price * x;\nsubject to cap: x <= 1;\n",
            "columns": ["price"],
            "rows": [["4"]],
            "mapping": [{"column": "price", "role": "parameter", "name": "price", "indexes": []}],
        },
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    project = client.post("/api/projects", json={"title": "审计", "dsl": PRODUCT, "statement": "审计"}, headers=headers)
    run = client.post(
        f"/api/projects/{project.json()['id']}/runs",
        json={"dsl": PRODUCT, "statement": "审计", "solver": "highs", "algorithm": "dual-simplex", "auto_approve": True},
        headers=headers,
    )
    assert run.status_code == 200, run.text
    assert run.json()["solver"] == "highs"
    report = client.get(f"/api/runs/{run.json()['id']}/report?format=md", headers=headers)
    assert report.status_code == 200
    actions = {row["action"] for row in client.get("/api/audit", headers=headers).json()}
    assert {"model.import", "model.edit", "data.import", "run.start", "report.export"} <= actions


def test_members_cannot_read_another_workspace(client: TestClient):
    admin = login(client)
    bob_user = client.post(
        "/api/users",
        json={"username": "bob", "password": "secret1", "display_name": "Bob", "role": "member"},
        headers=admin,
    )
    alice_user = client.post(
        "/api/users",
        json={"username": "alice", "password": "secret1", "display_name": "Alice", "role": "member"},
        headers=admin,
    )
    assert bob_user.status_code == 200 and alice_user.status_code == 200
    lab = client.post("/api/workspaces", json={"name": "BobLab"}, headers=admin)
    assert lab.status_code == 200
    added = client.post(f"/api/workspaces/{lab.json()['id']}/members", json={"username": "bob"}, headers=admin)
    assert added.status_code == 200
    bob = login(client, "bob", "secret1")
    alice = login(client, "alice", "secret1")
    created = client.post(
        "/api/projects",
        json={"title": "Bob only", "workspace_id": lab.json()["id"], "dsl": PRODUCT},
        headers=bob,
    )
    assert created.status_code == 200, created.text
    denied = client.get(f"/api/projects/{created.json()['id']}", headers=alice)
    assert denied.status_code == 403
