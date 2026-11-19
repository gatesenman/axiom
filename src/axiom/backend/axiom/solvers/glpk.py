"""GLPK adapter. Solves the LP file we export with the glpsol executable."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.bundled import executable
from axiom.solvers.common import assemble, failure, not_applicable


class GlpkSolver:
    name = "glpk"
    label = "GLPK"
    capabilities = {"lp", "mip"}
    license = "open"

    def available(self) -> bool:
        return executable("glpsol") is not None

    def version(self) -> str:
        return "glpsol" if self.available() else ""

    def detail(self) -> str:
        if self.available():
            return "GNU Linear Programming Kit via the bundled glpsol executable."
        return "glpsol was not found beside the app. The Windows package includes it under solvers/."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if not self.available():
            return failure(self.name, started, "未找到 glpsol。", "glpsol was not found.", "missing")
        if flat.nonlinear:
            return not_applicable(self.name, started, "GLPK 只求解线性模型。", "GLPK only solves linear models.")
        try:
            import pulp

            sense = pulp.LpMaximize if flat.sense == "maximize" else pulp.LpMinimize
            problem = pulp.LpProblem(flat.name or "axiom", sense)
            columns = {}
            for var in flat.variables:
                cat = pulp.LpInteger if var.domain in {"integer", "binary"} else pulp.LpContinuous
                columns[var.key] = pulp.LpVariable(
                    _name(var.key),
                    lowBound=None if var.lower is None else var.lower,
                    upBound=None if var.upper is None else var.upper,
                    cat=cat,
                )
            expr = flat.objective_const
            for key, coef in flat.objective.items():
                expr += coef * columns[key]
            problem += expr
            for con in flat.constraints:
                row = pulp.lpSum(coef * columns[key] for key, coef in con.coeffs.items())
                label = _name(con.key)
                if con.sense == "<=":
                    problem += row <= con.rhs, label
                elif con.sense == ">=":
                    problem += row >= con.rhs, label
                else:
                    problem += row == con.rhs, label
            binary = executable("glpsol")
            code = problem.solve(pulp.GLPK_CMD(msg=False, path=binary))
            raw = pulp.LpStatus.get(code, str(code))
            status = {
                "Optimal": "optimal",
                "Infeasible": "infeasible",
                "Unbounded": "unbounded",
                "Undefined": "unbounded_or_infeasible",
            }.get(raw, "error")
            values = {}
            if status in {"optimal", "feasible"}:
                values = {key: float(pulp.value(var) or 0.0) for key, var in columns.items()}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=f"GLPK 状态：{raw}。",
                message_en=f"GLPK status: {raw}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"GLPK 求解失败：{exc}", f"GLPK failed: {exc}")


def _name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    return cleaned[:180]
