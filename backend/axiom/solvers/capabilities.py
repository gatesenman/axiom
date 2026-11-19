"""Capability metadata and problem-class routing for every solver adapter.

Problem classes follow the usual mathematical-programming taxonomy:
LP, MILP, QP, MIQP, SOCP, SDP, NLP, MINLP, and CP. Feature flags record
whether an adapter can return duals, accept a warm start, expose callbacks,
compute an irreducible infeasible set, and run multithreaded, plus the
license type the vendor uses.
"""

from __future__ import annotations

from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.solvers.common import has_integer, integral_data

CLASSES = ("lp", "milp", "qp", "miqp", "socp", "sdp", "nlp", "minlp", "cp")
FEATURES = ("duals", "warm_start", "callbacks", "iis", "multithread")

# Static facts. ``distribution`` is bundled when the Windows package ships the
# solver, and detected when Axiom only uses a library the user installed.
CATALOG: dict[str, dict[str, Any]] = {
    "highs": {
        "classes": ["lp", "milp", "qp"],
        "features": ["duals", "warm_start", "multithread"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://highs.dev/",
    },
    "cbc": {
        "classes": ["lp", "milp"],
        "features": ["multithread"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://github.com/coin-or/Cbc",
    },
    "clp": {
        "classes": ["lp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://github.com/coin-or/Clp",
    },
    "glpk": {
        "classes": ["lp", "milp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://www.gnu.org/software/glpk/",
    },
    "scip": {
        "classes": ["lp", "milp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://www.scipopt.org/",
    },
    "pyscipopt": {
        "classes": ["lp", "milp", "qp", "miqp"],
        "features": ["duals", "warm_start", "callbacks", "iis", "multithread"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://pyscipopt.readthedocs.io/",
    },
    "glop": {
        "classes": ["lp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://developers.google.com/optimization/lp/glop",
    },
    "pdlp": {
        "classes": ["lp"],
        "features": ["multithread"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://developers.google.com/optimization/lp/pdlp",
    },
    "cp-sat": {
        "classes": ["cp", "milp"],
        "features": ["callbacks", "multithread"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://developers.google.com/optimization/cp/cp_solver",
    },
    "clarabel": {
        "classes": ["lp", "qp", "socp", "sdp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://clarabel.org/",
    },
    "ecos": {
        "classes": ["lp", "socp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://github.com/embotech/ecos",
    },
    "scs": {
        "classes": ["lp", "qp", "socp", "sdp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://www.cvxgrp.org/scs/",
    },
    "osqp": {
        "classes": ["lp", "qp"],
        "features": ["warm_start"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://osqp.org/",
    },
    "cvxopt": {
        "classes": ["lp", "qp", "socp", "sdp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://cvxopt.org/",
    },
    "python-mip": {
        "classes": ["lp", "milp"],
        "features": ["callbacks", "multithread"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://python-mip.readthedocs.io/",
    },
    "ipopt": {
        "classes": ["nlp", "lp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "detected",
        "docs_url": "https://coin-or.github.io/Ipopt/",
    },
    "ipopt-asl": {
        "classes": ["nlp", "lp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://github.com/coin-or/Ipopt/releases",
    },
    "bonmin": {
        "classes": ["minlp", "nlp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "detected",
        "docs_url": "https://github.com/coin-or/Bonmin",
    },
    "couenne": {
        "classes": ["minlp", "nlp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "detected",
        "docs_url": "https://github.com/coin-or/Couenne",
    },
    "scipy": {
        "classes": ["nlp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html",
    },
    "scipy-highs": {
        "classes": ["lp", "milp"],
        "features": ["duals"],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html",
    },
    "trust-constr": {
        "classes": ["nlp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "https://docs.scipy.org/doc/scipy/reference/optimize.minimize-trustconstr.html",
    },
    "gurobi": {
        "classes": ["lp", "milp", "qp", "miqp", "socp", "nlp", "minlp"],
        "features": ["duals", "warm_start", "callbacks", "iis", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://www.gurobi.com/documentation/",
    },
    "cplex": {
        "classes": ["lp", "milp", "qp", "miqp", "socp"],
        "features": ["duals", "warm_start", "callbacks", "iis", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://www.ibm.com/docs/en/icos",
    },
    "xpress": {
        "classes": ["lp", "milp", "qp", "miqp", "socp", "nlp", "minlp"],
        "features": ["duals", "warm_start", "callbacks", "iis", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://www.fico.com/fico-xpress-optimization/docs/",
    },
    "mosek": {
        "classes": ["lp", "milp", "qp", "miqp", "socp", "sdp"],
        "features": ["duals", "warm_start", "callbacks", "iis", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://docs.mosek.com/",
    },
    "copt": {
        "classes": ["lp", "milp", "qp", "miqp", "socp", "sdp"],
        "features": ["duals", "warm_start", "callbacks", "iis", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://www.copt.de/docs/",
    },
    "knitro": {
        "classes": ["nlp", "minlp", "lp", "qp"],
        "features": ["duals", "warm_start", "callbacks", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://www.artelys.com/docs/knitro/",
    },
    "baron": {
        "classes": ["nlp", "minlp", "lp"],
        "features": [],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://minlp.com/baron",
    },
    "hexaly": {
        "classes": ["lp", "milp", "nlp", "minlp", "cp"],
        "features": ["callbacks", "multithread"],
        "license_type": "commercial",
        "distribution": "detected",
        "docs_url": "https://www.hexaly.com/docs/",
    },
    "local": {
        "classes": ["milp", "cp"],
        "features": [],
        "license_type": "open-source",
        "distribution": "bundled",
        "docs_url": "",
    },
}


def problem_kind(flat: FlatModel) -> str:
    integer = has_integer(flat)
    if getattr(flat, "cones", None):
        return "minlp" if integer else "socp"
    if getattr(flat, "quadratic", None):
        return "miqp" if integer else "qp"
    if flat.nonlinear:
        return "minlp" if integer else "nlp"
    if integer:
        return "milp"
    return "lp"


def classes_of(solver) -> set[str]:
    meta = CATALOG.get(solver.name)
    if meta:
        return set(meta["classes"])
    raw = set(getattr(solver, "capabilities", set()))
    mapped = set()
    if "lp" in raw:
        mapped.add("lp")
    if "mip" in raw:
        mapped.add("milp")
    if "qp" in raw:
        mapped.add("qp")
    if "nlp" in raw:
        mapped.add("nlp")
    if "cp" in raw:
        mapped.add("cp")
    return mapped


def accepts(solver, flat: FlatModel) -> bool:
    kind = problem_kind(flat)
    classes = classes_of(solver)
    if kind in classes:
        if kind == "milp" and "cp" in classes and "milp" not in classes:
            return _cp_ready(flat)
        if solver.name == "cp-sat":
            return _cp_ready(flat)
        return True
    if kind == "lp" and "lp" not in classes and "cp" in classes and "milp" in classes and not (classes & {"qp", "socp", "sdp"}):
        return False
    if kind == "lp" and classes & {"milp", "qp", "miqp", "socp", "sdp"}:
        return True
    if kind == "qp" and "miqp" in classes:
        return True
    if kind == "milp" and "miqp" in classes:
        return True
    if kind == "milp" and "cp" in classes and _cp_ready(flat):
        return True
    if kind == "nlp" and "minlp" in classes and not has_integer(flat):
        return True
    return False


def _cp_ready(flat: FlatModel) -> bool:
    if any(var.domain == "continuous" for var in flat.variables):
        return False
    return integral_data(flat)


def race_names(model, preferred: str = "") -> list[str]:
    """Available solvers that can handle this model, preferred name first.

    Local search stays out of the automatic race. Importing the registry here
    is delayed so solver modules can import this file without a cycle.
    """
    from axiom.modeling.flatten import flatten
    from axiom.solvers.registry import SOLVERS

    flat = flatten(model)
    ready: list[str] = []
    for solver in SOLVERS:
        if solver.name == "local":
            continue
        if not accepts(solver, flat):
            continue
        try:
            if solver.available():
                ready.append(solver.name)
        except Exception:
            continue
    if preferred and preferred in ready:
        ready = [preferred] + [name for name in ready if name != preferred]
    elif preferred:
        try:
            from axiom.solvers.registry import get_solver

            adapter = get_solver(preferred)
            if adapter.available() and accepts(adapter, flat):
                ready = [preferred, *ready]
        except Exception:
            pass
    return ready


def license_state(solver) -> str:
    meta = CATALOG.get(solver.name, {})
    try:
        installed = bool(solver.available())
    except Exception:
        installed = False
    probe = getattr(solver, "license_state", None)
    if callable(probe):
        try:
            reported = probe()
            if reported:
                return str(reported)
        except Exception:
            if not installed:
                return "not_installed"
    if not installed:
        return "not_installed"
    if meta.get("license_type") == "commercial":
        return "licensed"
    return "open"


def describe(solver) -> dict[str, Any]:
    meta = CATALOG.get(solver.name, {})
    try:
        available = bool(solver.available())
        version = solver.version() if available else ""
    except Exception as exc:
        available = False
        version = str(exc)
    state = license_state(solver) if available or meta.get("license_type") == "commercial" else "not_installed"
    if not available and state == "open":
        state = "not_installed"
    features = list(meta.get("features") or [])
    classes = list(meta.get("classes") or sorted(classes_of(solver)))
    return {
        "name": solver.name,
        "label": solver.label,
        "available": available,
        "version": version,
        "capabilities": sorted(set(solver.capabilities) | set(classes)),
        "classes": classes,
        "features": features,
        "license": solver.license,
        "license_type": meta.get("license_type", solver.license),
        "license_state": state,
        "distribution": meta.get("distribution", "detected"),
        "bundled": meta.get("distribution") == "bundled",
        "docs_url": meta.get("docs_url", ""),
        "detail": solver.detail(),
    }
