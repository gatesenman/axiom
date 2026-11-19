"""Shared bounds, status assembly, and option reading for solver adapters."""

from __future__ import annotations

import math
import time
from typing import Any

from axiom.modeling.evaluate import constraint_report, objective_components
from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.base import SolveResult

INF = 1e30


def bounds(var) -> tuple[float, float]:
    lower = -INF if var.lower is None else float(var.lower)
    upper = INF if var.upper is None else float(var.upper)
    return lower, upper


def objective_value(flat: FlatModel, values: dict[str, float]) -> float:
    total = flat.objective_const
    for key, coef in flat.objective.items():
        total += coef * float(values.get(key, 0.0))
    for (left, right), coef in getattr(flat, "quadratic", {}).items():
        if left == right:
            total += coef * float(values.get(left, 0.0)) ** 2
        else:
            total += coef * float(values.get(left, 0.0)) * float(values.get(right, 0.0))
    return total


def assemble(
    *,
    solver: str,
    model: Model,
    flat: FlatModel,
    status: str,
    values: dict[str, float],
    raw_status: str,
    started: float,
    message: str,
    message_en: str,
    duals: dict[str, float] | None = None,
    reduced_costs: dict[str, float] | None = None,
) -> SolveResult:
    feasible = status in {"optimal", "feasible"}
    components: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    objective = None
    if feasible and values:
        objective = objective_value(flat, values) if not flat.nonlinear else None
        try:
            components = objective_components(model, values)
        except Exception:
            components = []
        if objective is None and components:
            objective = float(components[0]["value"])
        if not flat.nonlinear:
            constraints = constraint_report(model, flat, values)
    return SolveResult(
        solver=solver,
        status=status,
        objective=objective,
        objective_components=components,
        variables=values if feasible else {},
        constraints=constraints,
        duals=duals or {},
        reduced_costs=reduced_costs or {},
        runtime_sec=time.perf_counter() - started,
        message=message,
        message_en=message_en,
        raw_status=raw_status,
        feasible=feasible,
    )


def failure(solver: str, started: float, message: str, message_en: str, raw: str = "error") -> SolveResult:
    return SolveResult(
        solver=solver,
        status="error",
        objective=None,
        runtime_sec=time.perf_counter() - started,
        message=message,
        message_en=message_en,
        raw_status=raw,
        feasible=False,
    )


def not_applicable(solver: str, started: float, message: str, message_en: str) -> SolveResult:
    return SolveResult(
        solver=solver,
        status="not_applicable",
        objective=None,
        runtime_sec=time.perf_counter() - started,
        message=message,
        message_en=message_en,
        raw_status="not_applicable",
        feasible=False,
    )


def opt_float(options: dict[str, Any], key: str, default: float | None = None) -> float | None:
    value = options.get(key, default)
    if value is None or value == "":
        return None
    return float(value)


def has_integer(flat: FlatModel) -> bool:
    return any(var.domain in {"integer", "binary"} for var in flat.variables)


def near_integer(value: float, tol: float = 1e-6) -> bool:
    return abs(value - round(value)) <= tol


def integral_data(flat: FlatModel) -> bool:
    for coef in flat.objective.values():
        if not near_integer(coef):
            return False
    if not near_integer(flat.objective_const):
        return False
    for con in flat.constraints:
        if not near_integer(con.rhs):
            return False
        for coef in con.coeffs.values():
            if not near_integer(coef):
                return False
    for var in flat.variables:
        if var.lower is not None and not math.isinf(var.lower) and not near_integer(var.lower):
            return False
        if var.upper is not None and not math.isinf(var.upper) and not near_integer(var.upper):
            return False
    return True
