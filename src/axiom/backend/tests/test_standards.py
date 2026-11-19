"""File formats, modeling-library round trips, and the solver catalog."""

from pathlib import Path

import pytest

from axiom.modeling import parse_aml
from axiom.modeling.exchange import read_model
from axiom.modeling.translators import translate
from axiom.solvers.capabilities import describe, race_names
from axiom.solvers.registry import get_solver, list_solvers, solve_model

DATA = Path(__file__).parent / "data" / "benchmarks"
OPT = 11400 / 7

PRODUCT = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

QP = """
model Quad;
var x >= -2 <= 2;
var y >= -2 <= 2;
minimize quad: (x - 1) * (x - 1) + (y - 2) * (y - 2);
"""

FORMATS = ["lp", "mps", "mps-free", "qps", "nl", "osil", "cbf", "flatzinc", "minizinc"]
LIBRARIES = ["gmpl", "zimpl", "opl", "gurobipy", "docplex", "linopy", "mip", "casadi", "ampl", "gams", "jump", "pyomo", "pulp", "cvxpy"]


def _opt(model) -> float:
    result = solve_model(model, "highs")
    assert result.status == "optimal", result.message
    return float(result.objective)


@pytest.mark.parametrize("target", FORMATS)
def test_linear_format_round_trip(target: str):
    model = parse_aml(PRODUCT)
    imported = read_model(target, translate(model, target).code)
    assert _opt(imported) == pytest.approx(OPT, rel=1e-5)


def test_nl_keeps_quadratic_and_rosenbrock():
    from axiom.modeling.evaluate import evaluate

    quadratic = parse_aml(QP)
    imported = read_model("nl", translate(quadratic, "nl").code)
    solved = solve_model(imported, "highs")
    assert solved.status == "optimal"
    assert solved.objective == pytest.approx(0, abs=1e-5)
    assert solved.variables["x"] == pytest.approx(1, abs=1e-4)
    assert solved.variables["y"] == pytest.approx(2, abs=1e-4)

    rosen = parse_aml(
        """
        model BenchNLP;
        var x >= -2 <= 2;
        var y >= -2 <= 2;
        minimize rosen: (1 - x)^2 + 100 * (y - x^2)^2;
        """
    )
    restored = read_model("nl", translate(rosen, "nl").code)
    assert evaluate(restored, restored.objectives[0].expr, {"x": 1, "y": 1}) == pytest.approx(0, abs=1e-8)
    assert evaluate(restored, restored.objectives[0].expr, {"x": 0, "y": 0}) == pytest.approx(1, abs=1e-8)


def test_asl_sol_reader_keeps_primals_after_suffixes():
    from axiom.solvers.asl import _read_sol

    text = """
Ipopt 3.14.20: Optimal Solution Found
Options
3
1
1
0
2
2
2
2
7.142857142882195
8.57142857145084
21.428571642781968
25.714285971361747
objno 0 0
suffix 4 2 13 0 0
ipopt_zL_out
0 -1.16e-10
1 -9.74e-11
"""
    values, _message, status = _read_sol(text, ["x", "y"])
    assert status == "optimal"
    assert values["x"] == pytest.approx(21.428571642781968)
    assert values["y"] == pytest.approx(25.714285971361747)


def test_qps_keeps_a_quadratic_objective():
    model = parse_aml(QP)
    imported = read_model("qps", translate(model, "qps").code)
    result = solve_model(imported, "highs")
    assert result.status == "optimal"
    assert result.objective == pytest.approx(0, abs=1e-6)
    assert result.variables["x"] == pytest.approx(1, abs=1e-4)
    assert result.variables["y"] == pytest.approx(2, abs=1e-4)


@pytest.mark.parametrize("target", LIBRARIES)
def test_library_round_trip(target: str):
    model = parse_aml(PRODUCT)
    text = translate(model, target).code
    key = "mod" if target in {"ampl", "gmpl", "opl", "zimpl"} else "py" if target in {"gurobipy", "docplex", "linopy", "mip", "casadi", "pyomo", "pulp", "cvxpy"} else target
    if target == "gams":
        key = "gams"
    if target == "jump":
        key = "jump"
    imported = read_model(key, text)
    assert _opt(imported) == pytest.approx(OPT, rel=1e-4)


def test_netlib_afiro_and_miplib_flugpl():
    afiro = read_model("mps", (DATA / "afiro.mps").read_text())
    solved = solve_model(afiro, "highs")
    assert solved.status == "optimal"
    assert solved.objective == pytest.approx(-464.753142857, rel=1e-8)
    flugpl = read_model("mps", (DATA / "flugpl.mps").read_text())
    mip = solve_model(flugpl, "highs")
    assert mip.status == "optimal"
    assert mip.objective == pytest.approx(1_201_500)


def test_catalog_marks_bundled_and_commercial():
    rows = {item["name"]: item for item in list_solvers()}
    assert rows["highs"]["available"] is True
    assert rows["highs"]["distribution"] == "bundled"
    assert rows["highs"]["license_state"] == "open"
    assert {"lp", "milp", "qp"} <= set(rows["highs"]["classes"])
    for name in ("gurobi", "cplex", "xpress", "mosek", "copt", "knitro", "baron", "hexaly"):
        assert rows[name]["distribution"] == "detected"
        assert rows[name]["license_type"] == "commercial"
        assert rows[name]["license_state"] == "not_installed"
        assert rows[name]["available"] is False
        assert rows[name]["docs_url"]
    assert rows["bonmin"]["license_state"] == "not_installed"
    assert rows["couenne"]["license_state"] == "not_installed"
    assert "duals" in rows["highs"]["features"]


def test_race_includes_capable_open_solvers():
    names = race_names(parse_aml(PRODUCT), "highs")
    assert names[0] == "highs"
    for required in ("cbc", "clp", "glpk", "clarabel", "osqp", "cvxopt", "python-mip", "scipy-highs"):
        assert required in names
    assert "gurobi" not in names
    assert "local" not in names


def test_soc_and_sdp_optima():
    soc = parse_aml(
        """
        var x >= 0;
        var y >= 0;
        var t >= 0;
        minimize radius: t;
        subject to cover: x + y >= 1;
        subject to cone: (x * x) + (y * y) <= (t * t);
        """
    )
    clarabel = get_solver("clarabel")
    if clarabel.available():
        result = solve_model(soc, "clarabel")
        assert result.status == "optimal"
        assert result.objective == pytest.approx(2 ** -0.5, abs=1e-3)
    from axiom.analysis.benchmark import SDP
    from axiom.solvers.conic import solve_sdpa_with

    for name in ("clarabel", "scs", "cvxopt"):
        payload = solve_sdpa_with(name, SDP)
        assert payload["status"] == "optimal"
        assert payload["objective"] == pytest.approx(1, abs=1e-3)


def test_benchmark_agrees_on_every_available_solver():
    from axiom.analysis.benchmark import run_benchmark

    report = run_benchmark()
    bad = [row for row in report["rows"] if row["status"] != "not_installed" and not row["agree"]]
    assert not bad
    assert {"lp", "milp", "qp", "socp", "nlp", "minlp", "cp", "sdp"} <= set(report["classes"])


def test_describe_shape():
    row = describe(get_solver("highs"))
    assert row["bundled"] is True
    assert row["label"] == "HiGHS"
