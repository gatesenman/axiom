"""Pretty-printer from the IR back to Axiom Modeling Language."""

from __future__ import annotations

from axiom.modeling.ir import Constraint, Expr, Index, Model, Quantifier


def emit_aml(model: Model) -> str:
    lines: list[str] = []
    for key, value in model.meta.items():
        lines.append(f"#@ {key}: {value}")
    if model.name:
        lines.append(f"model {model.name};")
    for decl in model.sets.values():
        if _is_int_range(decl.elements):
            body = f"{decl.elements[0]}..{decl.elements[-1]}"
        else:
            body = "{ " + ", ".join(_element(item) for item in decl.elements) + " }"
        lines.append(f"set {decl.name} := {body};")
    for decl in model.parameters.values():
        index = _index_decl(decl.index_sets)
        default = "" if decl.default is None else f" default {_num(decl.default)}"
        if not decl.index_sets:
            value = _num(decl.values.get((), decl.default or 0.0))
            lines.append(f"param {decl.name}{default} := {value};")
        else:
            entries = []
            for key, value in decl.values.items():
                rendered = _element(key[0]) if len(key) == 1 else "(" + ", ".join(_element(part) for part in key) + ")"
                entries.append(f"{rendered}: {_num(value)}")
            table = "{ " + ", ".join(entries) + " }"
            lines.append(f"param {decl.name}{index}{default} := {table};")
    for decl in model.variables.values():
        parts = [f"var {decl.name}{_index_decl(decl.index_sets)}"]
        if decl.domain == "binary":
            parts.append("binary")
        elif decl.domain == "integer":
            parts.append("integer")
        if decl.domain != "binary" or decl.lower not in (None, 0):
            if decl.lower is not None and not (decl.domain == "binary" and decl.lower == 0):
                parts.append(f">= {_num(decl.lower)}")
        if decl.upper is not None and not (decl.domain == "binary" and decl.upper == 1):
            parts.append(f"<= {_num(decl.upper)}")
        if decl.domain == "binary" and decl.lower == 0 and parts[-1] != "binary":
            pass
        lines.append(" ".join(parts) + ";")
    for obj in model.objectives:
        lines.append(f"{obj.sense} {obj.name}: {_expr(obj.expr)};")
    for con in model.constraints:
        lines.append(_constraint(con))
    for obj in model.objectives:
        if abs(obj.weight - 1.0) > 1e-12:
            lines.append(f"weight {obj.name} {_num(obj.weight)};")
    for sos in model.sos:
        lines.append(f"sos1 {sos.name}: {', '.join(sos.members)};")
    for piece in model.pieces:
        points = ", ".join(f"({_num(x)}, {_num(y)})" for x, y in piece.points)
        lines.append(f"piecewise {piece.name} on {piece.variable}: {points};")
    return "\n".join(lines) + "\n"


def _constraint(con: Constraint) -> str:
    quant = _quant_decl(con.quants)
    if con.kind == "alldiff" and con.alldiff_ref is not None:
        inner = ", ".join(f"{q.index} in {q.set_name}" for q in con.alldiff_quants)
        return f"subject to {con.name}{quant}: alldiff {{{inner}}} {_expr(con.alldiff_ref)};"
    return (
        f"subject to {con.name}{quant}: {_expr(con.lhs)} {con.relation} {_expr(con.rhs)};"
        if con.lhs is not None and con.rhs is not None
        else f"subject to {con.name};"
    )


def _expr(expr: Expr) -> str:
    if expr.op == "const":
        return _num(float(expr.value or 0.0))
    if expr.op == "ref":
        if not expr.indices:
            return expr.name or "0"
        return f"{expr.name}[{', '.join(_index(index) for index in expr.indices)}]"
    if expr.op == "neg":
        return f"(-{_expr(expr.args[0])})"
    if expr.op == "sum":
        quants = ", ".join(f"{q.index} in {q.set_name}" for q in expr.quants)
        return f"(sum {{{quants}}} {_expr(expr.args[0])})"
    symbol = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^"}[expr.op]
    return f"({_expr(expr.args[0])} {symbol} {_expr(expr.args[1])})"


def _index(index: Index) -> str:
    if index.kind == "literal":
        return _element(index.value)
    if index.kind == "symbol":
        return index.value
    if index.kind == "prev":
        return f"prev({index.value})"
    if index.offset < 0:
        return f"{index.value}-{-index.offset}"
    return f"{index.value}+{index.offset}"


def _quant_decl(quants: tuple[Quantifier, ...]) -> str:
    if not quants:
        return ""
    body = ", ".join(f"{q.index} in {q.set_name}" for q in quants)
    return f"[{body}]"


def _index_decl(names: list[str]) -> str:
    if not names:
        return ""
    return "[" + ", ".join(names) + "]"


def _element(value: str) -> str:
    if value.isidentifier() or _is_int_text(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _num(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".12g")


def _is_int_text(value: str) -> bool:
    token = value[1:] if value.startswith("-") else value
    return token.isdigit()


def _is_int_range(elements: list[str]) -> bool:
    if len(elements) < 2 or not all(_is_int_text(item) for item in elements):
        return False
    numbers = [int(item) for item in elements]
    return numbers == list(range(numbers[0], numbers[-1] + 1))
