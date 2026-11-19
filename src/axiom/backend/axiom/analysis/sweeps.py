"""One- and two-factor parametric sweeps. Each node is a fresh solve."""

from __future__ import annotations

import numpy as np

from axiom.analysis.service import what_if_knobs
from axiom.errors import AxiomError
from axiom.modeling.ir import Model, const
from axiom.solvers.registry import solve_model


def sweep(model: Model, factors: list[dict] | None = None, steps: int = 9, solver: str = "highs", cancel=None) -> dict:
    knobs = factors or _default_factors(model)
    if not knobs:
        return {"ok": False, "message": "没有可扫描的右端或参数。", "message_en": "There is no right-hand side or parameter to sweep."}
    count = max(3, min(int(steps), 21))
    if len(knobs) == 1:
        return _curve(model, knobs[0], count, solver, cancel)
    return _surface(model, knobs[0], knobs[1], min(count, 9), solver, cancel)


def _default_factors(model: Model) -> list[dict]:
    rows = []
    for knob in what_if_knobs(model)[:2]:
        rows.append(
            {
                "target": knob["target"],
                "name": knob["name"],
                "index": knob.get("index") or [],
                "label": knob["label"],
                "lower": knob["min"],
                "upper": knob["max"],
            }
        )
    return rows


def _curve(model, factor, steps, solver, cancel) -> dict:
    axis = np.linspace(float(factor["lower"]), float(factor["upper"]), steps)
    points = []
    for index, value in enumerate(axis):
        if cancel and cancel():
            break
        solved = _solve_at(model, [dict(factor, value=float(value))], solver)
        points.append({"id": f"s-{index}", "x": float(value), "objective": solved.objective, "status": solved.status, "feasible": solved.feasible})
    return {
        "ok": any(point["objective"] is not None for point in points),
        "kind": "sweep-1d",
        "factor": factor,
        "points": points,
    }


def _surface(model, left, right, steps, solver, cancel) -> dict:
    xs = np.linspace(float(left["lower"]), float(left["upper"]), steps)
    ys = np.linspace(float(right["lower"]), float(right["upper"]), steps)
    grid = []
    points = []
    for i, x in enumerate(xs):
        row = []
        for j, y in enumerate(ys):
            if cancel and cancel():
                break
            solved = _solve_at(model, [dict(left, value=float(x)), dict(right, value=float(y))], solver)
            row.append(solved.objective)
            points.append({"id": f"s-{i}-{j}", "x": float(x), "y": float(y), "objective": solved.objective, "status": solved.status})
        grid.append(row)
    return {
        "ok": any(point["objective"] is not None for point in points),
        "kind": "sweep-2d",
        "factors": [left, right],
        "x": [float(item) for item in xs],
        "y": [float(item) for item in ys],
        "grid": grid,
        "points": points,
    }


def _solve_at(model: Model, changes: list[dict], solver: str):
    mutated = model.copy()
    for change in changes:
        value = float(change["value"])
        if change.get("target") == "param":
            name = change["name"]
            if name not in mutated.parameters:
                raise AxiomError(f"没有参数 {name}。", f"Parameter {name} is missing.", code="missing_data")
            index = tuple(str(part) for part in change.get("index") or [])
            mutated.parameters[name].values[index] = value
        else:
            found = False
            for con in mutated.constraints:
                if con.name == change["name"] and con.rhs is not None and con.rhs.op == "const":
                    con.rhs = const(value)
                    found = True
            if not found:
                raise AxiomError(f"没有右端 {change['name']}。", f"Right-hand side {change['name']} is missing.", code="missing_rhs")
    return solve_model(mutated, solver, {"time_limit": 8})
