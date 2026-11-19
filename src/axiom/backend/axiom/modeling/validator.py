"""Semantic checks for an Axiom model.

Parsing only checks grammar. Solving and export require a model that names
real sets, supplies parameter data, and keeps expressions inside scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from axiom.modeling.ir import Constraint, Expr, Model, Quantifier, cartesian


@dataclass
class Diagnostic:
    level: str
    code: str
    message: str
    message_en: str
    line: int = 0

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "message_en": self.message_en,
            "line": self.line,
        }


@dataclass
class ValidationResult:
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "diagnostics": [item.to_dict() for item in self.diagnostics]}


def validate(model: Model) -> ValidationResult:
    diagnostics: list[Diagnostic] = []

    def error(code: str, message: str, message_en: str, line: int = 0) -> None:
        diagnostics.append(Diagnostic("error", code, message, message_en, line))

    def warn(code: str, message: str, message_en: str, line: int = 0) -> None:
        diagnostics.append(Diagnostic("warning", code, message, message_en, line))

    declared: dict[str, str] = {}
    for bucket, mapping in (
        ("set", model.sets),
        ("param", model.parameters),
        ("var", model.variables),
    ):
        for name, decl in mapping.items():
            if name in declared:
                error(
                    "duplicate_name",
                    f"名称 {name} 同时被用作{declared[name]}和{bucket}。",
                    f"Name {name} is used both as a {declared[name]} and a {bucket}.",
                    getattr(decl, "line", 0),
                )
            else:
                declared[name] = bucket
            if not name:
                error("empty_name", "存在空名称。", "An empty name was declared.")

    for decl in model.sets.values():
        if not decl.elements:
            error(
                "empty_set",
                f"集合 {decl.name} 为空。",
                f"Set {decl.name} is empty.",
                decl.line,
            )
        if len(decl.elements) != len(set(decl.elements)):
            error(
                "duplicate_element",
                f"集合 {decl.name} 含有重复元素。",
                f"Set {decl.name} contains duplicate elements.",
                decl.line,
            )

    for decl in model.parameters.values():
        for set_name in decl.index_sets:
            if set_name not in model.sets:
                error(
                    "unknown_set",
                    f"参数 {decl.name} 引用了未声明的集合 {set_name}。",
                    f"Parameter {decl.name} references unknown set {set_name}.",
                    decl.line,
                )
        if not decl.index_sets and () not in decl.values and decl.default is None:
            error(
                "missing_data",
                f"标量参数 {decl.name} 没有取值。",
                f"Scalar parameter {decl.name} has no value.",
                decl.line,
            )
        known = all(name in model.sets for name in decl.index_sets)
        if known and decl.index_sets:
            expected = set(cartesian(model, decl.index_sets))
            for key in decl.values:
                if len(key) != len(decl.index_sets):
                    error(
                        "bad_arity",
                        f"参数 {decl.name} 的数据下标 {key} 维度不匹配。",
                        f"Data index {key} for parameter {decl.name} has the wrong dimension.",
                        decl.line,
                    )
                    continue
                if key not in expected:
                    error(
                        "bad_index",
                        f"参数 {decl.name} 的数据下标 {','.join(key)} 不在集合内。",
                        f"Data index {','.join(key)} for parameter {decl.name} is outside its sets.",
                        decl.line,
                    )
            missing = expected - set(decl.values)
            if missing and decl.default is None:
                sample = ", ".join("(" + ",".join(key) + ")" for key in list(missing)[:3])
                error(
                    "missing_data",
                    f"参数 {decl.name} 缺少 {len(missing)} 个取值，例如 {sample}。",
                    f"Parameter {decl.name} is missing {len(missing)} values, for example {sample}.",
                    decl.line,
                )

    for decl in model.variables.values():
        for set_name in decl.index_sets:
            if set_name not in model.sets:
                error(
                    "unknown_set",
                    f"变量 {decl.name} 引用了未声明的集合 {set_name}。",
                    f"Variable {decl.name} references unknown set {set_name}.",
                    decl.line,
                )
        if decl.domain not in {"continuous", "integer", "binary"}:
            error(
                "bad_domain",
                f"变量 {decl.name} 的类型 {decl.domain} 无效。",
                f"Variable {decl.name} has invalid domain {decl.domain}.",
                decl.line,
            )
        if decl.lower is not None and decl.upper is not None and decl.lower > decl.upper + 1e-9:
            error(
                "bad_bounds",
                f"变量 {decl.name} 的下界大于上界。",
                f"Variable {decl.name} has a lower bound above its upper bound.",
                decl.line,
            )
        if decl.domain == "binary":
            if (decl.lower is not None and decl.lower < -1e-9) or (
                decl.upper is not None and decl.upper > 1 + 1e-9
            ):
                error(
                    "bad_bounds",
                    f"0-1 变量 {decl.name} 的界必须落在 [0, 1]。",
                    f"Binary variable {decl.name} must stay inside [0, 1].",
                    decl.line,
                )
        if known_sets(model, decl.index_sets):
            count = 1
            for set_name in decl.index_sets:
                count *= len(model.sets[set_name].elements)
            if count > 100_000:
                error(
                    "too_large",
                    f"变量 {decl.name} 展开后有 {count} 个，超过 100000 的上限。",
                    f"Variable {decl.name} expands to {count} columns, above the 100000 limit.",
                    decl.line,
                )

    obj_names: set[str] = set()
    for obj in model.objectives:
        if obj.name in obj_names:
            error(
                "duplicate_name",
                f"目标名称 {obj.name} 重复。",
                f"Duplicate objective name {obj.name}.",
                obj.line,
            )
        obj_names.add(obj.name)
        if obj.sense not in {"minimize", "maximize"}:
            error(
                "bad_sense",
                f"目标 {obj.name} 的方向无效。",
                f"Objective {obj.name} has an invalid sense.",
                obj.line,
            )
        if obj.weight < 0:
            warn(
                "negative_weight",
                f"目标 {obj.name} 的权重为负，将反转优化方向。",
                f"Objective {obj.name} has a negative weight, which flips its sense.",
                obj.line,
            )
        _check_expr(model, obj.expr, set(), error, obj.line)

    if not model.objectives:
        warn(
            "no_objective",
            "模型没有目标函数。求解前需要至少一个目标。",
            "The model has no objective. Solving needs at least one.",
        )

    con_names: set[str] = set()
    for con in model.constraints:
        if con.name in con_names:
            error(
                "duplicate_name",
                f"约束名称 {con.name} 重复。",
                f"Duplicate constraint name {con.name}.",
                con.line,
            )
        con_names.add(con.name)
        scope = _check_quants(model, con.quants, error, con.line)
        if con.kind == "comparison":
            if con.lhs is None or con.rhs is None or con.relation not in {"<=", ">=", "=="}:
                error(
                    "bad_constraint",
                    f"约束 {con.name} 不完整。",
                    f"Constraint {con.name} is incomplete.",
                    con.line,
                )
            else:
                _check_expr(model, con.lhs, scope, error, con.line)
                _check_expr(model, con.rhs, scope, error, con.line)
        elif con.kind == "alldiff":
            _check_alldiff(model, con, scope, error)
        else:
            error(
                "bad_constraint",
                f"约束 {con.name} 的类型 {con.kind} 无效。",
                f"Constraint {con.name} has invalid kind {con.kind}.",
                con.line,
            )

    errors = [item for item in diagnostics if item.level == "error"]
    return ValidationResult(ok=not errors, diagnostics=diagnostics)


def known_sets(model: Model, names: list[str]) -> bool:
    return all(name in model.sets for name in names)


def _check_quants(model: Model, quants: tuple[Quantifier, ...], error, line: int) -> set[str]:
    scope: set[str] = set()
    for quant in quants:
        if quant.set_name not in model.sets:
            error(
                "unknown_set",
                f"量词 {quant.index} in {quant.set_name} 引用了未声明的集合。",
                f"Quantifier {quant.index} in {quant.set_name} references an unknown set.",
                line,
            )
        if quant.index in scope:
            error(
                "duplicate_index",
                f"下标 {quant.index} 在同一量词中重复。",
                f"Index {quant.index} is repeated in the same quantifier.",
                line,
            )
        scope.add(quant.index)
    return scope


def _check_alldiff(model: Model, con: Constraint, scope: set[str], error) -> None:
    inner = _check_quants(model, con.alldiff_quants, error, con.line)
    if not con.alldiff_quants:
        error(
            "bad_alldiff",
            f"alldiff 约束 {con.name} 没有下标。",
            f"alldiff constraint {con.name} has no index.",
            con.line,
        )
        return
    ref = con.alldiff_ref
    if ref is None or ref.op != "ref" or not ref.name:
        error(
            "bad_alldiff",
            f"alldiff 约束 {con.name} 必须作用于一个变量。",
            f"alldiff constraint {con.name} must apply to a variable.",
            con.line,
        )
        return
    var = model.variables.get(ref.name)
    if var is None:
        error(
            "unknown_var",
            f"alldiff 约束 {con.name} 引用了未知变量 {ref.name}。",
            f"alldiff constraint {con.name} references unknown variable {ref.name}.",
            con.line,
        )
        return
    if var.domain == "continuous":
        error(
            "bad_alldiff",
            f"alldiff 只能用于整数或 0-1 变量，{ref.name} 是连续变量。",
            f"alldiff requires an integer or binary variable; {ref.name} is continuous.",
            con.line,
        )
    if var.lower is None or var.upper is None:
        error(
            "bad_alldiff",
            f"alldiff 变量 {ref.name} 需要有限上下界。",
            f"alldiff variable {ref.name} needs finite bounds.",
            con.line,
        )
    elif var.upper - var.lower > 40:
        error(
            "bad_alldiff",
            f"alldiff 变量 {ref.name} 的定义域超过 40 个整数。",
            f"alldiff variable {ref.name} has a domain larger than 40 integers.",
            con.line,
        )
    if len(ref.indices) != len(var.index_sets):
        error(
            "bad_arity",
            f"变量 {ref.name} 在 alldiff 中的下标维度不匹配。",
            f"Variable {ref.name} has the wrong index arity in alldiff.",
            con.line,
        )
    full_scope = set(scope) | inner
    for index in ref.indices:
        if index.kind == "symbol" and index.value not in full_scope:
            error(
                "free_index",
                f"alldiff 下标 {index.value} 不在量词范围内。",
                f"alldiff index {index.value} is not bound by a quantifier.",
                con.line,
            )


def _check_expr(model: Model, expr: Expr, scope: set[str], error, line: int) -> None:
    if expr.op == "const":
        return
    if expr.op == "sum":
        inner = _check_quants(model, expr.quants, error, line)
        overlap = scope & inner
        if overlap:
            error(
                "shadowed_index",
                f"求和下标 {', '.join(sorted(overlap))} 遮蔽了外层下标。",
                f"Sum index {', '.join(sorted(overlap))} shadows an outer index.",
                line,
            )
        _check_expr(model, expr.args[0], scope | inner, error, line)
        return
    if expr.op == "neg":
        _check_expr(model, expr.args[0], scope, error, line)
        return
    if expr.op in {"add", "sub", "mul", "div", "pow"}:
        for arg in expr.args:
            _check_expr(model, arg, scope, error, line)
        return
    if expr.op == "ref":
        name = expr.name or ""
        if name in model.parameters:
            _check_indexed(model, model.parameters[name].index_sets, expr, scope, error, line, "参数", "Parameter")
            return
        if name in model.variables:
            _check_indexed(model, model.variables[name].index_sets, expr, scope, error, line, "变量", "Variable")
            return
        if name in scope and not expr.indices:
            return
        error(
            "unknown_symbol",
            f"表达式引用了未声明的符号 {name}。",
            f"Expression references undeclared symbol {name}.",
            line,
        )
        return
    error("bad_expr", f"表达式算子 {expr.op} 无效。", f"Invalid expression operator {expr.op}.", line)


def _check_indexed(model, index_sets, expr: Expr, scope, error, line, zh, en) -> None:
    if len(expr.indices) != len(index_sets):
        error(
            "bad_arity",
            f"{zh} {expr.name} 需要 {len(index_sets)} 个下标，实际写了 {len(expr.indices)} 个。",
            f"{en} {expr.name} expects {len(index_sets)} indices, got {len(expr.indices)}.",
            line,
        )
        return
    for position, index in enumerate(expr.indices):
        set_name = index_sets[position]
        if index.kind in {"symbol", "offset", "prev"}:
            if index.value not in scope:
                if set_name in model.sets and index.value in model.sets[set_name].elements:
                    continue
                error(
                    "free_index",
                    f"下标 {index.value} 既不是量词，也不是集合 {set_name} 的元素。",
                    f"Index {index.value} is neither a quantifier nor an element of set {set_name}.",
                    line,
                )
        elif index.kind == "literal":
            if set_name in model.sets and index.value not in model.sets[set_name].elements:
                error(
                    "bad_index",
                    f"下标 {index.value} 不属于集合 {set_name}。",
                    f"Index {index.value} is not an element of set {set_name}.",
                    line,
                )
