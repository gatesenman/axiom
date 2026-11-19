"""Weighted sum, epsilon-constraint, and NSGA-II / NSGA-III with hypervolume.

NSGA uses pymoo. Hypervolume uses pymoo's indicator. If pymoo cannot be
imported the population methods return an explained fallback; the scalar
methods still solve with the selected mathematical-programming solver.
"""

from __future__ import annotations

import numpy as np

from axiom.errors import AxiomError
from axiom.modeling.evaluate import evaluate
from axiom.modeling.ir import Constraint, Expr, Model, Objective, const
from axiom.solvers.registry import solve_model


def optimize(model: Model, method: str = "nsga2", weights: list[float] | None = None, steps: int = 8, solver: str = "highs", seed: int = 1, generations: int = 40, population: int = 40) -> dict:
    if len(model.objectives) < 2:
        raise AxiomError("多目标需要至少两个目标。", "Multi-objective optimization needs at least two objectives.", code="multi")
    method = (method or "nsga2").lower()
    if method in {"weighted", "weighted-sum"}:
        return _weighted(model, weights, solver)
    if method in {"epsilon", "epsilon-constraint"}:
        return _epsilon(model, steps, solver)
    if method in {"nsga2", "nsga-ii", "nsga3", "nsga-iii"}:
        return _nsga(model, "nsga3" if "3" in method else "nsga2", seed, generations, population)
    raise AxiomError(f"未知多目标方法 {method}。", f"Unknown multi-objective method {method}.", code="multi")


def hypervolume(points, reference) -> float:
    array = np.asarray(points, dtype=float)
    ref = np.asarray(reference, dtype=float)
    if array.size == 0:
        return 0.0
    try:
        from pymoo.indicators.hv import HV

        return float(HV(ref_point=ref)(array))
    except Exception:
        if array.shape[1] != 2:
            return 0.0
        order = np.argsort(array[:, 0])
        ordered = array[order]
        volume = 0.0
        previous = float(ref[0])
        for point in ordered[::-1]:
            width = max(0.0, previous - float(point[0]))
            height = max(0.0, float(ref[1]) - float(point[1]))
            volume += width * height
            previous = min(previous, float(point[0]))
        return float(volume)


def _weighted(model: Model, weights: list[float] | None, solver: str) -> dict:
    raw = weights or [1.0] * len(model.objectives)
    if len(raw) != len(model.objectives):
        raise AxiomError("权重个数要和目标个数一致。", "Provide one weight per objective.", code="multi")
    combined = model.copy()
    expr = _scalarize(combined, [float(item) for item in raw])
    combined.objectives = [Objective(name="weighted", sense="minimize", expr=expr)]
    solved = solve_model(combined, solver, {"time_limit": 10})
    point = _score(model, solved.variables) if solved.variables else None
    return {
        "ok": solved.status in {"optimal", "feasible"},
        "method": "weighted-sum",
        "status": solved.status,
        "weights": [float(item) for item in raw],
        "objective": solved.objective,
        "variables": solved.variables,
        "points": [] if point is None else [_point(0, solved.variables, point)],
        "message": solved.message,
        "message_en": solved.message_en,
    }


def _epsilon(model: Model, steps: int, solver: str) -> dict:
    primary = model.objectives[0]
    secondary = model.objectives[1]
    samples = _objective_samples(model, secondary, 12)
    if not samples:
        return {"ok": False, "method": "epsilon-constraint", "points": [], "message": "第二个目标无法取样。", "message_en": "The second objective could not be sampled."}
    low, high = min(samples), max(samples)
    if abs(high - low) < 1e-9:
        high = low + 1.0
    rows = []
    for index, epsilon in enumerate(np.linspace(low, high, max(3, int(steps)))):
        cloned = model.copy()
        expr = _as_minimize(primary)
        cloned.objectives = [Objective(name=primary.name, sense="minimize", expr=expr)]
        relation = "<=" if secondary.sense == "minimize" else ">="
        cloned.constraints.append(Constraint(name=f"eps_{secondary.name}", kind="comparison", relation=relation, lhs=secondary.expr, rhs=const(float(epsilon))))
        solved = solve_model(cloned, solver, {"time_limit": 8})
        if solved.status not in {"optimal", "feasible"} or not solved.variables:
            continue
        score = _score(model, solved.variables)
        rows.append(_point(index, solved.variables, score, {"epsilon": float(epsilon)}))
    front = _nondominated(rows)
    return {
        "ok": bool(front),
        "method": "epsilon-constraint",
        "points": rows,
        "pareto": front,
        "hypervolume": _hv(front),
        "message": f"{len(front)} 个非支配点。",
        "message_en": f"{len(front)} nondominated points.",
    }


def _nsga(model: Model, algorithm: str, seed: int, generations: int, population: int) -> dict:
    try:
        from pymoo.algorithms.moo.nsga2 import NSGA2
        from pymoo.algorithms.moo.nsga3 import NSGA3
        from pymoo.core.problem import Problem
        from pymoo.optimize import minimize
        from pymoo.util.ref_dirs import get_reference_directions
    except Exception as exc:
        return {
            "ok": False,
            "method": algorithm,
            "points": [],
            "message": f"pymoo 未能加载，NSGA 没有运行：{exc}",
            "message_en": f"pymoo did not import, so NSGA did not run: {exc}",
        }
    names, lower, upper = _bounds(model)
    if not names:
        return {"ok": False, "method": algorithm, "points": [], "message": "模型没有变量。", "message_en": "The model has no variables."}

    class _Problem(Problem):
        def __init__(self):
            super().__init__(n_var=len(names), n_obj=len(model.objectives), n_ieq_constr=_constraint_count(model), xl=np.array(lower), xu=np.array(upper))

        def _evaluate(self, x_array, out, *args, **kwargs):
            objectives = []
            constraints = []
            for row in x_array:
                values = {name: float(row[index]) for index, name in enumerate(names)}
                for var in model.variables.values():
                    if var.domain == "integer":
                        values[var.name] = float(np.round(values[var.name]))
                    elif var.domain == "binary":
                        values[var.name] = 1.0 if values[var.name] >= 0.5 else 0.0
                score = _score(model, values)
                objectives.append(score["minimize"])
                constraints.append(score["g"])
            out["F"] = np.asarray(objectives, dtype=float)
            out["G"] = np.asarray(constraints, dtype=float)

    if algorithm == "nsga3":
        directions = get_reference_directions("das-dennis", len(model.objectives), n_partitions=12 if len(model.objectives) == 2 else 4)
        engine = NSGA3(pop_size=max(len(directions), int(population)), ref_dirs=directions)
    else:
        engine = NSGA2(pop_size=max(20, int(population)))
    result = minimize(_Problem(), engine, ("n_gen", max(10, int(generations))), seed=seed, verbose=False)
    rows = []
    objectives = np.atleast_2d(np.asarray(result.F, dtype=float))
    design = np.atleast_2d(np.asarray(result.X, dtype=float))
    feasible = np.asarray(result.G).reshape(len(design), -1) if result.G is not None else np.zeros((len(design), 1))
    for index in range(len(design)):
        values = {name: float(design[index, pos]) for pos, name in enumerate(names)}
        raw = _from_minimized(model, objectives[index])
        rows.append(
            {
                "id": f"nsga-{index}",
                "variables": values,
                "objectives": raw,
                "minimize": [float(item) for item in objectives[index]],
                "feasible": bool(np.all(feasible[index] <= 1e-6)),
                "violation": float(np.sum(np.maximum(feasible[index], 0.0))),
            }
        )
    front = [row for row in rows if row["feasible"]]
    front = _nondominated(front)
    history = []
    if result.history:
        for entry in result.history:
            opt = getattr(entry, "opt", None)
            if opt is None or len(opt) == 0:
                continue
            history.append(float(np.min(np.sum(np.maximum(opt.get("G"), 0.0), axis=1))) if opt.get("G") is not None else 0.0)
    return {
        "ok": bool(rows),
        "method": algorithm,
        "library": "pymoo",
        "points": rows,
        "pareto": front,
        "hypervolume": _hv(front),
        "convergence": history,
        "message": f"pymoo {algorithm} 得到 {len(front)} 个可行非支配点。",
        "message_en": f"pymoo {algorithm} returned {len(front)} feasible nondominated points.",
    }


def _scalarize(model: Model, weights: list[float]) -> Expr:
    total = None
    for objective, weight in zip(model.objectives, weights, strict=True):
        term = _as_minimize(objective)
        weighted = Expr("mul", args=(const(abs(weight)), term))
        total = weighted if total is None else Expr("add", args=(total, weighted))
    return total or const(0.0)


def _as_minimize(objective: Objective) -> Expr:
    if objective.sense == "maximize":
        return Expr("neg", args=(objective.expr,))
    return objective.expr


def _score(model: Model, values: dict) -> dict:
    raw = {}
    minimized = []
    for objective in model.objectives:
        try:
            value = float(evaluate(model, objective.expr, values))
        except AxiomError:
            value = float("nan")
        raw[objective.name] = value
        minimized.append(-value if objective.sense == "maximize" else value)
    g = []
    violation = 0.0
    for con in model.constraints:
        if con.kind != "comparison" or con.lhs is None or con.rhs is None:
            continue
        try:
            lhs = float(evaluate(model, con.lhs, values))
            rhs = float(evaluate(model, con.rhs, values))
        except AxiomError:
            g.append(1.0)
            violation += 1.0
            continue
        if con.relation == "<=":
            slack = rhs - lhs
        elif con.relation == ">=":
            slack = lhs - rhs
        else:
            slack = -abs(lhs - rhs)
        g.append(-slack)
        violation += max(0.0, -slack)
    return {"objectives": raw, "minimize": minimized, "g": g or [0.0], "violation": violation}


def _from_minimized(model: Model, minimized) -> dict:
    raw = {}
    for objective, value in zip(model.objectives, minimized, strict=False):
        number = float(value)
        raw[objective.name] = -number if objective.sense == "maximize" else number
    return raw


def _bounds(model: Model):
    names, lower, upper = [], [], []
    for var in model.variables.values():
        if var.index_sets:
            continue
        lo = 0.0 if var.lower is None else float(var.lower)
        hi = 1.0 if var.domain == "binary" else (float(var.upper) if var.upper is not None else lo + 40.0)
        if hi <= lo:
            hi = lo + 1.0
        names.append(var.name)
        lower.append(lo)
        upper.append(hi)
    return names, lower, upper


def _constraint_count(model: Model) -> int:
    return max(1, sum(1 for con in model.constraints if con.kind == "comparison" and con.lhs is not None and con.rhs is not None))


def _objective_samples(model: Model, objective: Objective, count: int) -> list[float]:
    names, lower, upper = _bounds(model)
    if not names:
        return []
    rng = np.random.default_rng(1)
    values = []
    for _ in range(count):
        point = {name: float(rng.uniform(lo, hi)) for name, lo, hi in zip(names, lower, upper, strict=True)}
        try:
            values.append(float(evaluate(model, objective.expr, point)))
        except AxiomError:
            continue
    return values


def _point(index: int, variables: dict, score: dict, extra: dict | None = None) -> dict:
    row = {
        "id": f"mo-{index}",
        "variables": {key: float(value) for key, value in variables.items() if not str(key).startswith("_")},
        "objectives": score["objectives"],
        "minimize": [float(item) for item in score["minimize"]],
        "feasible": score["violation"] <= 1e-6,
        "violation": float(score["violation"]),
    }
    if extra:
        row.update(extra)
    return row


def _nondominated(rows: list[dict]) -> list[dict]:
    feasible = [row for row in rows if row.get("feasible")]
    front = []
    for row in feasible:
        dominated = False
        for other in feasible:
            if other is row:
                continue
            if _dominates(other["minimize"], row["minimize"]):
                dominated = True
                break
        if not dominated:
            front.append(row)
    return front


def _dominates(left, right) -> bool:
    better = False
    for a, b in zip(left, right, strict=False):
        if a > b + 1e-8:
            return False
        if a < b - 1e-8:
            better = True
    return better


def _hv(front: list[dict]) -> float | None:
    if not front:
        return None
    points = np.array([row["minimize"] for row in front], dtype=float)
    nadir = points.max(axis=0)
    ideal = points.min(axis=0)
    reference = nadir + 0.1 * np.maximum(1.0, nadir - ideal)
    return hypervolume(points, reference)
