"""Multidisciplinary problem statement.

A discipline is a function of a shared state. Coupling variables are the
outputs of one discipline that another discipline reads. Design variables are
either shared or owned by one discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


State = dict[str, float]
Evaluator = Callable[[State], dict[str, float]]
ConstraintFn = Callable[[State], list[tuple[str, float]]]


@dataclass
class DesignVar:
    name: str
    lower: float
    upper: float
    initial: float
    owner: str | None = None
    unit: str = ""


@dataclass
class Discipline:
    name: str
    inputs: list[str]
    outputs: list[str]
    evaluate: Evaluator
    constraints: ConstraintFn | None = None


@dataclass
class MDOProblem:
    name: str
    title_zh: str
    title_en: str
    design: list[DesignVar]
    couplings: list[str]
    disciplines: list[Discipline]
    objective: Callable[[State], float]
    sense: str = "minimize"
    units: dict[str, str] = field(default_factory=dict)
    contributions: Callable[[State], dict[str, float]] | None = None

    def initial_state(self) -> State:
        return {var.name: float(var.initial) for var in self.design}

    def design_names(self) -> list[str]:
        return [var.name for var in self.design]
