"""Evaluate an AML model as a black-box response over a design window."""

from __future__ import annotations

import numpy as np

from axiom.errors import AxiomError
from axiom.modeling.evaluate import evaluate
from axiom.modeling.flatten import flatten
from axiom.modeling.ir import Model
from axiom.solvers.common import objective_value


def windows(model: Model) -> list[dict]:
    flat = flatten(model)
    rows = []
    for var in flat.variables:
        if var.domain == "binary":
            lower, upper = 0.0, 1.0
        else:
            lower = 0.0 if var.lower is None else float(var.lower)
            if var.upper is None:
                caps = []
                for con in flat.constraints:
                    coef = float(con.coeffs.get(var.key, 0.0))
                    if con.sense == "<=" and coef > 1e-12 and con.rhs > 0:
                        caps.append(float(con.rhs) / coef)
                upper = min(caps) if caps else lower + 10.0
            else:
                upper = float(var.upper)
            if upper <= lower:
                upper = lower + 1.0
        rows.append({"name": var.key, "lower": lower, "upper": upper, "domain": var.domain, "unit": ""})
    return rows


def evaluate_design(model: Model, values: dict[str, float]) -> dict:
    flat = flatten(model)
    point = {key: float(value) for key, value in values.items()}
    objective = _objective(model, flat, point)
    rows = []
    violation = 0.0
    for con in model.constraints:
        if con.kind != "comparison" or con.lhs is None or con.rhs is None:
            continue
        try:
            lhs = float(evaluate(model, con.lhs, point))
            rhs = float(evaluate(model, con.rhs, point))
        except AxiomError:
            rows.append({"name": con.name, "violation": 1.0})
            violation += 1.0
            continue
        if con.relation == "<=":
            slack = rhs - lhs
        elif con.relation == ">=":
            slack = lhs - rhs
        else:
            slack = -abs(lhs - rhs)
        amount = max(0.0, -slack)
        violation += amount
        rows.append({"name": con.name, "slack": slack, "violation": amount})
    sense = model.objectives[0].sense if model.objectives else "minimize"
    penalty = violation * max(1.0, abs(objective) if objective is not None else 1.0) * 100.0
    minimized = None if objective is None else (objective if sense == "minimize" else -objective)
    penalized = None if minimized is None else minimized + penalty
    return {
        "objective": objective,
        "sense": sense,
        "violation": violation,
        "feasible": violation <= 1e-6,
        "penalized": penalized,
        "constraints": rows,
    }


def _objective(model: Model, flat, point: dict[str, float]) -> float | None:
    if model.objectives:
        try:
            return float(evaluate(model, model.objectives[0].expr, point))
        except AxiomError:
            pass
    if flat.nonlinear:
        return None
    return float(objective_value(flat, point))


def grid(lower: float, upper: float, count: int) -> np.ndarray:
    return np.linspace(float(lower), float(upper), max(2, int(count)))
