"""Lark parser that turns Axiom Modeling Language text into an IR model."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from lark import Lark, Token, Tree, UnexpectedInput

from axiom.errors import AxiomError
from axiom.modeling.ir import (
    Constraint,
    Expr,
    Index,
    Model,
    Objective,
    ParamDecl,
    Piecewise,
    Quantifier,
    SetDecl,
    SosSet,
    VarDecl,
)

_GRAMMAR = Path(__file__).with_name("grammar.lark")
_META = re.compile(r"^[ \t]*#@[ \t]*([A-Za-z0-9_-]+)[ \t]*:[ \t]*(.+?)[ \t]*$", re.M)


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(
        _GRAMMAR.read_text(encoding="utf-8"),
        parser="earley",
        propagate_positions=True,
        maybe_placeholders=False,
    )


def parse_aml(text: str) -> Model:
    """Parse AML. Semantic checks are intentionally separate (see validator)."""
    if text is None or not str(text).strip():
        raise AxiomError("模型文本为空。", "The model text is empty.", code="syntax")
    meta = {match.group(1).strip(): match.group(2).strip() for match in _META.finditer(text)}
    try:
        tree = _parser().parse(text)
    except UnexpectedInput as exc:
        context = exc.get_context(text, span=2).strip()
        raise AxiomError(
            f"AML 语法错误，第 {exc.line} 行第 {exc.column} 列。\n{context}",
            f"AML syntax error at line {exc.line}, column {exc.column}.\n{context}",
            code="syntax",
        ) from exc
    model = _build(tree)
    model.meta.update(meta)
    return model


def _build(tree: Tree) -> Model:
    model = Model()
    anon_obj = 0
    anon_con = 0
    for stmt in tree.children:
        if not isinstance(stmt, Tree):
            continue
        if stmt.data == "model_stmt":
            model.name = _name(stmt.children[0])
        elif stmt.data == "set_stmt":
            decl = _set_decl(stmt)
            model.sets[decl.name] = decl
        elif stmt.data == "param_stmt":
            decl = _param_decl(stmt)
            model.parameters[decl.name] = decl
        elif stmt.data == "var_stmt":
            decl = _var_decl(stmt)
            model.variables[decl.name] = decl
        elif stmt.data == "obj_stmt":
            anon_obj += 1
            model.objectives.append(_objective(stmt, anon_obj))
        elif stmt.data == "con_stmt":
            anon_con += 1
            model.constraints.append(_constraint(stmt, anon_con))
        elif stmt.data == "weight_stmt":
            _apply_weight(model, stmt)
        elif stmt.data == "sos_stmt":
            model.sos.append(_sos(stmt))
        elif stmt.data == "piece_stmt":
            model.pieces.append(_piece(stmt))
        else:
            raise AxiomError(
                f"无法识别的语句 {stmt.data}。",
                f"Unrecognized statement {stmt.data}.",
                code="syntax",
            )
    for piece in model.pieces:
        if piece.name not in model.variables and piece.name != piece.variable:
            model.variables[piece.name] = VarDecl(name=piece.name, domain="continuous")
    return model


def _sos(stmt: Tree) -> SosSet:
    name = _name(stmt.children[0])
    members = [_name(child) for child in stmt.children[1:] if isinstance(child, Token)]
    if len(members) < 1:
        raise AxiomError(
            f"SOS1 {name} 至少要列出一个变量。",
            f"SOS1 {name} needs at least one variable.",
            code="syntax",
        )
    return SosSet(name=name, members=members)


def _piece(stmt: Tree) -> Piecewise:
    name = _name(stmt.children[0])
    variable = _name(stmt.children[1])
    points: list[tuple[float, float]] = []
    for child in stmt.children[2:]:
        if isinstance(child, Tree) and child.data == "pair":
            points.append((_signed(child.children[0]), _signed(child.children[1])))
    if len(points) < 2:
        raise AxiomError(
            f"分段线性 {name} 至少需要两个断点。",
            f"Piecewise {name} needs at least two breakpoints.",
            code="syntax",
        )
    return Piecewise(name=name, variable=variable, points=points)


def _line(tree: Tree) -> int:
    meta = getattr(tree, "meta", None)
    return int(getattr(meta, "line", 0) or 0)


def _name(node: Token | Tree) -> str:
    if isinstance(node, Token):
        return str(node.value)
    raise AxiomError("期望标识符。", "Expected an identifier.", code="syntax")


def _number_token(node: Token | Tree) -> float:
    if isinstance(node, Token):
        return float(node.value)
    raise AxiomError("期望数字。", "Expected a number.", code="syntax")


def _signed(node: Tree) -> float:
    magnitude = _number_token(node.children[0])
    if node.data == "neg":
        return -magnitude
    if node.data == "pos":
        return magnitude
    raise AxiomError("期望有符号数字。", "Expected a signed number.", code="syntax")


def _element(node: Tree) -> str:
    child = node.children[0]
    if isinstance(child, Token):
        if child.type == "STRING":
            return _unquote(str(child.value))
        return str(child.value)
    if isinstance(child, Tree) and child.data in {"pos", "neg"}:
        value = _signed(child)
        if float(value).is_integer():
            return str(int(value))
        return format(value, ".12g")
    raise AxiomError("集合元素无效。", "Invalid set element.", code="syntax")


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        body = text[1:-1]
        return body.replace(r"\"", '"').replace(r"\\", "\\")
    return text


def _set_decl(stmt: Tree) -> SetDecl:
    name = _name(stmt.children[0])
    expr = stmt.children[1]
    if expr.data == "set_list":
        elements = [_element(child) for child in expr.children]
    elif expr.data == "set_range":
        start = _signed(expr.children[0])
        end = _signed(expr.children[1])
        if not float(start).is_integer() or not float(end).is_integer():
            raise AxiomError(
                f"集合 {name} 的区间端点必须是整数。",
                f"Range bounds of set {name} must be integers.",
                code="syntax",
            )
        lo, hi = int(start), int(end)
        if hi < lo:
            raise AxiomError(
                f"集合 {name} 的区间 {lo}..{hi} 为空。",
                f"Range {lo}..{hi} of set {name} is empty.",
                code="syntax",
            )
        if hi - lo > 100_000:
            raise AxiomError(
                f"集合 {name} 过大。",
                f"Set {name} is too large.",
                code="syntax",
            )
        elements = [str(value) for value in range(lo, hi + 1)]
    else:
        raise AxiomError("集合表达式无效。", "Invalid set expression.", code="syntax")
    return SetDecl(name=name, elements=elements, line=_line(stmt))


def _index_sets(node: Tree) -> list[str]:
    return [_name(child) for child in node.children]


def _key(node: Tree) -> tuple[str, ...]:
    if node.data == "singlekey":
        return (_element(node.children[0]),)
    if node.data == "tuplekey":
        return tuple(_element(child) for child in node.children)
    raise AxiomError("参数索引无效。", "Invalid parameter index.", code="syntax")


def _param_decl(stmt: Tree) -> ParamDecl:
    name = _name(stmt.children[0])
    index_sets: list[str] = []
    default: float | None = None
    values: dict[tuple[str, ...], float] = {}
    for child in stmt.children[1:]:
        if isinstance(child, Tree) and child.data == "indexdecl":
            index_sets = _index_sets(child)
        elif isinstance(child, Tree) and child.data == "default_clause":
            default = _signed(child.children[0])
        elif isinstance(child, Tree) and child.data == "scalar":
            values[()] = _signed(child.children[0])
        elif isinstance(child, Tree) and child.data == "table":
            for entry in child.children:
                values[_key(entry.children[0])] = _signed(entry.children[1])
    return ParamDecl(
        name=name,
        index_sets=index_sets,
        values=values,
        default=default,
        line=_line(stmt),
    )


def _var_decl(stmt: Tree) -> VarDecl:
    name = _name(stmt.children[0])
    index_sets: list[str] = []
    domain = "continuous"
    lower: float | None = None
    upper: float | None = None
    for child in stmt.children[1:]:
        if not isinstance(child, Tree):
            continue
        if child.data == "indexdecl":
            index_sets = _index_sets(child)
        elif child.data == "continuous":
            domain = "continuous"
        elif child.data == "integer":
            domain = "integer"
        elif child.data == "binary":
            domain = "binary"
        elif child.data == "lower":
            lower = _signed(child.children[0])
        elif child.data == "upper":
            upper = _signed(child.children[0])
    if domain == "binary":
        if lower is None:
            lower = 0.0
        if upper is None:
            upper = 1.0
    return VarDecl(
        name=name,
        index_sets=index_sets,
        domain=domain,  # type: ignore[arg-type]
        lower=lower,
        upper=upper,
        line=_line(stmt),
    )


def _objective(stmt: Tree, anon: int) -> Objective:
    sense_token = stmt.children[0]
    sense_raw = str(sense_token.value)
    sense = "minimize" if sense_raw in {"min", "minimize"} else "maximize"
    name = f"obj_{anon}"
    expr_node = None
    for child in stmt.children[1:]:
        if isinstance(child, Token):
            name = str(child.value)
        elif isinstance(child, Tree):
            expr_node = child
    if expr_node is None:
        raise AxiomError("目标函数缺少表达式。", "Objective is missing an expression.", code="syntax")
    return Objective(name=name, sense=sense, expr=_expr(expr_node), line=_line(stmt))


def _constraint(stmt: Tree, anon: int) -> Constraint:
    name = f"c{anon}"
    quants: tuple[Quantifier, ...] = ()
    body = None
    for child in stmt.children:
        if isinstance(child, Token):
            name = str(child.value)
        elif isinstance(child, Tree) and child.data == "quantifier":
            quants = tuple(_quantifiers(child))
        elif isinstance(child, Tree):
            body = child
    if body is None:
        raise AxiomError("约束缺少表达式。", "Constraint is missing a body.", code="syntax")
    if body.data == "comparison":
        relation = str(body.children[1].value)
        if relation == "=":
            relation = "=="
        return Constraint(
            name=name,
            quants=quants,
            kind="comparison",
            relation=relation,  # type: ignore[arg-type]
            lhs=_expr(body.children[0]),
            rhs=_expr(body.children[2]),
            line=_line(stmt),
        )
    if body.data == "alldiff":
        *qitems, ref_node = body.children
        return Constraint(
            name=name,
            quants=quants,
            kind="alldiff",
            alldiff_quants=tuple(_qitem(item) for item in qitems),
            alldiff_ref=_expr(ref_node),
            line=_line(stmt),
        )
    raise AxiomError("约束体无法识别。", "Unrecognized constraint body.", code="syntax")


def _apply_weight(model: Model, stmt: Tree) -> None:
    name = _name(stmt.children[0])
    weight = _signed(stmt.children[1])
    found = False
    for obj in model.objectives:
        if obj.name == name:
            obj.weight = weight
            found = True
    if not found:
        raise AxiomError(
            f"weight 引用了不存在的目标 {name}。",
            f"weight refers to unknown objective {name}.",
            code="syntax",
        )


def _quantifiers(node: Tree) -> list[Quantifier]:
    return [_qitem(child) for child in node.children]


def _qitem(node: Tree) -> Quantifier:
    return Quantifier(index=_name(node.children[0]), set_name=_name(node.children[1]))


def _expr(node: Tree) -> Expr:
    data = node.data
    if data == "const":
        return Expr(op="const", value=_number_token(node.children[0]))
    if data == "neg":
        return Expr(op="neg", args=(_expr(node.children[0]),))
    if data in {"add", "sub", "mul", "div", "pow"}:
        return Expr(op=data, args=(_expr(node.children[0]), _expr(node.children[1])))
    if data == "sumexpr":
        *qitems, body = node.children
        return Expr(
            op="sum",
            quants=tuple(_qitem(item) for item in qitems),
            args=(_expr(body),),
        )
    if data == "ref":
        return _ref(node)
    raise AxiomError(
        f"无法识别的表达式 {data}。",
        f"Unrecognized expression {data}.",
        code="syntax",
    )


def _ref(node: Tree) -> Expr:
    name = _name(node.children[0])
    indices: tuple[Index, ...] = ()
    if len(node.children) > 1:
        spec = node.children[1]
        indices = tuple(_index(child) for child in spec.children)
    return Expr(op="ref", name=name, indices=indices)


def _index(node: Tree) -> Index:
    if node.data == "ix_name":
        return Index(kind="symbol", value=_name(node.children[0]))
    if node.data == "ix_num":
        value = _number_token(node.children[0])
        text = str(int(value)) if float(value).is_integer() else format(value, ".12g")
        return Index(kind="literal", value=text)
    if node.data == "ix_str":
        return Index(kind="literal", value=_unquote(str(node.children[0].value)))
    if node.data == "ix_sub":
        return Index(kind="offset", value=_name(node.children[0]), offset=-int(float(node.children[1].value)))
    if node.data == "ix_add":
        return Index(kind="offset", value=_name(node.children[0]), offset=int(float(node.children[1].value)))
    if node.data == "ix_prev":
        return Index(kind="prev", value=_name(node.children[0]))
    raise AxiomError("下标无效。", "Invalid index.", code="syntax")
