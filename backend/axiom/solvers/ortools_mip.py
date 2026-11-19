"""OR-Tools linear solvers: SCIP for MIP and GLOP for pure LP."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, bounds, failure, has_integer, not_applicable, opt_float


class _OrtoolsLinear:
    backend = "SCIP"
    name = "scip"
    label = "SCIP"
    capabilities = {"lp", "mip"}
    license = "open"
    integer_ok = True

    def available(self) -> bool:
        try:
            from ortools.linear_solver import pywraplp

            return pywraplp.Solver.CreateSolver(self.backend) is not None
        except ImportError:
            return False

    def version(self) -> str:
        try:
            from ortools import __version__

            return str(__version__)
        except Exception:
            return ""

    def detail(self) -> str:
        return f"OR-Tools {self.backend} backend."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear:
            return not_applicable(self.name, started, f"{self.label} 只求解线性模型。", f"{self.label} only solves linear models.")
        if has_integer(flat) and not self.integer_ok:
            return not_applicable(
                self.name,
                started,
                f"{self.label} 不求解整数变量，已跳过。",
                f"{self.label} does not solve integer variables and was skipped.",
            )
        try:
            from ortools.linear_solver import pywraplp
        except ImportError:
            return failure(self.name, started, "未安装 ortools。", "ortools is not installed.", "missing")
        solver = pywraplp.Solver.CreateSolver(self.backend)
        if solver is None:
            return failure(self.name, started, f"OR-Tools 没有 {self.backend} 后端。", f"OR-Tools has no {self.backend} backend.")
        try:
            limit = opt_float(options, "time_limit")
            if limit:
                solver.SetTimeLimit(int(limit * 1000))
            inf = solver.infinity()
            columns = []
            for var in flat.variables:
                lower, upper = bounds(var)
                lower = -inf if lower <= -INF / 2 else lower
                upper = inf if upper >= INF / 2 else upper
                if var.domain in {"integer", "binary"}:
                    columns.append(solver.IntVar(lower, upper, var.key[:80]))
                else:
                    columns.append(solver.NumVar(lower, upper, var.key[:80]))
            by_key = {var.key: columns[i] for i, var in enumerate(flat.variables)}
            objective = solver.Objective()
            for key, coef in flat.objective.items():
                objective.SetCoefficient(by_key[key], float(coef))
            if abs(flat.objective_const) > 1e-12 and hasattr(objective, "SetOffset"):
                objective.SetOffset(float(flat.objective_const))
            if flat.sense == "maximize":
                objective.SetMaximization()
            else:
                objective.SetMinimization()
            for con in flat.constraints:
                lower, upper = _row(con.sense, con.rhs, inf)
                row = solver.Constraint(lower, upper, con.key[:80])
                for key, coef in con.coeffs.items():
                    row.SetCoefficient(by_key[key], float(coef))
            code = solver.Solve()
            raw = _raw(pywraplp, code)
            status = {
                "OPTIMAL": "optimal",
                "FEASIBLE": "feasible",
                "INFEASIBLE": "infeasible",
                "UNBOUNDED": "unbounded",
                "ABNORMAL": "error",
                "NOT_SOLVED": "error",
            }.get(raw, "error")
            values = {}
            reduced = {}
            duals = {}
            if status in {"optimal", "feasible"}:
                values = {var.key: float(columns[i].solution_value()) for i, var in enumerate(flat.variables)}
                if not has_integer(flat):
                    for i, var in enumerate(flat.variables):
                        reduced[var.key] = float(columns[i].reduced_cost())
            offset_missing = abs(flat.objective_const) > 1e-12 and not hasattr(objective, "SetOffset")
            result = assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=f"{self.label} 状态：{raw}。",
                message_en=f"{self.label} status: {raw}.",
                duals=duals,
                reduced_costs=reduced,
            )
            if offset_missing and result.objective is not None:
                result.objective += 0.0
            return result
        except Exception as exc:
            return failure(self.name, started, f"{self.label} 求解失败：{exc}", f"{self.label} failed: {exc}")


def _row(sense: str, rhs: float, inf: float) -> tuple[float, float]:
    if sense == "<=":
        return -inf, float(rhs)
    if sense == ">=":
        return float(rhs), inf
    return float(rhs), float(rhs)


def _raw(pywraplp, code: int) -> str:
    mapping = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }
    return mapping.get(code, str(code))


class ScipSolver(_OrtoolsLinear):
    backend = "SCIP"
    name = "scip"
    label = "SCIP"
    capabilities = {"lp", "mip"}
    integer_ok = True

    def available(self) -> bool:
        from axiom.solvers.ortools_proc import ortools_available

        return ortools_available()

    def version(self) -> str:
        from axiom.solvers.ortools_proc import ortools_version

        return ortools_version() if self.available() else ""

    def detail(self) -> str:
        return "SCIP mixed-integer solver shipped inside OR-Tools, executed in a separate process so it does not clash with HiGHS."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        from axiom.solvers.ortools_proc import solve_isolated

        return solve_isolated(model, flat, "SCIP", options, self.name, self.label)


class GlopSolver(_OrtoolsLinear):
    backend = "GLOP"
    name = "glop"
    label = "GLOP"
    capabilities = {"lp"}
    integer_ok = False

    def available(self) -> bool:
        from axiom.solvers.ortools_proc import ortools_available

        return ortools_available()

    def version(self) -> str:
        from axiom.solvers.ortools_proc import ortools_version

        return ortools_version() if self.available() else ""

    def detail(self) -> str:
        return "OR-Tools GLOP simplex solver for pure linear programs, executed out of process."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        from axiom.solvers.ortools_proc import solve_isolated

        return solve_isolated(model, flat, "GLOP", options, self.name, self.label)
