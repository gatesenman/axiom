"""Polynomial response surfaces, Gaussian-process Kriging, and radial basis surrogates.

Each fit reports k-fold (or leave-one-out) cross-validation error. Prediction
returns the mean and, for the Gaussian process, the posterior standard deviation.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import minimize

from axiom.errors import AxiomError


def fit(kind: str, x_values, y_values, folds: int = 5) -> dict:
    kind = (kind or "polynomial").lower().strip()
    x_array = np.asarray(x_values, dtype=float)
    y_array = np.asarray(y_values, dtype=float).reshape(-1)
    if x_array.ndim != 2 or x_array.shape[0] != y_array.shape[0] or x_array.shape[0] < 3:
        raise AxiomError("响应面至少需要 3 个设计点。", "A surrogate needs at least three design points.", code="surrogate")
    builder = {"polynomial": _Polynomial, "rsm": _Polynomial, "kriging": _Kriging, "gp": _Kriging, "rbf": _RBF}.get(kind)
    if builder is None:
        raise AxiomError(f"未知响应面 {kind}。", f"Unknown surrogate {kind}.", code="surrogate")
    model = builder(x_array, y_array)
    error = cross_validate(builder, x_array, y_array, folds)
    return {"kind": kind, "model": model, "cv": error, "n": int(x_array.shape[0]), "factors": int(x_array.shape[1])}


def cross_validate(builder, x_array: np.ndarray, y_array: np.ndarray, folds: int) -> dict:
    n = x_array.shape[0]
    k = n if n < 8 else min(max(2, int(folds)), n)
    order = np.arange(n)
    folds_idx = np.array_split(order, k)
    predicted = np.zeros(n)
    for hold in folds_idx:
        train = np.setdiff1d(order, hold, assume_unique=False)
        if train.size < 2:
            predicted[hold] = float(y_array.mean())
            continue
        model = builder(x_array[train], y_array[train])
        predicted[hold] = model.predict(x_array[hold])["mean"]
    residual = y_array - predicted
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((y_array - y_array.mean()) ** 2))
    return {
        "folds": int(k),
        "rmse": float(np.sqrt(np.mean(residual ** 2))),
        "mae": float(np.mean(np.abs(residual))),
        "r2": 1.0 if ss_tot < 1e-18 else float(1.0 - ss_res / ss_tot),
    }


class _Polynomial:
    def __init__(self, x_array, y_array):
        self.degree = 2 if x_array.shape[0] > x_array.shape[1] + 2 else 1
        design = _polynomial_features(x_array, self.degree)
        coef, *_ = np.linalg.lstsq(design, y_array, rcond=None)
        self.coef = coef
        self.x_mean = x_array.mean(axis=0)
        self.x_scale = np.maximum(x_array.std(axis=0), 1e-9)

    def predict(self, x_array):
        design = _polynomial_features(np.asarray(x_array, dtype=float), self.degree, self.x_mean, self.x_scale)
        mean = design @ self.coef
        return {"mean": np.asarray(mean, dtype=float), "std": np.zeros(len(mean))}


def _polynomial_features(x_array, degree: int, mean=None, scale=None) -> np.ndarray:
    x_array = np.asarray(x_array, dtype=float)
    if mean is None:
        mean = x_array.mean(axis=0)
        scale = np.maximum(x_array.std(axis=0), 1e-9)
    coded = (x_array - mean) / scale
    columns = [np.ones(coded.shape[0])]
    for index in range(coded.shape[1]):
        columns.append(coded[:, index])
    if degree >= 2:
        for left in range(coded.shape[1]):
            for right in range(left, coded.shape[1]):
                columns.append(coded[:, left] * coded[:, right])
    return np.column_stack(columns)


class _RBF:
    def __init__(self, x_array, y_array):
        self.x_array = np.asarray(x_array, dtype=float)
        self.y_array = np.asarray(y_array, dtype=float)
        smoothing = 1e-4 if self.x_array.shape[0] > self.x_array.shape[1] else 1e-2
        self.engine = RBFInterpolator(self.x_array, self.y_array, kernel="thin_plate_spline", smoothing=smoothing)

    def predict(self, x_array):
        mean = np.asarray(self.engine(np.asarray(x_array, dtype=float)), dtype=float)
        return {"mean": mean, "std": np.zeros(len(mean))}


class _Kriging:
    """Ordinary Kriging with a Gaussian correlation and a concentrated likelihood."""

    def __init__(self, x_array, y_array):
        raw = np.asarray(x_array, dtype=float)
        self.shift = raw.min(axis=0)
        self.span = np.maximum(raw.max(axis=0) - raw.min(axis=0), 1e-9)
        self.x_array = (raw - self.shift) / self.span
        self.y_mean = float(np.mean(y_array))
        self.y_array = np.asarray(y_array, dtype=float) - self.y_mean
        dimension = self.x_array.shape[1]
        opt = minimize(self._nll, np.zeros(dimension), method="L-BFGS-B", bounds=[(-3.0, 2.5)] * dimension)
        self.theta = np.exp(opt.x)
        self.corr = _gaussian(self.x_array, self.x_array, self.theta)
        self.corr.flat[:: self.corr.shape[0] + 1] += 1e-10
        self.chol = np.linalg.cholesky(self.corr)
        self.weights = np.linalg.solve(self.chol.T, np.linalg.solve(self.chol, self.y_array))
        self.sigma2 = max(float(self.y_array @ self.weights) / len(self.y_array), 1e-12)

    def _nll(self, log_theta: np.ndarray) -> float:
        theta = np.exp(log_theta)
        matrix = _gaussian(self.x_array, self.x_array, theta)
        matrix.flat[:: matrix.shape[0] + 1] += 1e-10
        try:
            chol = np.linalg.cholesky(matrix)
        except np.linalg.LinAlgError:
            return 1e12
        weights = np.linalg.solve(chol.T, np.linalg.solve(chol, self.y_array))
        sigma2 = max(float(self.y_array @ weights) / len(self.y_array), 1e-18)
        logdet = 2.0 * float(np.sum(np.log(np.diag(chol))))
        return 0.5 * (len(self.y_array) * np.log(sigma2) + logdet)

    def predict(self, x_array):
        coded = (np.asarray(x_array, dtype=float) - self.shift) / self.span
        rows = []
        stds = []
        for point in coded:
            r = _gaussian(self.x_array, point.reshape(1, -1), self.theta).reshape(-1)
            mean = self.y_mean + float(r @ self.weights)
            solved = np.linalg.solve(self.chol, r)
            variance = self.sigma2 * max(1.0 - float(solved @ solved), 0.0)
            rows.append(mean)
            stds.append(float(np.sqrt(variance)))
        return {"mean": np.array(rows), "std": np.array(stds)}


def _gaussian(left: np.ndarray, right: np.ndarray, theta: np.ndarray) -> np.ndarray:
    # left is (n, d), right is (m, d)
    delta = left[:, None, :] - right[None, :, :]
    return np.exp(-np.sum(theta * delta ** 2, axis=2))
