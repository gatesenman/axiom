"""Solver registry and the single entry point used by the API and agents."""

from __future__ import annotations

from typing import Any

from axiom.errors import AxiomError
from axiom.modeling.flatten import flatten
from axiom.modeling.ir import Model
from axiom.modeling.standard import standard_form
from axiom.modeling.validator import validate
from axiom.solvers.asl import BonminSolver, CouenneSolver, IpoptAslSolver
from axiom.solvers.base import SolveResult
from axiom.solvers.capabilities import accepts, describe
from axiom.solvers.cbc import CbcSolver
from axiom.solvers.commercial import BaronSolver, CoptSolver, HexalySolver, KnitroSolver, MosekSolver, XpressSolver
from axiom.solvers.conic import ClarabelSolver, EcosSolver, OsqpSolver, ScsSolver
from axiom.solvers.cplex import CplexSolver
from axiom.solvers.cpsat import CpSatSolver
from axiom.solvers.cvxopt_solver import CvxoptSolver
from axiom.solvers.glpk import GlpkSolver
from axiom.solvers.gurobi import GurobiSolver
from axiom.solvers.highs import HighsSolver
from axiom.solvers.local_search import LocalSearchSolver
from axiom.solvers.nonlinear import IpoptSolver, ScipySolver
from axiom.solvers.open_mip import ClpSolver, PdlpSolver, PyScipOptSolver, PythonMipSolver
from axiom.solvers.ortools_mip import GlopSolver, ScipSolver
from axiom.solvers.scipy_methods import ScipyHighsSolver, TrustConstrSolver

SOLVERS = [
    HighsSolver(),
    CbcSolver(),
    ClpSolver(),
    GlpkSolver(),
    ScipSolver(),
    PyScipOptSolver(),
    GlopSolver(),
    PdlpSolver(),
    CpSatSolver(),
    ClarabelSolver(),
    EcosSolver(),
    ScsSolver(),
    OsqpSolver(),
    CvxoptSolver(),
    PythonMipSolver(),
    IpoptSolver(),
    IpoptAslSolver(),
    BonminSolver(),
    CouenneSolver(),
    ScipySolver(),
    ScipyHighsSolver(),
    TrustConstrSolver(),
    GurobiSolver(),
    CplexSolver(),
    XpressSolver(),
    MosekSolver(),
    CoptSolver(),
    KnitroSolver(),
    BaronSolver(),
    HexalySolver(),
    LocalSearchSolver(),
]

_BY_NAME = {solver.name: solver for solver in SOLVERS}


def list_solvers() -> list[dict[str, Any]]:
    rows = []
    for solver in SOLVERS:
        try:
            rows.append(describe(solver))
        except Exception as exc:  # a broken optional install must not take down the app
            rows.append(
                {
                    "name": solver.name,
                    "label": solver.label,
                    "available": False,
                    "version": str(exc),
                    "capabilities": sorted(solver.capabilities),
                    "classes": [],
                    "features": [],
                    "license": solver.license,
                    "license_type": solver.license,
                    "license_state": "not_installed",
                    "distribution": "detected",
                    "bundled": False,
                    "docs_url": "",
                    "detail": solver.detail(),
                }
            )
    return rows


def get_solver(name: str):
    key = (name or "highs").lower()
    solver = _BY_NAME.get(key)
    if solver is None:
        raise AxiomError(
            f"未知求解器 {name}。",
            f"Unknown solver {name}.",
            code="unknown_solver",
        )
    return solver


def solve_model(model: Model, solver: str = "highs", options: dict[str, Any] | None = None) -> SolveResult:
    checked = validate(model)
    errors = [item for item in checked.diagnostics if item.level == "error"]
    if errors:
        raise AxiomError(
            errors[0].message,
            errors[0].message_en,
            code=errors[0].code,
            details=[item.to_dict() for item in checked.diagnostics],
        )
    standard_form(model)
    flat = flatten(model)
    opts = dict(options or {})
    if str(opts.get("algorithm") or "") == "row-generation" and not flat.nonlinear:
        from axiom.analysis.algorithms import solve_row_generation

        return solve_row_generation(model, flat, opts)
    adapter = get_solver(solver)
    if not adapter.available():
        raise AxiomError(
            f"求解器 {adapter.label} 当前不可用。",
            f"Solver {adapter.label} is not available.",
            code="solver_unavailable",
        )
    if not accepts(adapter, flat) and str(opts.get("algorithm") or "") != "row-generation":
        from axiom.solvers.capabilities import problem_kind
        from axiom.solvers.common import not_applicable

        kind = problem_kind(flat)
        return not_applicable(
            adapter.name,
            0.0,
            f"{adapter.label} 不能求解 {kind} 模型。",
            f"{adapter.label} cannot solve a {kind} model.",
        )
    return adapter.solve(model, flat, options or {})
