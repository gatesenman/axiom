"""Algorithm catalog for the studio picker, Auto, and the solver race.

Each method maps onto a solver that already ships. ``local-search`` is registered
but stays out of the default race. ``row-generation`` re-solves HiGHS, adding the
most violated omitted row until the point is feasible for every row.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from axiom.errors import AxiomError
from axiom.modeling.flatten import FlatCon, FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import has_integer

CATALOG: list[dict[str, Any]] = [
    {
        "id": "auto",
        "solver": "highs",
        "family": "auto",
        "label_zh": "自动",
        "label_en": "Auto",
        "summary_zh": "按模型结构选择方法，并让可用求解器并行竞赛。",
        "summary_en": "Picks a method from the model structure and still races the available solvers.",
        "options": {},
    },
    {
        "id": "dual-simplex",
        "solver": "highs",
        "family": "lp",
        "label_zh": "对偶单纯形",
        "label_en": "Dual simplex",
        "summary_zh": "HiGHS 对偶单纯形，适合连续线性规划。",
        "summary_en": "HiGHS dual simplex for continuous linear programs.",
        "options": {"algorithm": "dual-simplex"},
    },
    {
        "id": "primal-simplex",
        "solver": "highs",
        "family": "lp",
        "label_zh": "原始单纯形",
        "label_en": "Primal simplex",
        "summary_zh": "HiGHS 原始单纯形。",
        "summary_en": "HiGHS primal simplex.",
        "options": {"algorithm": "primal-simplex"},
    },
    {
        "id": "barrier",
        "solver": "highs",
        "family": "lp",
        "label_zh": "内点法",
        "label_en": "Barrier",
        "summary_zh": "HiGHS 内点法（障碍法）。",
        "summary_en": "HiGHS interior-point barrier method.",
        "options": {"algorithm": "barrier"},
    },
    {
        "id": "branch-and-cut",
        "solver": "highs",
        "family": "mip",
        "label_zh": "分支切割",
        "label_en": "Branch-and-cut",
        "summary_zh": "HiGHS 混合整数分支切割。",
        "summary_en": "HiGHS mixed-integer branch-and-cut.",
        "options": {"algorithm": "branch-and-cut"},
    },
    {
        "id": "cbc-branch-and-cut",
        "solver": "cbc",
        "family": "mip",
        "label_zh": "CBC 分支切割",
        "label_en": "CBC branch-and-cut",
        "summary_zh": "COIN-OR CBC 的分支切割。",
        "summary_en": "COIN-OR CBC branch-and-cut.",
        "options": {},
    },
    {
        "id": "scip-mip",
        "solver": "scip",
        "family": "mip",
        "label_zh": "SCIP",
        "label_en": "SCIP",
        "summary_zh": "SCIP 混合整数求解。",
        "summary_en": "SCIP mixed-integer solve.",
        "options": {},
    },
    {
        "id": "cp-sat",
        "solver": "cp-sat",
        "family": "cp",
        "label_zh": "CP-SAT",
        "label_en": "CP-SAT",
        "summary_zh": "OR-Tools CP-SAT，适合较小的整数模型。",
        "summary_en": "OR-Tools CP-SAT for smaller integer models.",
        "options": {},
    },
    {
        "id": "slsqp",
        "solver": "scipy",
        "family": "nlp",
        "label_zh": "SLSQP",
        "label_en": "SLSQP",
        "summary_zh": "SciPy SLSQP，连续非线性局部求解。",
        "summary_en": "SciPy SLSQP for continuous nonlinear models.",
        "options": {},
    },
    {
        "id": "ipopt",
        "solver": "ipopt",
        "family": "nlp",
        "label_zh": "IPOPT",
        "label_en": "IPOPT",
        "summary_zh": "IPOPT 内点法，连续非线性。",
        "summary_en": "IPOPT interior point for continuous nonlinear models.",
        "options": {},
    },
    {
        "id": "weighted-sum",
        "solver": "highs",
        "family": "mo",
        "label_zh": "加权和",
        "label_en": "Weighted sum",
        "summary_zh": "把多个线性目标按权重合成一个，再用 HiGHS 对偶单纯形。",
        "summary_en": "Combines linear objectives by weight, then runs HiGHS dual simplex.",
        "options": {"algorithm": "weighted-sum"},
    },
    {
        "id": "local-search",
        "solver": "local",
        "family": "meta",
        "label_zh": "局部搜索",
        "label_en": "Local search",
        "summary_zh": "对很小的整数定义域做完全枚举。只有选中时才加入竞赛。",
        "summary_en": "Enumerates a tiny integer domain. It joins the race only when selected.",
        "options": {},
    },
    {
        "id": "row-generation",
        "solver": "highs",
        "family": "decomp",
        "label_zh": "行生成",
        "label_en": "Row generation",
        "summary_zh": "先解第一条约束，再逐条加入违反最严重的行，直到对全部约束可行。",
        "summary_en": "Starts from the first row and adds the most violated omitted row until every row is satisfied.",
        "options": {"algorithm": "row-generation"},
    },
]

CATALOG.extend(
    [
        {"id": "clp", "solver": "clp", "family": "lp", "label_zh": "CLP", "label_en": "CLP", "summary_zh": "OR-Tools 里的 COIN-OR CLP 单纯形。", "summary_en": "COIN-OR CLP simplex inside OR-Tools.", "options": {}},
        {"id": "pdlp", "solver": "pdlp", "family": "lp", "label_zh": "PDLP", "label_en": "PDLP", "summary_zh": "OR-Tools 一阶 LP 方法 PDLP。", "summary_en": "OR-Tools first-order PDLP for linear programs.", "options": {}},
        {"id": "clarabel", "solver": "clarabel", "family": "conic", "label_zh": "Clarabel", "label_en": "Clarabel", "summary_zh": "Clarabel 求解 LP、凸 QP、二阶锥和半定规划。", "summary_en": "Clarabel for LP, convex QP, second-order cones, and semidefinite programs.", "options": {}},
        {"id": "ecos", "solver": "ecos", "family": "conic", "label_zh": "ECOS", "label_en": "ECOS", "summary_zh": "ECOS 嵌入式二阶锥求解器。", "summary_en": "ECOS embedded second-order-cone solver.", "options": {}},
        {"id": "scs", "solver": "scs", "family": "conic", "label_zh": "SCS", "label_en": "SCS", "summary_zh": "SCS 一阶锥规划，覆盖 QP 和半定规划。", "summary_en": "SCS first-order conic solver, including QP and semidefinite programs.", "options": {}},
        {"id": "osqp", "solver": "osqp", "family": "qp", "label_zh": "OSQP", "label_en": "OSQP", "summary_zh": "OSQP 算子分裂二次规划。", "summary_en": "OSQP operator-splitting quadratic programming.", "options": {}},
        {"id": "cvxopt", "solver": "cvxopt", "family": "conic", "label_zh": "CVXOPT", "label_en": "CVXOPT", "summary_zh": "CVXOPT 内点法，含半定规划。", "summary_en": "CVXOPT interior point, including semidefinite programs.", "options": {}},
        {"id": "python-mip", "solver": "python-mip", "family": "mip", "label_zh": "python-mip", "label_en": "python-mip", "summary_zh": "python-mip 自带的 CBC。", "summary_en": "CBC through python-mip.", "options": {}},
        {"id": "pyscipopt", "solver": "pyscipopt", "family": "mip", "label_zh": "PySCIPOpt", "label_en": "PySCIPOpt", "summary_zh": "PySCIPOpt 直接调用 SCIP。", "summary_en": "SCIP through the PySCIPOpt bindings.", "options": {}},
        {"id": "scipy-highs", "solver": "scipy-highs", "family": "lp", "label_zh": "SciPy HiGHS", "label_en": "SciPy HiGHS", "summary_zh": "SciPy 的 linprog / milp HiGHS 接口。", "summary_en": "SciPy linprog and milp HiGHS interface.", "options": {}},
        {"id": "trust-constr", "solver": "trust-constr", "family": "nlp", "label_zh": "trust-constr", "label_en": "trust-constr", "summary_zh": "SciPy 信赖域约束非线性求解。", "summary_en": "SciPy trust-region constrained nonlinear solver.", "options": {}},
        {"id": "gurobi", "solver": "gurobi", "family": "mip", "label_zh": "Gurobi", "label_en": "Gurobi", "summary_zh": "检测到已授权的 Gurobi 时使用。", "summary_en": "Uses Gurobi when a license is detected.", "options": {}},
        {"id": "cplex", "solver": "cplex", "family": "mip", "label_zh": "CPLEX", "label_en": "CPLEX", "summary_zh": "检测到已授权的 CPLEX 时使用。", "summary_en": "Uses CPLEX when a license is detected.", "options": {}},
        {"id": "xpress", "solver": "xpress", "family": "mip", "label_zh": "Xpress", "label_en": "Xpress", "summary_zh": "检测到已授权的 FICO Xpress 时使用。", "summary_en": "Uses FICO Xpress when a license is detected.", "options": {}},
        {"id": "mosek", "solver": "mosek", "family": "conic", "label_zh": "MOSEK", "label_en": "MOSEK", "summary_zh": "检测到已授权的 MOSEK 时使用。", "summary_en": "Uses MOSEK when a license is detected.", "options": {}},
        {"id": "copt", "solver": "copt", "family": "conic", "label_zh": "COPT", "label_en": "COPT", "summary_zh": "检测到已授权的 COPT 时使用。", "summary_en": "Uses COPT when a license is detected.", "options": {}},
        {"id": "knitro", "solver": "knitro", "family": "nlp", "label_zh": "Knitro", "label_en": "Knitro", "summary_zh": "检测到已授权的 Knitro 时使用。", "summary_en": "Uses Knitro when a license is detected.", "options": {}},
        {"id": "baron", "solver": "baron", "family": "minlp", "label_zh": "BARON", "label_en": "BARON", "summary_zh": "PATH 上有 baron 可执行文件时使用。", "summary_en": "Uses BARON when the baron executable is on PATH.", "options": {}},
        {"id": "hexaly", "solver": "hexaly", "family": "cp", "label_zh": "Hexaly", "label_en": "Hexaly", "summary_zh": "检测到已授权的 Hexaly 时使用。", "summary_en": "Uses Hexaly when a license is detected.", "options": {}},
        {"id": "bonmin", "solver": "bonmin", "family": "minlp", "label_zh": "Bonmin", "label_en": "Bonmin", "summary_zh": "PATH 上有 Bonmin 可执行文件时求解混合整数非线性。", "summary_en": "Solves mixed-integer nonlinear models when the Bonmin executable is on PATH.", "options": {}},
        {"id": "couenne", "solver": "couenne", "family": "minlp", "label_zh": "Couenne", "label_en": "Couenne", "summary_zh": "PATH 上有 Couenne 可执行文件时做全局混合整数非线性。", "summary_en": "Global mixed-integer nonlinear solve when the Couenne executable is on PATH.", "options": {}},
    ]
)

BY_ID = {item["id"]: item for item in CATALOG}


def public_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "solver": item["solver"],
            "family": item["family"],
            "label_zh": item["label_zh"],
            "label_en": item["label_en"],
            "summary_zh": item["summary_zh"],
            "summary_en": item["summary_en"],
        }
        for item in CATALOG
    ]


def choose(model: Model) -> dict[str, Any]:
    """Pick one concrete method. Raises when the model cannot be flattened."""
    from axiom.modeling.flatten import flatten

    flat = flatten(model)
    integer = any(var.domain in {"integer", "binary"} for var in model.variables.values()) or has_integer(flat)
    if getattr(flat, "cones", None):
        picked = _entry("clarabel")
        picked["reason_zh"] = "约束里有二阶锥，建议用 Clarabel。"
        picked["reason_en"] = "A constraint is a second-order cone, so Clarabel is the fit."
        return _with_race(model, picked)
    if getattr(flat, "quadratic", None) and not flat.nonlinear:
        picked = _entry("pyscipopt" if integer else "osqp")
        if integer:
            picked["reason_zh"] = "这是混合整数二次规划，建议用 PySCIPOpt。"
            picked["reason_en"] = "This is a mixed-integer quadratic program, so PySCIPOpt is the fit."
        else:
            picked["reason_zh"] = "这是凸二次规划，建议用 OSQP。"
            picked["reason_en"] = "This is a convex quadratic program, so OSQP is the fit."
        return _with_race(model, picked)
    if flat.nonlinear:
        picked = _entry("slsqp")
        picked["reason_zh"] = "目标或约束里有非线性项，建议用 SciPy 的 SLSQP 做连续非线性求解。"
        picked["reason_en"] = "An objective or constraint is nonlinear, so SciPy SLSQP is the fit for a continuous nonlinear solve."
        return _with_race(model, picked)
    if len(model.objectives) >= 2 and not flat.nonlinear:
        picked = _entry("weighted-sum")
        picked["reason_zh"] = "模型有多个线性目标，建议用加权和合成后再做对偶单纯形。"
        picked["reason_en"] = "The model has several linear objectives, so a weighted sum followed by dual simplex is the fit."
        return _with_race(model, picked)
    if integer:
        picked = _entry("branch-and-cut")
        small = len(flat.variables) <= 40
        extra = "规模不大，也可以改用 CP-SAT。" if small else "规模上来之后仍以分支切割为主。"
        extra_en = " It is small enough that CP-SAT is an easy alternative." if small else " Branch-and-cut stays appropriate as the model grows."
        picked["reason_zh"] = f"模型含整数或 0-1 变量，建议用 HiGHS 的分支切割。{extra}"
        picked["reason_en"] = f"The model has integer or binary variables, so HiGHS branch-and-cut is the fit.{extra_en}"
        return _with_race(model, picked)
    picked = _entry("dual-simplex")
    picked["reason_zh"] = "这是连续线性规划，建议用 HiGHS 的对偶单纯形。"
    picked["reason_en"] = "This is a continuous linear program, so HiGHS dual simplex is the fit."
    return _with_race(model, picked)


def _with_race(model: Model, picked: dict[str, Any]) -> dict[str, Any]:
    try:
        from axiom.solvers.capabilities import race_names

        names = race_names(model, str(picked.get("solver") or ""))
    except Exception:
        names = []
    if names:
        shown = names[:14]
        picked["reason_zh"] = picked["reason_zh"] + " 自动竞赛会按能力调用：" + "、".join(shown) + "。"
        picked["reason_en"] = picked["reason_en"] + " Auto races every capable solver: " + ", ".join(shown) + "."
    return picked


def resolve_request(algorithm: str, solver: str) -> str:
    """Solver name to store on a run. Auto keeps the user's solver."""
    algorithm = (algorithm or "auto").strip() or "auto"
    if algorithm == "auto":
        return (solver or "highs").lower()
    item = BY_ID.get(algorithm)
    if item is None:
        known = "、".join(item_id for item_id in BY_ID)
        raise AxiomError(
            f"未知算法 {algorithm}。可选：{known}。",
            f"Unknown algorithm {algorithm}.",
            code="unknown_algorithm",
        )
    return str(item["solver"])


def resolve(model: Model, algorithm: str, preferred: str) -> dict[str, Any]:
    """How the race should treat this run.

    Auto keeps the preferred solver and, when that solver is the one ``choose``
    named, passes the method options only to it. A specific method forces its
    solver and options.
    """
    algorithm = (algorithm or "auto").strip() or "auto"
    if algorithm not in BY_ID:
        algorithm = "auto"
    if algorithm == "auto":
        try:
            picked = choose(model)
        except AxiomError:
            picked = _entry("dual-simplex")
        options = dict(picked["options"]) if (preferred or "highs") == picked["solver"] else {}
        return {
            "id": "auto",
            "method": picked["id"],
            "solver": preferred or picked["solver"],
            "options_for": picked["solver"] if options else None,
            "options": options,
            "label_zh": "自动",
            "label_en": "Auto",
        }
    item = _entry(algorithm)
    return {
        "id": item["id"],
        "method": item["id"],
        "solver": item["solver"],
        "options_for": item["solver"],
        "options": dict(item["options"]),
        "label_zh": item["label_zh"],
        "label_en": item["label_en"],
    }


def solve_row_generation(model: Model, flat: FlatModel, options: dict[str, Any] | None = None):
    """Seed with the first constraint, then add the most violated omitted row."""
    from axiom.solvers.highs import HighsSolver

    adapter = HighsSolver()
    inner = {key: value for key, value in (options or {}).items() if key != "algorithm"}
    if not has_integer(flat):
        inner["algorithm"] = "dual-simplex"
    rows = list(flat.constraints)
    if len(rows) <= 1:
        return adapter.solve(model, flat, inner)
    active = [rows[0]]
    omitted = rows[1:]
    while True:
        current = replace(flat, constraints=list(active))
        result = adapter.solve(model, current, inner)
        if result.status in {"unbounded", "unbounded_or_infeasible", "error"}:
            if not omitted:
                return adapter.solve(model, flat, inner)
            active.append(omitted.pop(0))
            continue
        if result.status not in {"optimal", "feasible"}:
            return result
        worst: FlatCon | None = None
        worst_amount = 1e-6
        values = result.variables or {}
        for con in omitted:
            amount = _violation(con, values)
            if amount > worst_amount:
                worst = con
                worst_amount = amount
        if worst is None:
            return result
        omitted.remove(worst)
        active.append(worst)


def _entry(algorithm_id: str) -> dict[str, Any]:
    item = BY_ID[algorithm_id]
    return {
        "id": item["id"],
        "solver": item["solver"],
        "family": item["family"],
        "label_zh": item["label_zh"],
        "label_en": item["label_en"],
        "reason_zh": item["summary_zh"],
        "reason_en": item["summary_en"],
        "options": dict(item["options"]),
    }


def _violation(con: FlatCon, values: dict[str, float]) -> float:
    lhs = sum(coef * float(values.get(key, 0.0)) for key, coef in con.coeffs.items())
    if con.sense == "<=":
        return lhs - float(con.rhs)
    if con.sense == ">=":
        return float(con.rhs) - lhs
    return abs(lhs - float(con.rhs))
