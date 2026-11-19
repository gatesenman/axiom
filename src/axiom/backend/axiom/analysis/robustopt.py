"""Scenario robust optimization and individual chance constraints.

Two-stage problems share the original decisions and add a nonnegative slack
recourse on every inequality, charged at a linear penalty. Worst-case keeps
one decision feasible for every scenario. Chance constraints use the normal
deterministic equivalent on each right-hand side.
"""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.ir import Constraint, Expr, Model, Objective, VarDecl, const, ref
from axiom.solvers.registry import solve_model


def stochastic(model: Model, scenarios: list[dict] | None = None, mode: str = "two-stage", penalty: float = 1000.0, solver: str = "highs") -> dict:
    cases = scenarios or [
        {"name": "low", "probability": 0.5, "rhs_scale": 0.85},
        {"name": "high", "probability": 0.5, "rhs_scale": 1.15},
    ]
    probabilities = [float(item.get("probability", 1.0)) for item in cases]
    total = sum(probabilities) or 1.0
    probabilities = [item / total for item in probabilities]
    mode = (mode or "two-stage").lower()
    wait = _wait_and_see(model, cases, probabilities, solver)
    if mode in {"wait-and-see", "ws"}:
        return {"ok": True, "mode": "wait-and-see", "wait_and_see": wait, "objective": wait["expected"]}
    if mode in {"worst", "worst-case", "robust"}:
        built = _worst_case(model, cases)
    else:
        built = _two_stage(model, cases, probabilities, penalty)
    solved = solve_model(built, solver, {"time_limit": 10})
    here = solved.objective
    return {
        "ok": solved.status in {"optimal", "feasible"},
        "mode": "worst-case" if mode in {"worst", "worst-case", "robust"} else "two-stage",
        "status": solved.status,
        "objective": here,
        "variables": {key: value for key, value in solved.variables.items() if not key.startswith("recourse_")},
        "recourse": {key: value for key, value in solved.variables.items() if key.startswith("recourse_")},
        "wait_and_see": wait,
        "value_of_information": None if here is None or wait["expected"] is None else float(wait["expected"]) - float(here),
        "message": solved.message,
        "message_en": solved.message_en,
    }


def chance(model: Model, alpha: float = 0.05, cv: float = 0.05, solver: str = "highs") -> dict:
    """Individual chance constraints for normal right-hand-side noise."""
    from scipy.stats import norm

    level = min(max(float(alpha), 1e-6), 0.49)
    z = float(norm.ppf(1.0 - level))
    base = solve_model(model, solver, {"time_limit": 8})
    tightened = model.copy()
    changed = 0
    for con in tightened.constraints:
        if con.kind != "comparison" or con.rhs is None or con.rhs.op != "const" or con.relation not in {"<=", ">="}:
            continue
        rhs = float(con.rhs.value or 0.0)
        sigma = abs(rhs) * float(cv)
        if con.relation == "<=":
            con.rhs = const(rhs - z * sigma)
        else:
            con.rhs = const(rhs + z * sigma)
        changed += 1
    if not changed:
        return {"ok": False, "message": "没有可写成机会约束的右端。", "message_en": "No right-hand side can be turned into a chance constraint."}
    solved = solve_model(tightened, solver, {"time_limit": 8})
    return {
        "ok": solved.status in {"optimal", "feasible"},
        "status": solved.status,
        "alpha": level,
        "cv": float(cv),
        "z": z,
        "constraints": changed,
        "baseline": None if base.objective is None else float(base.objective),
        "objective": solved.objective,
        "variables": solved.variables,
        "message": "每个不等式单独满足 1-α 的正态机会约束，右端按 z 倍标准差收紧。",
        "message_en": "Each inequality is an individual normal chance constraint. The right-hand side moves by z standard deviations.",
    }


def _wait_and_see(model: Model, cases: list[dict], probabilities: list[float], solver: str) -> dict:
    rows = []
    expected = 0.0
    counted = 0.0
    for case, probability in zip(cases, probabilities, strict=True):
        mutated = _scaled(model, case)
        solved = solve_model(mutated, solver, {"time_limit": 8})
        rows.append({"name": case.get("name") or "scenario", "probability": probability, "status": solved.status, "objective": solved.objective})
        if solved.objective is not None and solved.status in {"optimal", "feasible"}:
            expected += probability * float(solved.objective)
            counted += probability
    return {"expected": None if counted <= 0 else expected, "rows": rows}


def _scaled(model: Model, case: dict) -> Model:
    mutated = model.copy()
    scale = case.get("rhs_scale")
    overrides = case.get("rhs") or {}
    for con in mutated.constraints:
        if con.rhs is None or con.rhs.op != "const":
            continue
        if con.name in overrides:
            con.rhs = const(float(overrides[con.name]))
        elif scale is not None:
            con.rhs = const(float(con.rhs.value or 0.0) * float(scale))
    return mutated


def _worst_case(model: Model, cases: list[dict]) -> Model:
    built = model.copy()
    original = list(built.constraints)
    built.constraints = []
    for index, case in enumerate(cases):
        scaled = _scaled(model, case)
        for con in scaled.constraints:
            built.constraints.append(
                Constraint(
                    name=f"{con.name}__s{index}",
                    kind=con.kind,
                    relation=con.relation,
                    lhs=con.lhs,
                    rhs=con.rhs,
                )
            )
    if not built.constraints:
        built.constraints = original
    return built


def _two_stage(model: Model, cases: list[dict], probabilities: list[float], penalty: float) -> Model:
    built = model.copy()
    sense = built.objectives[0].sense if built.objectives else "minimize"
    # Recourse is a cost, so a maximized profit subtracts the penalty.
    sign = -1.0 if sense == "maximize" else 1.0
    objective = built.objectives[0].expr if built.objectives else const(0.0)
    built.constraints = []
    for index, (case, probability) in enumerate(zip(cases, probabilities, strict=True)):
        scaled = _scaled(model, case)
        for con in scaled.constraints:
            if con.kind != "comparison" or con.relation not in {"<=", ">="} or con.lhs is None or con.rhs is None:
                built.constraints.append(con)
                continue
            slack = f"recourse_{index}_{con.name}"
            built.variables[slack] = VarDecl(name=slack, domain="continuous", lower=0.0)
            if con.relation == "<=":
                lhs = Expr("sub", args=(con.lhs, ref(slack)))
            else:
                lhs = Expr("add", args=(con.lhs, ref(slack)))
            built.constraints.append(Constraint(name=f"{con.name}__s{index}", kind="comparison", relation=con.relation, lhs=lhs, rhs=con.rhs))
            penalty_term = Expr("mul", args=(const(sign * float(penalty) * probability), ref(slack)))
            objective = Expr("add", args=(objective, penalty_term))
    if built.objectives:
        built.objectives = [Objective(name=built.objectives[0].name, sense=sense, expr=objective)]
    else:
        built.objectives = [Objective(name="recourse", sense="minimize", expr=objective)]
    return built
