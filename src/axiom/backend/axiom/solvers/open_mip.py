"""CLP, PDLP, PySCIPOpt, and python-mip adapters.

CLP and PDLP are the OR-Tools builds and run in the same isolated process as
GLOP, so the parent interpreter never loads OR-Tools next to HiGHS. PySCIPOpt
and python-mip are imported only when their own solve method runs.
"""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, failure, has_integer, not_applicable, opt_float


class ClpSolver:
    name = "clp"
    label = "CLP"
    capabilities = {"lp"}
    license = "open"

    def available(self) -> bool:
        from axiom.solvers.ortools_proc import backend_available

        return backend_available("CLP")

    def version(self) -> str:
        from axiom.solvers.ortools_proc import ortools_version

        return ortools_version() if self.available() else ""

    def detail(self) -> str:
        return "COIN-OR CLP simplex solver linked inside OR-Tools. LP only, out of process."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        from axiom.solvers.ortools_proc import solve_isolated

        return solve_isolated(model, flat, "CLP", options, self.name, self.label)


class PdlpSolver:
    name = "pdlp"
    label = "PDLP"
    capabilities = {"lp"}
    license = "open"

    def available(self) -> bool:
        from axiom.solvers.ortools_proc import backend_available

        return backend_available("PDLP")

    def version(self) -> str:
        from axiom.solvers.ortools_proc import ortools_version

        return ortools_version() if self.available() else ""

    def detail(self) -> str:
        return "OR-Tools PDLP first-order LP solver, executed out of process."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        from axiom.solvers.ortools_proc import solve_isolated

        return solve_isolated(model, flat, "PDLP", options, self.name, self.label)


class PyScipOptSolver:
    name = "pyscipopt"
    label = "SCIP (PySCIPOpt)"
    capabilities = {"lp", "mip", "qp"}
    license = "open"

    def available(self) -> bool:
        try:
            import pyscipopt  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        if not self.available():
            return ""
        import pyscipopt

        return str(getattr(pyscipopt, "__version__", "installed"))

    def detail(self) -> str:
        if self.available():
            return "PySCIPOpt bindings to the SCIP optimization suite, including quadratic constraints when SCIP accepts them."
        return "PySCIPOpt is bundled in the Windows package when its wheel is present. This environment cannot import it."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear and not getattr(flat, "quadratic", None):
            return not_applicable(self.name, started, "PySCIPOpt 适配器不求解一般非线性模型。", "This PySCIPOpt adapter does not solve general nonlinear models.")
        if getattr(flat, "cones", None):
            return not_applicable(self.name, started, "PySCIPOpt 适配器不求解二阶锥。", "This PySCIPOpt adapter does not solve second-order cones.")
        if not self.available():
            return failure(self.name, started, "未安装 pyscipopt。", "pyscipopt is not installed.", "missing")
        try:
            from pyscipopt import Model as ScipModel
            from pyscipopt import quicksum

            problem = ScipModel(flat.name or "axiom")
            problem.hideOutput()
            limit = opt_float(options, "time_limit")
            if limit:
                problem.setParam("limits/time", float(limit))
            columns = {}
            for var in flat.variables:
                lower = None if var.lower is None else float(var.lower)
                upper = None if var.upper is None else float(var.upper)
                vtype = "B" if var.domain == "binary" else "I" if var.domain == "integer" else "C"
                columns[var.key] = problem.addVar(name=var.key[:80], vtype=vtype, lb=lower, ub=upper)
            linear = quicksum(float(coef) * columns[key] for key, coef in flat.objective.items())
            if abs(flat.objective_const) > 1e-12:
                linear = linear + float(flat.objective_const)
            quad_terms = []
            for (left, right), coef in (getattr(flat, "quadratic", None) or {}).items():
                if abs(coef) < 1e-12:
                    continue
                if left == right:
                    quad_terms.append(float(coef) * columns[left] * columns[left])
                else:
                    quad_terms.append(float(coef) * columns[left] * columns[right])
            sense = "maximize" if flat.sense == "maximize" else "minimize"
            if quad_terms:
                # SCIP rejects a quadratic expression in setObjective. The epigraph is linear there.
                auxiliary = problem.addVar(name="_axiom_quad", vtype="C", lb=None, ub=None)
                quad = quicksum(quad_terms)
                if sense == "minimize":
                    problem.addCons(auxiliary >= quad)
                else:
                    problem.addCons(auxiliary <= quad)
                problem.setObjective(linear + auxiliary, sense=sense)
            else:
                problem.setObjective(linear, sense=sense)
            for con in flat.constraints:
                row = quicksum(float(coef) * columns[key] for key, coef in con.coeffs.items())
                if con.sense == "<=":
                    problem.addCons(row <= float(con.rhs))
                elif con.sense == ">=":
                    problem.addCons(row >= float(con.rhs))
                else:
                    problem.addCons(row == float(con.rhs))
            problem.optimize()
            raw = str(problem.getStatus())
            status = {"optimal": "optimal", "feasible": "feasible", "infeasible": "infeasible", "unbounded": "unbounded"}.get(raw, "error")
            values = {}
            if status in {"optimal", "feasible"}:
                values = {key: float(problem.getVal(var)) for key, var in columns.items()}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=f"PySCIPOpt 状态：{raw}。",
                message_en=f"PySCIPOpt status: {raw}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"PySCIPOpt 求解失败：{exc}", f"PySCIPOpt failed: {exc}")


class PythonMipSolver:
    name = "python-mip"
    label = "python-mip"
    capabilities = {"lp", "mip"}
    license = "open"

    def available(self) -> bool:
        try:
            import mip  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        if not self.available():
            return ""
        import mip

        return str(getattr(mip, "__version__", "installed"))

    def detail(self) -> str:
        if self.available():
            return "python-mip with its bundled CBC library."
        return "python-mip is not importable. The Windows package includes the mip wheel and CBC library."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear or getattr(flat, "quadratic", None) or getattr(flat, "cones", None):
            return not_applicable(self.name, started, "python-mip 只求解线性模型。", "python-mip only solves linear models.")
        if not self.available():
            return failure(self.name, started, "未安装 python-mip。", "python-mip is not installed.", "missing")
        try:
            import mip

            sense = mip.MAXIMIZE if flat.sense == "maximize" else mip.MINIMIZE
            problem = mip.Model(sense=sense, solver_name=mip.CBC)
            problem.verbose = 0
            limit = opt_float(options, "time_limit")
            if limit:
                problem.max_seconds = float(limit)
            columns = {}
            for var in flat.variables:
                kind = mip.BINARY if var.domain == "binary" else mip.INTEGER if var.domain == "integer" else mip.CONTINUOUS
                columns[var.key] = problem.add_var(
                    name=var.key[:80],
                    lb=-mip.INF if var.lower is None else float(var.lower),
                    ub=mip.INF if var.upper is None else float(var.upper),
                    var_type=kind,
                )
            problem.objective = mip.xsum(float(coef) * columns[key] for key, coef in flat.objective.items()) + float(flat.objective_const)
            for con in flat.constraints:
                row = mip.xsum(float(coef) * columns[key] for key, coef in con.coeffs.items())
                if con.sense == "<=":
                    problem += row <= float(con.rhs)
                elif con.sense == ">=":
                    problem += row >= float(con.rhs)
                else:
                    problem += row == float(con.rhs)
            raw_status = problem.optimize()
            raw = str(raw_status)
            status = {mip.OptimizationStatus.OPTIMAL: "optimal", mip.OptimizationStatus.FEASIBLE: "feasible", mip.OptimizationStatus.INFEASIBLE: "infeasible", mip.OptimizationStatus.UNBOUNDED: "unbounded"}.get(raw_status, "error")
            values = {}
            if status in {"optimal", "feasible"}:
                values = {key: float(var.x or 0.0) for key, var in columns.items()}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=f"python-mip 状态：{raw}。",
                message_en=f"python-mip status: {raw}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"python-mip 求解失败：{exc}", f"python-mip failed: {exc}")
