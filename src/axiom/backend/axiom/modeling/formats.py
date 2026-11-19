"""CPLEX LP and free MPS writers and importers.

The flat linear form is the source for export. Importers rebuild a scalar
Axiom model so a file can be solved again or rewritten as AML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from axiom.errors import AxiomError
from axiom.modeling.flatten import FlatModel, flatten
from axiom.modeling.ir import Constraint, Expr, Model, Objective, VarDecl, const, ref


def write_lp(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    if flat.nonlinear:
        raise AxiomError(
            "LP 格式只能表示线性模型。",
            "LP format can only represent linear models.",
            code="nonlinear",
        )
    names = _names(flat)
    lines = [f"\\ Axiom {flat.name}", "Maximize" if flat.sense == "maximize" else "Minimize"]
    lines.append(" obj: " + _expr(flat.objective, names, flat.objective_const))
    lines.append("Subject To")
    if not flat.constraints and flat.variables:
        lines.append(f" __redundant: 0 {names[flat.variables[0].key]} <= 1")
    for con in flat.constraints:
        lines.append(f" {names.get(con.key, _clean(con.key, set()))}: " + _expr(con.coeffs, names) + f" {con.sense if con.sense != '==' else '='} {_num(con.rhs)}")
    lines.append("Bounds")
    binaries, generals = [], []
    for var in flat.variables:
        name = names[var.key]
        lines.append(_bound(name, var.lower, var.upper))
        if var.domain == "binary":
            binaries.append(name)
        elif var.domain == "integer":
            generals.append(name)
    if generals:
        lines.append("General")
        lines.extend(f" {name}" for name in generals)
    if binaries:
        lines.append("Binary")
        lines.extend(f" {name}" for name in binaries)
    lines.append("End")
    lines.append("")
    return "\n".join(lines)


def write_mps(model: Model | FlatModel) -> str:
    flat = model if isinstance(model, FlatModel) else flatten(model)
    if flat.nonlinear:
        raise AxiomError(
            "MPS 格式只能表示线性模型。",
            "MPS format can only represent linear models.",
            code="nonlinear",
        )
    names = _names(flat)
    rows = ["NAME          " + _clean(flat.name, set())[:12], "OBJSENSE", " MAX" if flat.sense == "maximize" else " MIN", "ROWS", " N  OBJ"]
    for con in flat.constraints:
        kind = {"<=": "L", ">=": "G", "==": "E"}[con.sense]
        rows.append(f" {kind}  {names[con.key]}")
    rows.append("COLUMNS")
    if abs(flat.objective_const) > 1e-12:
        rows.append(f"    CONST OBJ {_num(flat.objective_const)}")
    columns: dict[str, list[tuple[str, float]]] = {names[var.key]: [] for var in flat.variables}
    for key, coef in flat.objective.items():
        if abs(coef) > 1e-12:
            columns[names[key]].append(("OBJ", coef))
    for con in flat.constraints:
        for key, coef in con.coeffs.items():
            if abs(coef) > 1e-12:
                columns[names[key]].append((names[con.key], coef))
    for name, entries in columns.items():
        if not entries:
            rows.append(f"    {name} OBJ 0")
            continue
        for row_name, coef in entries:
            rows.append(f"    {name} {row_name} {_num(coef)}")
    rows.append("RHS")
    for con in flat.constraints:
        if abs(con.rhs) > 1e-12:
            rows.append(f"    RHS {names[con.key]} {_num(con.rhs)}")
    rows.append("BOUNDS")
    if abs(flat.objective_const) > 1e-12:
        rows.append(" FX BND CONST 1")
    for var in flat.variables:
        name = names[var.key]
        if var.domain == "binary":
            rows.append(f" BV BND {name}")
            continue
        if var.lower is None and var.upper is None:
            rows.append(f" FR BND {name}")
        else:
            if var.lower is None and var.domain == "continuous":
                rows.append(f" MI BND {name}")
            if var.lower is not None:
                kind = "LI" if var.domain == "integer" else "LO"
                rows.append(f" {kind} BND {name} {_num(var.lower)}")
            if var.upper is not None:
                kind = "UI" if var.domain == "integer" else "UP"
                rows.append(f" {kind} BND {name} {_num(var.upper)}")
            if var.domain == "integer" and var.lower is None:
                rows.append(f" LI BND {name} -1000000")
            if var.domain == "integer" and var.upper is None:
                rows.append(f" UI BND {name} 1000000")
    rows.append("ENDATA")
    rows.append("")
    return "\n".join(rows)


def read_lp(text: str) -> Model:
    section = "none"
    sense = "minimize"
    objective: dict[str, float] = {}
    objective_const = 0.0
    constraints: list[tuple[str, dict[str, float], str, float]] = []
    bounds: dict[str, list] = {}
    integers: set[str] = set()
    binaries: set[str] = set()
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("\\", 1)[0].strip()
        if not line:
            continue
        lower = line.lower()
        if lower in {"end"}:
            break
        if lower in {"maximize", "maximum", "max"}:
            section = "obj"
            sense = "maximize"
            continue
        if lower in {"minimize", "minimum", "min"}:
            section = "obj"
            sense = "minimize"
            continue
        if lower in {"subject to", "subject", "st", "s.t.", "such that"}:
            section = "con"
            continue
        if lower == "bounds":
            section = "bounds"
            continue
        if lower in {"binary", "binaries"}:
            section = "binary"
            continue
        if lower in {"general", "generals", "integer"}:
            section = "general"
            continue
        if section == "obj":
            body = _after_colon(line)
            coef, constant = _parse_linear(body)
            objective = coef
            objective_const = constant
            names.update(coef)
        elif section == "con":
            name, body = "c", line
            if ":" in line.split("<=")[0].split(">=")[0].split("=")[0]:
                name, body = line.split(":", 1)
                name = name.strip()
            relation, expr, rhs = _split_relation(body)
            coef, constant = _parse_linear(expr)
            constraints.append((name, coef, relation, rhs - constant))
            names.update(coef)
        elif section == "bounds":
            _parse_bound(line, bounds, names)
        elif section == "binary":
            for token in line.split():
                binaries.add(token)
                names.add(token)
        elif section == "general":
            for token in line.split():
                integers.add(token)
                names.add(token)
    model = Model(name="imported_lp")
    if "__one" in names or not names:
        pass
    for name in sorted(names):
        if name.startswith("__"):
            continue
        lower, upper = bounds.get(name, [None, None])
        domain = "binary" if name in binaries else "integer" if name in integers else "continuous"
        if domain == "binary":
            lower = 0.0 if lower is None else lower
            upper = 1.0 if upper is None else upper
        model.variables[name] = VarDecl(name=name, domain=domain, lower=lower, upper=upper)  # type: ignore[arg-type]
    expr = _coef_expr(objective, objective_const)
    model.objectives.append(Objective(name="obj", sense=sense, expr=expr))  # type: ignore[arg-type]
    for index, (name, coef, relation, rhs) in enumerate(constraints, start=1):
        cname = name if name and not name.startswith("__") else f"c{index}"
        if cname in {con.name for con in model.constraints}:
            cname = f"{cname}_{index}"
        model.constraints.append(
            Constraint(
                name=cname,
                kind="comparison",
                relation=relation,  # type: ignore[arg-type]
                lhs=_coef_expr(coef, 0.0),
                rhs=const(rhs),
            )
        )
    return model


def read_mps(text: str) -> Model:
    section = "none"
    sense = "minimize"
    rows: dict[str, str] = {}
    columns: dict[str, dict[str, float]] = {}
    rhs: dict[str, float] = {}
    bounds: dict[str, list] = {}
    integers: set[str] = set()
    binaries: set[str] = set()
    section_integer = False
    free_columns: set[str] = set()
    lower_set: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        parts_head = line.split()
        head = parts_head[0].upper()
        # Data rows in the RHS section also start with the vector name "RHS",
        # so a section keyword only wins when it occupies the line by itself
        # (NAME may carry the problem title).
        if head in {"NAME", "ROWS", "COLUMNS", "RHS", "BOUNDS", "RANGES", "OBJSENSE", "ENDATA"} and (
            len(parts_head) == 1 or head == "NAME"
        ):
            section = "objsense" if head == "OBJSENSE" else head.lower()
            if head == "ENDATA":
                break
            continue
        if section == "objsense":
            if head == "MAX":
                sense = "maximize"
            elif head == "MIN":
                sense = "minimize"
            continue
        parts = line.split()
        if section == "rows" and len(parts) >= 2:
            rows[parts[1]] = parts[0].upper()
        elif section == "columns" and len(parts) >= 3:
            token = parts[1].strip("'\"")
            marker = parts[2].strip("'\"") if len(parts) >= 3 else ""
            if token.upper() == "MARKER":
                if marker.upper() == "INTORG":
                    section_integer = True
                elif marker.upper() == "INTEND":
                    section_integer = False
                continue
            col, row_name, value = parts[0], parts[1], float(parts[2])
            columns.setdefault(col, {})[row_name] = value
            if section_integer:
                integers.add(col)
            if len(parts) >= 5:
                columns[col][parts[3]] = float(parts[4])
        elif section == "rhs" and len(parts) >= 3:
            rhs[parts[1]] = float(parts[2])
            if len(parts) >= 5:
                rhs[parts[3]] = float(parts[4])
        elif section == "bounds" and len(parts) >= 3:
            kind, col = parts[0].upper(), parts[2]
            value = float(parts[3]) if len(parts) >= 4 else None
            slot = bounds.setdefault(col, [None, None])
            if kind == "LO" and value is not None:
                slot[0] = value
                lower_set.add(col)
            elif kind == "UP" and value is not None:
                slot[1] = value
            elif kind == "FX" and value is not None:
                slot[0] = slot[1] = value
                lower_set.add(col)
            elif kind == "FR":
                slot[0] = slot[1] = None
                free_columns.add(col)
            elif kind == "BV":
                binaries.add(col)
                slot[0], slot[1] = 0.0, 1.0
                lower_set.add(col)
            elif kind == "LI" and value is not None:
                integers.add(col)
                slot[0] = value
                lower_set.add(col)
            elif kind == "UI" and value is not None:
                integers.add(col)
                slot[1] = value
            elif kind == "MI":
                slot[0] = None
                free_columns.add(col)
            elif kind == "PL":
                slot[1] = None
    obj_row = next((name for name, kind in rows.items() if kind == "N"), "OBJ")
    model = Model(name="imported_mps")
    obj_coef: dict[str, float] = {}
    obj_const = 0.0
    for col, entries in columns.items():
        if col == "CONST":
            obj_const += entries.get(obj_row, 0.0)
            continue
        lower, upper = bounds.get(col, [None, None])
        if col not in free_columns and col not in lower_set:
            lower = 0.0
        domain = "binary" if col in binaries else "integer" if col in integers else "continuous"
        model.variables[col] = VarDecl(name=col, domain=domain, lower=lower, upper=upper)  # type: ignore[arg-type]
        if obj_row in entries:
            obj_coef[col] = entries[obj_row]
    model.objectives.append(Objective(name="obj", sense=sense, expr=_coef_expr(obj_coef, obj_const)))  # type: ignore[arg-type]
    index = 1
    for row_name, kind in rows.items():
        if kind == "N":
            continue
        relation = {"L": "<=", "G": ">=", "E": "=="}.get(kind)
        if relation is None:
            continue
        coef = {col: entries[row_name] for col, entries in columns.items() if row_name in entries and col != "CONST"}
        model.constraints.append(
            Constraint(
                name=row_name or f"c{index}",
                kind="comparison",
                relation=relation,  # type: ignore[arg-type]
                lhs=_coef_expr(coef, 0.0),
                rhs=const(rhs.get(row_name, 0.0)),
            )
        )
        index += 1
    return model


def flat_names(flat: FlatModel) -> dict[str, str]:
    return _names(flat)


@dataclass
class _Scan:
    coef: dict[str, float]
    const: float


def _names(flat: FlatModel) -> dict[str, str]:
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for var in flat.variables:
        mapping[var.key] = _clean(var.key, used)
    for con in flat.constraints:
        mapping[con.key] = _clean(con.key, used)
    return mapping


def _clean(name: str, used: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    base = cleaned[:60]
    candidate = base
    number = 2
    while candidate in used:
        candidate = f"{base}_{number}"
        number += 1
    used.add(candidate)
    return candidate


def _expr(coeffs: dict[str, float], names: dict[str, str], constant: float = 0.0) -> str:
    parts = []
    first = True
    for key, coef in coeffs.items():
        if abs(coef) < 1e-12:
            continue
        name = names.get(key, key)
        mag = abs(coef)
        body = name if abs(mag - 1.0) < 1e-10 else f"{_num(mag)} {name}"
        if first:
            parts.append(body if coef > 0 else f"- {body}")
            first = False
        else:
            parts.append(f"+ {body}" if coef > 0 else f"- {body}")
    if abs(constant) > 1e-12:
        token = _num(abs(constant))
        if first:
            parts.append(token if constant > 0 else f"- {token}")
        else:
            parts.append(f"+ {token}" if constant > 0 else f"- {token}")
    if not parts:
        return "0"
    return " ".join(parts)


def _bound(name: str, lower: float | None, upper: float | None) -> str:
    if lower is None and upper is None:
        return f" {name} free"
    if lower is not None and upper is not None:
        return f" {_num(lower)} <= {name} <= {_num(upper)}"
    if lower is not None:
        return f" {name} >= {_num(lower)}"
    return f" {name} <= {_num(upper)}"


def _num(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return format(float(value), ".12g")


def _after_colon(line: str) -> str:
    return line.split(":", 1)[1] if ":" in line else line


def _split_relation(body: str) -> tuple[str, str, float]:
    for symbol, relation in (("<=", "<="), (">=", ">="), ("=", "==")):
        if symbol in body:
            left, right = body.split(symbol, 1)
            return relation, left, float(right.strip())
    raise AxiomError(
        f"约束缺少比较符：{body}",
        f"Constraint is missing a relation: {body}",
        code="import",
    )


def _parse_bound(line: str, bounds: dict[str, list], names: set[str]) -> None:
    if "free" in line.lower():
        name = line.split()[0]
        bounds[name] = [None, None]
        names.add(name)
        return
    # a <= name <= b | name >= a | name <= b | a <= name
    if line.count("<=") == 2:
        left, name, right = re.split(r"\s*<=\s*", line)
        bounds[name.strip()] = [float(left), float(right)]
        names.add(name.strip())
        return
    if "<=" in line:
        left, right = [part.strip() for part in line.split("<=", 1)]
        if _is_number(left):
            bounds.setdefault(right, [None, None])[0] = float(left)
            names.add(right)
        else:
            bounds.setdefault(left, [None, None])[1] = float(right)
            names.add(left)
        return
    if ">=" in line:
        left, right = [part.strip() for part in line.split(">=", 1)]
        bounds.setdefault(left, [None, None])[0] = float(right)
        names.add(left)


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _parse_linear(expr: str) -> tuple[dict[str, float], float]:
    source = expr.strip()
    index = 0
    sign = 1.0
    expect_sign = False
    coeffs: dict[str, float] = {}
    constant = 0.0
    while index < len(source):
        while index < len(source) and source[index].isspace():
            index += 1
        if index >= len(source):
            break
        if source[index] in "+-":
            sign = 1.0 if source[index] == "+" else -1.0
            expect_sign = False
            index += 1
            continue
        if expect_sign:
            break
        number = re.match(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", source[index:])
        coef = None
        name = None
        if number:
            coef = float(number.group())
            index += number.end()
            while index < len(source) and source[index].isspace():
                index += 1
            ident = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[index:])
            if ident:
                name = ident.group()
                index += ident.end()
        else:
            ident = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[index:])
            if not ident:
                break
            name = ident.group()
            coef = 1.0
            index += ident.end()
        if name:
            coeffs[name] = coeffs.get(name, 0.0) + sign * float(coef)
        else:
            constant += sign * float(coef or 0.0)
        sign = 1.0
        expect_sign = True
    return coeffs, constant


def _coef_expr(coeffs: dict[str, float], constant: float) -> Expr:
    expr: Expr | None = None
    for name, coef in coeffs.items():
        term: Expr = ref(name) if abs(coef - 1.0) < 1e-12 else Expr(op="mul", args=(const(coef), ref(name)))
        expr = term if expr is None else Expr(op="add", args=(expr, term))
    if abs(constant) > 1e-12:
        term = const(constant)
        expr = term if expr is None else Expr(op="add", args=(expr, term))
    return expr or const(0.0)
