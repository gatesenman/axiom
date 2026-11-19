"""Nonlinear adapters: IPOPT (cyipopt) and a SciPy SLSQP fallback that is always available."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from axiom.modeling.evaluate import evaluate
from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, failure, has_integer, not_applicable, opt_float


class _NlpBase:
    capabilities = {"nlp", "lp"}
    license = "open"

    def _refuse(self, flat: FlatModel, started: float):
        if has_integer(flat):
            return not_applicable(
                self.name,
                started,
                f"{self.label} 求解连续松弛之外的整数模型会被拒绝；请改用 MIP 求解器。",
                f"{self.label} does not solve integer models. Use a MIP solver.",
            )
        return None

    def _pack(self, model: Model, flat: FlatModel):
        keys = [var.key for var in flat.variables]
        lower = []
        upper = []
        start = []
        for var in flat.variables:
            lo = -INF if var.lower is None else float(var.lower)
            hi = INF if var.upper is None else float(var.upper)
            lower.append(lo)
            upper.append(hi)
            if lo <= 0 <= hi:
                start.append(0.0)
            elif lo > -INF / 2 and hi < INF / 2:
                start.append(0.5 * (lo + hi))
            elif lo > -INF / 2:
                start.append(lo)
            else:
                start.append(hi)
        return keys, np.array(lower, dtype=float), np.array(upper, dtype=float), np.array(start, dtype=float)

    def _functions(self, model: Model, flat: FlatModel, keys: list[str]):
        sense = -1.0 if flat.sense == "maximize" else 1.0

        def values_of(x: np.ndarray) -> dict[str, float]:
            return {key: float(x[i]) for i, key in enumerate(keys)}

        def objective(x: np.ndarray) -> float:
            assignment = values_of(x)
            total = 0.0
            for obj in model.objectives:
                value = evaluate(model, obj.expr, assignment)
                if len(model.objectives) == 1:
                    total += sense * value
                else:
                    sign = 1.0 if obj.sense == "minimize" else -1.0
                    total += obj.weight * sign * value
            return float(total)

        rows = []
        expanded = flat.source or model
        for con in expanded.constraints:
            if con.kind != "comparison":
                continue
            from axiom.modeling.ir import cartesian

            names = [q.index for q in con.quants]
            sets = [q.set_name for q in con.quants]
            qmap = {q.index: q.set_name for q in con.quants}
            for combo in cartesian(expanded, sets):
                env = dict(zip(names, combo, strict=True))
                rows.append((con, env, qmap))

        def constraints(x: np.ndarray) -> np.ndarray:
            assignment = values_of(x)
            output = []
            for con, env, qmap in rows:
                lhs = evaluate(expanded, con.lhs, assignment, env, qmap)
                rhs = evaluate(expanded, con.rhs, assignment, env, qmap)
                output.append(lhs - rhs)
            return np.array(output, dtype=float)

        senses = [con.relation for con, _, _ in rows]
        return objective, constraints, senses


class IpoptSolver(_NlpBase):
    name = "ipopt"
    label = "IPOPT"

    def available(self) -> bool:
        try:
            import cyipopt  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        try:
            import cyipopt

            return str(getattr(cyipopt, "__version__", "installed"))
        except Exception:
            return ""

    def detail(self) -> str:
        if self.available():
            return "Interior-point nonlinear solver via cyipopt and COIN-OR Ipopt. Gradients are finite differences."
        return "No Windows build of cyipopt is bundled. Nonlinear models use SciPy instead."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        refused = self._refuse(flat, started)
        if refused:
            return refused
        if not self.available():
            return failure(self.name, started, "未安装 cyipopt/IPOPT。", "cyipopt/IPOPT is not installed.", "missing")
        try:
            import cyipopt

            keys, lower, upper, start = self._pack(model, flat)
            objective, constraints, senses = self._functions(model, flat, keys)
            cl, cu = [], []
            for sense in senses:
                if sense == "<=":
                    cl.append(-1e19)
                    cu.append(0.0)
                elif sense == ">=":
                    cl.append(0.0)
                    cu.append(1e19)
                else:
                    cl.append(0.0)
                    cu.append(0.0)

            class Problem:
                def objective(self, x):
                    return objective(np.asarray(x, dtype=float))

                def gradient(self, x):
                    return _gradient(objective, np.asarray(x, dtype=float))

                def constraints(self, x):
                    if not senses:
                        return np.zeros(0)
                    return constraints(np.asarray(x, dtype=float))

                def jacobian(self, x):
                    if not senses:
                        return np.zeros(0)
                    return _jacobian(constraints, np.asarray(x, dtype=float), len(senses), len(keys))

                def jacobianstructure(self):
                    rows, cols = [], []
                    for row in range(len(senses)):
                        for col in range(len(keys)):
                            rows.append(row)
                            cols.append(col)
                    return np.array(rows, dtype=int), np.array(cols, dtype=int)

            problem = cyipopt.Problem(
                n=len(keys),
                m=len(senses),
                problem_obj=Problem(),
                lb=lower,
                ub=upper,
                cl=np.array(cl, dtype=float),
                cu=np.array(cu, dtype=float),
            )
            problem.add_option("print_level", 0)
            problem.add_option("sb", "yes")
            limit = opt_float(options, "time_limit")
            if limit:
                problem.add_option("max_cpu_time", float(limit))
            vector, info = problem.solve(start)
            status_code = int(info.get("status", -1))
            status = "optimal" if status_code == 0 else "feasible" if status_code in {1, 6} else "error"
            values = {key: float(vector[i]) for i, key in enumerate(keys)}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=str(status_code),
                started=started,
                message=f"IPOPT 状态码 {status_code}。",
                message_en=f"IPOPT status code {status_code}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"IPOPT 求解失败：{exc}", f"IPOPT failed: {exc}")


class ScipySolver(_NlpBase):
    name = "scipy"
    label = "SciPy SLSQP"

    def available(self) -> bool:
        try:
            import scipy.optimize  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        try:
            import scipy

            return str(scipy.__version__)
        except Exception:
            return ""

    def detail(self) -> str:
        return "SLSQP from SciPy. Always-on nonlinear backend when IPOPT is not installed."

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
            result = minimize(
                objective,
                start,
                method="SLSQP",
                bounds=bound_pairs,
                constraints=cons,
                options={"maxiter": int(options.get("maxiter", 400)), "ftol": 1e-10, "disp": False},
            )
            status = "optimal" if result.success else "error"
            values = {key: float(result.x[i]) for i, key in enumerate(keys)}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=result.message if isinstance(result.message, str) else str(result.message),
                started=started,
                message="SciPy 求得局部最优。" if result.success else f"SciPy 未收敛：{result.message}",
                message_en="SciPy found a local optimum." if result.success else f"SciPy did not converge: {result.message}",
            )
        except Exception as exc:
            return failure(self.name, started, f"SciPy 求解失败：{exc}", f"SciPy failed: {exc}")


def _gradient(fun, x: np.ndarray) -> np.ndarray:
    grad = np.zeros_like(x)
    base = fun(x)
    for index in range(len(x)):
        step = 1e-6 * max(1.0, abs(x[index]))
        bumped = x.copy()
        bumped[index] += step
        grad[index] = (fun(bumped) - base) / step
    return grad


def _jacobian(fun, x: np.ndarray, rows: int, cols: int) -> np.ndarray:
    base = fun(x)
    matrix = np.zeros((rows, cols))
    for index in range(cols):
        step = 1e-6 * max(1.0, abs(x[index]))
        bumped = x.copy()
        bumped[index] += step
        matrix[:, index] = (fun(bumped) - base) / step
    return matrix.reshape(-1)
