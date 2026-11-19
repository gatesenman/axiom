"""Irreducible infeasible sets and a solution-quality report.

The IIS is a deletion filter: a constraint stays only when removing it makes
the model feasible. The quality report checks primal feasibility, dual signs
against the basis, and complementarity.
"""

from __future__ import annotations

from axiom.analysis.service import diagnose
from axiom.errors import AxiomError
from axiom.modeling.ir import Model
from axiom.solvers.registry import solve_model


def quality_report(model: Model, solver: str = "highs") -> dict:
    try:
        solved = solve_model(model, solver, {"time_limit": 10})
    except AxiomError as exc:
        return {"ok": False, "message": exc.message, "message_en": exc.message_en}
    if solved.status == "infeasible":
        conflict = infeasible_set(model, solver)
        return {"ok": True, "status": "infeasible", "quality": _metrics(solved), "iis": conflict}
    return {"ok": True, "status": solved.status, "quality": _metrics(solved), "iis": None}


def infeasible_set(model: Model, solver: str = "highs") -> dict:
    probe = solve_model(model, solver, {"time_limit": 8})
    if probe.status in {"optimal", "feasible"}:
        return {
            "feasible": True,
            "constraints": [],
            "message": "模型可行，没有不可约冲突。",
            "message_en": "The model is feasible, so there is no irreducible conflict.",
        }
    names = [con.name for con in model.constraints]
    required = _deletion_filter(model, names, solver)
    elastic = {}
    try:
        elastic = diagnose(model)
    except AxiomError as exc:
        elastic = {"message": exc.message, "message_en": exc.message_en}
    return {
        "feasible": False,
        "constraints": required,
        "elastic": elastic,
        "message": "删除滤波得到的不可约不可行子系统：" + "、".join(required) if required else "冲突来自变量界或目标之外的结构。",
        "message_en": "Deletion-filter IIS: " + ", ".join(required) if required else "The conflict is in variable bounds rather than the named constraints.",
    }


def _deletion_filter(model: Model, names: list[str], solver: str) -> list[str]:
    active = list(names)
    for name in list(names):
        if name not in active:
            continue
        trial = [item for item in active if item != name]
        if not trial:
            continue
        if _still_infeasible(model, trial, solver):
            active = trial
    return active


def _still_infeasible(model: Model, names: list[str], solver: str) -> bool:
    cloned = model.copy()
    cloned.constraints = [con for con in cloned.constraints if con.name in set(names)]
    try:
        solved = solve_model(cloned, solver, {"time_limit": 8})
    except AxiomError:
        return True
    return solved.status not in {"optimal", "feasible"}


def _metrics(solved) -> dict:
    violation = 0.0
    complementarity = 0.0
    binding = 0
    for row in solved.constraints or []:
        slack = float(row.get("slack") or 0.0)
        violation = max(violation, max(0.0, -slack))
        dual = float((solved.duals or {}).get(row.get("name"), 0.0))
        complementarity += abs(slack * dual)
        if row.get("binding"):
            binding += 1
    reduced_gap = 0.0
    for name, cost in (solved.reduced_costs or {}).items():
        value = float((solved.variables or {}).get(name, 0.0))
        reduced_gap += abs(float(cost) * value)
    return {
        "solver": solved.solver,
        "status": solved.status,
        "objective": solved.objective,
        "feasible": bool(solved.feasible),
        "max_violation": violation,
        "binding_constraints": binding,
        "complementarity": complementarity,
        "reduced_cost_gap": reduced_gap,
        "runtime_sec": solved.runtime_sec,
        "message": solved.message,
        "message_en": solved.message_en,
    }
