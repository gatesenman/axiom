"""Solver adapter contract.

A new solver is a subclass of ``SolverAdapter`` registered in
``axiom.solvers.registry``. Adapters receive the original model and its flat
form. They must not mutate the model. Commercial solvers stay in-tree and
report ``available=False`` until their Python packages are installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model


@dataclass
class SolveResult:
    solver: str
    status: str
    objective: float | None
    objective_components: list[dict[str, Any]] = field(default_factory=list)
    variables: dict[str, float] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    duals: dict[str, float] = field(default_factory=dict)
    reduced_costs: dict[str, float] = field(default_factory=dict)
    runtime_sec: float = 0.0
    message: str = ""
    message_en: str = ""
    raw_status: str = ""
    feasible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "solver": self.solver,
            "status": self.status,
            "objective": self.objective,
            "objective_components": self.objective_components,
            "variables": self.variables,
            "constraints": self.constraints,
            "duals": self.duals,
            "reduced_costs": self.reduced_costs,
            "runtime_sec": self.runtime_sec,
            "message": self.message,
            "message_en": self.message_en,
            "raw_status": self.raw_status,
            "feasible": self.feasible,
        }


class SolverAdapter(Protocol):
    name: str
    label: str
    capabilities: set[str]
    license: str

    def available(self) -> bool: ...

    def version(self) -> str: ...

    def detail(self) -> str: ...

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]) -> SolveResult: ...
