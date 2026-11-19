"""Cross-solver comparison on a fixed representative set.

The cases are small on purpose: LP, MILP, convex QP, a second-order cone,
a smooth NLP, a mixed-integer quadratic program, a CP model, and a 2×2 SDP.
Each available solver that declares the matching class is timed. Commercial
solvers appear only when this machine can import a license.
"""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling import parse_aml
from axiom.solvers.capabilities import accepts, classes_of, problem_kind
from axiom.solvers.registry import SOLVERS, solve_model

LP = """
model BenchLP;
var x >= 0;
var y >= 0;
maximize profit: 40 * x + 30 * y;
subject to labor: 2 * x + 3 * y <= 120;
subject to material: 3 * x + y <= 90;
"""

MILP = """
model BenchMIP;
var x binary;
var y binary;
maximize value: 5 * x + 4 * y;
subject to cap: 2 * x + 3 * y <= 4;
"""

QP = """
model BenchQP;
var x >= -2 <= 2;
var y >= -2 <= 2;
minimize quad: (x - 1) * (x - 1) + (y - 2) * (y - 2);
"""

SOCP = """
model BenchSOC;
var x >= 0;
var y >= 0;
var t >= 0;
minimize radius: t;
subject to cover: x + y >= 1;
subject to cone: (x * x) + (y * y) <= (t * t);
"""

NLP = """
model BenchNLP;
var x >= -2 <= 2;
var y >= -2 <= 2;
minimize rosen: (1 - x)^2 + 100 * (y - x^2)^2;
"""

MINLP = """
model BenchMINLP;
var x integer >= 0 <= 3;
var y >= -2 <= 4;
minimize gap: (x - 1) * (x - 1) + (y - 2) * (y - 2);
"""

CP = """
model BenchCP;
var x integer >= 1 <= 3;
var y integer >= 1 <= 3;
var z integer >= 1 <= 3;
minimize first: x;
subject to order: x + 1 <= y;
subject to order2: y + 1 <= z;
"""

CASES = [
    ("lp", LP, 11400 / 7),
    ("milp", MILP, 5),
    ("qp", QP, 0),
    ("socp", SOCP, 0.70710678118),
    ("nlp", NLP, 0),
    ("minlp", MINLP, 0),
    ("cp", CP, 1),
]

SDP = {
    "size": 2,
    "c": [1.0],
    "matrices": [
        [[0.0, 1.0], [1.0, 0.0]],
        [[1.0, 0.0], [0.0, 1.0]],
    ],
}


def run_benchmark(classes: set[str] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for kind, aml, expected in CASES:
        if classes and kind not in classes:
            continue
        model = parse_aml(aml)
        from axiom.modeling.flatten import flatten

        flat = flatten(model)
        for solver in SOLVERS:
            if solver.name in {"local"}:
                continue
            if not accepts(solver, flat):
                continue
            if kind == "cp" and "cp" not in classes_of(solver) and solver.name not in {"highs", "cbc", "scip"}:
                continue
            actual = problem_kind(flat)
            if kind == "minlp" and actual == "miqp":
                actual = "minlp"
            if kind != "cp" and actual != kind:
                continue
            rows.append(_time_solver(kind, solver, model, expected))
    if classes is None or "sdp" in classes:
        rows.extend(_sdp_rows())
    return {
        "rows": rows,
        "seconds": time.perf_counter() - started,
        "classes": sorted({row["class"] for row in rows}),
    }


def _time_solver(kind: str, solver, model, expected: float) -> dict[str, Any]:
    if not _ready(solver):
        return _row(kind, solver.name, "not_installed", None, 0.0, expected, False)
    started = time.perf_counter()
    try:
        result = solve_model(model, solver.name, {"time_limit": 8})
    except Exception as exc:
        return _row(kind, solver.name, "error", None, time.perf_counter() - started, expected, False, str(exc))
    agree = result.objective is not None and abs(float(result.objective) - expected) <= 1e-2 * max(1.0, abs(expected))
    if kind == "socp" and result.objective is not None:
        agree = abs(float(result.objective) - expected) <= 2e-2
    return _row(kind, solver.name, result.status, result.objective, result.runtime_sec, expected, bool(result.feasible and agree))


def _sdp_rows() -> list[dict[str, Any]]:
    from axiom.solvers.conic import solve_sdpa_with

    rows = []
    for name in ("clarabel", "scs", "cvxopt"):
        solver = next(item for item in SOLVERS if item.name == name)
        if not _ready(solver):
            rows.append(_row("sdp", name, "not_installed", None, 0.0, 1.0, False))
            continue
        started = time.perf_counter()
        try:
            payload = solve_sdpa_with(name, SDP)
        except Exception as exc:
            rows.append(_row("sdp", name, "error", None, time.perf_counter() - started, 1.0, False, str(exc)))
            continue
        objective = payload.get("objective")
        agree = objective is not None and abs(float(objective) - 1.0) <= 1e-2
        rows.append(_row("sdp", name, payload.get("status") or "error", objective, time.perf_counter() - started, 1.0, agree))
    return rows


def _ready(solver) -> bool:
    try:
        return bool(solver.available())
    except Exception:
        return False


def _row(kind: str, solver: str, status: str, objective, runtime: float, expected: float, agree: bool, message: str = "") -> dict[str, Any]:
    return {
        "class": kind,
        "solver": solver,
        "status": status,
        "objective": objective,
        "expected": expected,
        "runtime_sec": runtime,
        "agree": agree,
        "message": message,
    }
