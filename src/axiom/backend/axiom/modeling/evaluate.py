"""Numeric evaluation of AML expressions at a concrete variable assignment."""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.flatten import FlatModel
from axiom.modeling.index import resolve_index
from axiom.modeling.ir import Expr, Model, cartesian, var_key


def evaluate(model: Model, expr: Expr, values: dict[str, float], env: dict[str, str] | None = None, qmap: dict[str, str] | None = None) -> float:
    env = env or {}
    qmap = qmap or {}
    if expr.op == "const":
        return float(expr.value or 0.0)
    if expr.op == "neg":
        return -evaluate(model, expr.args[0], values, env, qmap)
    if expr.op == "add":
        return evaluate(model, expr.args[0], values, env, qmap) + evaluate(model, expr.args[1], values, env, qmap)
    if expr.op == "sub":
        return evaluate(model, expr.args[0], values, env, qmap) - evaluate(model, expr.args[1], values, env, qmap)
    if expr.op == "mul":
        return evaluate(model, expr.args[0], values, env, qmap) * evaluate(model, expr.args[1], values, env, qmap)
    if expr.op == "div":
        denom = evaluate(model, expr.args[1], values, env, qmap)
        if abs(denom) < 1e-15:
            raise AxiomError("表达式除以零。", "Expression divided by zero.", code="eval")
        return evaluate(model, expr.args[0], values, env, qmap) / denom
    if expr.op == "pow":
        return evaluate(model, expr.args[0], values, env, qmap) ** evaluate(model, expr.args[1], values, env, qmap)
    if expr.op == "sum":
        total = 0.0
        names = [q.index for q in expr.quants]
        local_map = dict(qmap)
        local_map.update({q.index: q.set_name for q in expr.quants})
        for combo in cartesian(model, [q.set_name for q in expr.quants]):
            local = dict(env)
            local.update(zip(names, combo, strict=True))
            total += evaluate(model, expr.args[0], values, local, local_map)
        return total
    if expr.op == "ref":
        name = expr.name or ""
        indices = tuple(resolve_index(index, env, qmap, model) for index in expr.indices)
        if name in model.parameters:
            return model.parameters[name].get(indices)
        if name in model.variables:
            key = var_key(name, indices)
            if key not in values:
                raise AxiomError(
                    f"解中缺少变量 {key}。",
                    f"Solution is missing variable {key}.",
                    code="eval",
                )
            return float(values[key])
        if name in env and not indices:
            return float(env[name])
        raise AxiomError(
            f"无法求值符号 {name}。",
            f"Cannot evaluate symbol {name}.",
            code="unknown_symbol",
        )
    raise AxiomError(f"无法求值算子 {expr.op}。", f"Cannot evaluate operator {expr.op}.", code="bad_expr")


def objective_components(model: Model, values: dict[str, float]) -> list[dict]:
    rows = []
    for obj in model.objectives:
        value = evaluate(model, obj.expr, values)
        rows.append(
            {
                "name": obj.name,
                "sense": obj.sense,
                "weight": obj.weight,
                "value": value,
            }
        )
    return rows


def constraint_report(model: Model, flat: FlatModel, values: dict[str, float]) -> list[dict]:
    rows = []
    for con in flat.constraints:
        lhs = sum(coef * float(values.get(key, 0.0)) for key, coef in con.coeffs.items())
        residual = lhs - con.rhs
        if con.sense == "<=":
            slack = con.rhs - lhs
        elif con.sense == ">=":
            slack = lhs - con.rhs
        else:
            slack = -abs(residual)
        rows.append(
            {
                "name": con.key,
                "sense": con.sense,
                "lhs": lhs,
                "rhs": con.rhs,
                "slack": slack,
                "binding": abs(slack) <= 1e-6,
                "violated": slack < -1e-5,
            }
        )
    return rows
