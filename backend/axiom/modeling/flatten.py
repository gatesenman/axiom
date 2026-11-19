"""Expand an Axiom model into a flat linear program.

Indexed sums become explicit coefficients. Nonlinear expressions are detected
and left for the NLP solvers, which call the numeric evaluator instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axiom.errors import AxiomError, NonlinearError
from axiom.modeling.index import resolve_index
from axiom.modeling.ir import Expr, Model, cartesian, var_key
from axiom.modeling.linearize import expand_specials


@dataclass
class FlatVar:
    key: str
    name: str
    indices: tuple[str, ...]
    domain: str
    lower: float | None
    upper: float | None


@dataclass
class FlatCon:
    key: str
    name: str
    indices: tuple[str, ...]
    coeffs: dict[str, float]
    sense: str
    rhs: float


@dataclass
class FlatModel:
    name: str
    sense: str
    variables: list[FlatVar]
    constraints: list[FlatCon]
    objective: dict[str, float]
    objective_const: float
    nonlinear: bool = False
    quadratic: dict[tuple[str, str], float] = field(default_factory=dict)
    cones: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    source: Model | None = None

    def var_map(self) -> dict[str, FlatVar]:
        return {var.key: var for var in self.variables}


def flatten(model: Model) -> FlatModel:
    expanded = expand_specials(model)
    variables = _variables(expanded)
    flat = FlatModel(
        name=expanded.name,
        sense="minimize",
        variables=variables,
        constraints=[],
        objective={},
        objective_const=0.0,
        meta=dict(model.meta),
        source=expanded,
    )
    if not expanded.objectives:
        raise AxiomError(
            "模型没有目标函数，无法展开求解。",
            "The model has no objective and cannot be flattened for solving.",
            code="no_objective",
        )
    try:
        sense, coef, constant = _combine_objectives(expanded)
        constraints = [_constraint(expanded, con, variables) for con in expanded.constraints]
    except NonlinearError:
        from axiom.modeling.quadratic import try_structured

        if try_structured(expanded, flat):
            _check_size(flat)
            return flat
        flat.nonlinear = True
        flat.sense = expanded.objectives[0].sense
        return flat
    flat.sense = sense
    flat.objective = coef
    flat.objective_const = constant
    flat.constraints = [item for group in constraints for item in group]
    _check_size(flat)
    return flat


def _variables(model: Model) -> list[FlatVar]:
    rows: list[FlatVar] = []
    for decl in model.variables.values():
        for index in cartesian(model, decl.index_sets):
            rows.append(
                FlatVar(
                    key=var_key(decl.name, index),
                    name=decl.name,
                    indices=index,
                    domain=decl.domain,
                    lower=decl.lower,
                    upper=decl.upper,
                )
            )
    return rows


def _check_size(flat: FlatModel) -> None:
    if len(flat.variables) > 100_000 or len(flat.constraints) > 200_000:
        raise AxiomError(
            f"展开规模过大：{len(flat.variables)} 个变量、{len(flat.constraints)} 条约束。",
            f"Expanded model is too large: {len(flat.variables)} variables and {len(flat.constraints)} constraints.",
            code="too_large",
        )


def _combine_objectives(model: Model) -> tuple[str, dict[str, float], float]:
    parts = []
    for obj in model.objectives:
        coef, constant = linearize_expr(model, obj.expr, {}, {})
        parts.append((obj, coef, constant))
    if len(parts) == 1:
        obj, coef, constant = parts[0]
        return obj.sense, coef, constant
    coef: dict[str, float] = {}
    constant = 0.0
    for obj, part, part_const in parts:
        sign = 1.0 if obj.sense == "minimize" else -1.0
        weight = obj.weight * sign
        for key, value in part.items():
            coef[key] = coef.get(key, 0.0) + weight * value
        constant += weight * part_const
    return "minimize", coef, constant


def _constraint(model: Model, con, variables: list[FlatVar]) -> list[FlatCon]:
    if con.kind != "comparison":
        raise AxiomError(
            f"约束 {con.name} 在线性化之后仍不是普通比较。",
            f"Constraint {con.name} is still not a comparison after linearization.",
            code="bad_constraint",
        )
    produced: list[FlatCon] = []
    qmap = {q.index: q.set_name for q in con.quants}
    set_names = [q.set_name for q in con.quants]
    index_names = [q.index for q in con.quants]
    for combo in cartesian(model, set_names):
        env = dict(zip(index_names, combo, strict=True))
        lhs_coef, lhs_const = linearize_expr(model, con.lhs, env, qmap)
        rhs_coef, rhs_const = linearize_expr(model, con.rhs, env, qmap)
        coef: dict[str, float] = {}
        for key, value in lhs_coef.items():
            coef[key] = coef.get(key, 0.0) + value
        for key, value in rhs_coef.items():
            coef[key] = coef.get(key, 0.0) - value
        coef = {key: value for key, value in coef.items() if abs(value) > 1e-12}
        rhs = rhs_const - lhs_const
        key = var_key(con.name, combo)
        if not coef:
            if _trivially_true(con.relation, rhs):
                continue
            # 0 <= -1 forces the solver to report infeasibility.
            produced.append(
                FlatCon(key=key, name=con.name, indices=combo, coeffs={}, sense="<=", rhs=-1.0)
            )
            continue
        produced.append(
            FlatCon(key=key, name=con.name, indices=combo, coeffs=coef, sense=con.relation, rhs=rhs)
        )
    return produced


def _trivially_true(relation: str, rhs: float) -> bool:
    # coef·x + lhs_const <= rhs_const  became  0 sense rhs, with rhs = rhs_const - lhs_const.
    if relation == "<=":
        return rhs >= -1e-9
    if relation == ">=":
        return rhs <= 1e-9
    return abs(rhs) <= 1e-9


def linearize_expr(
    model: Model,
    expr: Expr,
    env: dict[str, str],
    qmap: dict[str, str],
) -> tuple[dict[str, float], float]:
    if expr.op == "const":
        return {}, float(expr.value or 0.0)
    if expr.op == "neg":
        coef, constant = linearize_expr(model, expr.args[0], env, qmap)
        return {key: -value for key, value in coef.items()}, -constant
    if expr.op in {"add", "sub"}:
        left_c, left_k = linearize_expr(model, expr.args[0], env, qmap)
        right_c, right_k = linearize_expr(model, expr.args[1], env, qmap)
        sign = 1.0 if expr.op == "add" else -1.0
        merged = dict(left_c)
        for key, value in right_c.items():
            merged[key] = merged.get(key, 0.0) + sign * value
        return merged, left_k + sign * right_k
    if expr.op == "mul":
        left_c, left_k = linearize_expr(model, expr.args[0], env, qmap)
        right_c, right_k = linearize_expr(model, expr.args[1], env, qmap)
        if left_c and right_c:
            raise NonlinearError(
                "表达式包含两个变量的乘积，不是线性模型。",
                "The expression multiplies two variable terms and is not linear.",
            )
        if left_c:
            return {key: value * right_k for key, value in left_c.items()}, left_k * right_k
        if right_c:
            return {key: value * left_k for key, value in right_c.items()}, left_k * right_k
        return {}, left_k * right_k
    if expr.op == "div":
        left_c, left_k = linearize_expr(model, expr.args[0], env, qmap)
        right_c, right_k = linearize_expr(model, expr.args[1], env, qmap)
        if right_c or abs(right_k) < 1e-15:
            raise NonlinearError(
                "除数不是非零常数，表达式不是线性的。",
                "The divisor is not a nonzero constant, so the expression is not linear.",
            )
        return {key: value / right_k for key, value in left_c.items()}, left_k / right_k
    if expr.op == "pow":
        base_c, base_k = linearize_expr(model, expr.args[0], env, qmap)
        exp_c, exp_k = linearize_expr(model, expr.args[1], env, qmap)
        if exp_c:
            raise NonlinearError("指数中含有变量。", "The exponent contains a variable.")
        if not base_c:
            return {}, base_k**exp_k
        if abs(exp_k - 1.0) < 1e-12:
            return base_c, base_k
        if abs(exp_k) < 1e-12:
            return {}, 1.0
        raise NonlinearError("变量的幂不是线性表达式。", "A variable power is not linear.")
    if expr.op == "sum":
        merged: dict[str, float] = {}
        constant = 0.0
        names = [q.index for q in expr.quants]
        sets = [q.set_name for q in expr.quants]
        local_map = dict(qmap)
        local_map.update({q.index: q.set_name for q in expr.quants})
        for combo in cartesian(model, sets):
            local_env = dict(env)
            local_env.update(zip(names, combo, strict=True))
            coef, part = linearize_expr(model, expr.args[0], local_env, local_map)
            for key, value in coef.items():
                merged[key] = merged.get(key, 0.0) + value
            constant += part
        return merged, constant
    if expr.op == "ref":
        return _linear_ref(model, expr, env, qmap)
    raise AxiomError(
        f"无法线性化算子 {expr.op}。",
        f"Cannot linearize operator {expr.op}.",
        code="bad_expr",
    )


def _linear_ref(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]):
    name = expr.name or ""
    indices = tuple(resolve_index(index, env, qmap, model) for index in expr.indices)
    if name in model.parameters:
        return {}, model.parameters[name].get(indices)
    if name in model.variables:
        return {var_key(name, indices): 1.0}, 0.0
    if name in env and not indices:
        try:
            return {}, float(env[name])
        except ValueError as exc:
            raise AxiomError(
                f"下标 {name}={env[name]} 不能当作数值使用。",
                f"Index {name}={env[name]} cannot be used as a number.",
                code="bad_index",
            ) from exc
    raise AxiomError(
        f"符号 {name} 不是参数、变量或数值下标。",
        f"Symbol {name} is not a parameter, variable, or numeric index.",
        code="unknown_symbol",
    )
