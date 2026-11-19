"""Readers and writers for the standard mathematical-programming file formats.

LP and MPS stay in ``formats``. This module adds free and fixed MPS notes,
QPS, AMPL NL (linear rows plus expression trees for smooth nonlinear models), OSiL, CBF,
SDPA, and FlatZinc / MiniZinc.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from axiom.errors import AxiomError
from axiom.modeling.flatten import FlatModel, flatten
from axiom.modeling.formats import read_lp, read_mps, write_lp, write_mps
from axiom.modeling.index import resolve_index
from axiom.modeling.ir import Constraint, Expr, Model, Objective, VarDecl, cartesian, const, ref, var_key


def write_free_mps(model: Model | FlatModel) -> str:
    return write_mps(model)


def write_fixed_mps(model: Model | FlatModel) -> str:
    """Fixed-column MPS. Fields sit in the classic 4-column layout."""
    free = write_mps(model).splitlines()
    fixed = []
    for line in free:
        if not line or line.startswith("NAME") or line in {"ROWS", "COLUMNS", "RHS", "BOUNDS", "ENDATA", "OBJSENSE"} or line.startswith(" "):
            if line.startswith("    ") and not line.startswith(" " * 4 + " "):
                parts = line.split()
                if len(parts) >= 3 and parts[0] not in {"N", "L", "G", "E", "MAX", "MIN"}:
                    fixed.append(_fixed_data(parts))
                    continue
            fixed.append(line)
        else:
            fixed.append(line)
    return "\n".join(fixed) + "\n"


def _fixed_data(parts: list[str]) -> str:
    def field(text: str, width: int) -> str:
        return str(text)[:width].ljust(width)

    if len(parts) >= 5:
        return "    " + field(parts[0], 8) + "  " + field(parts[1], 8) + "  " + field(parts[2], 12) + "   " + field(parts[3], 8) + "  " + field(parts[4], 12)
    if len(parts) == 4 and parts[0] in {"LO", "UP", "FX", "FR", "BV", "LI", "UI", "MI", "PL"}:
        return " " + field(parts[0], 2) + " " + field(parts[1], 8) + "  " + field(parts[2], 8) + "  " + field(parts[3], 12)
    if len(parts) == 3:
        return "    " + field(parts[0], 8) + "  " + field(parts[1], 8) + "  " + field(parts[2], 12)
    return "    " + "  ".join(parts)


def write_qps(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    body = write_mps(flat)
    if not getattr(flat, "quadratic", None):
        return body
    names = {var.key: _safe(var.key) for var in flat.variables}
    lines = ["QUADOBJ"]
    for (left, right), coef in flat.quadratic.items():
        if abs(coef) < 1e-15:
            continue
        lines.append(f"    {names[left]} {names[right]} {_num(coef)}")
    lines.append("ENDATA")
    text = body.replace("ENDATA\n", "")
    return text + "\n".join(lines) + "\n"


def read_qps(text: str) -> Model:
    quad_lines = []
    kept = []
    section = ""
    for raw in text.splitlines():
        head = raw.strip().split()[:1]
        token = head[0].upper() if head else ""
        if token in {"QUADOBJ", "QMATRIX"}:
            section = "quad"
            continue
        if token == "ENDATA":
            section = ""
            kept.append(raw)
            continue
        if section == "quad":
            quad_lines.append(raw.strip())
        else:
            kept.append(raw)
    model = read_mps("\n".join(kept))
    if not quad_lines or not model.objectives:
        return model
    terms = [model.objectives[0].expr]
    for line in quad_lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        left, right, coef = parts[0], parts[1], float(parts[2])
        product = Expr(op="mul", args=(ref(left), ref(right)))
        terms.append(product if abs(coef - 1) < 1e-12 else Expr(op="mul", args=(const(coef), product)))
    model.objectives[0].expr = _sum_expr(terms)
    return model


class _NlParts:
    def __init__(self) -> None:
        self.const = 0.0
        self.linear: dict[str, float] = {}
        self.residual: Expr | None = None
        self.nl_vars: set[str] = set()


def nl_variable_keys(model: Model | FlatModel) -> list[str]:
    """Variable keys in the order ``write_nl`` emits them.

    ASL requires nonlinear variables to occupy a prefix of the column list.
    The solver's ``.sol`` file returns primals in that same order.
    """
    flat = model if isinstance(model, FlatModel) else flatten(model)
    if _nl_needs_expr(flat):
        return _nl_plan(flat).order
    return [var.key for var in flat.variables]


def write_nl(model: Model | FlatModel, comments: bool = True) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    if _nl_needs_expr(flat):
        if flat.source is None:
            raise AxiomError(
                "非线性 NL 导出需要保留原始表达式。",
                "Nonlinear NL export needs the original expression tree.",
                code="nonlinear",
            )
        return _write_nl_expr(flat, comments)
    n = len(flat.variables)
    m = len(flat.constraints)
    eqns = sum(1 for con in flat.constraints if con.sense == "==")
    binaries = sum(1 for var in flat.variables if var.domain == "binary")
    integers = sum(1 for var in flat.variables if var.domain == "integer")
    nnz = sum(len(con.coeffs) for con in flat.constraints)
    gnz = sum(1 for coef in flat.objective.values() if abs(coef) > 1e-15)
    names = [_safe(var.key) for var in flat.variables]
    con_names = [_safe(con.key) for con in flat.constraints]
    lines = [
        "g3 1 1 0\t# problem axiom",
        f" {n} {m} 1 0 {eqns}",
        " 0 0 0 0 0 0",
        " 0 0",
        " 0 0 0",
        " 0 0 0 1",
        f" {binaries} {integers} 0 0 0",
        f" {nnz} {gnz}",
        f" {max((len(name) for name in con_names), default=0)} {max((len(name) for name in names), default=0)}",
        " 0 0 0 0 0",
    ]
    for index, name in enumerate(con_names):
        lines.append(f"C{index}\t#{name}")
        lines.append("n0")
    sense = 1 if flat.sense == "maximize" else 0
    lines.append(f"O0 {sense}\t#obj")
    lines.append("n0")
    lines.append("x0")
    if m:
        lines.append("r")
        for con, name in zip(flat.constraints, con_names, strict=True):
            code = {"<=": 1, ">=": 2, "==": 4}[con.sense]
            lines.append(f"{code} {_num(con.rhs)}\t#{name}")
    lines.append("b")
    for var, name in zip(flat.variables, names, strict=True):
        lines.append(_nl_bound(var.lower, var.upper) + f"\t#{name}")
        if comments:
            lines.append(f"# axiom-domain {name} {var.domain}")
    if n:
        lines.append(f"k{n - 1}")
        running = 0
        for var in flat.variables[:-1]:
            running += sum(1 for con in flat.constraints if abs(con.coeffs.get(var.key, 0.0)) > 1e-15)
            lines.append(str(running))
    index = {var.key: i for i, var in enumerate(flat.variables)}
    for row, con in enumerate(flat.constraints):
        entries = [(index[key], coef) for key, coef in con.coeffs.items() if abs(coef) > 1e-15]
        lines.append(f"J{row} {len(entries)}")
        for col, coef in entries:
            lines.append(f"{col} {_num(coef)}")
    entries = [(index[key], coef) for key, coef in flat.objective.items() if abs(coef) > 1e-15]
    lines.append(f"G0 {len(entries)}")
    for col, coef in entries:
        lines.append(f"{col} {_num(coef)}")
    if comments and abs(flat.objective_const) > 1e-15:
        lines.append(f"# axiom-constant {_num(flat.objective_const)}")
    return "\n".join(lines) + "\n"


def _nl_needs_expr(flat: FlatModel) -> bool:
    return bool(flat.nonlinear or flat.quadratic or flat.cones)


class _NlPlan:
    def __init__(self) -> None:
        self.order: list[str] = []
        self.rows: list[tuple[str, str, _NlParts, str]] = []
        self.objective = _NlParts()
        self.sense = "minimize"
        self.n_nl_con = 0
        self.n_nl_obj = 0
        self.n_con_vars = 0
        self.n_obj_vars = 0
        self.n_both = 0


def _nl_plan(flat: FlatModel) -> _NlPlan:
    source = flat.source
    if source is None or not source.objectives:
        raise AxiomError("NL 导出需要目标函数。", "NL export needs an objective.", code="no_objective")
    plan = _NlPlan()
    rows: list[tuple[str, str, _NlParts, str]] = []
    for con in source.constraints:
        rows.extend(_nl_constraint_rows(source, con))
    sense, objective = _nl_objective(source)
    nl_con: set[str] = set()
    for _key, _name, parts, _sense in rows:
        nl_con |= parts.nl_vars
    nl_obj = set(objective.nl_vars)
    both = nl_con & nl_obj
    declared = [var.key for var in flat.variables]
    extras = [key for key in (nl_con | nl_obj) if key not in declared]
    declared = declared + extras

    def take(group: set[str]) -> list[str]:
        return [key for key in declared if key in group]

    plan.order = take(both) + take(nl_con - both) + take(nl_obj - both) + take(set(declared) - nl_con - nl_obj)
    plan.rows = [row for row in rows if row[2].residual is not None] + [row for row in rows if row[2].residual is None]
    plan.objective = objective
    plan.sense = sense
    plan.n_nl_con = sum(1 for row in plan.rows if row[2].residual is not None)
    plan.n_nl_obj = 1 if objective.residual is not None else 0
    plan.n_both = len(both)
    plan.n_con_vars = len(nl_con)
    n_obj = plan.n_con_vars + len(nl_obj) - plan.n_both
    if n_obj == plan.n_con_vars:
        n_obj = plan.n_both
    plan.n_obj_vars = n_obj
    return plan


def _nl_objective(model: Model) -> tuple[str, _NlParts]:
    obj = model.objectives[0]
    parts = _nl_scale(_nl_walk(model, obj.expr, {}, {}), obj.weight)
    if parts.residual is not None and abs(parts.const) > 1e-15:
        parts.residual = Expr(op="add", args=(parts.residual, const(parts.const)))
        parts.const = 0.0
    return obj.sense, parts


def _nl_constraint_rows(model: Model, con: Constraint) -> list[tuple[str, str, _NlParts, str]]:
    if con.kind != "comparison" or con.lhs is None or con.rhs is None:
        raise AxiomError(
            f"约束 {con.name} 不能写成 NL 比较式。",
            f"Constraint {con.name} cannot be written as an NL comparison.",
            code="bad_constraint",
        )
    qmap = {q.index: q.set_name for q in con.quants}
    names = [q.index for q in con.quants]
    rows: list[tuple[str, str, _NlParts, str]] = []
    for combo in cartesian(model, [q.set_name for q in con.quants]):
        env = dict(zip(names, combo, strict=True))
        parts = _nl_add(_nl_walk(model, con.lhs, env, qmap), _nl_scale(_nl_walk(model, con.rhs, env, qmap), -1.0))
        kind = _nl_trivial(parts, con.relation or "<=")
        relation = con.relation or "<="
        if kind == "true":
            continue
        if kind == "false":
            parts = _NlParts()
            parts.const = 1.0
            relation = "<="
        rows.append((var_key(con.name, combo), con.name, parts, relation))
    return rows


def _nl_trivial(parts: _NlParts, sense: str) -> str | None:
    if parts.residual is not None or parts.linear:
        return None
    rhs = -parts.const
    if sense == "<=" and rhs >= -1e-9:
        return "true"
    if sense == ">=" and rhs <= 1e-9:
        return "true"
    if sense == "==" and abs(rhs) <= 1e-9:
        return "true"
    return "false"


def _nl_walk(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> _NlParts:
    if expr.op == "const":
        parts = _NlParts()
        parts.const = float(expr.value or 0.0)
        return parts
    if expr.op == "neg":
        return _nl_scale(_nl_walk(model, expr.args[0], env, qmap), -1.0)
    if expr.op == "add":
        return _nl_add(_nl_walk(model, expr.args[0], env, qmap), _nl_walk(model, expr.args[1], env, qmap))
    if expr.op == "sub":
        return _nl_add(_nl_walk(model, expr.args[0], env, qmap), _nl_scale(_nl_walk(model, expr.args[1], env, qmap), -1.0))
    if expr.op == "mul":
        left = _nl_walk(model, expr.args[0], env, qmap)
        right = _nl_walk(model, expr.args[1], env, qmap)
        if _nl_is_number(left):
            return _nl_scale(right, left.const)
        if _nl_is_number(right):
            return _nl_scale(left, right.const)
        return _nl_nonlinear(model, expr, env, qmap)
    if expr.op == "div":
        left = _nl_walk(model, expr.args[0], env, qmap)
        right = _nl_walk(model, expr.args[1], env, qmap)
        if _nl_is_number(right):
            if abs(right.const) < 1e-15:
                raise AxiomError("NL 表达式除以零。", "NL expression divided by zero.", code="eval")
            return _nl_scale(left, 1.0 / right.const)
        return _nl_nonlinear(model, expr, env, qmap)
    if expr.op == "pow":
        base = _nl_walk(model, expr.args[0], env, qmap)
        exponent = _nl_walk(model, expr.args[1], env, qmap)
        if _nl_is_number(base) and _nl_is_number(exponent):
            parts = _NlParts()
            parts.const = base.const**exponent.const
            return parts
        if _nl_is_number(exponent) and abs(exponent.const - 1.0) < 1e-12:
            return base
        if _nl_is_number(exponent) and abs(exponent.const) < 1e-12:
            parts = _NlParts()
            parts.const = 1.0
            return parts
        return _nl_nonlinear(model, expr, env, qmap)
    if expr.op == "sum":
        total = _NlParts()
        names = [q.index for q in expr.quants]
        local_map = dict(qmap)
        local_map.update({q.index: q.set_name for q in expr.quants})
        for combo in cartesian(model, [q.set_name for q in expr.quants]):
            local = dict(env)
            local.update(zip(names, combo, strict=True))
            total = _nl_add(total, _nl_walk(model, expr.args[0], local, local_map))
        return total
    if expr.op == "ref":
        return _nl_ref(model, expr, env, qmap)
    raise AxiomError(f"NL 导出不能表示算子 {expr.op}。", f"NL export cannot represent operator {expr.op}.", code="bad_expr")


def _nl_ref(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> _NlParts:
    name = expr.name or ""
    indices = tuple(resolve_index(index, env, qmap, model) for index in expr.indices)
    parts = _NlParts()
    if name in model.parameters:
        parts.const = float(model.parameters[name].get(indices))
        return parts
    if name in model.variables:
        parts.linear[var_key(name, indices)] = 1.0
        return parts
    if name in env and not indices:
        parts.const = float(env[name])
        return parts
    raise AxiomError(f"NL 导出找不到符号 {name}。", f"NL export cannot find symbol {name}.", code="unknown_symbol")


def _nl_is_number(parts: _NlParts) -> bool:
    return parts.residual is None and not parts.linear and not parts.nl_vars


def _nl_scale(parts: _NlParts, factor: float) -> _NlParts:
    if abs(factor) < 1e-15:
        return _NlParts()
    scaled = _NlParts()
    scaled.const = parts.const * factor
    scaled.linear = {key: value * factor for key, value in parts.linear.items() if abs(value * factor) > 1e-15}
    scaled.nl_vars = set(parts.nl_vars)
    if parts.residual is not None:
        if abs(factor - 1.0) <= 1e-12:
            scaled.residual = parts.residual
        elif abs(factor + 1.0) <= 1e-12:
            scaled.residual = Expr(op="neg", args=(parts.residual,))
        else:
            scaled.residual = Expr(op="mul", args=(const(factor), parts.residual))
    return scaled


def _nl_add(left: _NlParts, right: _NlParts) -> _NlParts:
    merged = _NlParts()
    merged.const = left.const + right.const
    linear = dict(left.linear)
    for key, value in right.linear.items():
        linear[key] = linear.get(key, 0.0) + value
    merged.linear = {key: value for key, value in linear.items() if abs(value) > 1e-15}
    merged.nl_vars = set(left.nl_vars) | set(right.nl_vars)
    if left.residual is not None and right.residual is not None:
        merged.residual = Expr(op="add", args=(left.residual, right.residual))
    else:
        merged.residual = left.residual if left.residual is not None else right.residual
    return merged


def _nl_nonlinear(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> _NlParts:
    parts = _NlParts()
    parts.residual = _nl_concrete(model, expr, env, qmap)
    parts.nl_vars = _nl_collect(parts.residual)
    return parts


def _nl_concrete(model: Model, expr: Expr, env: dict[str, str], qmap: dict[str, str]) -> Expr:
    if expr.op == "const":
        return const(float(expr.value or 0.0))
    if expr.op == "ref":
        name = expr.name or ""
        indices = tuple(resolve_index(index, env, qmap, model) for index in expr.indices)
        if name in model.parameters:
            return const(float(model.parameters[name].get(indices)))
        if name in model.variables:
            return ref(var_key(name, indices))
        if name in env and not indices:
            return const(float(env[name]))
        raise AxiomError(f"NL 导出找不到符号 {name}。", f"NL export cannot find symbol {name}.", code="unknown_symbol")
    if expr.op == "sum":
        names = [q.index for q in expr.quants]
        local_map = dict(qmap)
        local_map.update({q.index: q.set_name for q in expr.quants})
        terms = []
        for combo in cartesian(model, [q.set_name for q in expr.quants]):
            local = dict(env)
            local.update(zip(names, combo, strict=True))
            terms.append(_nl_concrete(model, expr.args[0], local, local_map))
        return _sum_expr(terms)
    if expr.op == "neg":
        return Expr(op="neg", args=(_nl_concrete(model, expr.args[0], env, qmap),))
    return Expr(op=expr.op, args=tuple(_nl_concrete(model, arg, env, qmap) for arg in expr.args))


def _nl_collect(expr: Expr) -> set[str]:
    if expr.op == "ref":
        return {expr.name or ""}
    found: set[str] = set()
    for arg in expr.args:
        found |= _nl_collect(arg)
    return found


def _nl_emit(expr: Expr | None, index: dict[str, int]) -> list[str]:
    if expr is None:
        return ["n0"]
    if expr.op == "const":
        return [f"n{_num(float(expr.value or 0.0))}"]
    if expr.op == "ref":
        return [f"v{index[expr.name or '']}"]
    if expr.op == "neg":
        return ["o16", *_nl_emit(expr.args[0], index)]
    opcodes = {"add": "o0", "sub": "o1", "mul": "o2", "div": "o3", "pow": "o5"}
    if expr.op not in opcodes:
        raise AxiomError(f"NL 导出不能表示算子 {expr.op}。", f"NL export cannot represent operator {expr.op}.", code="bad_expr")
    return [opcodes[expr.op], *_nl_emit(expr.args[0], index), *_nl_emit(expr.args[1], index)]


def _nl_matrix(parts: _NlParts, index: dict[str, int], nonlinear: bool) -> list[tuple[int, float]]:
    entries: dict[int, float] = {}
    for key, coef in parts.linear.items():
        if abs(coef) > 1e-15:
            entries[index[key]] = coef
    if nonlinear and parts.residual is not None:
        for key in parts.nl_vars:
            entries.setdefault(index[key], 0.0)
    return sorted(entries.items())


def _write_nl_expr(flat: FlatModel, comments: bool) -> str:
    plan = _nl_plan(flat)
    by_key = {var.key: var for var in flat.variables}
    order = plan.order
    index = {key: position for position, key in enumerate(order)}
    names = [_safe(key) for key in order]
    rows = plan.rows
    con_names = [_safe(key) for key, _name, _parts, _sense in rows]
    binaries = sum(1 for key in order if key in by_key and by_key[key].domain == "binary")
    integers = sum(1 for key in order if key in by_key and by_key[key].domain == "integer")
    jacobian = [_nl_matrix(parts, index, parts.residual is not None) for _key, _name, parts, _sense in rows]
    gradient = _nl_matrix(plan.objective, index, plan.objective.residual is not None)
    nnz = sum(len(row) for row in jacobian)
    eqns = sum(1 for _key, _name, _parts, sense in rows if sense == "==")
    lines = [
        "g3 1 1 0\t# problem axiom",
        f" {len(order)} {len(rows)} 1 0 {eqns}",
        f" {plan.n_nl_con} {plan.n_nl_obj} 0 0 0 0",
        " 0 0",
        f" {plan.n_con_vars} {plan.n_obj_vars} {plan.n_both}",
        " 0 0 0 1",
        f" {binaries} {integers} 0 0 0",
        f" {nnz} {len(gradient)}",
        f" {max((len(name) for name in con_names), default=0)} {max((len(name) for name in names), default=0)}",
        " 0 0 0 0 0",
    ]
    for row, ((key, _name, parts, _sense), cname) in enumerate(zip(rows, con_names, strict=True)):
        lines.append(f"C{row}\t#{cname}")
        lines.extend(_nl_emit(parts.residual, index))
    sense = 1 if plan.sense == "maximize" else 0
    lines.append(f"O0 {sense}\t#obj")
    lines.extend(_nl_emit(plan.objective.residual, index))
    lines.append("x0")
    lines.append("r")
    for (key, _name, parts, sense), cname in zip(rows, con_names, strict=True):
        code = {"<=": 1, ">=": 2, "==": 4}[sense]
        lines.append(f"{code} {_num(-parts.const)}\t#{cname}")
    lines.append("b")
    for key, name in zip(order, names, strict=True):
        var = by_key.get(key)
        lower = None if var is None else var.lower
        upper = None if var is None else var.upper
        domain = "continuous" if var is None else var.domain
        lines.append(_nl_bound(lower, upper) + f"\t#{name}")
        if comments:
            lines.append(f"# axiom-domain {name} {domain}")
    if order:
        lines.append(f"k{len(order) - 1}")
        running = 0
        counts = [0] * len(order)
        for entries in jacobian:
            for col, _coef in entries:
                counts[col] += 1
        for count in counts[:-1]:
            running += count
            lines.append(str(running))
    for row, entries in enumerate(jacobian):
        lines.append(f"J{row} {len(entries)}")
        for col, coef in entries:
            lines.append(f"{col} {_num(coef)}")
    lines.append(f"G0 {len(gradient)}")
    for col, coef in gradient:
        lines.append(f"{col} {_num(coef)}")
    if comments and plan.objective.residual is None and abs(plan.objective.const) > 1e-15:
        lines.append(f"# axiom-constant {_num(plan.objective.const)}")
    return "\n".join(lines) + "\n"


def read_nl(text: str) -> Model:
    if _nl_has_expr(text):
        return _read_nl_expr(text)
    lines = text.splitlines()
    if not lines or not lines[0].startswith("g"):
        raise AxiomError("这不是 ASCII NL 文件。", "This is not an ASCII NL file.", code="import")
    counts = lines[1].split()
    n_var, n_con = int(counts[0]), int(counts[1])
    domains = ["continuous"] * n_var
    names = [f"x{i + 1}" for i in range(n_var)]
    con_names = [f"c{i + 1}" for i in range(n_con)]
    bounds = [[None, None] for _ in range(n_var)]
    ranges: list[tuple[int, float]] = []
    jacobian: dict[int, dict[int, float]] = {}
    gradient: dict[int, float] = {}
    constant = 0.0
    sense = "minimize"
    section = ""
    row = -1
    bound_index = 0
    for raw in lines[2:]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# axiom-domain"):
            _, _, name, domain = line.split()
            if name in names:
                domains[names.index(name)] = domain
            continue
        if line.startswith("# axiom-constant"):
            constant = float(line.split()[-1])
            continue
        if line.startswith("C") and line[1:2].isdigit():
            row = int(line.split()[0][1:])
            comment = line.split("#", 1)[1].strip() if "#" in line else ""
            if comment:
                con_names[row] = comment
            continue
        if line.startswith("O0"):
            sense = "maximize" if line.split()[1] == "1" else "minimize"
            continue
        if line == "r":
            section = "r"
            row = 0
            continue
        if line == "b":
            section = "b"
            bound_index = 0
            continue
        if line.startswith("k") and line[1:].isdigit():
            section = "k"
            continue
        if line.startswith("J") and line[1:2].isdigit():
            section = "J"
            row = int(line.split()[0][1:])
            jacobian.setdefault(row, {})
            continue
        if line.startswith("G0"):
            section = "G"
            continue
        if line.startswith("n") or line.startswith("x") or line.startswith("C"):
            continue
        parts = line.split()
        if section == "r" and len(parts) >= 2 and parts[0].lstrip("-").isdigit():
            code, rhs = int(parts[0]), float(parts[1])
            ranges.append((code, rhs))
            if "#" in line:
                con_names[len(ranges) - 1] = line.split("#", 1)[1].strip()
            continue
        if section == "b" and parts[0] in {"0", "1", "2", "3", "4"}:
            code = int(parts[0])
            lo = hi = None
            if code == 0 and len(parts) >= 3:
                lo, hi = float(parts[1]), float(parts[2])
            elif code == 1 and len(parts) >= 2:
                hi = float(parts[1])
            elif code == 2 and len(parts) >= 2:
                lo = float(parts[1])
            elif code == 4 and len(parts) >= 2:
                lo = hi = float(parts[1])
            if bound_index < n_var:
                bounds[bound_index] = [lo, hi]
                if "#" in line:
                    names[bound_index] = line.split("#", 1)[1].strip()
                bound_index += 1
            continue
        if section == "J" and len(parts) >= 2:
            jacobian.setdefault(row, {})[int(parts[0])] = float(parts[1])
            continue
        if section == "G" and len(parts) >= 2:
            gradient[int(parts[0])] = float(parts[1])
    model = Model(name="imported_nl")
    for i, name in enumerate(names):
        model.variables[name] = VarDecl(name=name, domain=domains[i], lower=bounds[i][0], upper=bounds[i][1])  # type: ignore[arg-type]
    obj = {names[col]: coef for col, coef in gradient.items()}
    model.objectives.append(Objective(name="obj", sense=sense, expr=_coef(obj, constant)))  # type: ignore[arg-type]
    for row, (code, rhs) in enumerate(ranges):
        relation = {1: "<=", 2: ">=", 4: "=="}.get(code, "<=")
        coef = {names[col]: value for col, value in jacobian.get(row, {}).items()}
        model.constraints.append(Constraint(name=con_names[row], kind="comparison", relation=relation, lhs=_coef(coef, 0.0), rhs=const(rhs)))  # type: ignore[arg-type]
    return model


_NL_OP = {0: ("add", 2), 1: ("sub", 2), 2: ("mul", 2), 3: ("div", 2), 5: ("pow", 2), 16: ("neg", 1)}


def _nl_has_expr(text: str) -> bool:
    for raw in text.splitlines():
        token = _nl_token(raw)
        if len(token) > 1 and token[0] in {"o", "v"} and (token[1].isdigit() or token[1] == "-"):
            return True
    return False


def _nl_token(line: str) -> str:
    body = line.split("#", 1)[0].strip()
    return body.split()[0] if body else ""


def _read_nl_expr(text: str) -> Model:
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].startswith("g"):
        raise AxiomError("这不是 ASCII NL 文件。", "This is not an ASCII NL file.", code="import")
    counts = lines[1].split()
    n_var, n_con = int(counts[0]), int(counts[1])
    names = [f"x{i + 1}" for i in range(n_var)]
    domains = ["continuous"] * n_var
    domain_by_name: dict[str, str] = {}
    con_names = [f"c{i + 1}" for i in range(n_con)]
    bounds: list[list[float | None]] = [[None, None] for _ in range(n_var)]
    ranges: list[tuple[int, float]] = []
    jacobian: dict[int, dict[int, float]] = {}
    gradient: dict[int, float] = {}
    bodies: dict[int, Expr] = {}
    obj_expr: Expr = const(0.0)
    constant = 0.0
    sense = "minimize"
    section = ""
    bound_index = 0
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        token = _nl_token(raw)
        if stripped.startswith("# axiom-domain"):
            _, _, name, domain = stripped.split()
            domain_by_name[name] = domain
            index += 1
            continue
        if stripped.startswith("# axiom-constant"):
            constant = float(stripped.split()[-1])
            index += 1
            continue
        if token.startswith("C") and len(token) > 1 and token[1].isdigit():
            row = int(token[1:])
            if "#" in raw and row < n_con:
                con_names[row] = raw.split("#", 1)[1].strip()
            obj_body, index = _parse_nl_expr(lines, index + 1)
            bodies[row] = obj_body
            continue
        if token.startswith("O") and len(token) > 1 and token[1].isdigit():
            parts = raw.split("#", 1)[0].split()
            if len(parts) > 1 and parts[1] == "1":
                sense = "maximize"
            obj_expr, index = _parse_nl_expr(lines, index + 1)
            continue
        if token.startswith("x") and token[1:].isdigit():
            index += 1 + int(token[1:])
            continue
        if token.startswith("k") and token[1:].isdigit():
            skip = int(token[1:])
            index += 1
            seen = 0
            while index < len(lines) and seen < skip:
                if _nl_token(lines[index]):
                    seen += 1
                index += 1
            continue
        if token.startswith("J") and len(token) > 1 and token[1].isdigit():
            row = int(token[1:])
            count = int(raw.split("#", 1)[0].split()[1])
            jacobian[row] = {}
            for _ in range(count):
                index += 1
                col_s, coef_s = lines[index].split("#", 1)[0].split()[:2]
                jacobian[row][int(col_s)] = float(coef_s)
            index += 1
            continue
        if token.startswith("G") and len(token) > 1 and token[1].isdigit():
            count = int(raw.split("#", 1)[0].split()[1])
            for _ in range(count):
                index += 1
                col_s, coef_s = lines[index].split("#", 1)[0].split()[:2]
                gradient[int(col_s)] = float(coef_s)
            index += 1
            continue
        if token == "r":
            section = "r"
            index += 1
            continue
        if token == "b":
            section = "b"
            bound_index = 0
            index += 1
            continue
        if not token or token[0] in {"g", "n", "o", "v", "F", "S"} or token[:1].isdigit() and section == "":
            index += 1
            continue
        parts = raw.split("#", 1)[0].split()
        if section == "r" and parts and parts[0].lstrip("-").isdigit():
            code = int(parts[0])
            rhs = float(parts[1]) if len(parts) > 1 else 0.0
            ranges.append((code, rhs))
            if "#" in raw and len(ranges) <= n_con:
                con_names[len(ranges) - 1] = raw.split("#", 1)[1].strip()
            index += 1
            continue
        if section == "b" and parts and parts[0] in {"0", "1", "2", "3", "4"}:
            code = int(parts[0])
            lo = hi = None
            if code == 0 and len(parts) >= 3:
                lo, hi = float(parts[1]), float(parts[2])
            elif code == 1 and len(parts) >= 2:
                hi = float(parts[1])
            elif code == 2 and len(parts) >= 2:
                lo = float(parts[1])
            elif code == 4 and len(parts) >= 2:
                lo = hi = float(parts[1])
            if bound_index < n_var:
                bounds[bound_index] = [lo, hi]
                if "#" in raw:
                    names[bound_index] = raw.split("#", 1)[1].strip()
                bound_index += 1
            index += 1
            continue
        index += 1
    for position, name in enumerate(names):
        if name in domain_by_name:
            domains[position] = domain_by_name[name]
    model = Model(name="imported_nl")
    for position, name in enumerate(names):
        model.variables[name] = VarDecl(name=name, domain=domains[position], lower=bounds[position][0], upper=bounds[position][1])  # type: ignore[arg-type]
    gradient_expr = _coef({names[col]: coef for col, coef in gradient.items() if col < len(names)}, constant)
    model.objectives.append(Objective(name="obj", sense=sense, expr=_nl_join(_nl_rename(obj_expr, names), gradient_expr)))
    for row, (code, rhs) in enumerate(ranges):
        relation = {1: "<=", 2: ">=", 4: "=="}.get(code, "<=")
        linear = _coef({names[col]: coef for col, coef in jacobian.get(row, {}).items() if col < len(names)}, 0.0)
        body = _nl_join(_nl_rename(bodies.get(row, const(0.0)), names), linear)
        model.constraints.append(Constraint(name=con_names[row], kind="comparison", relation=relation, lhs=body, rhs=const(rhs)))  # type: ignore[arg-type]
    return model


def _parse_nl_expr(lines: list[str], index: int) -> tuple[Expr, int]:
    if index >= len(lines):
        raise AxiomError("NL 表达式不完整。", "The NL expression is incomplete.", code="import")
    token = _nl_token(lines[index])
    if token.startswith("n"):
        return const(float(token[1:])), index + 1
    if token.startswith("v"):
        return ref(f"__v{int(token[1:])}"), index + 1
    if token.startswith("o"):
        code = int(token[1:])
        if code not in _NL_OP:
            raise AxiomError(f"NL 算子 o{code} 尚未支持。", f"NL opcode o{code} is not supported.", code="import")
        op, arity = _NL_OP[code]
        args: list[Expr] = []
        index += 1
        for _ in range(arity):
            arg, index = _parse_nl_expr(lines, index)
            args.append(arg)
        if op == "neg":
            return Expr(op="neg", args=(args[0],)), index
        return Expr(op=op, args=tuple(args)), index
    raise AxiomError(f"无法读取 NL 表达式 {token or lines[index]!r}。", f"Cannot read NL expression {token or lines[index]!r}.", code="import")


def _nl_rename(expr: Expr, names: list[str]) -> Expr:
    if expr.op == "const":
        return expr
    if expr.op == "ref":
        name = expr.name or ""
        if name.startswith("__v"):
            return ref(names[int(name[3:])])
        return expr
    if expr.op == "neg":
        return Expr(op="neg", args=(_nl_rename(expr.args[0], names),))
    return Expr(op=expr.op, args=tuple(_nl_rename(arg, names) for arg in expr.args))


def _nl_join(left: Expr, right: Expr) -> Expr:
    if _nl_expr_zero(left):
        return right
    if _nl_expr_zero(right):
        return left
    return Expr(op="add", args=(left, right))


def _nl_expr_zero(expr: Expr) -> bool:
    return expr.op == "const" and abs(float(expr.value or 0.0)) < 1e-15


def _nl_bound(lower: float | None, upper: float | None) -> str:
    if lower is None and upper is None:
        return "3"
    if lower is not None and upper is not None:
        if abs(lower - upper) < 1e-12:
            return f"4 {_num(lower)}"
        return f"0 {_num(lower)} {_num(upper)}"
    if upper is not None:
        return f"1 {_num(upper)}"
    return f"2 {_num(lower)}"


def write_osil(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    variables = []
    for var in flat.variables:
        kind = {"continuous": "C", "integer": "I", "binary": "B"}[var.domain]
        lb = "" if var.lower is None else f' lb="{_num(var.lower)}"'
        ub = "" if var.upper is None else f' ub="{_num(var.upper)}"'
        variables.append(f'      <var name="{escape(_safe(var.key))}" type="{kind}"{lb}{ub}/>')
    names = [_safe(var.key) for var in flat.variables]
    index = {var.key: i for i, var in enumerate(flat.variables)}
    obj_coef = "".join(f'<coef idx="{index[key]}">{_num(coef)}</coef>' for key, coef in flat.objective.items() if abs(coef) > 1e-15)
    cons = []
    for con in flat.constraints:
        attrs = [f'name="{escape(_safe(con.key))}"']
        if con.sense == "<=":
            attrs.append(f'ub="{_num(con.rhs)}"')
        elif con.sense == ">=":
            attrs.append(f'lb="{_num(con.rhs)}"')
        else:
            attrs.append(f'lb="{_num(con.rhs)}" ub="{_num(con.rhs)}"')
        cons.append("      <con " + " ".join(attrs) + "/>")
    starts = [0]
    rows, values = [], []
    for var in flat.variables:
        for con_index, con in enumerate(flat.constraints):
            coef = con.coeffs.get(var.key, 0.0)
            if abs(coef) > 1e-15:
                rows.append(str(con_index))
                values.append(_num(coef))
        starts.append(len(values))
    sense = "max" if flat.sense == "maximize" else "min"
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<osil xmlns="os.optimizationservices.org">',
            "  <instanceHeader>",
            f"    <name>{escape(flat.name or 'axiom')}</name>",
            "  </instanceHeader>",
            "  <instanceData>",
            f'    <variables numberOfVariables="{len(flat.variables)}">',
            *variables,
            "    </variables>",
            '    <objectives numberOfObjectives="1">',
            f'      <obj name="obj" maxOrMin="{sense}" numberOfObjCoef="{obj_coef.count("<coef")}" constant="{_num(flat.objective_const)}">{obj_coef}</obj>',
            "    </objectives>",
            f'    <constraints numberOfConstraints="{len(flat.constraints)}">',
            *cons,
            "    </constraints>",
            f'    <linearConstraintCoefficients numberOfValues="{len(values)}">',
            "      <start>" + "".join(f"<el>{item}</el>" for item in starts) + "</start>",
            "      <rowIdx>" + "".join(f"<el>{item}</el>" for item in rows) + "</rowIdx>",
            "      <value>" + "".join(f"<el>{item}</el>" for item in values) + "</value>",
            "    </linearConstraintCoefficients>",
            "  </instanceData>",
            "</osil>",
            "",
        ]
    )


def read_osil(text: str) -> Model:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise AxiomError("OSiL 不是有效的 XML。", "OSiL is not valid XML.", code="import") from exc
    model = Model(name="imported_osil")
    variables = list(root.iter("var"))
    names = []
    for index, node in enumerate(variables):
        name = node.attrib.get("name") or f"x{index + 1}"
        names.append(name)
        kind = {"C": "continuous", "I": "integer", "B": "binary"}.get(node.attrib.get("type", "C"), "continuous")
        lower = float(node.attrib["lb"]) if "lb" in node.attrib else None
        upper = float(node.attrib["ub"]) if "ub" in node.attrib else None
        model.variables[name] = VarDecl(name=name, domain=kind, lower=lower, upper=upper)  # type: ignore[arg-type]
    obj = next(root.iter("obj"), None)
    sense = "maximize" if obj is not None and obj.attrib.get("maxOrMin") == "max" else "minimize"
    coef: dict[str, float] = {}
    constant = float(obj.attrib.get("constant", "0")) if obj is not None else 0.0
    if obj is not None:
        for child in list(obj):
            if child.tag.endswith("coef") and child.text:
                coef[names[int(child.attrib["idx"])]] = float(child.text)
    model.objectives.append(Objective(name="obj", sense=sense, expr=_coef(coef, constant)))  # type: ignore[arg-type]
    cons = list(root.iter("con"))
    start = [int(node.text or 0) for node in root.iter("el") if _parent_tag(node) == "start"]
    row_idx = [int(node.text or 0) for node in root.iter("el") if _parent_tag(node) == "rowIdx"]
    values = [float(node.text or 0) for node in root.iter("el") if _parent_tag(node) == "value"]
    columns: list[dict[int, float]] = []
    if start and row_idx and values:
        for col in range(len(start) - 1):
            entries = {}
            for cursor in range(start[col], start[col + 1]):
                entries[row_idx[cursor]] = values[cursor]
            columns.append(entries)
    for row, node in enumerate(cons):
        name = node.attrib.get("name") or f"c{row + 1}"
        lb = float(node.attrib["lb"]) if "lb" in node.attrib else None
        ub = float(node.attrib["ub"]) if "ub" in node.attrib else None
        if lb is not None and ub is not None and abs(lb - ub) < 1e-12:
            relation, rhs = "==", lb
        elif ub is not None:
            relation, rhs = "<=", ub
        else:
            relation, rhs = ">=", lb or 0.0
        coef = {names[col]: entries[row] for col, entries in enumerate(columns) if row in entries}
        model.constraints.append(Constraint(name=name, kind="comparison", relation=relation, lhs=_coef(coef, 0.0), rhs=const(rhs)))  # type: ignore[arg-type]
    return model


def _parent_tag(node: ET.Element) -> str:
    # ElementTree does not keep parents. The writer puts el nodes in order start, rowIdx, value,
    # so callers filter by walking with a custom parent map instead.
    return ""


def read_osil(text: str) -> Model:  # noqa: F811
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise AxiomError("OSiL 不是有效的 XML。", "OSiL is not valid XML.", code="import") from exc
    parent = {child: element for element in root.iter() for child in list(element)}
    model = Model(name="imported_osil")
    variables = [node for node in root.iter() if _local(node) == "var"]
    names = []
    for index, node in enumerate(variables):
        name = node.attrib.get("name") or f"x{index + 1}"
        names.append(name)
        kind = {"C": "continuous", "I": "integer", "B": "binary"}.get(node.attrib.get("type", "C"), "continuous")
        lower = float(node.attrib["lb"]) if "lb" in node.attrib else None
        upper = float(node.attrib["ub"]) if "ub" in node.attrib else None
        model.variables[name] = VarDecl(name=name, domain=kind, lower=lower, upper=upper)  # type: ignore[arg-type]
    obj = next((node for node in root.iter() if _local(node) == "obj"), None)
    sense = "maximize" if obj is not None and obj.attrib.get("maxOrMin") == "max" else "minimize"
    coef: dict[str, float] = {}
    constant = float(obj.attrib.get("constant", "0")) if obj is not None else 0.0
    if obj is not None:
        for child in list(obj):
            if _local(child) == "coef" and child.text:
                coef[names[int(child.attrib["idx"])]] = float(child.text)
    model.objectives.append(Objective(name="obj", sense=sense, expr=_coef(coef, constant)))  # type: ignore[arg-type]
    cons = [node for node in root.iter() if _local(node) == "con"]

    def elements(tag: str) -> list[ET.Element]:
        return [node for node in root.iter() if _local(node) == "el" and _local(parent.get(node)) == tag]

    start = [int(node.text or 0) for node in elements("start")]
    row_idx = [int(node.text or 0) for node in elements("rowIdx")]
    values = [float(node.text or 0) for node in elements("value")]
    columns: list[dict[int, float]] = []
    if start and row_idx and values:
        for col in range(len(start) - 1):
            entries = {}
            for cursor in range(start[col], start[col + 1]):
                entries[row_idx[cursor]] = values[cursor]
            columns.append(entries)
    for row, node in enumerate(cons):
        name = node.attrib.get("name") or f"c{row + 1}"
        lb = float(node.attrib["lb"]) if "lb" in node.attrib else None
        ub = float(node.attrib["ub"]) if "ub" in node.attrib else None
        if lb is not None and ub is not None and abs(lb - ub) < 1e-12:
            relation, rhs = "==", lb
        elif ub is not None:
            relation, rhs = "<=", ub
        else:
            relation, rhs = ">=", float(lb or 0.0)
        row_coef = {names[col]: entries[row] for col, entries in enumerate(columns) if row in entries}
        model.constraints.append(Constraint(name=name, kind="comparison", relation=relation, lhs=_coef(row_coef, 0.0), rhs=const(rhs)))  # type: ignore[arg-type]
    return model


def write_cbf(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    n = len(flat.variables)
    lines = ["VER", "3", "OBJSENSE", "MAX" if flat.sense == "maximize" else "MIN", "VAR", f"{n} 1", "F", str(n)]
    # Map free variables through explicit bounds as linear cones: L+ is not general.
    # Use a single free cone and encode bounds as constraints.
    m = len(flat.constraints)
    bound_rows = []
    for var in flat.variables:
        if var.lower is not None:
            bound_rows.append((var.key, ">=", float(var.lower)))
        if var.upper is not None:
            bound_rows.append((var.key, "<=", float(var.upper)))
    total = m + len(bound_rows)
    lines += ["CON", f"{total} 1", "L=", str(total)]
    obj = [(i, float(flat.objective.get(var.key, 0.0))) for i, var in enumerate(flat.variables) if abs(flat.objective.get(var.key, 0.0)) > 1e-15]
    lines += ["OBJACOORD", str(len(obj))]
    lines += [f"{i} 0 {_num(coef)}" for i, coef in obj]
    entries = []
    row = 0
    index = {var.key: i for i, var in enumerate(flat.variables)}
    bcoord = []
    for con in flat.constraints:
        for key, coef in con.coeffs.items():
            if abs(coef) > 1e-15:
                entries.append((row, index[key], float(coef)))
        if con.sense == "<=":
            bcoord.append((row, float(con.rhs)))
        elif con.sense == ">=":
            # stored as -row <= -rhs by flipping coefficients below
            pass
        else:
            bcoord.append((row, float(con.rhs)))
        row += 1
    # Rebuild constraints in <= / == form. Simpler second pass:
    entries = []
    bcoord = []
    row = 0
    senses = []
    for con in flat.constraints:
        signs = (1.0, -1.0) if con.sense == "==" else ((-1.0,) if con.sense == ">=" else (1.0,))
        for sign in signs:
            for key, coef in con.coeffs.items():
                if abs(coef) > 1e-15:
                    entries.append(f"{row} {index[key]} {_num(sign * coef)}")
            bcoord.append(f"{row} {_num(sign * con.rhs)}")
            row += 1
    for var in flat.variables:
        if var.upper is not None:
            entries.append(f"{row} {index[var.key]} 1")
            bcoord.append(f"{row} {_num(var.upper)}")
            senses.append("L")
            row += 1
        if var.lower is not None:
            entries.append(f"{row} {index[var.key]} -1")
            bcoord.append(f"{row} {_num(-var.lower)}")
            senses.append("L")
            row += 1
    # Replace the placeholder cone with the real row count. All rows are linear inequalities
    # except equalities, which CBF represents as two L rows. Equalities were stored once;
    # split them.
    eq_extra = []
    # Keep the file consistent with `row` constraints, all L+.
    lines = [
        "VER",
        "3",
        "OBJSENSE",
        "MAX" if flat.sense == "maximize" else "MIN",
        "VAR",
        f"{n} 1",
        "F",
        str(n),
        "CON",
        f"{row} 1",
        "L+",
        str(row),
        "OBJACOORD",
        str(len(obj)),
        *[f"{i} {_num(coef)}" for i, coef in obj],
        "ACOORD",
        str(len(entries)),
        *entries,
        "BCOORD",
        str(len(bcoord)),
        *bcoord,
    ]
    if abs(flat.objective_const) > 1e-15:
        lines += ["# axiom-constant " + _num(flat.objective_const)]
    lines.append("")
    return "\n".join(lines)


def read_cbf(text: str) -> Model:
    rows = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    cursor = 0

    def take() -> str:
        nonlocal cursor
        if cursor >= len(rows):
            raise AxiomError("CBF 文件提前结束。", "The CBF file ended early.", code="import")
        cursor += 1
        return rows[cursor - 1]

    header = {}
    while cursor < len(rows):
        key = take()
        if key in {"VER", "OBJSENSE", "VAR", "CON", "OBJACOORD", "ACOORD", "BCOORD"}:
            header[key] = take()
            if key in {"VAR", "CON"}:
                count = int(header[key].split()[0])
                cones = []
                left = count
                while left > 0:
                    kind = take()
                    number = int(take())
                    cones.append((kind, number))
                    left -= number
                header[key + "_CONES"] = cones
            elif key in {"OBJACOORD", "ACOORD", "BCOORD"}:
                count = int(header[key])
                header[key + "_ROWS"] = [take() for _ in range(count)]
        else:
            break
    n = int(str(header.get("VAR", "0")).split()[0])
    model = Model(name="imported_cbf")
    names = [f"x{i + 1}" for i in range(n)]
    for name in names:
        model.variables[name] = VarDecl(name=name, domain="continuous")
    sense = "maximize" if header.get("OBJSENSE") == "MAX" else "minimize"
    coef = {}
    for line in header.get("OBJACOORD_ROWS", []):
        col, value = line.split()[:2]
        coef[names[int(col)]] = float(value)
    constant = 0.0
    model.objectives.append(Objective(name="obj", sense=sense, expr=_coef(coef, constant)))  # type: ignore[arg-type]
    by_row: dict[int, dict[str, float]] = {}
    for line in header.get("ACOORD_ROWS", []):
        row, col, value = line.split()[:3]
        by_row.setdefault(int(row), {})[names[int(col)]] = float(value)
    rhs = {}
    for line in header.get("BCOORD_ROWS", []):
        row, value = line.split()[:2]
        rhs[int(row)] = float(value)
    for row, entries in sorted(by_row.items()):
        model.constraints.append(
            Constraint(name=f"c{row + 1}", kind="comparison", relation="<=", lhs=_coef(entries, 0.0), rhs=const(rhs.get(row, 0.0)))
        )
    return model


def write_sdpa(problem: dict) -> str:
    """Write a sparse SDPA file from ``{size, c, matrices}``."""
    size = int(problem["size"])
    c = list(problem["c"])
    matrices = problem["matrices"]
    lines = [str(len(c)), "1", str(size), " ".join(_num(value) for value in c)]
    for index, matrix in enumerate(matrices):
        for i, row in enumerate(matrix):
            for j, value in enumerate(row):
                if j < i or abs(float(value)) < 1e-15:
                    continue
                lines.append(f"{index} 1 {i + 1} {j + 1} {_num(float(value))}")
    lines.append("")
    return "\n".join(lines)


def read_sdpa(text: str) -> Model:
    rows = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith('"') and not line.startswith("*")]
    m = int(rows[0].split()[0])
    blocks = [int(float(part)) for part in rows[2].split()]
    size = abs(blocks[0])
    c = [float(part) for part in rows[3].split()]
    matrices = [[[0.0 for _ in range(size)] for _ in range(size)] for _ in range(m + 1)]
    for line in rows[4:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        mat, _block, i, j, value = int(parts[0]), int(parts[1]), int(parts[2]) - 1, int(parts[3]) - 1, float(parts[4])
        matrices[mat][i][j] = value
        matrices[mat][j][i] = value
    model = Model(name="imported_sdpa")
    for index in range(m):
        model.variables[f"y{index + 1}"] = VarDecl(name=f"y{index + 1}", domain="continuous")
    model.objectives.append(Objective(name="obj", sense="minimize", expr=_coef({f"y{i + 1}": c[i] for i in range(m)}, 0.0)))  # type: ignore[arg-type]
    import json

    model.meta["sdpa"] = json.dumps({"size": size, "c": c, "matrices": matrices})
    return model


def write_minizinc(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    if any(var.domain == "continuous" for var in flat.variables) and not all(var.domain != "continuous" for var in flat.variables):
        pass
    lines = ["% Generated by Axiom", "include \"globals.mzn\";"] if False else ["% Generated by Axiom"]
    for var in flat.variables:
        if var.domain == "binary":
            lines.append(f"var 0..1: {_mz(_safe(var.key))};")
        elif var.domain == "integer":
            lo = "-1000000" if var.lower is None else _num(var.lower)
            hi = "1000000" if var.upper is None else _num(var.upper)
            lines.append(f"var {lo}..{hi}: {_mz(_safe(var.key))};")
        else:
            lo = _float_bound(var.lower, "-1.0e30")
            hi = _float_bound(var.upper, "1.0e30")
            lines.append(f"var {lo}..{hi}: {_mz(_safe(var.key))};")
    names = {var.key: _mz(_safe(var.key)) for var in flat.variables}
    for con in flat.constraints:
        lines.append(f"constraint {_mz_expr(con.coeffs, names)} {con.sense if con.sense != '==' else '='} {_num(con.rhs)};")
    sense = "maximize" if flat.sense == "maximize" else "minimize"
    lines.append(f"solve {sense} {_mz_expr(flat.objective, names)};")
    lines.append("")
    return "\n".join(lines)


def write_flatzinc(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    lines = ["% Generated by Axiom as FlatZinc"]
    names = {}
    for var in flat.variables:
        name = _mz(_safe(var.key))
        names[var.key] = name
        if var.domain in {"integer", "binary"}:
            lo = 0 if var.domain == "binary" and var.lower is None else int(var.lower or -1000000)
            hi = 1 if var.domain == "binary" and var.upper is None else int(var.upper or 1000000)
            lines.append(f"var {lo}..{hi}: {name};")
        else:
            lo = _float_bound(var.lower, "-1.0e30")
            hi = _float_bound(var.upper, "1.0e30")
            lines.append(f"var {lo}..{hi}: {name};")
    for con in flat.constraints:
        coefs = ", ".join(_num(con.coeffs.get(var.key, 0.0)) for var in flat.variables)
        vars_ = ", ".join(names[var.key] for var in flat.variables)
        if con.sense == "<=":
            pred = "float_lin_le" if any(var.domain == "continuous" for var in flat.variables) else "int_lin_le"
            lines.append(f"constraint {pred}([{coefs}], [{vars_}], {_num(con.rhs)});")
        elif con.sense == ">=":
            pred = "float_lin_le" if any(var.domain == "continuous" for var in flat.variables) else "int_lin_le"
            flipped = ", ".join(_num(-con.coeffs.get(var.key, 0.0)) for var in flat.variables)
            lines.append(f"constraint {pred}([{flipped}], [{vars_}], {_num(-con.rhs)});")
        else:
            pred = "float_lin_eq" if any(var.domain == "continuous" for var in flat.variables) else "int_lin_eq"
            lines.append(f"constraint {pred}([{coefs}], [{vars_}], {_num(con.rhs)});")
    sense = "maximize" if flat.sense == "maximize" else "minimize"
    obj_coef = ", ".join(_num(flat.objective.get(var.key, 0.0)) for var in flat.variables)
    obj_vars = ", ".join(names[var.key] for var in flat.variables)
    lines.append(f"var -1.0e30..1.0e30: axiom_obj;")
    pred = "float_lin_eq" if any(var.domain == "continuous" for var in flat.variables) else "int_lin_eq"
    lines.append(f"constraint {pred}([{obj_coef}, -1], [{obj_vars}, axiom_obj], {_num(-flat.objective_const)});")
    lines.append(f"solve {sense} axiom_obj;")
    lines.append("")
    return "\n".join(lines)


def read_flatzinc(text: str) -> Model:
    model = Model(name="imported_fzn")
    sense = "minimize"
    objective_name = None
    for raw in text.splitlines():
        line = raw.split("%", 1)[0].strip()
        if not line:
            continue
        if line.startswith("var "):
            body = line[4:].rstrip(";")
            domain, name = body.split(":")
            name = name.strip()
            if ".." in domain:
                lo, hi = domain.split("..", 1)
                lower = _maybe_float(lo.strip())
                upper = _maybe_float(hi.strip())
            else:
                lower = upper = None
            kind = "integer" if re.fullmatch(r"-?\d+", lo.strip()) and re.fullmatch(r"-?\d+", hi.strip()) else "continuous"
            if kind == "integer" and lower == 0 and upper == 1:
                kind = "binary"
            model.variables[name] = VarDecl(name=name, domain=kind, lower=lower, upper=upper)  # type: ignore[arg-type]
        elif line.startswith("constraint "):
            call = line[len("constraint ") :].rstrip(";")
            pred, rest = call.split("(", 1)
            args = _split_args(rest[:-1])
            if pred in {"int_lin_le", "float_lin_le", "int_lin_eq", "float_lin_eq"} and len(args) == 3:
                coefs = _bracket_floats(args[0])
                vars_ = _bracket_names(args[1])
                rhs = float(args[2])
                relation = "==" if pred.endswith("_eq") else "<="
                coef = {name: coefs[i] for i, name in enumerate(vars_) if abs(coefs[i]) > 1e-15}
                model.constraints.append(Constraint(name=f"c{len(model.constraints) + 1}", kind="comparison", relation=relation, lhs=_coef(coef, 0.0), rhs=const(rhs)))  # type: ignore[arg-type]
        elif line.startswith("solve "):
            parts = line.rstrip(";").split()
            if len(parts) >= 3:
                sense = "maximize" if parts[1] == "maximize" else "minimize"
                objective_name = parts[2]
    if objective_name and objective_name in model.variables:
        # The generated file defines axiom_obj by an equality. Pull that row out as the objective.
        kept = []
        expr = ref(objective_name)
        for con in model.constraints:
            if _uses_only(con, objective_name) and con.relation == "==":
                expr = _objective_from_eq(con, objective_name)
                continue
            kept.append(con)
        model.constraints = [con for con in kept if objective_name not in _names_in(con.lhs)]
        model.objectives.append(Objective(name="obj", sense=sense, expr=expr))  # type: ignore[arg-type]
        model.variables.pop(objective_name, None)
    elif not model.objectives:
        model.objectives.append(Objective(name="obj", sense=sense, expr=const(0)))  # type: ignore[arg-type]
    return model


def read_minizinc(text: str) -> Model:
    model = Model(name="imported_mzn")
    sense = "minimize"
    obj = const(0)
    for raw in text.splitlines():
        line = raw.split("%", 1)[0].strip()
        if not line or line.startswith("include"):
            continue
        if line.startswith("var "):
            body = line[4:].rstrip(";")
            domain, name = body.split(":")
            name = name.strip()
            lo, hi = domain.split("..")
            lower, upper = _maybe_float(lo.strip()), _maybe_float(hi.strip())
            kind = "integer" if _integer_range(lo, hi) else "continuous"
            if kind == "integer" and lower == 0 and upper == 1:
                kind = "binary"
            model.variables[name] = VarDecl(name=name, domain=kind, lower=lower, upper=upper)  # type: ignore[arg-type]
        elif line.startswith("constraint "):
            body = line[len("constraint ") :].rstrip(";")
            relation, lhs, rhs = _split_rel(body)
            model.constraints.append(Constraint(name=f"c{len(model.constraints) + 1}", kind="comparison", relation=relation, lhs=_parse_linear_expr(lhs), rhs=_parse_linear_expr(rhs)))  # type: ignore[arg-type]
        elif line.startswith("solve "):
            parts = line.rstrip(";").split(None, 2)
            sense = "maximize" if len(parts) > 1 and parts[1] == "maximize" else "minimize"
            obj = _parse_linear_expr(parts[2]) if len(parts) > 2 else const(0)
    model.objectives.append(Objective(name="obj", sense=sense, expr=obj))  # type: ignore[arg-type]
    return model


def _local(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return node.tag.rsplit("}", 1)[-1]


def _safe(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "()_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    return cleaned[:60]


def _mz(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    return cleaned


def _num(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return format(float(value), ".12g")


def _float_bound(value: float | None, missing: str) -> str:
    """MiniZinc treats `0..10` as an integer domain. Continuous bounds stay floats."""
    if value is None:
        return missing
    text = _num(float(value))
    if "." not in text and "e" not in text.lower():
        return text + ".0"
    return text


def _integer_range(lower: str, upper: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", lower.strip()) and re.fullmatch(r"-?\d+", upper.strip()))


def _coef(coeffs: dict[str, float], constant: float) -> Expr:
    terms: list[Expr] = []
    if abs(constant) > 1e-15:
        terms.append(const(constant))
    for key, coef in coeffs.items():
        if abs(coef) < 1e-15:
            continue
        piece: Expr = ref(key)
        if abs(coef - 1) > 1e-12:
            piece = Expr(op="mul", args=(const(coef), piece))
        terms.append(piece)
    return _sum_expr(terms)


def _sum_expr(terms: list[Expr]) -> Expr:
    if not terms:
        return const(0)
    expr = terms[0]
    for term in terms[1:]:
        expr = Expr(op="add", args=(expr, term))
    return expr


def _mz_expr(coeffs: dict[str, float], names: dict[str, str]) -> str:
    parts = []
    for key, coef in coeffs.items():
        if abs(coef) < 1e-15:
            continue
        name = names[key]
        parts.append(name if abs(coef - 1) < 1e-12 else f"({_num(coef)}) * {name}")
    return " + ".join(parts) if parts else "0"


def _maybe_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _split_args(text: str) -> list[str]:
    parts, buf, depth = [], [], 0
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _bracket_floats(text: str) -> list[float]:
    body = text.strip()[1:-1]
    if not body.strip():
        return []
    return [float(part) for part in body.split(",")]


def _bracket_names(text: str) -> list[str]:
    body = text.strip()[1:-1]
    if not body.strip():
        return []
    return [part.strip() for part in body.split(",")]


def _uses_only(con: Constraint, name: str) -> bool:
    return name in _names_in(con.lhs)


def _names_in(expr: Expr | None) -> set[str]:
    if expr is None:
        return set()
    found = set()
    if expr.op == "ref" and expr.name:
        found.add(expr.name)
    for arg in expr.args:
        found |= _names_in(arg)
    return found


def _objective_from_eq(con: Constraint, obj_name: str) -> Expr:
    # coef·x - axiom_obj = rhs  => axiom_obj = coef·x - rhs
    coef, constant = _collect(con.lhs)
    rhs_coef, rhs_const = _collect(con.rhs)
    for key, value in rhs_coef.items():
        coef[key] = coef.get(key, 0.0) - value
    constant -= rhs_const
    obj_coef = coef.pop(obj_name, -1.0)
    scale = -1.0 / obj_coef if abs(obj_coef) > 1e-12 else 1.0
    return _coef({key: value * scale for key, value in coef.items()}, constant * scale)


def _collect(expr: Expr | None) -> tuple[dict[str, float], float]:
    if expr is None:
        return {}, 0.0
    if expr.op == "const":
        return {}, float(expr.value or 0.0)
    if expr.op == "ref":
        return {expr.name or "x": 1.0}, 0.0
    if expr.op == "neg":
        coef, constant = _collect(expr.args[0])
        return {key: -value for key, value in coef.items()}, -constant
    if expr.op in {"add", "sub"}:
        left, left_c = _collect(expr.args[0])
        right, right_c = _collect(expr.args[1])
        sign = 1.0 if expr.op == "add" else -1.0
        merged = dict(left)
        for key, value in right.items():
            merged[key] = merged.get(key, 0.0) + sign * value
        return merged, left_c + sign * right_c
    if expr.op == "mul":
        left, left_c = _collect(expr.args[0])
        right, right_c = _collect(expr.args[1])
        if not left and not right:
            return {}, left_c * right_c
        if not left:
            return {key: value * left_c for key, value in right.items()}, left_c * right_c
        if not right:
            return {key: value * right_c for key, value in left.items()}, left_c * right_c
    return {}, 0.0


def _split_rel(body: str) -> tuple[str, str, str]:
    for symbol, relation in (("<=", "<="), (">=", ">="), ("=", "==")):
        if symbol in body:
            left, right = body.split(symbol, 1)
            return relation, left.strip(), right.strip()
    raise AxiomError(f"无法识别约束：{body}", f"Could not read constraint: {body}", code="import")


def _parse_linear_expr(text: str) -> Expr:
    tokens = text.replace("+", " + ").replace("-", " - ").split()
    coef: dict[str, float] = {}
    constant = 0.0
    sign = 1.0
    pending = None
    for token in tokens:
        if token == "+":
            sign = 1.0
            continue
        if token == "-":
            sign = -1.0
            continue
        if token in {"*", "/"}:
            continue
        try:
            number = float(token.strip("()"))
        except ValueError:
            number = None
        if number is not None and pending is None:
            pending = sign * number
            sign = 1.0
            continue
        if number is None:
            value = sign if pending is None else pending
            coef[token] = coef.get(token, 0.0) + value
            pending = None
            sign = 1.0
            continue
        constant += sign * number
        sign = 1.0
    if pending is not None:
        constant += pending
    return _coef(coef, constant)


def read_model(fmt: str, text: str) -> Model:
    key = fmt.lower().strip().lstrip(".")
    if key == "py":
        from axiom.modeling.libraries import import_library, sniff_python

        return import_library(sniff_python(text), text)
    if key in {"mod", "model"}:
        from axiom.modeling.libraries import import_library

        if re.search(r"(?m)^\s*dvar\b", text):
            return import_library("opl", text)
        if re.search(r"(?m)^\s*subto\b", text):
            return import_library("zimpl", text)
        return import_library("ampl", text)
    if key in {"lp", "txt"}:
        return read_lp(text)
    if key in {"mps", "mps-free"}:
        return read_mps(text)
    if key == "qps":
        return read_qps(text)
    if key == "nl":
        return read_nl(text)
    if key in {"osil", "xml"}:
        return read_osil(text)
    if key == "cbf":
        return read_cbf(text)
    if key in {"sdpa", "dat-s"}:
        return read_sdpa(text)
    if key in {"fzn", "flatzinc"}:
        return read_flatzinc(text)
    if key in {"mzn", "minizinc"}:
        return read_minizinc(text)
    if key in {"aml", "axiom"}:
        from axiom.modeling import parse_aml

        return parse_aml(text)
    from axiom.modeling.libraries import import_library

    return import_library(key, text)
