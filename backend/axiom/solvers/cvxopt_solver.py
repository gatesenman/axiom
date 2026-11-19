"""CVXOPT adapter for LP, convex QP, SOCP, and a direct SDP path."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import assemble, failure, has_integer, not_applicable


class CvxoptSolver:
    name = "cvxopt"
    label = "CVXOPT"
    capabilities = {"lp", "qp", "socp", "sdp"}
    license = "open"

    def available(self) -> bool:
        try:
            import cvxopt  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        if not self.available():
            return ""
        import cvxopt

        return str(getattr(cvxopt, "__version__", "installed"))

    def detail(self) -> str:
        if self.available():
            return "CVXOPT interior-point solvers for linear, quadratic, second-order-cone, and semidefinite programs."
        return "CVXOPT is not importable. The Windows package includes the official win_amd64 wheel."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if has_integer(flat):
            return not_applicable(self.name, started, "CVXOPT 不求解整数变量。", "CVXOPT does not solve integer variables.")
        if flat.nonlinear and not getattr(flat, "quadratic", None) and not getattr(flat, "cones", None):
            return not_applicable(self.name, started, "CVXOPT 不求解一般非线性模型。", "CVXOPT does not solve general nonlinear models.")
        if not self.available():
            return failure(self.name, started, "未安装 CVXOPT。", "CVXOPT is not installed.", "missing")
        try:
            from cvxopt import matrix, solvers

            solvers.options["show_progress"] = False
            keys = [var.key for var in flat.variables]
            index = {key: i for i, key in enumerate(keys)}
            n = len(keys)
            sign = -1.0 if flat.sense == "maximize" else 1.0
            c = matrix([sign * float(flat.objective.get(key, 0.0)) for key in keys])
            g_rows: list[list[float]] = []
            h_vals: list[float] = []
            a_rows: list[list[float]] = []
            b_vals: list[float] = []

            def add_ineq(coeffs: dict[str, float], rhs: float) -> None:
                g_rows.append([float(coeffs.get(key, 0.0)) for key in keys])
                h_vals.append(float(rhs))

            for var in flat.variables:
                if var.upper is not None:
                    add_ineq({var.key: 1.0}, float(var.upper))
                if var.lower is not None:
                    add_ineq({var.key: -1.0}, -float(var.lower))
            for con in flat.constraints:
                if con.sense == "<=":
                    add_ineq(con.coeffs, con.rhs)
                elif con.sense == ">=":
                    add_ineq({key: -coef for key, coef in con.coeffs.items()}, -con.rhs)
                else:
                    a_rows.append([float(con.coeffs.get(key, 0.0)) for key in keys])
                    b_vals.append(float(con.rhs))
            cones = list(getattr(flat, "cones", None) or [])
            quad = getattr(flat, "quadratic", None) or {}
            G = matrix(g_rows).T if g_rows else None
            h = matrix(h_vals) if h_vals else None
            A = matrix(a_rows).T if a_rows else None
            b = matrix(b_vals) if b_vals else None
            if cones and not quad:
                # ||x|| <= t  becomes a second-order cone on a local copy of those columns.
                Gq, hq = _soc_blocks(keys, index, cones)
                sol = solvers.socp(c, Gl=G, hl=h, Gq=Gq, hq=hq, A=A, b=b)
            elif quad:
                P = [[0.0] * n for _ in range(n)]
                for (left, right), coef in quad.items():
                    i, j = index[left], index[right]
                    stored = sign * (2.0 * coef if i == j else coef)
                    if i == j:
                        P[i][j] += stored
                    else:
                        P[i][j] += stored
                        P[j][i] += stored
                # CVXOPT qp uses 1/2 x' P x + q' x. We stored the full polynomial
                # coefficient, so the diagonal 2*coef matches 1/2 * P_ii = coef.
                sol = solvers.qp(matrix(P), c, G, h, A, b)
            else:
                sol = solvers.lp(c, G, h, A, b)
            raw = str(sol["status"])
            status = "optimal" if raw == "optimal" else "error"
            values = {}
            if status == "optimal":
                point = list(sol["x"])
                values = {key: float(point[i]) for i, key in enumerate(keys)}
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=f"CVXOPT 状态：{raw}。",
                message_en=f"CVXOPT status: {raw}.",
            )
        except Exception as exc:
            return failure(self.name, started, f"CVXOPT 求解失败：{exc}", f"CVXOPT failed: {exc}")


def _soc_blocks(keys: list[str], index: dict[str, int], cones: list[dict]):
    from cvxopt import matrix, spmatrix

    blocks_g = []
    blocks_h = []
    n = len(keys)
    for cone in cones:
        members = [cone["bound"], *cone["vars"]]
        dim = len(members)
        rows, cols, vals = [], [], []
        for local, key in enumerate(members):
            rows.append(local)
            cols.append(index[key])
            vals.append(-1.0)
        blocks_g.append(spmatrix(vals, rows, cols, (dim, n)))
        blocks_h.append(matrix(0.0, (dim, 1)))
    return blocks_g, blocks_h
