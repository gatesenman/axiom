"""Standard mathematical form of an Axiom model.

Every solve starts from this view: a compact matrix statement, the expanded
equations tied back to constraint names, and, for linear models, the classic
equality form with nonnegative slack and surplus variables.
"""

from __future__ import annotations

import html
from typing import Any

from axiom.errors import AxiomError
from axiom.modeling.flatten import FlatCon, FlatModel, FlatVar, flatten
from axiom.modeling.ir import Expr, Model, var_key


def standard_form(model: Model) -> dict[str, Any]:
    """Build the standard-form payload. Raises ``AxiomError`` when it cannot."""
    try:
        flat = flatten(model)
    except AxiomError:
        raise
    except Exception as exc:
        raise AxiomError(
            f"无法生成标准方程：{exc}",
            f"Could not build standard equations: {exc}",
            code="standard_form",
        ) from exc
    if flat.nonlinear:
        return _nonlinear(model, flat)
    return _linear(model, flat)


def _linear(model: Model, flat: FlatModel) -> dict[str, Any]:
    variables = list(flat.variables)
    order = [var.key for var in variables]
    integers = [var.key for var in variables if var.domain == "integer"]
    binaries = [var.key for var in variables if var.domain == "binary"]
    rows = [_row(con, order) for con in flat.constraints]
    c = {key: float(flat.objective.get(key, 0.0)) for key in order}
    bounds = [_bound(var) for var in variables]
    kind = "milp" if integers or binaries else "lp"
    equations = [_objective_equation(flat, model)]
    equations.extend(_constraint_equation(row) for row in rows)
    equations.extend(_bound_equation(var) for var in variables)
    if integers:
        equations.append(_set_equation("integers", integers, r"\mathbb{Z}", "integer"))
    if binaries:
        equations.append(_set_equation("binaries", binaries, r"\{0,1\}", "binary"))
    indexed = _indexed_templates(model)
    canonical = _canonical(flat, variables)
    compact_latex = _compact_latex(flat.sense, rows, variables, integers, binaries)
    parts_latex = [compact_latex, _aligned([item["latex"] for item in equations if item["latex"]])]
    if canonical["applicable"]:
        parts_latex.append(canonical["latex"])
    plain = _plain_document(flat, equations, canonical, kind)
    plain_en = _plain_document(flat, equations, canonical, kind, english=True)
    payload = {
        "ok": True,
        "kind": kind,
        "sense": flat.sense,
        "name": flat.name,
        "objective_name": model.objectives[0].name if model.objectives else "",
        "c": {key: value for key, value in c.items() if abs(value) > 1e-12},
        "c_full": c,
        "constant": flat.objective_const,
        "rows": rows,
        "bounds": bounds,
        "integers": integers,
        "binaries": binaries,
        "variables": order,
        "equations": equations,
        "indexed": indexed,
        "maps": [
            {"equation_id": item["id"], "constraint": item["constraint"], "key": item["key"]}
            for item in equations
            if item.get("constraint")
        ],
        "canonical": canonical,
        "matrix_latex": compact_latex,
        "latex": "\n\n".join(part for part in parts_latex if part),
        "plain": plain,
        "plain_en": plain_en,
        "mathml": _math(_mtable([item["mathml_inner"] for item in equations])),
    }
    return payload


def _nonlinear(model: Model, flat: FlatModel) -> dict[str, Any]:
    equations: list[dict[str, Any]] = []
    for obj in model.objectives:
        latex = f"{_sense_word(obj.sense)} {expr_latex(obj.expr)}"
        plain = f"{obj.sense} {obj.name}: {expr_plain(obj.expr)}"
        equations.append(
            {
                "id": f"obj:{obj.name}",
                "role": "objective",
                "name": obj.name,
                "constraint": None,
                "key": obj.name,
                "indices": [],
                "latex": latex,
                "plain": plain,
                "mathml": _math(expr_mathml(obj.expr)),
                "mathml_inner": expr_mathml(obj.expr),
            }
        )
    for con in model.constraints:
        if con.kind == "alldiff":
            latex = rf"\operatorname{{alldiff}}({expr_latex(con.alldiff_ref) if con.alldiff_ref else con.name})"
            plain = f"{con.name}: alldiff"
            inner = f"<mrow><mi>alldiff</mi><mo>(</mo><mi>{html.escape(con.name)}</mi><mo>)</mo></mrow>"
            constraint = con.name
        else:
            latex = f"{expr_latex(con.lhs) if con.lhs else ''} {_rel_tex(con.relation or '==')} {expr_latex(con.rhs) if con.rhs else ''}"
            plain = f"{con.name}: {expr_plain(con.lhs) if con.lhs else ''} {_rel_plain(con.relation or '==')} {expr_plain(con.rhs) if con.rhs else ''}"
            inner = "<mrow>" + (expr_mathml(con.lhs) if con.lhs else "") + _mo(_rel_char(con.relation or "==")) + (expr_mathml(con.rhs) if con.rhs else "") + "</mrow>"
            constraint = con.name
        quant = ", ".join(f"{q.index} \\in {q.set_name}" for q in con.quants)
        if quant:
            latex = rf"\forall {quant}:\ {latex}"
        equations.append(
            {
                "id": con.name,
                "role": "constraint",
                "name": con.name,
                "constraint": constraint,
                "key": con.name,
                "indices": [],
                "latex": latex,
                "plain": plain,
                "mathml": _math(inner),
                "mathml_inner": inner,
            }
        )
    note_zh = "非线性模型写成 min/max f(x)，约束写成 g(x) ≤ 0、h(x) = 0 的形式。经典的松弛等式标准形只适用于线性模型，这里不生成。"
    note_en = "A nonlinear model is written as min/max f(x) with constraints g(x) ≤ 0 and h(x) = 0. The classic slack equality form applies only to linear models and is omitted."
    canonical = {"applicable": False, "note_zh": note_zh, "note_en": note_en, "equations": [], "nonnegative": [], "latex": "", "plain": note_zh, "plain_en": note_en}
    compact = rf"{_sense_word(flat.sense)}\ f(x)"
    if any(con.kind == "comparison" for con in model.constraints):
        compact += r"\\ \mathrm{s.t.}\quad g(x)\le 0,\ h(x)=0"
    plain = _join_plain("nonlinear program  /  非线性规划", [item["plain"] for item in equations], note_zh)
    plain_en = _join_plain("nonlinear program", [item["plain"] for item in equations], note_en)
    return {
        "ok": True,
        "kind": "nlp",
        "sense": flat.sense,
        "name": model.name,
        "objective_name": model.objectives[0].name if model.objectives else "",
        "c": {},
        "c_full": {},
        "constant": 0.0,
        "rows": [],
        "bounds": [_bound_decl(model, name) for name in model.variables],
        "integers": [],
        "binaries": [],
        "variables": list(model.variables),
        "equations": equations,
        "indexed": [],
        "maps": [{"equation_id": item["id"], "constraint": item["constraint"], "key": item["key"]} for item in equations if item.get("constraint")],
        "canonical": canonical,
        "matrix_latex": compact,
        "latex": compact + "\n\n" + _aligned([item["latex"] for item in equations]),
        "plain": plain,
        "plain_en": plain_en,
        "mathml": _math(_mtable([item["mathml_inner"] for item in equations])),
    }


def _row(con: FlatCon, order: list[str]) -> dict[str, Any]:
    coeffs = {key: float(con.coeffs.get(key, 0.0)) for key in order if abs(con.coeffs.get(key, 0.0)) > 1e-12}
    for key, value in con.coeffs.items():
        if key not in coeffs and abs(value) > 1e-12:
            coeffs[key] = float(value)
    return {
        "id": con.key,
        "key": con.key,
        "name": con.name,
        "indices": list(con.indices),
        "sense": con.sense,
        "rhs": float(con.rhs),
        "coeffs": coeffs,
    }


def _bound(var: FlatVar) -> dict[str, Any]:
    return {"key": var.key, "domain": var.domain, "lower": var.lower, "upper": var.upper}


def _bound_decl(model: Model, name: str) -> dict[str, Any]:
    var = model.variables[name]
    return {"key": name, "domain": var.domain, "lower": var.lower, "upper": var.upper}


def _objective_equation(flat: FlatModel, model: Model) -> dict[str, Any]:
    name = model.objectives[0].name if model.objectives else "objective"
    terms = [(key, value) for key, value in flat.objective.items() if abs(value) > 1e-12]
    latex = f"{_sense_word(flat.sense)} {_lin_latex(terms, flat.objective_const)}"
    plain = f"{flat.sense} {name}: {_lin_plain(terms, flat.objective_const)}"
    inner = "<mrow>" + _sense_mathml(flat.sense) + _lin_mathml(terms, flat.objective_const) + "</mrow>"
    return {
        "id": f"obj:{name}",
        "role": "objective",
        "name": name,
        "constraint": None,
        "key": name,
        "indices": [],
        "latex": latex,
        "plain": plain,
        "mathml": _math(inner),
        "mathml_inner": inner,
    }


def _constraint_equation(row: dict[str, Any]) -> dict[str, Any]:
    terms = list(row["coeffs"].items())
    latex = f"{_lin_latex(terms)} {_rel_tex(row['sense'])} {_fmt(row['rhs'])}"
    plain = f"{row['key']}: {_lin_plain(terms)} {_rel_plain(row['sense'])} {_fmt(row['rhs'])}"
    inner = "<mrow>" + _lin_mathml(terms) + _mo(_rel_char(row["sense"])) + f"<mn>{_fmt(row['rhs'])}</mn>" + "</mrow>"
    return {
        "id": row["key"],
        "role": "constraint",
        "name": row["name"],
        "constraint": row["name"],
        "key": row["key"],
        "indices": row["indices"],
        "latex": latex,
        "plain": plain,
        "mathml": _math(inner),
        "mathml_inner": inner,
    }


def _bound_equation(var: FlatVar) -> dict[str, Any]:
    bits = []
    plain_bits = []
    if var.lower is not None:
        bits.append(rf"{_fmt(var.lower)} \le ")
        plain_bits.append(f"{_fmt(var.lower)} <= ")
    bits.append(_latex_var(var.key))
    plain_bits.append(var.key)
    if var.upper is not None:
        bits.append(rf" \le {_fmt(var.upper)}")
        plain_bits.append(f" <= {_fmt(var.upper)}")
    if var.lower is None and var.upper is None:
        bits = [_latex_var(var.key) + r" \text{ free}"]
        plain_bits = [f"{var.key} free"]
    latex = "".join(bits)
    plain = "".join(plain_bits)
    inner = f"<mrow><mi>{html.escape(var.key)}</mi></mrow>"
    return {
        "id": f"bound:{var.key}",
        "role": "bound",
        "name": var.key,
        "constraint": None,
        "key": var.key,
        "indices": list(var.indices),
        "domain": var.domain,
        "latex": latex,
        "plain": plain,
        "mathml": _math(inner),
        "mathml_inner": inner,
    }


def _set_equation(role: str, keys: list[str], domain_tex: str, word: str) -> dict[str, Any]:
    listed = ", ".join(_latex_var(key) for key in keys)
    latex = listed + r" \in " + domain_tex
    plain = ", ".join(keys) + f" {word}"
    inner = "<mrow>" + "".join(f"<mi>{html.escape(key)}</mi>" for key in keys) + f"<mo>∈</mo><mi>{html.escape(word)}</mi></mrow>"
    return {
        "id": role,
        "role": role,
        "name": role,
        "constraint": None,
        "key": role,
        "indices": [],
        "latex": latex,
        "plain": plain,
        "mathml": _math(inner),
        "mathml_inner": inner,
    }


def _indexed_templates(model: Model) -> list[dict[str, Any]]:
    rows = []
    for con in model.constraints:
        if not con.quants or con.kind != "comparison" or con.lhs is None or con.rhs is None:
            continue
        quant = ", ".join(f"{q.index} \\in \\mathrm{{{_tex(q.set_name)}}}" for q in con.quants)
        latex = rf"\forall {quant}:\ {expr_latex(con.lhs)} {_rel_tex(con.relation or '==')} {expr_latex(con.rhs)}"
        plain = f"{con.name}[{', '.join(q.index + ' in ' + q.set_name for q in con.quants)}]: {expr_plain(con.lhs)} {_rel_plain(con.relation or '==')} {expr_plain(con.rhs)}"
        rows.append({"constraint": con.name, "latex": latex, "plain": plain})
    return rows


def _canonical(flat: FlatModel, variables: list[FlatVar]) -> dict[str, Any]:
    coeffs: dict[str, float] = {key: float(value) for key, value in flat.objective.items()}
    constant = float(flat.objective_const)
    rows: list[dict[str, Any]] = []
    for con in flat.constraints:
        rows.append(
            {
                "name": con.name,
                "key": con.key,
                "sense": con.sense,
                "rhs": float(con.rhs),
                "coeffs": {key: float(value) for key, value in con.coeffs.items()},
            }
        )
    nonnegative: list[str] = []
    used = {var.key for var in variables}
    shifts: list[dict[str, Any]] = []
    for var in variables:
        if var.lower is None:
            plus, minus = _fresh(f"{_slug(var.key)}_plus", used), _fresh(f"{_slug(var.key)}_minus", used)
            constant += _replace(coeffs, rows, var.key, {plus: 1.0, minus: -1.0}, 0.0)
            nonnegative.extend([plus, minus])
            shifts.append({"variable": var.key, "expression": f"{plus} - {minus}"})
            if var.upper is not None:
                slack = _fresh(f"s_ub_{_slug(var.key)}", used)
                rows.append(
                    {
                        "name": f"bound:{var.key}",
                        "key": f"ub:{var.key}",
                        "sense": "=",
                        "rhs": float(var.upper),
                        "coeffs": {plus: 1.0, minus: -1.0, slack: 1.0},
                        "slack": slack,
                    }
                )
                nonnegative.append(slack)
            continue
        elif var.lower < -1e-9:
            shift = float(var.lower)
            constant += _replace(coeffs, rows, var.key, {var.key: 1.0}, shift)
            nonnegative.append(var.key)
            shifts.append({"variable": var.key, "expression": f"{var.key} + ({_fmt(shift)})"})
            upper_rhs = None if var.upper is None else float(var.upper) - shift
            shifted_key = var.key
        else:
            nonnegative.append(var.key)
            upper_rhs = None if var.upper is None else float(var.upper)
            shifted_key = var.key
            if var.lower > 1e-9:
                surplus = _fresh(f"t_lb_{_slug(var.key)}", used)
                rows.append(
                    {
                        "name": f"bound:{var.key}",
                        "key": f"lb:{var.key}",
                        "sense": "=",
                        "rhs": float(var.lower),
                        "coeffs": {var.key: 1.0, surplus: -1.0},
                        "surplus": surplus,
                    }
                )
                nonnegative.append(surplus)
        if upper_rhs is not None and shifted_key is not None:
            slack = _fresh(f"s_ub_{_slug(var.key)}", used)
            rows.append(
                {
                    "name": f"bound:{var.key}",
                    "key": f"ub:{var.key}",
                    "sense": "=",
                    "rhs": upper_rhs,
                    "coeffs": {shifted_key: 1.0, slack: 1.0},
                    "slack": slack,
                }
            )
            nonnegative.append(slack)
    equalities = []
    for row in rows:
        sense = row["sense"]
        coeffs_row = dict(row["coeffs"])
        extra = None
        kind = "equality"
        if sense == "<=":
            slack = _fresh(f"s_{_slug(row['key'])}", used)
            coeffs_row[slack] = coeffs_row.get(slack, 0.0) + 1.0
            extra = slack
            kind = "slack"
            nonnegative.append(slack)
            sense = "="
        elif sense == ">=":
            surplus = _fresh(f"t_{_slug(row['key'])}", used)
            coeffs_row[surplus] = coeffs_row.get(surplus, 0.0) - 1.0
            extra = surplus
            kind = "surplus"
            nonnegative.append(surplus)
            sense = "="
        terms = [(key, value) for key, value in coeffs_row.items() if abs(value) > 1e-12]
        latex = f"{_lin_latex(terms)} = {_fmt(row['rhs'])}"
        plain = f"{_lin_plain(terms)} = {_fmt(row['rhs'])}"
        equalities.append(
            {
                "constraint": row["name"],
                "key": row["key"],
                "sense": "=",
                "rhs": row["rhs"],
                "coeffs": {key: value for key, value in coeffs_row.items() if abs(value) > 1e-12},
                "slack": extra if kind == "slack" else row.get("slack"),
                "surplus": extra if kind == "surplus" else row.get("surplus"),
                "kind": kind,
                "latex": latex,
                "plain": plain,
            }
        )
    obj_terms = [(key, value) for key, value in coeffs.items() if abs(value) > 1e-12]
    obj_latex = f"{_sense_word(flat.sense)} {_lin_latex(obj_terms, constant)}"
    nn = _dedupe(nonnegative)
    nn_latex = ", ".join(_latex_var(key) for key in nn) + r" \ge 0"
    body = [obj_latex, *[item["latex"] for item in equalities], nn_latex]
    note_zh = "经典标准形把每条不等式写成等式：≤ 增加非负松弛变量，≥ 减去非负剩余变量。有限上界同样写成等式。整数限制单独标出，不进入松弛变量。"
    note_en = "The classic form writes each inequality as an equality: ≤ adds a nonnegative slack, ≥ subtracts a nonnegative surplus. Finite upper bounds become equalities too. Integrality stays beside the equalities."
    return {
        "applicable": True,
        "note_zh": note_zh,
        "note_en": note_en,
        "shifts": shifts,
        "equations": equalities,
        "nonnegative": nn,
        "objective_latex": obj_latex,
        "latex": _aligned(body),
        "plain": "\n".join([f"{flat.sense} {_lin_plain(obj_terms, constant)}", *[item["plain"] for item in equalities], ", ".join(nn) + " >= 0"]),
        "plain_en": "\n".join([f"{flat.sense} {_lin_plain(obj_terms, constant)}", *[item["plain"] for item in equalities], ", ".join(nn) + " >= 0"]),
    }


def _replace(objective: dict[str, float], rows: list[dict[str, Any]], key: str, replacement: dict[str, float], constant: float) -> float:
    extra = 0.0
    if key in objective:
        factor = objective.pop(key)
        for name, coef in replacement.items():
            objective[name] = objective.get(name, 0.0) + factor * coef
        extra += factor * constant
    for row in rows:
        if key not in row["coeffs"]:
            continue
        factor = row["coeffs"].pop(key)
        for name, coef in replacement.items():
            row["coeffs"][name] = row["coeffs"].get(name, 0.0) + factor * coef
        row["rhs"] = float(row["rhs"]) - factor * constant
    return extra


def _compact_latex(sense: str, rows: list[dict[str, Any]], variables: list[FlatVar], integers: list[str], binaries: list[str]) -> str:
    order = [var.key for var in variables]
    lines = [rf"{_sense_word(sense)} \; c^{{\mathsf{{T}}}} x"]
    groups = [("le", r"\le", "<="), ("eq", "=", "=="), ("ge", r"\ge", ">=")]
    present = []
    for token, symbol, sense_name in groups:
        block = [row for row in rows if row["sense"] == sense_name]
        if not block:
            continue
        present.append((token, symbol, block))
        lines.append(rf"A_{{{token}}} x {symbol} b_{{{token}}}")
    lines.append(r"\ell \le x \le u")
    if integers:
        lines.append(r"x_j \in \mathbb{Z},\ j \in \mathcal{I}")
    if binaries:
        lines.append(r"x_j \in \{0,1\},\ j \in \mathcal{B}")
    blocks = [_aligned(lines)]
    for token, _symbol, block in present:
        matrix = [[_fmt_tex(row["coeffs"].get(key, 0.0)) for key in order] for row in block]
        rhs = [[_fmt_tex(row["rhs"])] for row in block]
        names = ", ".join(rf"\mathrm{{{_tex(row['key'])}}}" for row in block)
        blocks.append(
            rf"A_{{{token}}} = {_pmatrix(matrix)},\quad b_{{{token}}} = {_pmatrix(rhs)},\quad ({names})"
        )
    if integers:
        blocks.append(r"\mathcal{I} = \{" + ", ".join(_latex_var(key) for key in integers) + r"\}")
    if binaries:
        blocks.append(r"\mathcal{B} = \{" + ", ".join(_latex_var(key) for key in binaries) + r"\}")
    return "\n".join(blocks)


def _plain_document(flat: FlatModel, equations: list[dict[str, Any]], canonical: dict[str, Any], kind: str, english: bool = False) -> str:
    title = {
        "lp": "linear program" if english else "线性规划",
        "milp": "mixed-integer linear program" if english else "混合整数线性规划",
        "nlp": "nonlinear program" if english else "非线性规划",
    }[kind]
    sense = "maximize" if flat.sense == "maximize" else "minimize"
    head = f"{title}: {sense} c^T x"
    body = [item["plain"] for item in equations]
    classic = canonical.get("plain_en" if english else "plain") or ""
    label = "classic standard form" if english else "经典标准形（等式 + 非负松弛/剩余）"
    return _join_plain(head, body, f"{label}\n{classic}" if classic else "")


def _join_plain(head: str, lines: list[str], tail: str) -> str:
    chunks = [head, ""]
    chunks.extend(lines)
    if tail:
        chunks.extend(["", tail])
    return "\n".join(chunks).rstrip() + "\n"


def _aligned(lines: list[str]) -> str:
    if not lines:
        return ""
    body = r" \\ ".join(lines)
    return r"\begin{aligned} " + body + r" \end{aligned}"


def _pmatrix(rows: list[list[str]]) -> str:
    if not rows:
        return r"\begin{pmatrix}\end{pmatrix}"
    body = r" \\ ".join(" & ".join(row) for row in rows)
    return r"\begin{pmatrix} " + body + r" \end{pmatrix}"


def _lin_latex(terms: list[tuple[str, float]], const: float = 0.0) -> str:
    parts: list[str] = []
    for key, coef in terms:
        if abs(coef) <= 1e-12:
            continue
        sign = "-" if coef < 0 else "+"
        mag = abs(coef)
        body = _latex_var(key) if abs(mag - 1.0) < 1e-9 else rf"{_fmt_tex(mag)}\,{_latex_var(key)}"
        if not parts:
            parts.append(body if coef > 0 else "-" + body)
        else:
            parts.append(f" {sign} {body}")
    if abs(const) > 1e-12:
        sign = "-" if const < 0 else "+"
        chunk = _fmt_tex(abs(const))
        parts.append(chunk if not parts and const > 0 else f" {sign} {chunk}" if parts else ("-" + chunk))
    return "".join(parts) if parts else "0"


def _lin_plain(terms: list[tuple[str, float]], const: float = 0.0) -> str:
    parts: list[str] = []
    for key, coef in terms:
        if abs(coef) <= 1e-12:
            continue
        mag = abs(coef)
        body = key if abs(mag - 1.0) < 1e-9 else f"{_fmt(mag)}*{key}"
        if not parts:
            parts.append(body if coef > 0 else "-" + body)
        else:
            parts.append((" + " if coef > 0 else " - ") + body)
    if abs(const) > 1e-12:
        chunk = _fmt(abs(const))
        if not parts:
            parts.append(chunk if const > 0 else "-" + chunk)
        else:
            parts.append((" + " if const > 0 else " - ") + chunk)
    return "".join(parts) if parts else "0"


def _lin_mathml(terms: list[tuple[str, float]], const: float = 0.0) -> str:
    parts: list[str] = []
    for key, coef in terms:
        if abs(coef) <= 1e-12:
            continue
        mag = abs(coef)
        chunk = _mi_raw(key) if abs(mag - 1.0) < 1e-9 else f"<mn>{_fmt(mag)}</mn><mo>⁢</mo>{_mi_raw(key)}"
        if not parts:
            parts.append(chunk if coef > 0 else "<mo>-</mo>" + chunk)
        else:
            parts.append(("<mo>+</mo>" if coef > 0 else "<mo>-</mo>") + chunk)
    if abs(const) > 1e-12:
        chunk = f"<mn>{_fmt(abs(const))}</mn>"
        if not parts:
            parts.append(chunk if const > 0 else "<mo>-</mo>" + chunk)
        else:
            parts.append(("<mo>+</mo>" if const > 0 else "<mo>-</mo>") + chunk)
    if not parts:
        parts.append("<mn>0</mn>")
    return "<mrow>" + "".join(parts) + "</mrow>"


def expr_latex(expr: Expr | None) -> str:
    if expr is None:
        return ""
    if expr.op == "const":
        return _fmt_tex(float(expr.value or 0.0))
    if expr.op == "ref":
        if expr.indices:
            idx = ",".join(_tex(index.value) for index in expr.indices)
            return rf"\mathrm{{{_tex(expr.name or 'x')}}}_{{{idx}}}"
        return rf"\mathrm{{{_tex(expr.name or 'x')}}}"
    if expr.op == "neg":
        return rf"-{_wrap(expr.args[0])}"
    if expr.op == "add":
        return rf"{expr_latex(expr.args[0])} + {expr_latex(expr.args[1])}"
    if expr.op == "sub":
        return rf"{expr_latex(expr.args[0])} - {_wrap(expr.args[1])}"
    if expr.op == "mul":
        return rf"{_wrap(expr.args[0])} \cdot {_wrap(expr.args[1])}"
    if expr.op == "div":
        return rf"\frac{{{expr_latex(expr.args[0])}}}{{{expr_latex(expr.args[1])}}}"
    if expr.op == "pow":
        return rf"{_wrap(expr.args[0])}^{{{expr_latex(expr.args[1])}}}"
    if expr.op == "sum":
        quant = ",".join(rf"{q.index} \in \mathrm{{{_tex(q.set_name)}}}" for q in expr.quants)
        return rf"\sum_{{{quant}}} {expr_latex(expr.args[0])}"
    return expr.op


def expr_plain(expr: Expr | None) -> str:
    if expr is None:
        return ""
    if expr.op == "const":
        return _fmt(float(expr.value or 0.0))
    if expr.op == "ref":
        if expr.indices:
            return f"{expr.name}[{','.join(index.value for index in expr.indices)}]"
        return expr.name or "x"
    if expr.op == "neg":
        return f"-({expr_plain(expr.args[0])})"
    if expr.op == "add":
        return f"{expr_plain(expr.args[0])} + {expr_plain(expr.args[1])}"
    if expr.op == "sub":
        return f"{expr_plain(expr.args[0])} - {expr_plain(expr.args[1])}"
    if expr.op == "mul":
        return f"({expr_plain(expr.args[0])})*({expr_plain(expr.args[1])})"
    if expr.op == "div":
        return f"({expr_plain(expr.args[0])})/({expr_plain(expr.args[1])})"
    if expr.op == "pow":
        return f"({expr_plain(expr.args[0])})^({expr_plain(expr.args[1])})"
    if expr.op == "sum":
        quant = ", ".join(f"{q.index} in {q.set_name}" for q in expr.quants)
        return f"sum{{{quant}}} {expr_plain(expr.args[0])}"
    return expr.op


def expr_mathml(expr: Expr | None) -> str:
    if expr is None:
        return "<mrow></mrow>"
    if expr.op == "const":
        return f"<mn>{_fmt(float(expr.value or 0.0))}</mn>"
    if expr.op == "ref":
        return _mi_raw(var_key(expr.name or "x", tuple(index.value for index in expr.indices)) if expr.indices else (expr.name or "x"))
    if expr.op == "neg":
        return "<mrow><mo>-</mo>" + expr_mathml(expr.args[0]) + "</mrow>"
    if expr.op in {"add", "sub", "mul"}:
        op = {"add": "+", "sub": "-", "mul": "·"}[expr.op]
        return "<mrow>" + expr_mathml(expr.args[0]) + _mo(op) + expr_mathml(expr.args[1]) + "</mrow>"
    if expr.op == "div":
        return "<mfrac>" + expr_mathml(expr.args[0]) + expr_mathml(expr.args[1]) + "</mfrac>"
    if expr.op == "pow":
        return "<msup>" + expr_mathml(expr.args[0]) + expr_mathml(expr.args[1]) + "</msup>"
    if expr.op == "sum":
        return "<mrow><mo>∑</mo>" + expr_mathml(expr.args[0]) + "</mrow>"
    return f"<mi>{html.escape(expr.op)}</mi>"


def _wrap(expr: Expr) -> str:
    if expr.op in {"const", "ref", "sum"}:
        return expr_latex(expr)
    return rf"\left({expr_latex(expr)}\right)"


def _latex_var(key: str) -> str:
    if "[" in key and key.endswith("]"):
        name, rest = key.split("[", 1)
        return rf"\mathrm{{{_tex(name)}}}_{{{_tex(rest[:-1])}}}"
    return rf"\mathrm{{{_tex(key)}}}"


def _tex(text: str) -> str:
    return (
        str(text)
        .replace("\\", r"\textbackslash{}")
        .replace("_", r"\_")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _fmt(value: float) -> str:
    if abs(value) < 1e-12:
        return "0"
    if abs(value - round(value)) < 1e-8:
        return str(int(round(value)))
    return format(value, ".8g")


def _fmt_tex(value: float) -> str:
    return _fmt(value)


def _slug(key: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in key).strip("_")
    return cleaned or "v"


def _fresh(base: str, used: set[str]) -> str:
    name = base
    suffix = 2
    while name in used:
        name = f"{base}_{suffix}"
        suffix += 1
    used.add(name)
    return name


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    rows = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        rows.append(item)
    return rows


def _sense_word(sense: str) -> str:
    return r"\max" if sense == "maximize" else r"\min"


def _sense_mathml(sense: str) -> str:
    word = "max" if sense == "maximize" else "min"
    return f"<mi>{word}</mi><mo>&#8290;</mo>"


def _rel_tex(sense: str) -> str:
    return {"<=": r"\le", ">=": r"\ge", "==": "="}.get(sense, "=")


def _rel_plain(sense: str) -> str:
    return {"<=": "<=", ">=": ">=", "==": "="}.get(sense, "=")


def _rel_char(sense: str) -> str:
    return {"<=": "≤", ">=": "≥", "==": "="}.get(sense, "=")


def _mo(op: str) -> str:
    return f"<mo>{html.escape(op)}</mo>"


def _mi_raw(name: str) -> str:
    return f"<mi>{html.escape(name)}</mi>"


def _math(inner: str) -> str:
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">{inner}</math>'


def _mtable(rows: list[str]) -> str:
    body = "".join(f"<mtr><mtd>{row}</mtd></mtr>" for row in rows if row)
    return f"<mtable>{body}</mtable>"
