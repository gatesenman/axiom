"""Resolve AML subscripts against the active quantifier environment."""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.ir import Index, Model


def resolve_index(
    index: Index,
    env: dict[str, str],
    qmap: dict[str, str],
    model: Model,
) -> str:
    if index.kind == "literal":
        return index.value
    if index.kind == "symbol":
        if index.value in env:
            return env[index.value]
        return index.value
    if index.value not in env:
        raise AxiomError(
            f"下标 {index.value} 没有绑定。",
            f"Index {index.value} is not bound.",
            code="free_index",
        )
    current = env[index.value]
    set_name = qmap.get(index.value)
    elements = model.sets[set_name].elements if set_name and set_name in model.sets else None
    if index.kind == "prev":
        if not elements or current not in elements:
            raise AxiomError(
                f"prev({index.value}) 无法在集合中定位 {current}。",
                f"prev({index.value}) cannot locate {current} in its set.",
                code="bad_index",
            )
        position = elements.index(current)
        if position == 0:
            raise AxiomError(
                f"prev({index.value}) 在集合第一个元素 {current} 上没有前驱。",
                f"prev({index.value}) has no predecessor at the first element {current}.",
                code="bad_index",
            )
        return elements[position - 1]
    if index.kind == "offset":
        if _is_int_text(current):
            return str(int(current) + index.offset)
        if not elements or current not in elements:
            raise AxiomError(
                f"下标偏移 {index.value}{index.offset:+d} 无法解释。",
                f"Index offset {index.value}{index.offset:+d} cannot be resolved.",
                code="bad_index",
            )
        position = elements.index(current) + index.offset
        if position < 0 or position >= len(elements):
            raise AxiomError(
                f"下标 {index.value}{index.offset:+d} 从 {current} 起超出集合 {set_name}（共 {len(elements)} 个元素）。",
                f"Index {index.value}{index.offset:+d} from {current} falls outside set {set_name} ({len(elements)} elements).",
                code="bad_index",
            )
        return elements[position]
    raise AxiomError(
        f"未知下标类型 {index.kind}。",
        f"Unknown index kind {index.kind}.",
        code="bad_index",
    )


def _is_int_text(value: str) -> bool:
    if value.startswith("-"):
        value = value[1:]
    return value.isdigit()
