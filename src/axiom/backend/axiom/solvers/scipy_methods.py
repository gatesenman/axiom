"""SciPy HiGHS (linprog / milp) and trust-constr, beside the existing SLSQP adapter."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, failure, has_integer, not_applicable
from axiom.solvers.nonlinear import ScipySolver


class ScipyHighsSolver:
    name = "scipy-highs"
    label = "SciPy HiGHS"
    capabilities = {"lp", "mip"}
    license = "open"

    def available(self) -> bool:
        try:
            from scipy.optimize import linprog, milp  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        if not self.available():
            return ""
        import scipy

        return str(scipy.__version__)

    def detail(self) -> str:
        return "SciPy's HiGHS wrapper: linprog for continuous LPs and milp for mixed-integer linear programs."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear or getattr(flat, "quadratic", None) or getattr(flat, "cones", None):
            return not_applicable(self.name, started, "SciPy HiGHS 只求解线性模型。", "SciPy HiGHS only solves linear models.")
        if not self.available():
            return failure(self.name, started, "未安装 SciPy。", "SciPy is not installed.", "missing")
        try:
            from scipy.optimize import Bounds, LinearConstraint, linprog, milp

            keys = [var.key for var in flat.variables]
            sign = -1.0 if flat.sense == "maximize" else 1.0
            cost = np.array([sign * float(flat.objective.get(key, 0.0)) for key in keys], dtype=float)
            lower = np.array([-np.inf if var.lower is None else float(var.lower) for var in flat.variables])
            upper = np.array([np.inf if var.upper is None else float(var.upper) for var in flat.variables])
            rows_ub, rhs_ub, rows_eq, rhs_eq = [], [], [], []
            for con in flat.constraints:
                row = [float(con.coeffs.get(key, 0.0)) for key in keys]
                if con.sense == "<=":
                    rows_ub.append(row)
                    rhs_ub.append(float(con.rhs))
                elif con.sense == ">=":
                    rows_ub.append([-value for value in row])
                    rhs_ub.append(-float(con.rhs))
                else:
                    rows_eq.append(row)
                    rhs_eq.append(float(con.rhs))
            a_ub = None if not rows_ub else np.array(rows_ub, dtype=float)
            b_ub = None if not rhs_ub else np.array(rhs_ub, dtype=float)
            a_eq = None if not rows_eq else np.array(rows_eq, dtype=float)
            b_eq = None if not rhs_eq else np.array(rhs_eq, dtype=float)
            if has_integer(flat):
                constraints = []
                if a_ub is not None:
                    constraints.append(LinearConstraint(a_ub, -np.inf, b_ub))
                if a_eq is not None:
                    constraints.append(LinearConstraint(a_eq, b_eq, b_eq))
                integrality = np.array([1 if var.domain in {"integer", "binary"} else 0 for var in flat.variables])
                result = milp(c=cost, integrality=integrality, bounds=Bounds(lower, upper), constraints=constraints)
                raw = str(result.message)
                status = "optimal" if result.success else "error"
                point = result.x
            else:
                result = linprog(
                    cost,
                    A_ub=a_ub,
                    b_ub=b_ub,
                    A_eq=a_eq,
                    b_eq=b_eq,
                    bounds=list(zip(lower, upper, strict=True)),
                    method="highs",
                )
                raw = str(result.message)
                status = "optimal" if result.success else "infeasible" if result.status == 2 else "unbounded" if result.status == 3 else "error"
                point = result.x
            values = {}
            if status == "optimal" and point is not None:
                values = {key: float(point[i]) for i, key in enumerate(keys)}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=f"SciPy HiGHS：{raw}",
                message_en=f"SciPy HiGHS: {raw}",
            )
        except Exception as exc:
            return failure(self.name, started, f"SciPy HiGHS 求解失败：{exc}", f"SciPy HiGHS failed: {exc}")


class TrustConstrSolver(ScipySolver):
    name = "trust-constr"
    label = "SciPy trust-constr"

    def detail(self) -> str:
        return "SciPy trust-region constrained solver for continuous nonlinear programs."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        refused = self._refuse(flat, started)
        if refused:
            return refused
        try:
            from scipy.optimize import minimize

            keys, lower, upper, start = self._pack(model, flat)
            objective, constraints, senses = self._functions(model, flat, keys)
            bound_pairs = []
            for lo, hi in zip(lower, upper, strict=True):
                bound_pairs.append((None if lo <= -INF / 2 else lo, None if hi >= INF / 2 else hi))
            cons = []
            for row, sense in enumerate(senses):
                if sense == "<=":
                    cons.append({"type": "ineq", "fun": lambda x, row=row: -constraints(x)[row]})
                elif sense == ">=":
                    cons.append({"type": "ineq", "fun": lambda x, row=row: constraints(x)[row]})
                else:
                    cons.append({"type": "eq", "fun": lambda x, row=row: constraints(x)[row]})
            result = minimize(objective, start, method="trust-constr", bounds=bound_pairs, constraints=cons, options={"maxiter": int(options.get("maxiter", 400)), "verbose": 0})
            status = "optimal" if result.success else "error"
            values = {key: float(result.x[i]) for i, key in enumerate(keys)}
            message = result.message if isinstance(result.message, str) else str(result.message)
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=message,
                started=started,
                message="trust-constr 求得局部最优。" if result.success else f"trust-constr 未收敛：{message}",
                message_en="trust-constr found a local optimum." if result.success else f"trust-constr did not converge: {message}",
            )
        except Exception as exc:
            return failure(self.name, started, f"trust-constr 求解失败：{exc}", f"trust-constr failed: {exc}")
