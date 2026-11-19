"""Bounded enumeration for tiny integer and binary models.

This adapter is used only when the catalog method ``local-search`` is selected.
It stays out of the default solver race.
"""

from __future__ import annotations

import itertools
import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import assemble, has_integer, not_applicable, objective_value


class LocalSearchSolver:
    name = "local"
    label = "Local search"
    capabilities = {"mip"}
    license = "open"

    def available(self) -> bool:
        return True

    def version(self) -> str:
        return "1"

    def detail(self) -> str:
        return "Enumerates binary variables and integer variables whose bounds span at most 8, when the domain product is at most 8192."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear or not has_integer(flat):
            return not_applicable(
                self.name,
                started,
                "局部搜索只用于带有限界的整数或 0-1 模型。",
                "Local search only applies to bounded integer or binary models.",
            )
        domains: list[tuple[str, list[float]]] = []
        for var in flat.variables:
            if var.domain == "binary":
                domains.append((var.key, [0.0, 1.0]))
                continue
            if var.domain == "integer":
                if var.lower is None or var.upper is None:
                    return not_applicable(
                        self.name,
                        started,
                        f"整数变量 {var.key} 没有有限界，无法枚举。",
                        f"Integer variable {var.key} has no finite bounds, so it cannot be enumerated.",
                    )
                lo = int(round(var.lower))
                hi = int(round(var.upper))
                if hi < lo or hi - lo > 8:
                    return not_applicable(
                        self.name,
                        started,
                        f"整数变量 {var.key} 的跨度超过 8，局部搜索不适用。",
                        f"Integer variable {var.key} spans more than 8, so local search does not apply.",
                    )
                domains.append((var.key, [float(value) for value in range(lo, hi + 1)]))
                continue
            return not_applicable(
                self.name,
                started,
                "局部搜索不处理连续变量。",
                "Local search does not handle continuous variables.",
            )
        product = 1
        for _key, values in domains:
            product *= len(values)
            if product > 8192:
                return not_applicable(
                    self.name,
                    started,
                    "定义域的乘积超过 8192，局部搜索不适用。",
                    "The product of the domains exceeds 8192, so local search does not apply.",
                )
        keys = [key for key, _values in domains]
        grids = [values for _key, values in domains]
        best: dict[str, float] | None = None
        best_objective: float | None = None
        for combo in itertools.product(*grids):
            values = dict(zip(keys, combo, strict=True))
            if not _feasible(flat, values):
                continue
            objective = objective_value(flat, values)
            better = best is None or (
                objective < float(best_objective) if flat.sense == "minimize" else objective > float(best_objective)
            )
            if better:
                best = values
                best_objective = objective
        if best is None:
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status="infeasible",
                values={},
                raw_status="infeasible",
                started=started,
                message="枚举没有找到可行解。",
                message_en="Enumeration found no feasible point.",
            )
        return assemble(
            solver=self.name,
            model=model,
            flat=flat,
            status="optimal",
            values=best,
            raw_status="enumerated",
            started=started,
            message="局部搜索枚举得到最优解。",
            message_en="Local search enumeration found an optimal point.",
        )


def _feasible(flat: FlatModel, values: dict[str, float]) -> bool:
    for con in flat.constraints:
        lhs = sum(coef * float(values.get(key, 0.0)) for key, coef in con.coeffs.items())
        if con.sense == "<=" and lhs > con.rhs + 1e-7:
            return False
        if con.sense == ">=" and lhs < con.rhs - 1e-7:
            return False
        if con.sense == "==" and abs(lhs - con.rhs) > 1e-6:
            return False
    return True
