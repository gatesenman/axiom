"""CVXPY adapters for Clarabel, ECOS, SCS, and OSQP.

Each adapter builds the same convex model and asks CVXPY for one solver.
ECOS does not accept a quadratic objective. OSQP is limited to quadratic
programs. Clarabel and SCS also take second-order cones recorded on the flat
model, and the SDP helpers solve a sparse SDPA block directly.
"""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, failure, has_integer, not_applicable


class _CvxpySolver:
    name = "clarabel"
    label = "Clarabel"
    cvx_name = "CLARABEL"
    capabilities = {"lp", "qp", "socp", "sdp"}
    license = "open"
    allows_qp = True
    allows_integer = False

    def available(self) -> bool:
        try:
            import cvxpy as cp
        except ImportError:
            return False
        return self.cvx_name in cp.installed_solvers()

    def version(self) -> str:
        if not self.available():
            return ""
        module = {"CLARABEL": "clarabel", "ECOS": "ecos", "SCS": "scs", "OSQP": "osqp"}[self.cvx_name]
        try:
            imported = __import__(module)
            return str(getattr(imported, "__version__", "installed"))
        except Exception:
            return "installed"

    def detail(self) -> str:
        if self.available():
            return f"CVXPY backend {self.cvx_name}, bundled for offline use."
        return f"{self.label} is not importable in this Python. The Windows package vendors the wheel when one exists."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear and not getattr(flat, "quadratic", None) and not getattr(flat, "cones", None):
            return not_applicable(self.name, started, f"{self.label} 不求解一般非线性模型。", f"{self.label} does not solve general nonlinear models.")
        if has_integer(flat) and not self.allows_integer:
            return not_applicable(self.name, started, f"{self.label} 不求解整数变量。", f"{self.label} does not solve integer variables.")
        if getattr(flat, "quadratic", None) and not self.allows_qp:
            return not_applicable(self.name, started, f"{self.label} 不求解二次目标。", f"{self.label} does not solve a quadratic objective.")
        if not self.available():
            return failure(self.name, started, f"未安装 {self.label}。", f"{self.label} is not installed.", "missing")
        try:
            import cvxpy as cp

            values, raw, duals = _solve_cvxpy(cp, flat, self.cvx_name, options)
            status = "optimal" if values is not None else "error"
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values or {},
                raw_status=raw,
                started=started,
                message=f"{self.label} 状态：{raw}。",
                message_en=f"{self.label} status: {raw}.",
                duals=duals,
            )
        except Exception as exc:
            return failure(self.name, started, f"{self.label} 求解失败：{exc}", f"{self.label} failed: {exc}")


class ClarabelSolver(_CvxpySolver):
    name = "clarabel"
    label = "Clarabel"
    cvx_name = "CLARABEL"
    capabilities = {"lp", "qp", "socp", "sdp"}
    allows_qp = True


class EcosSolver(_CvxpySolver):
    name = "ecos"
    label = "ECOS"
    cvx_name = "ECOS"
    capabilities = {"lp", "socp"}
    allows_qp = False


class ScsSolver(_CvxpySolver):
    name = "scs"
    label = "SCS"
    cvx_name = "SCS"
    capabilities = {"lp", "qp", "socp", "sdp"}
    allows_qp = True


class OsqpSolver(_CvxpySolver):
    name = "osqp"
    label = "OSQP"
    cvx_name = "OSQP"
    capabilities = {"lp", "qp"}
    allows_qp = True


def _solve_cvxpy(cp, flat: FlatModel, solver_name: str, options: dict[str, Any]):
    keys = [var.key for var in flat.variables]
    index = {key: position for position, key in enumerate(keys)}
    x = cp.Variable(len(keys))
    constraints = []
    for position, var in enumerate(flat.variables):
        if var.lower is not None and var.lower > -INF / 2:
            constraints.append(x[position] >= float(var.lower))
        if var.upper is not None and var.upper < INF / 2:
            constraints.append(x[position] <= float(var.upper))
    cost = float(flat.objective_const)
    linear = [float(flat.objective.get(key, 0.0)) for key in keys]
    expression = cost + linear @ x
    quad = getattr(flat, "quadratic", None) or {}
    if quad:
        import numpy as np

        matrix = np.zeros((len(keys), len(keys)))
        for (left, right), coef in quad.items():
            i, j = index[left], index[right]
            if i == j:
                matrix[i, j] += coef
            else:
                matrix[i, j] += coef / 2
                matrix[j, i] += coef / 2
        expression += cp.quad_form(x, cp.psd_wrap(matrix))
    for con in flat.constraints:
        row = sum(float(coef) * x[index[key]] for key, coef in con.coeffs.items())
        if con.sense == "<=":
            constraints.append(row <= float(con.rhs))
        elif con.sense == ">=":
            constraints.append(row >= float(con.rhs))
        else:
            constraints.append(row == float(con.rhs))
    for cone in getattr(flat, "cones", None) or []:
        if cone.get("kind") != "soc":
            continue
        bound = x[index[cone["bound"]]]
        members = cp.hstack([x[index[key]] for key in cone["vars"]])
        constraints.append(cp.SOC(bound, members))
    objective = cp.Maximize(expression) if flat.sense == "maximize" else cp.Minimize(expression)
    problem = cp.Problem(objective, constraints)
    kwargs: dict[str, Any] = {"solver": solver_name, "verbose": False}
    problem.solve(**kwargs)
    raw = str(problem.status)
    if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or x.value is None:
        return None, raw, {}
    values = {key: float(x.value[position]) for position, key in enumerate(keys)}
    return values, raw, {}


def solve_sdpa_with(solver_name: str, block: dict[str, Any]) -> dict[str, Any]:
    """Solve one sparse SDPA problem. ``block`` has c, n, and F matrices."""
    import numpy as np

    size = int(block["size"])
    c = np.array(block["c"], dtype=float)
    matrices = block["matrices"]
    if solver_name == "cvxopt":
        return _sdpa_cvxopt(c, size, matrices)
    import cvxpy as cp

    y = cp.Variable(len(c))
    f0 = np.array(matrices[0], dtype=float)
    expr = f0
    for index, column in enumerate(c):
        expr = expr + y[index] * np.array(matrices[index + 1], dtype=float)
        del column
    problem = cp.Problem(cp.Minimize(c @ y), [expr >> 0])
    cvx = {"clarabel": "CLARABEL", "scs": "SCS", "mosek": "MOSEK"}.get(solver_name, solver_name.upper())
    problem.solve(solver=cvx, verbose=False)
    if y.value is None:
        return {"status": "error", "raw": str(problem.status), "values": {}, "objective": None}
    return {
        "status": "optimal",
        "raw": str(problem.status),
        "values": {f"y{i + 1}": float(y.value[i]) for i in range(len(c))},
        "objective": float(problem.value),
    }


def _sdpa_cvxopt(c, size: int, matrices) -> dict[str, Any]:
    """CVXOPT wants ``mat(Gs x) ≼ hs``, i.e. ``F0 + sum y_i F_i ≽ 0`` as ``-sum y_i F_i ≼ F0``."""
    from cvxopt import matrix, solvers

    solvers.options["show_progress"] = False
    width = len(c)
    columns = matrix(0.0, (size * size, width))
    for index, mat in enumerate(matrices[1:]):
        columns[:, index] = matrix([-value for value in _vec(mat)])
    constant = matrix(_vec(matrices[0]), (size, size))
    sol = solvers.sdp(matrix(c), Gs=[columns], hs=[constant])
    if sol["status"] != "optimal":
        return {"status": "error", "raw": str(sol["status"]), "values": {}, "objective": None}
    point = list(sol["x"])
    return {
        "status": "optimal",
        "raw": "optimal",
        "values": {f"y{i + 1}": float(point[i]) for i in range(width)},
        "objective": float(sol["primal objective"]),
    }


def _vec(mat) -> list[float]:
    import numpy as np

    array = np.array(mat, dtype=float)
    return array.reshape(-1, order="F").tolist()
