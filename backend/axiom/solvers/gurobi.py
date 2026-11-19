"""Gurobi adapter. Active only when gurobipy imports and a license is present."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, failure, not_applicable, opt_float


class GurobiSolver:
    name = "gurobi"
    label = "Gurobi"
    capabilities = {"lp", "mip", "qp"}
    license = "commercial"

    def license_state(self) -> str:
        try:
            import gurobipy as gp
        except ImportError:
            return "not_installed"
        try:
            env = gp.Env(empty=True)
            env.setParam("OutputFlag", 0)
            env.start()
            env.dispose()
            return "licensed"
        except Exception:
            return "unlicensed"

    def available(self) -> bool:
        return self.license_state() == "licensed"

    def version(self) -> str:
        if self.license_state() == "not_installed":
            return ""
        import gurobipy

        return str(getattr(gurobipy.gurobi, "version", lambda: ("",))())

    def detail(self) -> str:
        state = self.license_state()
        if state == "licensed":
            return "Commercial LP/MILP/QP solver. gurobipy accepted a license."
        if state == "unlicensed":
            return "gurobipy is installed but no license was accepted. Gurobi is not bundled."
        return "Gurobi is not installed. It is not bundled; install gurobipy and a license to enable it. https://www.gurobi.com/documentation/"

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if not self.available():
            return failure(self.name, started, "未安装 gurobipy。", "gurobipy is not installed.", "missing")
        if flat.nonlinear:
            return not_applicable(self.name, started, "当前 Gurobi 适配器求解线性与二次模型；该模型被判定为一般非线性。", "This Gurobi adapter solves linear models; the model is generally nonlinear.")
        try:
            import gurobipy as gp
            from gurobipy import GRB

            env = gp.Env(empty=True)
            env.setParam("OutputFlag", 0)
            env.start()
            problem = gp.Model(env=env)
            problem.Params.OutputFlag = 0
            if opt_float(options, "time_limit"):
                problem.Params.TimeLimit = float(options["time_limit"])
            if opt_float(options, "mip_gap") is not None:
                problem.Params.MIPGap = float(options["mip_gap"])
            columns = {}
            for var in flat.variables:
                lower = -GRB.INFINITY if var.lower is None else var.lower
                upper = GRB.INFINITY if var.upper is None else var.upper
                vtype = GRB.BINARY if var.domain == "binary" else GRB.INTEGER if var.domain == "integer" else GRB.CONTINUOUS
                columns[var.key] = problem.addVar(lb=lower, ub=upper, obj=float(flat.objective.get(var.key, 0.0)), vtype=vtype, name=var.key[:180])
            problem.ModelSense = GRB.MAXIMIZE if flat.sense == "maximize" else GRB.MINIMIZE
            if abs(flat.objective_const) > 1e-12:
                problem.ObjCon = float(flat.objective_const)
            for con in flat.constraints:
                expr = gp.LinExpr((list(con.coeffs.values()), [columns[key] for key in con.coeffs]))
                if con.sense == "<=":
                    problem.addConstr(expr <= con.rhs)
                elif con.sense == ">=":
                    problem.addConstr(expr >= con.rhs)
                else:
                    problem.addConstr(expr == con.rhs)
            problem.optimize()
            status_code = problem.Status
            status = {
                GRB.OPTIMAL: "optimal",
                GRB.INFEASIBLE: "infeasible",
                GRB.UNBOUNDED: "unbounded",
                GRB.INF_OR_UNBD: "unbounded_or_infeasible",
                GRB.TIME_LIMIT: "time_limit",
                GRB.SUBOPTIMAL: "feasible",
            }.get(status_code, "error")
            if status == "time_limit" and problem.SolCount:
                status = "feasible"
            values = {}
            if status in {"optimal", "feasible"}:
                values = {key: float(var.X) for key, var in columns.items()}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=str(status_code),
                started=started,
                message=f"Gurobi 状态码 {status_code}。",
                message_en=f"Gurobi status code {status_code}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"Gurobi 求解失败：{exc}", f"Gurobi failed: {exc}")
