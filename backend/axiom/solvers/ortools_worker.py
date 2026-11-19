"""Subprocess entry point for OR-Tools.

highspy and the OR-Tools wheel both ship a HiGHS shared library. Loading them
in one process breaks dynamic linking, so SCIP, GLOP, and CP-SAT run here in
a clean interpreter. The parent sends a flat model as JSON on stdin.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    payload = json.load(sys.stdin)
    backend = payload["backend"]
    if backend == "CP-SAT":
        result = _cpsat(payload)
    else:
        result = _linear(payload, backend)
    json.dump(result, sys.stdout)
    return 0


def _linear(payload: dict, backend: str) -> dict:
    from ortools.linear_solver import pywraplp

    solver = pywraplp.Solver.CreateSolver(backend)
    if solver is None:
        return {"status": "error", "raw": "missing-backend", "values": {}}
    inf = solver.infinity()
    columns = {}
    for var in payload["variables"]:
        lower = -inf if var["lower"] is None else float(var["lower"])
        upper = inf if var["upper"] is None else float(var["upper"])
        if var["domain"] in {"integer", "binary"}:
            columns[var["key"]] = solver.IntVar(lower, upper, var["key"][:80])
        else:
            columns[var["key"]] = solver.NumVar(lower, upper, var["key"][:80])
    objective = solver.Objective()
    for key, coef in payload["objective"].items():
        objective.SetCoefficient(columns[key], float(coef))
    if abs(float(payload.get("constant") or 0.0)) > 1e-12 and hasattr(objective, "SetOffset"):
        objective.SetOffset(float(payload["constant"]))
    if payload["sense"] == "maximize":
        objective.SetMaximization()
    else:
        objective.SetMinimization()
    for con in payload["constraints"]:
        if con["sense"] == "<=":
            lower, upper = -inf, float(con["rhs"])
        elif con["sense"] == ">=":
            lower, upper = float(con["rhs"]), inf
        else:
            lower = upper = float(con["rhs"])
        row = solver.Constraint(lower, upper, con["key"][:80])
        for key, coef in con["coeffs"].items():
            row.SetCoefficient(columns[key], float(coef))
    if payload.get("time_limit"):
        solver.SetTimeLimit(int(float(payload["time_limit"]) * 1000))
    code = solver.Solve()
    mapping = {
        pywraplp.Solver.OPTIMAL: "optimal",
        pywraplp.Solver.FEASIBLE: "feasible",
        pywraplp.Solver.INFEASIBLE: "infeasible",
        pywraplp.Solver.UNBOUNDED: "unbounded",
    }
    status = mapping.get(code, "error")
    values = {}
    if status in {"optimal", "feasible"}:
        values = {key: float(var.solution_value()) for key, var in columns.items()}
    return {"status": status, "raw": str(code), "values": values}


def _cpsat(payload: dict) -> dict:
    from ortools.sat.python import cp_model

    problem = cp_model.CpModel()
    columns = {}
    for var in payload["variables"]:
        if var["domain"] == "binary":
            lower = 0 if var["lower"] is None else int(round(var["lower"]))
            upper = 1 if var["upper"] is None else int(round(var["upper"]))
        else:
            lower = -1_000_000 if var["lower"] is None else int(round(var["lower"]))
            upper = 1_000_000 if var["upper"] is None else int(round(var["upper"]))
        columns[var["key"]] = problem.NewIntVar(lower, upper, var["key"][:80])
    for con in payload["constraints"]:
        expr = sum(int(round(coef)) * columns[key] for key, coef in con["coeffs"].items())
        rhs = int(round(con["rhs"]))
        if con["sense"] == "<=":
            problem.Add(expr <= rhs)
        elif con["sense"] == ">=":
            problem.Add(expr >= rhs)
        else:
            problem.Add(expr == rhs)
    objective = sum(int(round(coef)) * columns[key] for key, coef in payload["objective"].items())
    if payload["sense"] == "maximize":
        problem.Maximize(objective)
    else:
        problem.Minimize(objective)
    solver = cp_model.CpSolver()
    if payload.get("time_limit"):
        solver.parameters.max_time_in_seconds = float(payload["time_limit"])
    code = solver.Solve(problem)
    raw = solver.StatusName(code)
    status = {"OPTIMAL": "optimal", "FEASIBLE": "feasible", "INFEASIBLE": "infeasible"}.get(raw, "error")
    values = {}
    if status in {"optimal", "feasible"}:
        values = {key: float(solver.Value(var)) for key, var in columns.items()}
    return {"status": status, "raw": raw, "values": values}


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - reported to the parent
        json.dump({"status": "error", "raw": "exception", "values": {}, "message": str(exc)}, sys.stdout)
        raise SystemExit(1)
