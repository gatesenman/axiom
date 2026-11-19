"""Parser, validator, exporters, and solver agreement."""

from __future__ import annotations

import pytest

from axiom.modeling import emit_aml, parse_aml, validate
from axiom.modeling.formats import read_lp, read_mps
from axiom.modeling.translators import translate
from axiom.solvers.registry import solve_model

PRODUCT = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

TRANSPORT = """
model Transport;
set O := {O1, O2};
set D := {D1, D2};
param supply[O] := {O1: 5, O2: 5};
param demand[D] := {D1: 4, D2: 6};
param cost[O, D] := {(O1, D1): 2, (O1, D2): 9, (O2, D1): 3, (O2, D2): 1};
var x[O, D] >= 0;
minimize total: sum {o in O, d in D} cost[o, d] * x[o, d];
subject to sup[o in O]: sum {d in D} x[o, d] <= supply[o];
subject to dem[d in D]: sum {o in O} x[o, d] >= demand[d];
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

ALLDIFF = """
set I := {A, B, C};
var x[I] integer >= 1 <= 3;
minimize first: x[A];
subject to distinct: alldiff {i in I} x[i];
"""

ROSEN = """
var x >= -2 <= 2;
var y >= -2 <= 2;
minimize rosenbrock: (1 - x)^2 + 100 * (y - x^2)^2;
"""


def test_product_mix_parses_and_roundtrips():
    model = parse_aml(PRODUCT)
    result = validate(model)
    assert result.ok
    again = parse_aml(emit_aml(model))
    assert validate(again).ok
    assert again.objectives[0].sense == "maximize"
    assert set(again.variables) == {"xA", "xB"}


def test_validator_reports_missing_data_and_bad_bounds():
    model = parse_aml("set P := {A, B}; param c[P] := {A: 1}; var x >= 5 <= 1;")
    result = validate(model)
    codes = {item.code for item in result.diagnostics if item.level == "error"}
    assert "missing_data" in codes
    assert "bad_bounds" in codes


def test_syntax_error_is_bilingual():
    with pytest.raises(Exception) as caught:
        parse_aml("var x >= ;")
    assert caught.value.code == "syntax"
    assert caught.value.message_en


@pytest.mark.parametrize("solver", ["highs", "cbc", "glpk", "scip", "glop"])
def test_product_mix_solvers_agree(solver):
    result = solve_model(parse_aml(PRODUCT), solver)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(11400 / 7, rel=1e-4)
    assert result.variables["xA"] == pytest.approx(150 / 7, rel=1e-3)
    assert result.variables["xB"] == pytest.approx(180 / 7, rel=1e-3)


def test_transport_and_format_roundtrip():
    model = parse_aml(TRANSPORT)
    base = solve_model(model, "highs")
    assert base.status == "optimal"
    assert base.objective == pytest.approx(22)
    for reader, target in ((read_lp, "lp"), (read_mps, "mps")):
        imported = reader(translate(model, target).code)
        solved = solve_model(imported, "highs")
        assert solved.status == "optimal"
        assert solved.objective == pytest.approx(base.objective, rel=1e-5)


def test_knapsack_and_alldiff():
    knapsack = solve_model(parse_aml(KNAPSACK), "cp-sat")
    assert knapsack.status == "optimal"
    assert knapsack.objective == pytest.approx(44)
    highs = solve_model(parse_aml(KNAPSACK), "highs")
    assert highs.objective == pytest.approx(44)
    distinct = solve_model(parse_aml(ALLDIFF), "highs")
    assert distinct.status == "optimal"
    chosen = [distinct.variables[key] for key in ("x[A]", "x[B]", "x[C]")]
    assert sorted(round(value) for value in chosen) == [1, 2, 3]


@pytest.mark.parametrize("solver", ["scipy", "ipopt"])
def test_nonlinear_local_solvers(solver: str):
    from axiom.solvers.registry import get_solver

    if not get_solver(solver).available():
        pytest.skip(f"{solver} is not installed")
    result = solve_model(parse_aml(ROSEN), solver)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(0, abs=1e-4)
    assert result.variables["x"] == pytest.approx(1, abs=1e-2)
    assert result.variables["y"] == pytest.approx(1, abs=1e-2)


def test_python_exporters_build_equivalent_models():
    model = parse_aml(PRODUCT)
    pulp_ns: dict = {}
    exec(translate(model, "pulp").code, pulp_ns)
    assert pulp_ns["objective_value"] == pytest.approx(11400 / 7, rel=1e-4)
    pyomo_ns: dict = {}
    exec(translate(model, "pyomo").code, pyomo_ns)
    assert pyomo_ns["model"].nvariables() == 2
    cvx_ns: dict = {}
    exec(translate(model, "cvxpy").code, cvx_ns)
    assert cvx_ns["objective_value"] == pytest.approx(11400 / 7, rel=1e-4)


def test_text_exporters_contain_the_model():
    model = parse_aml(TRANSPORT)
    ampl = translate(model, "ampl").code
    assert "minimize objective" in ampl and "sum {o in O, d in D}" in ampl
    gams = translate(model, "gams").code
    assert "axiom_obj" in gams and "=e=" in gams
    jump = translate(model, "jump").code
    assert "@variable" in jump and "@objective" in jump and "HiGHS" in jump
    ortools = translate(model, "ortools").code
    assert 'CreateSolver("SCIP")' in ortools
    compile(ortools, "ortools", "exec")


def test_indexed_pulp_matches_highs():
    model = parse_aml(TRANSPORT)
    namespace: dict = {}
    exec(translate(model, "pulp").code, namespace)
    assert namespace["objective_value"] == pytest.approx(solve_model(model, "highs").objective, rel=1e-5)


def test_infeasible_model_is_reported():
    model = parse_aml("var x >= 0; minimize z: x; subject to need: x >= 2; subject to cap: x <= 1;")
    result = solve_model(model, "highs")
    assert result.status == "infeasible"


def test_multiobjective_weighted_sum():
    model = parse_aml(
        """
        var x >= 0 <= 5;
        minimize cost: 4 * x;
        maximize service: x;
        weight cost 1;
        weight service 1;
        """
    )
    result = solve_model(model, "highs")
    assert result.status == "optimal"
    # minimize 4x - x = 3x, so the smallest feasible x wins.
    assert result.variables["x"] == pytest.approx(0, abs=1e-6)
    names = {item["name"]: item["value"] for item in result.objective_components}
    assert names["cost"] == pytest.approx(0, abs=1e-6)
    assert names["service"] == pytest.approx(0, abs=1e-6)
