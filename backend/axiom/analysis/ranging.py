"""Local sensitivity: duals, reduced costs, and re-solved objective / RHS ranges.

The allowable range is the largest probed interval on which the optimal basis
stays the same. A basis is the set of variables strictly between their bounds
together with the binding constraints. One finite-difference probe fixes the
sign of HiGHS duals, which are stored for the minimized form.
"""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.flatten import FlatModel, flatten
from axiom.modeling.ir import Constraint, Expr, Model, Objective, VarDecl, const, ref
from axiom.solvers.registry import solve_model


def local_sensitivity(model: Model, solver: str = "highs", probes: int = 12) -> dict:
    flat = flatten(model)
    if flat.nonlinear or flat.cones:
        return {
            "ok": False,
            "message": "局部对偶和基范围针对线性与二次规划。这个模型交给全局灵敏度。",
            "message_en": "Duals and basis ranging are for linear and quadratic programs. Use global sensitivity for this model.",
        }
    base = solve_model(model, solver, {"time_limit": 8})
    if base.status not in {"optimal", "feasible"}:
        return {"ok": False, "base": base.to_dict(), "message": base.message, "message_en": base.message_en}
    sign = _dual_sign(flat, base)
    signature = _signature(flat, base)
    objective_rows = []
    for var in flat.variables[:8]:
        coef = float(flat.objective.get(var.key, 0.0))
        low, high, note = _range(
            lambda value, key=var.key: _solve_objective(flat, key, value, solver),
            coef,
            signature,
            probes,
            flat,
        )
        objective_rows.append(
            {
                "name": var.key,
                "coefficient": coef,
                "reduced_cost": sign * float(base.reduced_costs.get(var.key, 0.0)),
                "allowable_min": low,
                "allowable_max": high,
                "note": note[0],
                "note_en": note[1],
            }
        )
    rhs_rows = []
    for con in flat.constraints[:8]:
        low, high, note = _range(
            lambda value, key=con.key: _solve_rhs(flat, key, value, solver),
            float(con.rhs),
            signature,
            probes,
            flat,
        )
        rhs_rows.append(
            {
                "name": con.key,
                "rhs": float(con.rhs),
                "dual": sign * float(base.duals.get(con.key, 0.0)),
                "allowable_min": low,
                "allowable_max": high,
                "note": note[0],
                "note_en": note[1],
            }
        )
    return {
        "ok": True,
        "solver": base.solver,
        "status": base.status,
        "objective": base.objective,
        "sense": flat.sense,
        "dual_sign": sign,
        "variables": {key: value for key, value in base.variables.items()},
        "duals": {key: sign * float(value) for key, value in base.duals.items()},
        "reduced_costs": {key: sign * float(value) for key, value in base.reduced_costs.items()},
        "objective_ranging": objective_rows,
        "rhs_ranging": rhs_rows,
        "message": "对偶和既约费用已按目标方向校正。允许范围是最优基保持不变的区间。",
        "message_en": "Duals and reduced costs are signed for the model sense. An allowable range keeps the optimal basis.",
    }


def _dual_sign(flat: FlatModel, base) -> float:
    if not flat.constraints:
        return 1.0
    con = flat.constraints[0]
    step = max(1e-3, 0.01 * max(1.0, abs(con.rhs)))
    moved = _solve_rhs(flat, con.key, con.rhs + step, base.solver)
    if moved.objective is None or base.objective is None:
        return 1.0
    finite = (moved.objective - base.objective) / step
    dual = float(base.duals.get(con.key, 0.0))
    if abs(dual) < 1e-8:
        return 1.0
    return 1.0 if finite * dual >= 0 else -1.0


def _signature(flat: FlatModel, result) -> tuple:
    basic = []
    for var in flat.variables:
        value = float(result.variables.get(var.key, 0.0))
        lower = -1e30 if var.lower is None else float(var.lower)
        upper = 1e30 if var.upper is None else float(var.upper)
        if lower + 1e-5 < value < upper - 1e-5:
            basic.append(var.key)
    binding = [row["name"] for row in result.constraints if row.get("binding")]
    return (tuple(basic), tuple(binding))


def _range(solve, center: float, signature: tuple, probes: int, flat: FlatModel | None = None):
    def holds(value: float) -> bool:
        result = solve(value)
        if result.status not in {"optimal", "feasible"} or flat is None:
            return result.status in {"optimal", "feasible"} and flat is None
        return _signature(flat, result) == signature

    if not holds(center):
        return center, center, ("基准基没有稳定下来。", "The base basis was not stable.")
    low = _search(holds, center, -1)
    high = _search(holds, center, 1)
    note = ("区间端点之外最优基发生变化。", "The optimal basis changes outside this interval.")
    if low is None or high is None:
        note = ("在探测范围内基没有变化。", "The basis did not change inside the probed window.")
    return low if low is not None else center - _span(center), high if high is not None else center + _span(center), note


def _search(holds, center: float, direction: int):
    span = _span(center)
    good = 0.0
    bad = None
    step = span * 0.05
    for _ in range(14):
        trial = center + direction * step
        if holds(trial):
            good = step
            step *= 2.0
            if step > 50 * span:
                return None
        else:
            bad = step
            break
    if bad is None:
        return None
    for _ in range(12):
        mid = 0.5 * (good + bad)
        if holds(center + direction * mid):
            good = mid
        else:
            bad = mid
    return center + direction * good


def _span(center: float) -> float:
    return max(1.0, abs(center))


def _solve_objective(flat: FlatModel, key: str, coefficient: float, solver: str):
    cloned = _copy_flat(flat)
    if abs(coefficient) < 1e-15:
        cloned.objective.pop(key, None)
    else:
        cloned.objective[key] = float(coefficient)
    return solve_model(model_from_flat(cloned), solver, {"time_limit": 8})


def _solve_rhs(flat: FlatModel, key: str, rhs: float, solver: str):
    cloned = _copy_flat(flat)
    for con in cloned.constraints:
        if con.key == key:
            con.rhs = float(rhs)
    return solve_model(model_from_flat(cloned), solver, {"time_limit": 8})


def _copy_flat(flat: FlatModel) -> FlatModel:
    return FlatModel(
        name=flat.name,
        sense=flat.sense,
        variables=list(flat.variables),
        constraints=[type(con)(con.key, con.name, con.indices, dict(con.coeffs), con.sense, float(con.rhs)) for con in flat.constraints],
        objective=dict(flat.objective),
        objective_const=flat.objective_const,
        quadratic=dict(flat.quadratic),
        cones=list(flat.cones),
        meta=dict(flat.meta),
    )


def model_from_flat(flat: FlatModel) -> Model:
    model = Model(name=flat.name or "model", meta=dict(flat.meta))
    for var in flat.variables:
        domain = var.domain if var.domain in {"continuous", "integer", "binary"} else "continuous"
        model.variables[var.key] = VarDecl(name=var.key, domain=domain, lower=var.lower, upper=var.upper)
    expr: Expr = const(flat.objective_const)
    for key, coef in flat.objective.items():
        if abs(coef) < 1e-15:
            continue
        expr = Expr("add", args=(expr, Expr("mul", args=(const(float(coef)), ref(key)))))
    for (left, right), coef in flat.quadratic.items():
        if abs(coef) < 1e-15:
            continue
        product = Expr("mul", args=(ref(left), ref(right)))
        expr = Expr("add", args=(expr, Expr("mul", args=(const(float(coef)), product))))
    sense = "maximize" if flat.sense == "maximize" else "minimize"
    model.objectives = [Objective(name="obj", sense=sense, expr=expr)]
    for con in flat.constraints:
        lhs: Expr = const(0.0)
        for key, coef in con.coeffs.items():
            lhs = Expr("add", args=(lhs, Expr("mul", args=(const(float(coef)), ref(key)))))
        relation = con.sense if con.sense in {"<=", ">=", "=="} else "<="
        model.constraints.append(Constraint(name=con.key, kind="comparison", relation=relation, lhs=lhs, rhs=const(float(con.rhs))))
    return model
