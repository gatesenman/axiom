"""Recognize quadratic objectives and second-order cones inside an AML model.

A model stays linear when every product is a constant times one variable.
When the only extra terms are products of two variables, the flat form keeps
the linear rows and records a quadratic objective or a second-order cone.
General nonlinear expressions are left for the NLP adapters.
"""

from __future__ import annotations

from axiom.errors import NonlinearError
from axiom.modeling.flatten import FlatCon, FlatModel, _constraint, _variables
from axiom.modeling.ir import Expr, Model, cartesian, var_key


class _Poly:
    def __init__(self) -> None:
        self.const = 0.0
        self.lin: dict[str, float] = {}
        self.quad: dict[tuple[str, str], float] = {}

    def copy(self) -> "_Poly":
        other = _Poly()
        other.const = self.const
        other.lin = dict(self.lin)
        other.quad = dict(self.quad)
        return other


def try_structured(model: Model, flat: FlatModel) -> bool:
    """Fill ``flat`` when the model is a QP/QCQP cone form. Return False for general NLP."""
    if not model.objectives:
        return False
    try:
        sense, objective = _combine(model)
        rows: list[FlatCon] = []
        cones: list[dict] = []
        for con in model.constraints:
            if con.kind != "comparison" or con.lhs is None or con.rhs is None:
                return False
            linear_rows, cone = _constraint_poly(model, con)
            if cone is not None:
                cones.append(cone)
            elif linear_rows is None:
                return False
            else:
                rows.extend(linear_rows)
    except NonlinearError:
        return False
    flat.variables = _variables(model)
    flat.sense = sense
    flat.objective = objective.lin
    flat.objective_const = objective.const
    flat.quadratic = {key: value for key, value in objective.quad.items() if abs(value) > 1e-12}
    flat.constraints = rows
    flat.cones = cones
    flat.nonlinear = False
    if not flat.quadratic and not flat.cones:
        return False
    return True


def _combine(model: Model) -> tuple[str, _Poly]:
    parts = [_objective_poly(model, obj.expr) for obj in model.objectives]
    if len(parts) == 1:
        return model.objectives[0].sense, parts[0]
    total = _Poly()
    for obj, poly in zip(model.objectives, parts, strict=True):
        sign = 1.0 if obj.sense == "minimize" else -1.0
        _add_into(total, poly, obj.weight * sign)
    return "minimize", total


def _objective_poly(model: Model, expr: Expr) -> _Poly:
    return _poly(model, expr, {}, {})


def _constraint_poly(model: Model, con) -> tuple[list[FlatCon] | None, dict | None]:
    names = [q.index for q in con.quants]
    sets = [q.set_name for q in con.quants]
    qmap = {q.index: q.set_name for q in con.quants}
    combos = cartesian(model, sets) or [()]
    env = dict(zip(names, combos[0], strict=True)) if names else {}
    left = _poly(model, con.lhs, env, qmap)
    right = _poly(model, con.rhs, env, qmap)
    moved = left.copy()
    _add_into(moved, right, -1.0)
    if not moved.quad:
        return _constraint(model, con, _variables(model)), None
    detected = _soc(moved, con.relation)
    if detected is None or con.quants:
        return None, None
    detected["name"] = con.name
    return [], detected


def _soc(poly: _Poly, relation: str) -> dict | None:
    if relation not in {"<=", ">="}:
        return None
    sign = 1.0 if relation == "<=" else -1.0
    squares = {}
    for (left, right), coef in poly.quad.items():
        if left != right or abs(coef) < 1e-12:
            return None
        squares[left] = sign * coef
    if any(abs(value) > 1e-10 for value in poly.lin.values()) or abs(poly.const) > 1e-10:
        return None
    negative = [key for key, coef in squares.items() if coef < 0]
    positive = [key for key, coef in squares.items() if coef > 0]
    if len(negative) != 1 or not positive:
        return None
    bound = negative[0]
    if abs(squares[bound] + 1) > 1e-8:
        return None
    if any(abs(squares[key] - 1) > 1e-8 for key in positive):
        return None
    return {"kind": "soc", "bound": bound, "vars": positive}


def _poly(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> _Poly:
    if expr.op == "const":
        out = _Poly()
        out.const = float(expr.value or 0.0)
        return out
    if expr.op == "neg":
        inner = _poly(model, expr.args[0], env, qmap)
        return _scale(inner, -1.0)
    if expr.op in {"add", "sub"}:
        left = _poly(model, expr.args[0], env, qmap)
        right = _poly(model, expr.args[1], env, qmap)
        _add_into(left, right, 1.0 if expr.op == "add" else -1.0)
        return left
    if expr.op == "mul":
        return _mul(model, expr, env, qmap)
    if expr.op == "div":
        left = _poly(model, expr.args[0], env, qmap)
        right = _poly(model, expr.args[1], env, qmap)
        if right.lin or right.quad or abs(right.const) < 1e-15:
            raise NonlinearError("除数不是常数。", "The divisor is not a constant.")
        return _scale(left, 1.0 / right.const)
    if expr.op == "pow":
        base = _poly(model, expr.args[0], env, qmap)
        exp = _poly(model, expr.args[1], env, qmap)
        if exp.lin or exp.quad:
            raise NonlinearError("指数中含有变量。", "The exponent contains a variable.")
        if abs(exp.const - 2) < 1e-12:
            return _mul_poly(base, base)
        if abs(exp.const - 1) < 1e-12:
            return base
        if not base.lin and not base.quad:
            out = _Poly()
            out.const = base.const**exp.const
            return out
        raise NonlinearError("变量的幂不是二次式。", "A variable power is not quadratic.")
    if expr.op == "sum":
        total = _Poly()
        names = [q.index for q in expr.quants]
        sets = [q.set_name for q in expr.quants]
        local_map = dict(qmap)
        local_map.update({q.index: q.set_name for q in expr.quants})
        for combo in cartesian(model, sets):
            local_env = dict(env)
            local_env.update(zip(names, combo, strict=True))
            _add_into(total, _poly(model, expr.args[0], local_env, local_map), 1.0)
        return total
    if expr.op == "ref":
        return _ref(model, expr, env, qmap)
    raise NonlinearError(f"算子 {expr.op} 不是二次式。", f"Operator {expr.op} is not quadratic.")


def _ref(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> _Poly:
    from axiom.modeling.flatten import linearize_expr

    coef, constant = linearize_expr(model, expr, env, qmap)
    out = _Poly()
    out.const = constant
    out.lin = coef
    return out


def _mul(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> _Poly:
    return _mul_poly(_poly(model, expr.args[0], env, qmap), _poly(model, expr.args[1], env, qmap))


def _mul_poly(left: _Poly, right: _Poly) -> _Poly:
    if (left.quad and (right.lin or right.quad)) or (right.quad and (left.lin or left.quad)):
        raise NonlinearError("乘积超过二次。", "The product has degree higher than two.")
    out = _Poly()
    out.const = left.const * right.const
    for key, coef in left.lin.items():
        out.lin[key] = out.lin.get(key, 0.0) + coef * right.const
    for key, coef in right.lin.items():
        out.lin[key] = out.lin.get(key, 0.0) + coef * left.const
    for key, coef in left.quad.items():
        out.quad[key] = out.quad.get(key, 0.0) + coef * right.const
    for key, coef in right.quad.items():
        out.quad[key] = out.quad.get(key, 0.0) + coef * left.const
    for i, ai in left.lin.items():
        for j, bj in right.lin.items():
            _add_quad(out, i, j, ai * bj)
    return out


def _add_quad(poly: _Poly, left: str, right: str, coef: float) -> None:
    key = (left, right) if left <= right else (right, left)
    poly.quad[key] = poly.quad.get(key, 0.0) + coef


def _scale(poly: _Poly, factor: float) -> _Poly:
    out = _Poly()
    out.const = poly.const * factor
    out.lin = {key: value * factor for key, value in poly.lin.items()}
    out.quad = {key: value * factor for key, value in poly.quad.items()}
    return out


def _add_into(target: _Poly, other: _Poly, factor: float) -> None:
    target.const += other.const * factor
    for key, value in other.lin.items():
        target.lin[key] = target.lin.get(key, 0.0) + value * factor
    for key, value in other.quad.items():
        target.quad[key] = target.quad.get(key, 0.0) + value * factor
