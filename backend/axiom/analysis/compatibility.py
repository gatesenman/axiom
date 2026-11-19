"""Solver and modeling-language compatibility matrix.

Every problem class is paired with every registered solver. A solver that
does not accept the class, or is not installed, gets an explained fallback
instead of a crash. The same classes are exported and imported through every
modeling language that can represent them.
"""

from __future__ import annotations

import json
from typing import Any

from axiom.analysis.benchmark import CASES, SDP
from axiom.errors import AxiomError
from axiom.modeling import parse_aml
from axiom.modeling.exchange import read_model
from axiom.modeling.flatten import flatten
from axiom.modeling.translators.registry import list_translators, translate
from axiom.solvers.capabilities import accepts, classes_of, license_state
from axiom.solvers.registry import SOLVERS, solve_model

# Classes each exchange target is able to represent. Others are reported,
# not treated as failures.
LANGUAGE_CLASSES: dict[str, set[str]] = {
    "pyomo": {"lp", "milp", "qp", "nlp"},
    "pulp": {"lp", "milp"},
    "ortools": set(),
    "cvxpy": {"lp", "milp", "qp", "socp"},
    "ampl": {"lp", "milp", "qp", "nlp"},
    "gams": {"lp", "milp", "qp"},
    "jump": {"lp", "milp", "qp"},
    "lp": {"lp", "milp"},
    "mps": {"lp", "milp"},
    "mps-free": {"lp", "milp"},
    "qps": {"lp", "qp"},
    "nl": {"lp", "milp", "qp", "nlp"},
    "osil": {"lp", "milp", "qp"},
    "cbf": {"lp"},
    "sdpa": {"sdp"},
    "minizinc": {"lp", "milp", "cp"},
    "flatzinc": {"lp", "milp", "cp"},
    "gmpl": {"lp", "milp"},
    "zimpl": {"lp", "milp"},
    "opl": {"lp", "milp"},
    "gurobipy": {"lp", "milp", "qp"},
    "docplex": {"lp", "milp", "qp"},
    "linopy": {"lp", "milp"},
    "mip": {"lp", "milp"},
    "casadi": {"lp", "milp", "qp", "nlp"},
}

_VERIFY = {
    "lp": "highs",
    "milp": "highs",
    "qp": "highs",
    "socp": "clarabel",
    "nlp": "ipopt",
    "minlp": "pyscipopt",
    "cp": "cp-sat",
    "sdp": "clarabel",
}


def compatibility_matrix(execute: bool = False, cancel=None) -> dict[str, Any]:
    models = {kind: parse_aml(aml) for kind, aml, _expected in CASES}
    expected = {kind: value for kind, _aml, value in CASES}
    solver_rows = []
    for kind, model in models.items():
        if cancel and cancel():
            break
        flat = flatten(model)
        for solver in SOLVERS:
            if solver.name == "local":
                continue
            solver_rows.append(_solver_cell(kind, model, flat, solver, expected[kind], execute))
    solver_rows.extend(_sdp_cells(execute))
    language_rows = _language_cells(models, expected, execute, cancel)
    return {
        "ok": True,
        "execute": bool(execute),
        "classes": [kind for kind, _aml, _expected in CASES] + ["sdp"],
        "solvers": solver_rows,
        "languages": language_rows,
        "summary": _summary(solver_rows, language_rows),
    }


def _solver_cell(kind: str, model, flat, solver, expected: float, execute: bool) -> dict[str, Any]:
    capable = bool(accepts(solver, flat))
    try:
        installed = bool(solver.available())
    except Exception:
        installed = False
    state = "not_installed"
    try:
        state = license_state(solver)
    except Exception:
        state = "not_installed" if not installed else "open"
    if not capable:
        classes = ", ".join(sorted(classes_of(solver))) or "none"
        return _cell(
            "solver",
            kind,
            solver.name,
            "unsupported",
            False,
            f"{solver.label} 不求解 {kind}。它接受：{classes}。",
            f"{solver.label} does not solve {kind}. It accepts: {classes}.",
            available=installed,
            accepts=False,
        )
    if not installed:
        return _cell(
            "solver",
            kind,
            solver.name,
            "not_installed",
            False,
            f"{solver.label} 能求解 {kind}，但这台机器上没有可用的许可证或程序（{state}）。",
            f"{solver.label} can solve {kind}, but no license or binary is available on this machine ({state}).",
            available=False,
            accepts=True,
        )
    if not execute:
        return _cell(
            "solver",
            kind,
            solver.name,
            "capable",
            True,
            f"{solver.label} 可以求解 {kind}。还没有逐个复核数值。",
            f"{solver.label} can solve {kind}. The numeric check has not been run.",
            available=True,
            accepts=True,
        )
    try:
        result = solve_model(model, solver.name, {"time_limit": 8})
    except Exception as exc:
        return _cell("solver", kind, solver.name, "error", False, str(exc), str(exc), available=True, accepts=True)
    agree = _agree(kind, result.objective, expected) and bool(result.feasible)
    if agree:
        return _cell(
            "solver",
            kind,
            solver.name,
            "ok",
            True,
            f"目标 {result.objective:.6g}，与参考值一致。",
            f"Objective {result.objective:.6g} matches the reference.",
            available=True,
            accepts=True,
            objective=result.objective,
        )
    return _cell(
        "solver",
        kind,
        solver.name,
        result.status or "mismatch",
        False,
        f"返回 {result.status}，目标 {result.objective}，参考值 {expected:.6g}。{result.message}",
        f"Returned {result.status}, objective {result.objective}, reference {expected:.6g}. {result.message_en}",
        available=True,
        accepts=True,
        objective=result.objective,
    )


def _sdp_cells(execute: bool) -> list[dict[str, Any]]:
    from axiom.solvers.conic import solve_sdpa_with

    rows = []
    direct = {"clarabel", "scs", "cvxopt"}
    for solver in SOLVERS:
        if solver.name == "local":
            continue
        claims = "sdp" in classes_of(solver) or solver.name in direct
        installed = _safe_available(solver)
        if not claims:
            rows.append(
                _cell(
                    "solver",
                    "sdp",
                    solver.name,
                    "unsupported",
                    False,
                    f"{solver.label} 不求解半定规划。",
                    f"{solver.label} does not solve semidefinite programs.",
                    available=installed,
                    accepts=False,
                )
            )
            continue
        if solver.name not in direct:
            rows.append(
                _cell(
                    "solver",
                    "sdp",
                    solver.name,
                    "not_installed" if not installed else "unsupported",
                    False,
                    f"{solver.label} 声明了 SDP，但兼容矩阵的数值复核只接到 Clarabel、SCS 和 CVXOPT。当前状态：{'已安装' if installed else '未安装'}。",
                    f"{solver.label} declares SDP, but the numeric matrix checks Clarabel, SCS, and CVXOPT. It is {'installed' if installed else 'not installed'}.",
                    available=installed,
                    accepts=False,
                )
            )
            continue
        if not installed:
            rows.append(
                _cell(
                    "solver",
                    "sdp",
                    solver.name,
                    "not_installed",
                    False,
                    f"{solver.label} 能求解 SDP，但当前不可用。",
                    f"{solver.label} can solve SDPs, but it is not available.",
                    available=False,
                    accepts=True,
                )
            )
            continue
        if not execute:
            rows.append(_cell("solver", "sdp", solver.name, "capable", True, "可以求解 SDP。", "Can solve an SDP.", available=True, accepts=True))
            continue
        try:
            result = solve_sdpa_with(solver.name, SDP)
        except Exception as exc:
            rows.append(_cell("solver", "sdp", solver.name, "error", False, str(exc), str(exc), available=True, accepts=True))
            continue
        objective = result.get("objective") if isinstance(result, dict) else result.objective
        status = result.get("status") if isinstance(result, dict) else result.status
        agree = _agree("sdp", objective, 1.0) and status in {"optimal", "feasible"}
        rows.append(
            _cell(
                "solver",
                "sdp",
                solver.name,
                "ok" if agree else (status or "mismatch"),
                agree,
                "目标与参考值 1 一致。" if agree else f"目标 {objective}。",
                "Objective matches the reference value 1." if agree else f"Objective {objective}.",
                available=True,
                accepts=True,
                objective=objective,
            )
        )
    return rows


def _language_cells(models: dict, expected: dict, execute: bool, cancel) -> list[dict[str, Any]]:
    sdp_text = json.dumps(SDP)
    rows = []
    classes = list(models) + ["sdp"]
    for target in list_translators():
        name = target["name"]
        supported = LANGUAGE_CLASSES.get(name, set())
        for kind in classes:
            if cancel and cancel():
                return rows
            if kind not in supported:
                reason = "这个导出只有写出，没有对应的读入。" if name == "ortools" else f"{name} 不表示 {kind}。"
                reason_en = "This export has no importer." if name == "ortools" else f"{name} does not represent {kind}."
                rows.append(_cell("language", kind, name, "unsupported", False, reason, reason_en))
                continue
            if not execute:
                rows.append(_cell("language", kind, name, "capable", True, f"{name} 可以表示 {kind}。", f"{name} can represent {kind}."))
                continue
            rows.append(_round_trip(name, kind, models.get(kind), expected.get(kind, 1.0), sdp_text))
    return rows


def _round_trip(name: str, kind: str, model, expected: float, sdp_text: str) -> dict[str, Any]:
    try:
        if kind == "sdp":
            from axiom.modeling.exchange import read_sdpa, write_sdpa

            text = write_sdpa(json.loads(sdp_text))
            restored = read_sdpa(text)
        else:
            text = translate(model, name).code
            restored = read_model(name, text)
    except AxiomError as exc:
        return _cell("language", kind, name, "unsupported", False, exc.message, exc.message_en)
    except Exception as exc:
        return _cell("language", kind, name, "error", False, str(exc), str(exc))
    solver = _VERIFY.get(kind, "highs")
    try:
        if kind == "sdp":
            from axiom.solvers.conic import solve_sdpa_with

            payload = solve_sdpa_with(solver, json.loads(restored.meta["sdpa"]))
            objective = payload.get("objective")
            feasible = payload.get("status") in {"optimal", "feasible"}
        else:
            result = solve_model(restored, solver, {"time_limit": 8})
            objective = result.objective
            feasible = bool(result.feasible)
    except Exception as exc:
        return _cell("language", kind, name, "error", False, f"读回后求解失败：{exc}", f"The imported model failed to solve: {exc}")
    agree = _agree(kind, objective, expected) and feasible
    shown = "none" if objective is None else f"{float(objective):.6g}"
    if agree:
        return _cell("language", kind, name, "ok", True, f"导出再导入后目标 {shown}。", f"Export/import kept the objective at {shown}.", objective=objective)
    return _cell(
        "language",
        kind,
        name,
        "mismatch",
        False,
        f"导出再导入后目标 {shown}，参考值 {expected:.6g}。",
        f"Export/import returned objective {shown}; the reference is {expected:.6g}.",
        objective=objective,
    )


def _agree(kind: str, objective, expected: float) -> bool:
    if objective is None:
        return False
    tol = 2e-2 if kind == "socp" else 1e-2 * max(1.0, abs(expected))
    return abs(float(objective) - expected) <= tol


def _safe_available(solver) -> bool:
    try:
        return bool(solver.available())
    except Exception:
        return False


def _cell(axis: str, kind: str, name: str, status: str, agree: bool, reason: str, reason_en: str, **extra) -> dict[str, Any]:
    return {"axis": axis, "class": kind, "name": name, "status": status, "agree": bool(agree), "reason": reason, "reason_en": reason_en, **extra}


def _summary(solvers: list[dict], languages: list[dict]) -> dict[str, int]:
    def count(rows, status):
        return sum(1 for row in rows if row["status"] == status)

    return {
        "solver_ok": count(solvers, "ok"),
        "solver_capable": count(solvers, "capable"),
        "solver_unsupported": count(solvers, "unsupported"),
        "solver_not_installed": count(solvers, "not_installed"),
        "language_ok": count(languages, "ok"),
        "language_capable": count(languages, "capable"),
        "language_unsupported": count(languages, "unsupported"),
        "language_mismatch": count(languages, "mismatch"),
    }
