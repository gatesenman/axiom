"""OR-Tools CP-SAT adapter for integer and binary models, including alldiff."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import has_integer, integral_data, not_applicable


class CpSatSolver:
    name = "cp-sat"
    label = "OR-Tools CP-SAT"
    capabilities = {"cp", "mip"}
    license = "open"

    def available(self) -> bool:
        from axiom.solvers.ortools_proc import ortools_available

        return ortools_available()

    def version(self) -> str:
        from axiom.solvers.ortools_proc import ortools_version

        return ortools_version() if self.available() else ""

    def detail(self) -> str:
        return "Constraint-programming SAT solver for integer programs and alldiff models with integral data."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear:
            return not_applicable(self.name, started, "CP-SAT 不求解连续非线性模型。", "CP-SAT does not solve continuous nonlinear models.")
        if any(var.domain == "continuous" for var in flat.variables):
            return not_applicable(
                self.name,
                started,
                "CP-SAT 需要全部变量为整数或 0-1。",
                "CP-SAT requires every variable to be integer or binary.",
            )
        if not has_integer(flat) or not integral_data(flat):
            return not_applicable(
                self.name,
                started,
                "CP-SAT 需要整数系数、整数右端项和整数变量界。",
                "CP-SAT requires integral coefficients, right-hand sides, and bounds.",
            )
        from axiom.solvers.ortools_proc import solve_isolated

        return solve_isolated(model, flat, "CP-SAT", options, self.name, self.label)
