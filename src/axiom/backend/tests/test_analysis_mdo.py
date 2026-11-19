"""Compatibility, post-optimal analysis, and multidisciplinary optimization."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from axiom.agents.studies import propose
from axiom.analysis.designs import generate
from axiom.analysis.studio import run_study
from axiom.analysis.surrogates import fit
from axiom.analysis.uncertainty import hlrf
from axiom.modeling import parse_aml
from axiom.mdo.architectures import n2_diagram, solve
from axiom.mdo.openmdao_backend import available as openmdao_available
from axiom.mdo.templates import sellar, supply, wing
from tests.support import login

PRODUCT = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

BI = """
model Trade;
var xA >= 0 <= 40;
var xB >= 0 <= 40;
maximize profit: 40 * xA + 30 * xB;
minimize labor: 2 * xA + 3 * xB;
subject to material: 3 * xA + xB <= 90;
"""

INFEASIBLE = """
model Clash;
var x >= 0;
maximize profit: x;
subject to low: x >= 5;
subject to high: x <= 2;
subject to slack: x <= 10;
"""


def test_designs_cover_the_classical_plans():
    bounds = [(0.0, 1.0), (2.0, 4.0), (-1.0, 1.0)]
    full = generate("full", bounds[:2], levels=3)
    assert full["samples"] == 9
    fractional = generate("fractional", bounds + [(0.0, 1.0)])
    assert fractional["samples"] < 16
    assert fractional["samples"] >= 4
    for method in ("lhs", "sobol", "halton"):
        design = generate(method, bounds, samples=8, seed=2)
        assert design["samples"] >= 8
        array = np.array(design["natural"])
        assert array.min(axis=0)[0] >= -1e-9
        assert array.max(axis=0)[0] <= 1 + 1e-9
    ccd = generate("ccd", bounds[:2])
    assert ccd["samples"] == 9
    box = generate("box-behnken", bounds)
    assert box["samples"] == 15


def test_surrogates_recover_a_quadratic_and_report_cv():
    rng = np.random.default_rng(0)
    x_values = rng.uniform(-1, 1, size=(24, 2))
    y_values = 1.0 + 2.0 * x_values[:, 0] - 0.5 * x_values[:, 1] + 0.3 * x_values[:, 0] ** 2
    for kind in ("polynomial", "rbf", "kriging"):
        fitted = fit(kind, x_values, y_values)
        assert fitted["cv"]["r2"] > 0.9
        mean = fitted["model"].predict(x_values[:3])["mean"]
        assert mean.shape == (3,)


def test_sobol_and_morris_match_a_linear_function():
    def function(sample):
        return float(sample[0] + 2.0 * sample[1])

    from axiom.analysis.screening import morris, sobol as sobol_indices

    indices = sobol_indices(function, ["x", "y"], [(0.0, 1.0), (0.0, 1.0)], samples=64, seed=1)
    assert indices["library"] == "SALib"
    assert indices["rows"][0]["S1"] == pytest.approx(0.2, abs=0.08)
    assert indices["rows"][1]["S1"] == pytest.approx(0.8, abs=0.08)
    screened = morris(lambda sample: float(5.0 * sample[0]), ["x", "y"], [(0.0, 1.0), (0.0, 1.0)], trajectories=8, seed=1)
    assert screened["rows"][0]["mu_star"] > screened["rows"][1]["mu_star"] * 5


def test_local_ranging_duals_and_quality_on_the_product_mix():
    local = run_study("local", PRODUCT)
    assert local["ok"]
    assert local["objective"] == pytest.approx(11400 / 7, rel=1e-5)
    duals = local["duals"]
    assert duals["labor"] == pytest.approx(50 / 7, rel=1e-3)
    assert duals["material"] == pytest.approx(60 / 7, rel=1e-3)
    profit = next(row for row in local["objective_ranging"] if row["name"] == "xA")
    assert profit["allowable_min"] <= 40 <= profit["allowable_max"]
    assert profit["allowable_max"] > profit["allowable_min"]
    report = run_study("quality", PRODUCT)
    assert report["quality"]["max_violation"] <= 1e-6
    conflict = run_study("iis", INFEASIBLE)
    assert set(conflict["iis"]["constraints"]) == {"low", "high"}


def test_sweeps_uncertainty_chance_and_recourse():
    curve = run_study("sweep", PRODUCT, {"steps": 5})
    assert curve["kind"] == "sweep-1d" or curve["kind"] == "sweep"
    assert len(curve["points"]) >= 5
    objectives = [point["objectives"]["objective"] for point in curve["points"] if point["objectives"]["objective"] is not None]
    assert max(objectives) >= min(objectives)
    cloud = run_study("uq", PRODUCT, {"method": "lhs", "samples": 12, "cv": 0.05, "seed": 3})
    assert cloud["samples"] >= 8
    assert cloud["std"] > 0
    tightened = run_study("chance", PRODUCT, {"alpha": 0.05, "cv": 0.1})
    assert tightened["ok"]
    assert tightened["objective"] < tightened["baseline"]
    robust = run_study("robust", PRODUCT, {"mode": "two-stage"})
    assert robust["ok"]
    assert robust["wait_and_see"]["expected"] is not None


def test_form_on_a_linear_limit_state():
    beta, point, converged = hlrf(lambda unit: 2.0 - float(unit[0]), 1)
    assert converged
    assert beta == pytest.approx(2.0, abs=1e-2)
    assert point[0] == pytest.approx(2.0, abs=1e-2)


def test_multiobjective_front_and_hypervolume():
    weighted = run_study("multi", BI, {"method": "weighted", "weights": [1.0, 0.0]})
    assert weighted["ok"]
    front = run_study("multi", BI, {"method": "nsga2", "generations": 20, "population": 24, "seed": 1})
    assert front["library"] == "pymoo"
    assert front["hypervolume"] > 0
    assert len(front["pareto"]) >= 3
    nsga3 = run_study("multi", BI, {"method": "nsga3", "generations": 12, "population": 20, "seed": 1})
    assert nsga3["ok"]
    epsilon = run_study("multi", BI, {"method": "epsilon", "steps": 4})
    assert epsilon["ok"]
    assert epsilon["hypervolume"] > 0


def test_doe_fits_a_surface_on_the_product_mix():
    study = run_study("doe", PRODUCT, {"method": "lhs", "samples": 12, "surrogate": "polynomial", "seed": 1})
    assert study["ok"]
    assert len(study["points"]) >= 12
    assert study["surface"]["z"]
    assert study["surrogate"]["cv"]["r2"] > 0.95
    assert study["correlation"]["matrix"]
    assert study["effects"]["main"]


def test_sellar_architectures_match_the_published_optimum():
    target = 3.18339395
    for architecture in ("mdf", "idf", "co", "bliss", "openmdao"):
        result = solve(sellar(), architecture)
        assert result["ok"], result.get("message_en")
        assert result["objective"] == pytest.approx(target, abs=0.02)
        assert result["violation"] <= 1e-4
        assert result["n2"]["labels"] == ["discipline1", "discipline2"]
    diagram = n2_diagram(sellar())
    couplings = [cell for cell in diagram["cells"] if cell["kind"] == "coupling"]
    assert {tuple(cell["variables"]) for cell in couplings} == {("y2",), ("y1",)}
    assert openmdao_available()[0]


def test_wing_and_supply_are_feasible_multidisciplinary_problems():
    for problem in (wing(), supply()):
        mdf = solve(problem, "mdf")
        idf = solve(problem, "idf")
        assert mdf["ok"] and idf["ok"]
        assert mdf["violation"] <= 1e-4
        assert idf["violation"] <= 1e-4
        assert idf["objective"] == pytest.approx(mdf["objective"], rel=0.05, abs=1e-3)
        assert mdf["disciplines"]


def test_schedule_gantt_and_language_proposal():
    schedule = run_study("schedule", "")
    assert schedule["ok"]
    assert schedule["objective"] == pytest.approx(9, abs=1e-6)
    assert len(schedule["gantt"]) == 3
    intent = propose("请用 IDF 做 Sellar 多学科优化，并画出 N2")
    assert intent["auto"]["kind"] == "mdo"
    assert intent["auto"]["options"]["architecture"] == "idf"
    assert intent["auto"]["options"]["template"] == "sellar"
    assert propose("做一组 Sobol 全局灵敏度")["auto"]["kind"] == "sobol"


def test_compatibility_explains_every_gap_and_checks_the_solvers(client: TestClient):
    from axiom.analysis.compatibility import compatibility_matrix
    from axiom.solvers.registry import SOLVERS

    structural = compatibility_matrix(execute=False)
    classes = set(structural["classes"])
    names = {solver.name for solver in SOLVERS if solver.name != "local"}
    seen = {(row["class"], row["name"]) for row in structural["solvers"]}
    for kind in classes:
        for name in names:
            assert (kind, name) in seen
    for row in structural["solvers"] + structural["languages"]:
        assert row["status"]
        if row["status"] != "ok":
            assert row["reason_en"]
    headers = login(client)
    listed = client.get("/api/compatibility", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["summary"]["solver_unsupported"] > 0


def test_compatibility_execution_agrees():
    from axiom.analysis.compatibility import compatibility_matrix

    report = compatibility_matrix(execute=True)
    bad = [
        row
        for row in report["solvers"]
        if row.get("available") and row.get("accepts") and row["status"] != "ok"
    ]
    assert not bad, bad[:6]
    languages = [row for row in report["languages"] if row["class"] == "lp" and row["status"] == "ok"]
    assert len(languages) >= 10
    mismatches = [row for row in report["languages"] if row["status"] == "mismatch" and row["class"] == "lp"]
    assert not mismatches, mismatches
