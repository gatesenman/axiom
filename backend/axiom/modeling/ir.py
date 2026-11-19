"""Canonical intermediate representation for the Axiom Modeling Language.

The IR is the product's stable contract. Parsers, translators, solvers, and
the JSON schema all speak this structure. Expressions are trees so that a
single walker can linearize, evaluate, or pretty-print them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Domain = Literal["continuous", "integer", "binary"]
Sense = Literal["minimize", "maximize"]
Relation = Literal["<=", ">=", "=="]


def _canon_element(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".12g")
    text = str(value).strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer() and "e" not in text.lower() and "." not in text:
        return str(int(number))
    return text


@dataclass(frozen=True)
class Index:
    """One subscript. ``symbol`` is a quantifier in scope or a literal name."""

    kind: Literal["symbol", "literal", "offset", "prev"]
    value: str
    offset: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.kind == "offset":
            payload["offset"] = self.offset
        return payload

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Index":
        return Index(
            kind=data["kind"],
            value=str(data["value"]),
            offset=int(data.get("offset", 0)),
        )


@dataclass(frozen=True)
class Quantifier:
    index: str
    set_name: str

    def to_dict(self) -> dict[str, str]:
        return {"index": self.index, "set": self.set_name}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Quantifier":
        return Quantifier(index=str(data["index"]), set_name=str(data["set"]))


@dataclass(frozen=True)
class Expr:
    op: str
    value: float | None = None
    name: str | None = None
    indices: tuple[Index, ...] = ()
    args: tuple["Expr", ...] = ()
    quants: tuple[Quantifier, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        if self.op == "const":
            return {"op": "const", "value": self.value}
        if self.op == "ref":
            payload: dict[str, Any] = {"op": "ref", "name": self.name}
            if self.indices:
                payload["indices"] = [index.to_dict() for index in self.indices]
            return payload
        if self.op == "sum":
            return {
                "op": "sum",
                "quantifiers": [q.to_dict() for q in self.quants],
                "body": self.args[0].to_dict(),
            }
        if self.op == "neg":
            return {"op": "neg", "arg": self.args[0].to_dict()}
        return {
            "op": self.op,
            "args": [arg.to_dict() for arg in self.args],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Expr":
        op = data["op"]
        if op == "const":
            return Expr(op="const", value=float(data["value"]))
        if op == "ref":
            indices = tuple(Index.from_dict(item) for item in data.get("indices", []))
            return Expr(op="ref", name=str(data["name"]), indices=indices)
        if op == "sum":
            quants = tuple(Quantifier.from_dict(item) for item in data.get("quantifiers", []))
            return Expr(op="sum", quants=quants, args=(Expr.from_dict(data["body"]),))
        if op == "neg":
            return Expr(op="neg", args=(Expr.from_dict(data["arg"]),))
        return Expr(op=op, args=tuple(Expr.from_dict(item) for item in data.get("args", [])))


def const(value: float) -> Expr:
    return Expr(op="const", value=float(value))


def ref(name: str, indices: Iterable[Index] = ()) -> Expr:
    return Expr(op="ref", name=name, indices=tuple(indices))


def sym(name: str) -> Index:
    return Index(kind="symbol", value=name)


def lit(value: Any) -> Index:
    return Index(kind="literal", value=_canon_element(value))


@dataclass
class SetDecl:
    name: str
    elements: list[str]
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "elements": list(self.elements)}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SetDecl":
        return SetDecl(name=str(data["name"]), elements=[_canon_element(e) for e in data["elements"]])


@dataclass
class ParamDecl:
    name: str
    index_sets: list[str] = field(default_factory=list)
    values: dict[tuple[str, ...], float] = field(default_factory=dict)
    default: float | None = None
    line: int = 0

    def get(self, index: tuple[str, ...]) -> float:
        key = tuple(_canon_element(part) for part in index)
        if key in self.values:
            return self.values[key]
        if self.default is not None:
            return self.default
        shown = ",".join(key) if key else self.name
        from axiom.errors import AxiomError

        raise AxiomError(
            f"参数 {self.name}[{shown}] 没有数据，也没有 default。",
            f"Parameter {self.name}[{shown}] has no data and no default.",
            code="missing_data",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index_sets": list(self.index_sets),
            "default": self.default,
            "values": [
                {"index": list(key), "value": value}
                for key, value in self.values.items()
            ],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ParamDecl":
        values: dict[tuple[str, ...], float] = {}
        for item in data.get("values", []):
            key = tuple(_canon_element(part) for part in item.get("index", []))
            values[key] = float(item["value"])
        default = data.get("default", None)
        return ParamDecl(
            name=str(data["name"]),
            index_sets=[str(name) for name in data.get("index_sets", [])],
            values=values,
            default=None if default is None else float(default),
        )


@dataclass
class VarDecl:
    name: str
    index_sets: list[str] = field(default_factory=list)
    domain: Domain = "continuous"
    lower: float | None = None
    upper: float | None = None
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index_sets": list(self.index_sets),
            "domain": self.domain,
            "lower": self.lower,
            "upper": self.upper,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "VarDecl":
        lower = data.get("lower", None)
        upper = data.get("upper", None)
        return VarDecl(
            name=str(data["name"]),
            index_sets=[str(name) for name in data.get("index_sets", [])],
            domain=data.get("domain", "continuous"),
            lower=None if lower is None else float(lower),
            upper=None if upper is None else float(upper),
        )


@dataclass
class Objective:
    name: str
    sense: Sense
    expr: Expr
    weight: float = 1.0
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sense": self.sense,
            "weight": self.weight,
            "expr": self.expr.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Objective":
        return Objective(
            name=str(data["name"]),
            sense=data["sense"],
            expr=Expr.from_dict(data["expr"]),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass
class Constraint:
    name: str
    quants: tuple[Quantifier, ...] = ()
    kind: Literal["comparison", "alldiff"] = "comparison"
    relation: Relation | None = None
    lhs: Expr | None = None
    rhs: Expr | None = None
    alldiff_quants: tuple[Quantifier, ...] = ()
    alldiff_ref: Expr | None = None
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "quantifiers": [q.to_dict() for q in self.quants],
            "kind": self.kind,
        }
        if self.kind == "comparison":
            payload["relation"] = self.relation
            payload["lhs"] = None if self.lhs is None else self.lhs.to_dict()
            payload["rhs"] = None if self.rhs is None else self.rhs.to_dict()
        else:
            payload["alldiff_quantifiers"] = [q.to_dict() for q in self.alldiff_quants]
            payload["alldiff_ref"] = None if self.alldiff_ref is None else self.alldiff_ref.to_dict()
        return payload

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Constraint":
        kind = data.get("kind", "comparison")
        return Constraint(
            name=str(data["name"]),
            quants=tuple(Quantifier.from_dict(item) for item in data.get("quantifiers", [])),
            kind=kind,
            relation=data.get("relation"),
            lhs=Expr.from_dict(data["lhs"]) if data.get("lhs") else None,
            rhs=Expr.from_dict(data["rhs"]) if data.get("rhs") else None,
            alldiff_quants=tuple(
                Quantifier.from_dict(item) for item in data.get("alldiff_quantifiers", [])
            ),
            alldiff_ref=Expr.from_dict(data["alldiff_ref"]) if data.get("alldiff_ref") else None,
        )


@dataclass
class SosSet:
    """SOS1: at most one listed variable may be nonzero."""

    name: str
    members: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "members": list(self.members)}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SosSet":
        return SosSet(name=str(data["name"]), members=[str(item) for item in data.get("members", [])])


@dataclass
class Piecewise:
    """Convex-combination breakpoints of a scalar piecewise-linear function."""

    name: str
    variable: str
    points: list[tuple[float, float]]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "variable": self.variable, "points": [list(point) for point in self.points]}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Piecewise":
        points = [(float(item[0]), float(item[1])) for item in data.get("points", [])]
        return Piecewise(name=str(data["name"]), variable=str(data["variable"]), points=points)


@dataclass
class Model:
    name: str = "model"
    sets: dict[str, SetDecl] = field(default_factory=dict)
    parameters: dict[str, ParamDecl] = field(default_factory=dict)
    variables: dict[str, VarDecl] = field(default_factory=dict)
    objectives: list[Objective] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    sos: list[SosSet] = field(default_factory=list)
    pieces: list[Piecewise] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def objective_map(self) -> dict[str, Objective]:
        return {obj.name: obj for obj in self.objectives}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "meta": dict(self.meta),
            "sets": [item.to_dict() for item in self.sets.values()],
            "parameters": [item.to_dict() for item in self.parameters.values()],
            "variables": [item.to_dict() for item in self.variables.values()],
            "objectives": [item.to_dict() for item in self.objectives],
            "constraints": [item.to_dict() for item in self.constraints],
            "sos": [item.to_dict() for item in self.sos],
            "pieces": [item.to_dict() for item in self.pieces],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Model":
        model = Model(name=str(data.get("name") or "model"), meta=dict(data.get("meta") or {}))
        for item in data.get("sets", []):
            decl = SetDecl.from_dict(item)
            model.sets[decl.name] = decl
        for item in data.get("parameters", []):
            decl = ParamDecl.from_dict(item)
            model.parameters[decl.name] = decl
        for item in data.get("variables", []):
            decl = VarDecl.from_dict(item)
            model.variables[decl.name] = decl
        model.objectives = [Objective.from_dict(item) for item in data.get("objectives", [])]
        model.constraints = [Constraint.from_dict(item) for item in data.get("constraints", [])]
        model.sos = [SosSet.from_dict(item) for item in data.get("sos", [])]
        model.pieces = [Piecewise.from_dict(item) for item in data.get("pieces", [])]
        return model

    def copy(self) -> "Model":
        return Model.from_dict(self.to_dict())


def var_key(name: str, indices: tuple[str, ...] | list[str]) -> str:
    if not indices:
        return name
    return f"{name}[{','.join(indices)}]"


def cartesian(model: Model, set_names: list[str]) -> list[tuple[str, ...]]:
    if not set_names:
        return [()]
    pools = [model.sets[name].elements for name in set_names]
    rows: list[tuple[str, ...]] = [()]
    for pool in pools:
        rows = [row + (item,) for row in rows for item in pool]
    return rows
