"""CBC adapter. Uses PuLP's bundled CBC binary, then a system cbc if present."""

from __future__ import annotations

import shutil
import time
from typing import Any

import pulp

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import assemble, failure, not_applicable, opt_float


class CbcSolver:
    name = "cbc"
    label = "CBC"
    capabilities = {"lp", "mip"}
    license = "open"

    def available(self) -> bool:
        return shutil.which("cbc") is not None or hasattr(pulp, "PULP_CBC_CMD")

    def version(self) -> str:
        return "PuLP CBC" if hasattr(pulp, "PULP_CBC_CMD") else ""

    def detail(self) -> str:
        return "COIN-OR Branch and Cut via PuLP's bundled executable, with the system cbc as a fallback."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear:
            return not_applicable(self.name, started, "CBC 只求解线性模型。", "CBC only solves linear models.")
        try:
            sense = pulp.LpMaximize if flat.sense == "maximize" else pulp.LpMinimize
            problem = pulp.LpProblem(flat.name or "axiom", sense)
            columns = {}
            for var in flat.variables:
                cat = pulp.LpInteger if var.domain in {"integer", "binary"} else pulp.LpContinuous
                low = None if var.lower is None else var.lower
                up = None if var.upper is None else var.upper
                columns[var.key] = pulp.LpVariable(_pulp_name(var.key), lowBound=low, upBound=up, cat=cat)
            objective = flat.objective_const
            for key, coef in flat.objective.items():
                objective += coef * columns[key]
            problem += objective
            for con in flat.constraints:
                expr = pulp.lpSum(coef * columns[key] for key, coef in con.coeffs.items())
                if con.sense == "<=":
                    problem += expr <= con.rhs, _pulp_name(con.key)
                elif con.sense == ">=":
                    problem += expr >= con.rhs, _pulp_name(con.key)
                else:
                    problem += expr == con.rhs, _pulp_name(con.key)
            limit = opt_float(options, "time_limit")
            gap = opt_float(options, "mip_gap")
            cmd_options = []
            if gap is not None:
                cmd_options.append(f"ratio {gap}")
            solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=limit, options=cmd_options or None)
            raw_code = problem.solve(solver)
            raw = pulp.LpStatus.get(raw_code, str(raw_code))
            status = _map(raw)
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
                message=f"CBC 状态：{raw}。",
                message_en=f"CBC status: {raw}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"CBC 求解失败：{exc}", f"CBC failed: {exc}")


def _map(status: str) -> str:
    table = {
        "Optimal": "optimal",
        "Not Solved": "error",
        "Infeasible": "infeasible",
        "Unbounded": "unbounded",
        "Undefined": "unbounded_or_infeasible",
    }
    return table.get(status, "error")


def _pulp_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    return cleaned[:180]
