"""CPLEX adapter. Uses docplex when available, otherwise the cplex Python API."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import assemble, failure, not_applicable, opt_float


class CplexSolver:
    name = "cplex"
    label = "CPLEX"
    capabilities = {"lp", "mip", "qp"}
    license = "commercial"

    def license_state(self) -> str:
        docplex_ok = False
        cplex_ok = False
        try:
            import docplex.mp.model  # noqa: F401

            docplex_ok = True
        except ImportError:
            pass
        try:
            import cplex  # noqa: F401

            cplex_ok = True
        except ImportError:
            pass
        if not docplex_ok and not cplex_ok:
            return "not_installed"
        try:
            if cplex_ok:
                import cplex

                problem = cplex.Cplex()
                problem.set_results_stream(None)
                problem.set_log_stream(None)
                problem.end()
                return "licensed"
            from docplex.mp.model import Model as CpxModel

            problem = CpxModel(name="probe")
            problem.binary_var()
            problem.solve()
            return "licensed"
        except Exception:
            return "unlicensed"

    def available(self) -> bool:
        return self.license_state() == "licensed"

    def version(self) -> str:
        return "installed" if self.license_state() != "not_installed" else ""

    def detail(self) -> str:
        state = self.license_state()
        if state == "licensed":
            return "Commercial LP/MILP/QP solver. docplex or the CPLEX Python API accepted a license."
        if state == "unlicensed":
            return "docplex or cplex is installed but no license was accepted. CPLEX is not bundled."
        return "CPLEX is not installed. It is not bundled; install docplex or the cplex package and a license. https://www.ibm.com/docs/en/icos"

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if not self.available():
            return failure(self.name, started, "未安装 docplex 或 cplex。", "Neither docplex nor cplex is installed.", "missing")
        if flat.nonlinear:
            return not_applicable(self.name, started, "当前 CPLEX 适配器求解线性模型。", "This CPLEX adapter solves linear models.")
        try:
            import docplex.mp.model

            return self._docplex(model, flat, options, started)
        except ImportError:
            return self._cplex_api(model, flat, options, started)
        except Exception as exc:
            return failure(self.name, started, f"CPLEX 求解失败：{exc}", f"CPLEX failed: {exc}")

    def _docplex(self, model, flat, options, started):
        from docplex.mp.model import Model as CpxModel

        problem = CpxModel(name=flat.name or "axiom")
        problem.context.solver.log_output = False
        if opt_float(options, "time_limit"):
            problem.set_time_limit(float(options["time_limit"]))
        columns = {}
        for var in flat.variables:
            if var.domain == "binary":
                columns[var.key] = problem.binary_var(name=var.key[:80])
            elif var.domain == "integer":
                columns[var.key] = problem.integer_var(lb=var.lower, ub=var.upper, name=var.key[:80])
            else:
                columns[var.key] = problem.continuous_var(lb=var.lower, ub=var.upper, name=var.key[:80])
        expr = flat.objective_const + sum(coef * columns[key] for key, coef in flat.objective.items())
        if flat.sense == "maximize":
            problem.maximize(expr)
        else:
            problem.minimize(expr)
        for con in flat.constraints:
            row = sum(coef * columns[key] for key, coef in con.coeffs.items())
            if con.sense == "<=":
                problem.add_constraint(row <= con.rhs)
            elif con.sense == ">=":
                problem.add_constraint(row >= con.rhs)
            else:
                problem.add_constraint(row == con.rhs)
        solution = problem.solve()
        status = "optimal" if solution is not None else "infeasible"
        values = {}
        if solution is not None:
            values = {key: float(solution.get_value(var)) for key, var in columns.items()}
            if problem.solve_details.status_code in {101, 102}:
                status = "optimal"
        return assemble(
            solver=self.name,
            model=model,
            flat=flat,
            status=status,
            values=values,
            raw_status=str(getattr(problem.solve_details, "status", "")),
            started=started,
            message="CPLEX 求解完成。" if values else "CPLEX 未返回可行解。",
            message_en="CPLEX finished." if values else "CPLEX did not return a feasible solution.",
        )

    def _cplex_api(self, model, flat, options, started):
        import cplex

        problem = cplex.Cplex()
        problem.set_results_stream(None)
        problem.set_log_stream(None)
        problem.objective.set_sense(
            problem.objective.sense.maximize if flat.sense == "maximize" else problem.objective.sense.minimize
        )
        names, lb, ub, types, obj = [], [], [], [], []
        for var in flat.variables:
            names.append(var.key[:80])
            lb.append(-cplex.infinity if var.lower is None else var.lower)
            ub.append(cplex.infinity if var.upper is None else var.upper)
            types.append("B" if var.domain == "binary" else "I" if var.domain == "integer" else "C")
            obj.append(float(flat.objective.get(var.key, 0.0)))
        problem.variables.add(obj=obj, lb=lb, ub=ub, types=types, names=names)
        rows, senses, rhs = [], [], []
        for con in flat.constraints:
            rows.append([[key[:80] for key in con.coeffs], list(con.coeffs.values())])
            senses.append({"<=": "L", ">=": "G", "==": "E"}[con.sense])
            rhs.append(float(con.rhs))
        if rows:
            problem.linear_constraints.add(lin_expr=rows, senses=senses, rhs=rhs)
        if opt_float(options, "time_limit"):
            problem.parameters.timelimit.set(float(options["time_limit"]))
        problem.solve()
        raw = str(problem.solution.get_status_string())
        code = problem.solution.get_status()
        optimal = code in {1, 101, 102}
        feasible = optimal or code in {23, 107, 131}
        values = {}
        if feasible:
            got = problem.solution.get_values()
            values = {var.key: float(got[i]) for i, var in enumerate(flat.variables)}
        return assemble(
            solver=self.name,
            model=model,
            flat=flat,
            status="optimal" if optimal else "feasible" if feasible else "infeasible",
            values=values,
            raw_status=raw,
            started=started,
            message=f"CPLEX 状态：{raw}。",
            message_en=f"CPLEX status: {raw}.",
        )
