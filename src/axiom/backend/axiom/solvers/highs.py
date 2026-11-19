"""HiGHS adapter built on the highspy Python API."""

from __future__ import annotations

import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, bounds, failure, has_integer, not_applicable, opt_float

_STATUS = {
    "kOptimal": "optimal",
    "kInfeasible": "infeasible",
    "kUnbounded": "unbounded",
    "kUnboundedOrInfeasible": "unbounded_or_infeasible",
    "kTimeLimit": "time_limit",
    "kIterationLimit": "iteration_limit",
    "kSolutionLimit": "feasible",
    "kObjectiveBound": "feasible",
    "kObjectiveTarget": "feasible",
}


class HighsSolver:
    name = "highs"
    label = "HiGHS"
    capabilities = {"lp", "mip"}
    license = "open"

    def available(self) -> bool:
        try:
            import highspy  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        if not self.available():
            return ""
        import highspy

        return str(highspy.Highs().version())

    def detail(self) -> str:
        return "Open-source LP/MIP solver via the highspy bindings. Default solver."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        if flat.nonlinear:
            return not_applicable(
                self.name,
                started,
                "HiGHS 只求解线性和混合整数线性模型。",
                "HiGHS only solves linear and mixed-integer linear models.",
            )
        try:
            import highspy
        except ImportError as exc:
            return failure(self.name, started, "未安装 highspy。", "highspy is not installed.", "missing")
        try:
            highs = highspy.Highs()
            highs.setOptionValue("output_flag", False)
            limit = opt_float(options, "time_limit")
            if limit:
                highs.setOptionValue("time_limit", limit)
            gap = opt_float(options, "mip_gap")
            if gap is not None and has_integer(flat):
                highs.setOptionValue("mip_rel_gap", gap)
            threads = options.get("threads")
            if threads:
                highs.setOptionValue("threads", int(threads))
            _apply_method(highs, flat, options)
            if flat.sense == "maximize":
                highs.changeObjectiveSense(highspy.ObjSense.kMaximize)
            index = {var.key: position for position, var in enumerate(flat.variables)}
            for var in flat.variables:
                lower, upper = bounds(var)
                coef = float(flat.objective.get(var.key, 0.0))
                highs.addVariable(lb=lower, ub=upper, obj=coef, name=_safe(var.key))
                if var.domain in {"integer", "binary"}:
                    highs.changeColIntegrality(index[var.key], highspy.HighsVarType.kInteger)
            if abs(flat.objective_const) > 1e-12:
                highs.changeObjectiveOffset(float(flat.objective_const))
            for con in flat.constraints:
                lower, upper = _row_bounds(con.sense, con.rhs)
                columns = [index[key] for key in con.coeffs]
                values = [float(con.coeffs[key]) for key in con.coeffs]
                highs.addRow(lower, upper, len(columns), columns, values)
            if getattr(flat, "cones", None):
                return not_applicable(self.name, started, "HiGHS 不求解二阶锥约束。", "HiGHS does not solve second-order cones.")
            _pass_quadratic(highs, highspy, flat, index)
            highs.run()
            raw = str(highs.getModelStatus()).split(".")[-1]
            status = _STATUS.get(raw, "error")
            if raw == "kTimeLimit":
                info = highs.getInfo()
                status = "feasible" if getattr(info, "primal_solution_status", None) else "time_limit"
                # A time limit with a feasible MIP solution still exposes column values.
                try:
                    if highs.getSolution().value_valid:
                        status = "feasible"
                except Exception:
                    pass
            values: dict[str, float] = {}
            reduced: dict[str, float] = {}
            duals: dict[str, float] = {}
            if status in {"optimal", "feasible"}:
                solution = highs.getSolution()
                for position, var in enumerate(flat.variables):
                    values[var.key] = float(solution.col_value[position])
                    if position < len(solution.col_dual):
                        reduced[var.key] = float(solution.col_dual[position])
                for position, con in enumerate(flat.constraints):
                    if position < len(solution.row_dual):
                        duals[con.key] = float(solution.row_dual[position])
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw,
                started=started,
                message=_message(status)[0],
                message_en=_message(status)[1],
                duals=duals,
                reduced_costs=reduced,
            )
        except Exception as exc:
            return failure(self.name, started, f"HiGHS 求解失败：{exc}", f"HiGHS failed: {exc}")


def _pass_quadratic(highs, highspy, flat: FlatModel, index: dict[str, int]) -> None:
    quad = getattr(flat, "quadratic", None) or {}
    if not quad:
        return
    entries: dict[tuple[int, int], float] = {}
    for (left, right), coef in quad.items():
        if abs(coef) < 1e-15:
            continue
        row, col = index[left], index[right]
        if row < col:
            row, col = col, row
        # HiGHS stores the lower triangle of Q in 1/2 x' Q x.
        stored = 2.0 * coef if row == col else coef
        entries[(row, col)] = entries.get((row, col), 0.0) + stored
    columns: dict[int, list[tuple[int, float]]] = {}
    for (row, col), value in entries.items():
        columns.setdefault(col, []).append((row, value))
    dimension = len(flat.variables)
    start = [0]
    q_index: list[int] = []
    q_value: list[float] = []
    cursor = 0
    for column in range(dimension):
        for row, value in sorted(columns.get(column, [])):
            q_index.append(row)
            q_value.append(value)
            cursor += 1
        start.append(cursor)
    highs.passHessian(
        dimension,
        cursor,
        highspy.HessianFormat.kTriangular,
        start,
        q_index,
        q_value,
    )


def _apply_method(highs, flat: FlatModel, options: dict[str, Any]) -> None:
    """Force simplex or the barrier only on continuous LPs. MIP keeps branch-and-cut."""
    algorithm = str(options.get("algorithm") or "")
    if not algorithm or has_integer(flat) or getattr(flat, "quadratic", None):
        return
    try:
        if algorithm in {"dual-simplex", "weighted-sum"}:
            highs.setOptionValue("solver", "simplex")
            highs.setOptionValue("simplex_strategy", 1)
        elif algorithm == "primal-simplex":
            highs.setOptionValue("solver", "simplex")
            highs.setOptionValue("simplex_strategy", 4)
        elif algorithm == "barrier":
            highs.setOptionValue("solver", "ipm")
    except Exception:
        return


def _row_bounds(sense: str, rhs: float) -> tuple[float, float]:
    if sense == "<=":
        return -INF, float(rhs)
    if sense == ">=":
        return float(rhs), INF
    return float(rhs), float(rhs)


def _safe(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "()_" else "_" for ch in name)
    return cleaned[:200] or "x"


def _message(status: str) -> tuple[str, str]:
    table = {
        "optimal": ("求得最优解。", "Optimal solution found."),
        "feasible": ("求得可行解，但未证明最优。", "A feasible solution was found without a proof of optimality."),
        "infeasible": ("模型不可行。", "The model is infeasible."),
        "unbounded": ("模型无界。", "The model is unbounded."),
        "unbounded_or_infeasible": ("模型无界或不可行。", "The model is unbounded or infeasible."),
        "time_limit": ("达到时间上限，没有可行解。", "Time limit reached before a feasible solution."),
        "error": ("求解器返回了无法识别的状态。", "The solver returned an unrecognized status."),
    }
    return table.get(status, table["error"])
