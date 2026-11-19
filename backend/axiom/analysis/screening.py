"""Global sensitivity: Morris screening and Sobol indices.

Sobol indices are computed with SALib's Saltelli sampler and the Sobol
analyzer. Morris uses SALib's trajectory sampler and analyzer when SALib is
installed, and the same elementary-effect estimator otherwise.
"""

from __future__ import annotations

import numpy as np

from axiom.errors import AxiomError


def morris(function, names: list[str], bounds: list[tuple[float, float]], trajectories: int = 8, levels: int = 4, seed: int = 1) -> dict:
    if len(names) != len(bounds) or not names:
        raise AxiomError("Morris 筛查需要每个因子的边界。", "Morris screening needs a bound for every factor.", code="morris")
    problem = _problem(names, bounds)
    try:
        from SALib.analyze import morris as morris_analyze
        from SALib.sample.morris import sample as morris_sample
    except Exception as exc:
        return _morris_fallback(function, names, bounds, trajectories, levels, seed, str(exc))
    samples = morris_sample(problem, N=max(4, int(trajectories)), num_levels=max(4, int(levels)), seed=seed)
    values = _evaluate(function, samples)
    analyzed = morris_analyze.analyze(problem, samples, values, seed=seed)
    rows = []
    for index, name in enumerate(names):
        rows.append(
            {
                "name": name,
                "mu": float(analyzed["mu"][index]),
                "mu_star": float(analyzed["mu_star"][index]),
                "sigma": float(analyzed["sigma"][index]),
            }
        )
    return {"method": "morris", "library": "SALib", "samples": int(len(values)), "rows": rows}


def sobol(function, names: list[str], bounds: list[tuple[float, float]], samples: int = 32, seed: int = 1, second_order: bool = True) -> dict:
    if len(names) != len(bounds) or not names:
        raise AxiomError("Sobol 指数需要每个因子的边界。", "Sobol indices need a bound for every factor.", code="sobol")
    try:
        from SALib.analyze import sobol as sobol_analyze
        from SALib.sample import sobol as sobol_sample
    except Exception as exc:
        return {
            "method": "sobol",
            "library": None,
            "ok": False,
            "samples": 0,
            "rows": [],
            "message": f"SALib 未能加载，Sobol 指数没有计算：{exc}",
            "message_en": f"SALib did not import, so Sobol indices were not computed: {exc}",
        }
    problem = _problem(names, bounds)
    count = max(8, int(samples))
    matrix = sobol_sample.sample(problem, count, calc_second_order=second_order and len(names) > 1, seed=seed)
    values = _evaluate(function, matrix)
    if float(np.std(values)) < 1e-12:
        return {
            "method": "sobol",
            "library": "SALib",
            "ok": False,
            "samples": int(len(values)),
            "rows": [{"name": name, "S1": 0.0, "ST": 0.0} for name in names],
            "message": "模型响应几乎是常数，Sobol 指数没有意义。",
            "message_en": "The response is essentially constant, so Sobol indices are not meaningful.",
        }
    analyzed = sobol_analyze.analyze(problem, values, calc_second_order=second_order and len(names) > 1, print_to_console=False)
    rows = []
    for index, name in enumerate(names):
        row = {
            "name": name,
            "S1": float(analyzed["S1"][index]),
            "S1_conf": float(analyzed["S1_conf"][index]),
            "ST": float(analyzed["ST"][index]),
            "ST_conf": float(analyzed["ST_conf"][index]),
        }
        rows.append(row)
    pairs = []
    if second_order and len(names) > 1 and "S2" in analyzed:
        matrix_s2 = np.asarray(analyzed["S2"], dtype=float)
        for left in range(len(names)):
            for right in range(left + 1, len(names)):
                pairs.append({"a": names[left], "b": names[right], "S2": float(matrix_s2[left, right])})
    return {"method": "sobol", "library": "SALib", "ok": True, "samples": int(len(values)), "rows": rows, "pairs": pairs}


def _problem(names, bounds) -> dict:
    return {"num_vars": len(names), "names": list(names), "bounds": [[float(lo), float(hi)] for lo, hi in bounds]}


def _evaluate(function, samples: np.ndarray) -> np.ndarray:
    values = []
    for row in samples:
        values.append(float(function(row)))
    return np.asarray(values, dtype=float)


def _morris_fallback(function, names, bounds, trajectories, levels, seed, reason: str) -> dict:
    """Elementary effects on a p-level grid. Used only when SALib cannot be imported."""
    rng = np.random.default_rng(seed)
    p = max(4, int(levels))
    delta = p / (2.0 * (p - 1))
    effects = [[] for _ in names]
    for _ in range(max(4, int(trajectories))):
        point = rng.integers(0, p, size=len(names)).astype(float) / (p - 1)
        for index in range(len(names)):
            if point[index] + delta > 1:
                point[index] -= delta
        order = rng.permutation(len(names))
        current = float(function(_scale(point, bounds)))
        for index in order:
            step = delta if point[index] + delta <= 1 else -delta
            nxt = point.copy()
            nxt[index] = point[index] + step
            value = float(function(_scale(nxt, bounds)))
            effects[index].append((value - current) / step)
            point, current = nxt, value
    rows = []
    for index, name in enumerate(names):
        column = np.array(effects[index], dtype=float)
        rows.append(
            {
                "name": name,
                "mu": float(column.mean()),
                "mu_star": float(np.mean(np.abs(column))),
                "sigma": float(column.std()),
            }
        )
    return {
        "method": "morris",
        "library": "elementary-effects",
        "samples": int(sum(len(item) for item in effects) + trajectories),
        "rows": rows,
        "message": f"SALib 未能加载，已改用基本效应估计：{reason}",
        "message_en": f"SALib did not import. Elementary effects were used instead: {reason}",
    }


def _scale(unit: np.ndarray, bounds) -> np.ndarray:
    lower = np.array([lo for lo, _ in bounds], dtype=float)
    upper = np.array([hi for _, hi in bounds], dtype=float)
    return lower + unit * (upper - lower)
