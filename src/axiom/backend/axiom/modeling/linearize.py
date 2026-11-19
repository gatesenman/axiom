"""Expand global constraints such as alldiff into an equivalent MIP."""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.ir import (
    Constraint,
    Expr,
    Index,
    Model,
    Quantifier,
    SetDecl,
    VarDecl,
    const,
    ref,
    sym,
)


def expand_specials(model: Model) -> Model:
    """Return a model whose constraints are all linear comparisons.

    alldiff, SOS1, and piecewise-linear functions become ordinary linear rows.
    Models without those constructs are returned unchanged.
    """
    if not any(con.kind == "alldiff" for con in model.constraints) and not model.sos and not model.pieces:
        return model
    expanded = model.copy()
    constraints: list[Constraint] = []
    for con in expanded.constraints:
        if con.kind != "alldiff":
            constraints.append(con)
            continue
        constraints.extend(_linearize_alldiff(expanded, con))
    for sos in expanded.sos:
        constraints.extend(_linearize_sos1(expanded, sos))
    for piece in expanded.pieces:
        constraints.extend(_linearize_piecewise(expanded, piece))
    expanded.constraints = constraints
    expanded.sos = []
    expanded.pieces = []
    return expanded


def _linearize_alldiff(model: Model, con: Constraint) -> list[Constraint]:
    target = con.alldiff_ref
    if target is None or target.op != "ref" or not target.name:
        raise AxiomError(
            f"alldiff 约束 {con.name} 无效。",
            f"alldiff constraint {con.name} is invalid.",
            code="bad_alldiff",
        )
    var = model.variables[target.name]
    if var.lower is None or var.upper is None:
        raise AxiomError(
            f"alldiff 变量 {target.name} 需要有限界。",
            f"alldiff variable {target.name} needs finite bounds.",
            code="bad_alldiff",
        )
    lo = int(round(var.lower))
    hi = int(round(var.upper))
    if abs(var.lower - lo) > 1e-8 or abs(var.upper - hi) > 1e-8:
        raise AxiomError(
            f"alldiff 变量 {target.name} 的界必须是整数。",
            f"alldiff variable {target.name} needs integer bounds.",
            code="bad_alldiff",
        )
    if hi < lo or hi - lo > 40:
        raise AxiomError(
            f"alldiff 变量 {target.name} 的定义域不可线性化。",
            f"alldiff variable {target.name} has a domain that cannot be linearized.",
            code="bad_alldiff",
        )
    values = [str(value) for value in range(lo, hi + 1)]
    value_set = f"_{con.name}_V"
    suffix = 2
    while value_set in model.sets:
        value_set = f"_{con.name}_V{suffix}"
        suffix += 1
    model.sets[value_set] = SetDecl(name=value_set, elements=values)

    z_name = f"_{con.name}_z"
    suffix = 2
    while z_name in model.variables:
        z_name = f"_{con.name}_z{suffix}"
        suffix += 1
    item_quants = list(con.quants) + list(con.alldiff_quants)
    model.variables[z_name] = VarDecl(
        name=z_name,
        index_sets=[q.set_name for q in item_quants] + [value_set],
        domain="binary",
        lower=0.0,
        upper=1.0,
    )
    v_index = f"_{con.name}_v"
    v_quant = Quantifier(index=v_index, set_name=value_set)
    item_syms = [sym(q.index) for q in item_quants]
    z_item = ref(z_name, item_syms + [sym(v_index)])
    produced = [
        Constraint(
            name=f"{con.name}_assign",
            quants=tuple(item_quants),
            kind="comparison",
            relation="==",
            lhs=_sum((v_quant,), z_item),
            rhs=const(1),
        ),
        Constraint(
            name=f"{con.name}_link",
            quants=tuple(item_quants),
            kind="comparison",
            relation="==",
            lhs=ref(target.name, target.indices),
            rhs=_sum((v_quant,), Expr(op="mul", args=(ref(v_index), z_item))),
        ),
        Constraint(
            name=f"{con.name}_unique",
            quants=tuple(con.quants) + (v_quant,),
            kind="comparison",
            relation="<=",
            lhs=_sum(tuple(con.alldiff_quants), z_item),
            rhs=const(1),
        ),
    ]
    return produced


def _linearize_sos1(model: Model, sos) -> list[Constraint]:
    if len(sos.members) < 1:
        raise AxiomError(
            f"SOS1 {sos.name} 没有成员。",
            f"SOS1 {sos.name} has no members.",
            code="bad_sos",
        )
    binaries: list[str] = []
    produced: list[Constraint] = []
    for member in sos.members:
        var = model.variables.get(member)
        if var is None:
            raise AxiomError(
                f"SOS1 {sos.name} 引用了未声明的变量 {member}。",
                f"SOS1 {sos.name} refers to undeclared variable {member}.",
                code="bad_sos",
            )
        if var.index_sets:
            raise AxiomError(
                f"SOS1 {sos.name} 目前只接受标量变量，{member} 带下标。",
                f"SOS1 {sos.name} currently accepts scalar variables; {member} is indexed.",
                code="bad_sos",
            )
        if var.upper is None:
            raise AxiomError(
                f"SOS1 变量 {member} 需要有限上界。",
                f"SOS1 variable {member} needs a finite upper bound.",
                code="bad_sos",
            )
        y_name = _fresh(model, f"_{sos.name}_{member}_y")
        model.variables[y_name] = VarDecl(name=y_name, domain="binary", lower=0.0, upper=1.0)
        binaries.append(y_name)
        produced.append(
            Constraint(
                name=f"{sos.name}_{member}_ub",
                relation="<=",
                lhs=ref(member),
                rhs=Expr(op="mul", args=(const(float(var.upper)), ref(y_name))),
            )
        )
        if var.lower is not None and var.lower < 0:
            produced.append(
                Constraint(
                    name=f"{sos.name}_{member}_lb",
                    relation=">=",
                    lhs=ref(member),
                    rhs=Expr(op="mul", args=(const(float(var.lower)), ref(y_name))),
                )
            )
    produced.append(
        Constraint(
            name=f"{sos.name}_card",
            relation="<=",
            lhs=_add_refs(binaries),
            rhs=const(1),
        )
    )
    return produced


def _linearize_piecewise(model: Model, piece) -> list[Constraint]:
    points = list(piece.points)
    if len(points) < 2:
        raise AxiomError(
            f"分段线性 {piece.name} 至少需要两个断点。",
            f"Piecewise {piece.name} needs at least two breakpoints.",
            code="bad_piecewise",
        )
    for earlier, later in zip(points, points[1:]):
        if later[0] <= earlier[0] + 1e-12:
            raise AxiomError(
                f"分段线性 {piece.name} 的横坐标必须严格递增。",
                f"Piecewise {piece.name} needs strictly increasing x breakpoints.",
                code="bad_piecewise",
            )
    if piece.variable not in model.variables:
        raise AxiomError(
            f"分段线性 {piece.name} 的自变量 {piece.variable} 未声明。",
            f"Piecewise {piece.name} refers to undeclared variable {piece.variable}.",
            code="bad_piecewise",
        )
    if piece.name == piece.variable:
        raise AxiomError(
            f"分段线性 {piece.name} 的函数名不能和自变量相同。",
            f"Piecewise {piece.name} cannot use the same name for the function and the variable.",
            code="bad_piecewise",
        )
    if piece.name not in model.variables:
        model.variables[piece.name] = VarDecl(name=piece.name, domain="continuous")
    lambdas: list[str] = []
    for position, _point in enumerate(points):
        name = _fresh(model, f"_{piece.name}_l{position}")
        model.variables[name] = VarDecl(name=name, domain="continuous", lower=0.0)
        lambdas.append(name)
    segments: list[str] = []
    for position in range(len(points) - 1):
        name = _fresh(model, f"_{piece.name}_z{position}")
        model.variables[name] = VarDecl(name=name, domain="binary", lower=0.0, upper=1.0)
        segments.append(name)
    produced = [
        Constraint(name=f"{piece.name}_lambda", relation="==", lhs=_add_refs(lambdas), rhs=const(1)),
        Constraint(name=f"{piece.name}_x", relation="==", lhs=ref(piece.variable), rhs=_dot(points, lambdas, 0)),
        Constraint(name=f"{piece.name}_y", relation="==", lhs=ref(piece.name), rhs=_dot(points, lambdas, 1)),
        Constraint(name=f"{piece.name}_seg", relation="==", lhs=_add_refs(segments), rhs=const(1)),
    ]
    last = len(points) - 1
    for position, lam in enumerate(lambdas):
        if position == 0:
            rhs = ref(segments[0])
        elif position == last:
            rhs = ref(segments[-1])
        else:
            rhs = Expr(op="add", args=(ref(segments[position - 1]), ref(segments[position])))
        produced.append(Constraint(name=f"{piece.name}_adj{position}", relation="<=", lhs=ref(lam), rhs=rhs))
    return produced


def _fresh(model: Model, stem: str) -> str:
    name = stem
    suffix = 2
    while name in model.variables or name in model.sets or name in model.parameters:
        name = f"{stem}_{suffix}"
        suffix += 1
    return name


def _add_refs(names: list[str]) -> Expr:
    expr = ref(names[0])
    for name in names[1:]:
        expr = Expr(op="add", args=(expr, ref(name)))
    return expr


def _dot(points: list[tuple[float, float]], lambdas: list[str], axis: int) -> Expr:
    expr = Expr(op="mul", args=(const(float(points[0][axis])), ref(lambdas[0])))
    for point, lam in zip(points[1:], lambdas[1:]):
        term = Expr(op="mul", args=(const(float(point[axis])), ref(lam)))
        expr = Expr(op="add", args=(expr, term))
    return expr


def _sum(quants: tuple[Quantifier, ...], body: Expr) -> Expr:
    if not quants:
        return body
    return Expr(op="sum", quants=quants, args=(body,))
