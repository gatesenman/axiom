"""Uncertainty quantification: Monte Carlo, Latin hypercube propagation, and FORM.

Monte Carlo and Latin hypercube re-solve the model at each draw of the
uncertain right-hand sides (or parameters). FORM is the Hasofer–Lind
Rackwitz–Fiessler iteration on that same limit state.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm, qmc

from axiom.errors import AxiomError
from axiom.modeling.ir import Model, const
from axiom.solvers.registry import solve_model


def propagate(model: Model, method: str = "monte-carlo", samples: int = 32, cv: float = 0.08, seed: int = 1, solver: str = "highs", cancel=None) -> dict:
    method = (method or "monte-carlo").lower()
    count = max(8, min(int(samples), 200))
    draws = _draws(method, count, seed)
    values = []
    for draw in draws:
        if cancel and cancel():
            break
        mutated = model.copy()
        if not _apply_noise(mutated, float(draw), cv):
            return {"ok": False, "message": "没有可扰动的右端或参数。", "message_en": "There is no right-hand side or parameter to perturb."}
        try:
            solved = solve_model(mutated, solver, {"time_limit": 5})
        except AxiomError:
            continue
        if solved.objective is not None and solved.status in {"optimal", "feasible"}:
            values.append(float(solved.objective))
    if len(values) < 4:
        return {"ok": False, "samples": len(values), "message": "有效样本太少。", "message_en": "Too few solves succeeded."}
    array = np.array(values, dtype=float)
    edges = np.linspace(float(array.min()), float(array.max()), 12)
    counts, _ = np.histogram(array, bins=edges)
    ordered = np.sort(array)
    cdf = [(float(ordered[index]), (index + 1) / len(ordered)) for index in range(len(ordered))]
    return {
        "ok": True,
        "method": "lhs" if method in {"lhs", "latin"} else "monte-carlo",
        "samples": int(len(array)),
        "cv": float(cv),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "p05": float(np.quantile(array, 0.05)),
        "p50": float(np.quantile(array, 0.50)),
        "p95": float(np.quantile(array, 0.95)),
        "values": [float(item) for item in array],
        "histogram": {"edges": [float(item) for item in edges], "counts": [int(item) for item in counts]},
        "cdf": cdf,
    }


def form(model: Model, cv: float = 0.08, alpha: float = 0.05, solver: str = "highs", limit: float | None = None) -> dict:
    """Reliability index for the event that the optimal objective crosses `limit`."""
    base = solve_model(model, solver, {"time_limit": 8})
    if base.objective is None or base.status not in {"optimal", "feasible"}:
        return {"ok": False, "message": base.message, "message_en": base.message_en}
    sense = model.objectives[0].sense if model.objectives else "minimize"
    threshold = float(limit) if limit is not None else (float(base.objective) * (0.9 if sense == "maximize" else 1.1))
    names = _noise_names(model)
    if not names:
        return {"ok": False, "message": "没有可扰动的右端或参数。", "message_en": "There is no right-hand side or parameter to perturb."}

    def limit_state(unit: np.ndarray) -> float | None:
        mutated = model.copy()
        _apply_named(mutated, names, unit, cv)
        try:
            solved = solve_model(mutated, solver, {"time_limit": 5})
        except AxiomError:
            return None
        if solved.objective is None or solved.status not in {"optimal", "feasible"}:
            return None
        if sense == "maximize":
            return float(solved.objective) - threshold
        return threshold - float(solved.objective)

    beta, point, converged = hlrf(limit_state, len(names))
    if beta is None:
        return {
            "ok": False,
            "message": "FORM 迭代没有得到光滑的极限状态。",
            "message_en": "FORM did not obtain a smooth limit state.",
        }
    return {
        "ok": True,
        "method": "FORM",
        "beta": beta,
        "probability": float(norm.cdf(-beta)),
        "alpha": float(alpha),
        "limit": threshold,
        "design_point": {name: float(point[index]) for index, name in enumerate(names)},
        "converged": converged,
        "message": "极限状态是最优值越过阈值。g>0 为安全，beta 为标准正态空间中的距离。",
        "message_en": "The limit state is the optimum crossing the threshold. g>0 is safe, and beta is the distance in standard normal space.",
    }


def hlrf(limit_state, dimension: int, iters: int = 25):
    """Hasofer–Lind / Rackwitz–Fiessler on a standard-normal limit state g(u)>0 safe."""
    point = np.zeros(dimension)
    beta = 0.0
    converged = False
    origin = limit_state(point)
    for _ in range(iters):
        value = limit_state(point)
        if value is None or not np.isfinite(value):
            return None, point, False
        gradient = _gradient(limit_state, point, value)
        norm_g = float(np.linalg.norm(gradient))
        if norm_g < 1e-10:
            return None, point, False
        # Closest point on the linearized surface g + ∇g·(u'−u) = 0.
        updated = gradient * ((gradient @ point - value) / (norm_g ** 2))
        if float(np.linalg.norm(updated - point)) < 1e-4:
            point = updated
            converged = True
            break
        point = updated
    beta = float(np.linalg.norm(point))
    if origin is not None and origin < 0:
        beta = -beta
    return beta, point, converged


def _gradient(limit_state, point: np.ndarray, base: float) -> np.ndarray:
    gradient = np.zeros(len(point))
    for index in range(len(point)):
        step = 1e-3
        moved = point.copy()
        moved[index] += step
        value = limit_state(moved)
        if value is None:
            moved[index] -= 2 * step
            value = limit_state(moved)
            step = -step
        gradient[index] = 0.0 if value is None else (value - base) / step
    return gradient


def _draws(method: str, count: int, seed: int) -> np.ndarray:
    if method in {"lhs", "latin"}:
        engine = qmc.LatinHypercube(d=1, seed=seed)
        unit = engine.random(count).reshape(-1)
        return norm.ppf(np.clip(unit, 1e-6, 1 - 1e-6))
    return np.random.default_rng(seed).normal(size=count)


def _noise_names(model: Model) -> list[tuple[str, str, tuple]]:
    names = []
    for con in model.constraints:
        if con.rhs is not None and con.rhs.op == "const" and not con.quants:
            names.append(("rhs", con.name, ()))
    if names:
        return names
    for param in model.parameters.values():
        for key in list(param.values)[:6]:
            names.append(("param", param.name, key))
    return names


def _apply_noise(model: Model, unit: float, cv: float) -> bool:
    names = _noise_names(model)
    if not names:
        return False
    _apply_named(model, names, np.full(len(names), unit), cv)
    return True


def _apply_named(model: Model, names, unit: np.ndarray, cv: float) -> None:
    for index, (kind, name, key) in enumerate(names):
        factor = 1.0 + float(cv) * float(unit[index])
        if kind == "rhs":
            for con in model.constraints:
                if con.name == name and con.rhs is not None and con.rhs.op == "const":
                    base = float(con.rhs.value or 0.0)
                    con.rhs = const(base * factor)
        else:
            param = model.parameters[name]
            param.values[key] = float(param.values[key]) * factor
