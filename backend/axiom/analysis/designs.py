"""Design of experiments.

Full and fractional factorials, Latin hypercube, Sobol and Halton sequences,
central composite, and Box-Behnken. Points are returned in the caller's
units. Coded columns use the usual [-1, 1] cube (axial CCD points use the
rotatable radius before scaling back onto that cube).
"""

from __future__ import annotations

from itertools import combinations, product

import numpy as np
from scipy.stats import qmc

from axiom.errors import AxiomError


def generate(method: str, bounds: list[tuple[float, float]], samples: int = 16, levels: int = 2, seed: int = 1) -> dict:
    method = (method or "lhs").lower().strip()
    if not bounds:
        raise AxiomError("试验设计至少需要一个因子。", "A design needs at least one factor.", code="doe")
    coded, natural, note = _dispatch(method, bounds, samples, levels, seed)
    return {
        "method": method,
        "samples": int(natural.shape[0]),
        "factors": len(bounds),
        "coded": coded.tolist(),
        "natural": natural.tolist(),
        "bounds": [[float(lo), float(hi)] for lo, hi in bounds],
        "note": note[0],
        "note_en": note[1],
    }


def _dispatch(method, bounds, samples, levels, seed):
    if method in {"full", "full-factorial", "factorial"}:
        coded = _full_factorial(len(bounds), levels)
        return coded, _decode(coded, bounds), ("全因子设计。", "Full factorial design.")
    if method in {"fractional", "fractional-factorial", "frf"}:
        coded = _fractional(len(bounds))
        return coded, _decode(coded, bounds), ("二水平分部因子，生成元为低阶列的交互。", "Two-level fractional factorial built from interaction columns.")
    if method in {"lhs", "latin", "latin-hypercube"}:
        return _qmc("lhs", bounds, samples, seed)
    if method == "sobol":
        return _qmc("sobol", bounds, samples, seed)
    if method == "halton":
        return _qmc("halton", bounds, samples, seed)
    if method in {"ccd", "central-composite", "central"}:
        coded = _ccd(len(bounds))
        return coded, _decode(np.clip(coded, -1, 1), bounds), ("可旋转中心复合设计，轴点半径已缩放到边界。", "Rotatable central composite design, with axial points scaled onto the bounds.")
    if method in {"bb", "box-behnken", "box"}:
        if len(bounds) < 3:
            raise AxiomError("Box-Behnken 至少需要 3 个因子。", "Box-Behnken needs at least three factors.", code="doe")
        coded = _box_behnken(len(bounds))
        return coded, _decode(coded, bounds), ("Box-Behnken 设计，含 3 个中心点。", "Box-Behnken design with three center points.")
    raise AxiomError(f"未知试验设计 {method}。", f"Unknown design {method}.", code="doe")


def _full_factorial(k: int, levels: int) -> np.ndarray:
    count = max(2, int(levels))
    if count ** k > 4096:
        raise AxiomError("全因子设计过大。", "The full factorial is too large.", code="doe")
    axis = np.linspace(-1.0, 1.0, count)
    rows = np.array(list(product(axis, repeat=k)), dtype=float)
    return rows


def _fractional(k: int) -> np.ndarray:
    if k == 1:
        return np.array([[-1.0], [1.0]])
    base = 2
    while base < k and 2 ** base < 4 * k:
        # Keep a proper fraction once four or more factors would fill 2^k.
        if 2 ** base >= k + 1 and 2 ** base < 2 ** k:
            break
        base += 1
    if 2 ** base >= 2 ** k:
        base = max(2, k - 1)
    n = 2 ** base
    signs = np.ones((n, base))
    for row in range(n):
        for bit in range(base):
            signs[row, bit] = 1.0 if (row >> bit) & 1 else -1.0
    columns = [signs[:, i] for i in range(base)]
    for width in range(2, base + 1):
        for comb in combinations(range(base), width):
            column = np.ones(n)
            for index in comb:
                column *= signs[:, index]
            columns.append(column)
            if len(columns) >= k:
                break
        if len(columns) >= k:
            break
    return np.column_stack(columns[:k])


def _ccd(k: int) -> np.ndarray:
    factor = _full_factorial(k, 2)
    alpha = float(2 ** (k / 4))
    axial = []
    for index in range(k):
        for sign in (-alpha, alpha):
            row = np.zeros(k)
            row[index] = sign
            axial.append(row)
    center = np.zeros((1, k))
    coded = np.vstack([factor, np.array(axial), center])
    # Map the rotatable radius back to the coded cube so the axial points sit on the bounds.
    return coded / alpha


def _box_behnken(k: int) -> np.ndarray:
    rows = []
    for left, right in combinations(range(k), 2):
        for a, b in ((1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0)):
            row = np.zeros(k)
            row[left] = a
            row[right] = b
            rows.append(row)
    rows.extend([np.zeros(k) for _ in range(3)])
    return np.vstack(rows)


def _qmc(kind: str, bounds, samples: int, seed: int):
    k = len(bounds)
    count = max(k + 2, int(samples))
    if kind == "sobol":
        # scipy Sobol wants a power of two to balance the sequence.
        count = 1 << max(1, int(np.ceil(np.log2(count))))
        engine = qmc.Sobol(d=k, scramble=True, seed=seed)
    elif kind == "halton":
        engine = qmc.Halton(d=k, scramble=True, seed=seed)
    else:
        engine = qmc.LatinHypercube(d=k, seed=seed)
    unit = np.asarray(engine.random(count), dtype=float)
    lower = np.array([lo for lo, _ in bounds], dtype=float)
    upper = np.array([hi for _, hi in bounds], dtype=float)
    natural = qmc.scale(unit, lower, upper)
    coded = _encode(natural, bounds)
    notes = {
        "lhs": ("拉丁超立方。", "Latin hypercube."),
        "sobol": ("扰码 Sobol 序列，样本数取 2 的幂。", "Scrambled Sobol sequence, rounded up to a power of two."),
        "halton": ("扰码 Halton 序列。", "Scrambled Halton sequence."),
    }
    return coded, natural, notes[kind]


def _decode(coded: np.ndarray, bounds) -> np.ndarray:
    lower = np.array([lo for lo, _ in bounds], dtype=float)
    upper = np.array([hi for _, hi in bounds], dtype=float)
    return lower + (np.asarray(coded, dtype=float) + 1.0) * 0.5 * (upper - lower)


def _encode(natural: np.ndarray, bounds) -> np.ndarray:
    lower = np.array([lo for lo, _ in bounds], dtype=float)
    upper = np.array([hi for _, hi in bounds], dtype=float)
    span = np.maximum(upper - lower, 1e-12)
    return 2.0 * (np.asarray(natural, dtype=float) - lower) / span - 1.0
