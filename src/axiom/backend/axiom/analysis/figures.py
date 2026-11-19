"""Publication figures derived from a solved model: feasible region and Pareto front."""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.evaluate import objective_components
from axiom.modeling.flatten import flatten
from axiom.modeling.ir import Model
from axiom.solvers.registry import solve_model


def academic_figures(model: Model, variables: dict[str, float] | None = None, solver: str = "highs") -> dict:
    region = None
    front = None
    try:
        region = feasible_region(model)
    except AxiomError:
        region = None
    if region is not None and variables:
        region["optimum"] = {
            "x": _maybe(variables.get(region["x"])),
            "y": _maybe(variables.get(region["y"])),
        }
    if len(model.objectives) >= 2:
        try:
            front = pareto_front(model, solver)
        except AxiomError:
            front = None
    return {"feasible_region": region, "pareto": front}


def feasible_region(model: Model) -> dict | None:
    """Polygon of a linear program in exactly two continuous decision variables."""
    flat = flatten(model)
    if flat.nonlinear:
        return None
    chosen = [var for var in flat.variables if not var.key.startswith("_") and not var.key.startswith("s_")]
    if len(chosen) != 2 or any(var.domain != "continuous" for var in chosen):
        return None
    x_var, y_var = chosen
    planes: list[tuple[float, float, float, str]] = []
    for con in flat.constraints:
        extra = [key for key, coef in con.coeffs.items() if key not in {x_var.key, y_var.key} and abs(coef) > 1e-9]
        if extra:
            return None
        a = float(con.coeffs.get(x_var.key, 0.0))
        b = float(con.coeffs.get(y_var.key, 0.0))
        rhs = float(con.rhs)
        if con.sense == "<=":
            planes.append((a, b, rhs, con.key))
        elif con.sense == ">=":
            planes.append((-a, -b, -rhs, con.key))
        elif con.sense == "==":
            planes.append((a, b, rhs, con.key))
            planes.append((-a, -b, -rhs, con.key + "="))
    planes.extend(_bound_planes(x_var.key, x_var.lower, x_var.upper, axis="x"))
    planes.extend(_bound_planes(y_var.key, y_var.lower, y_var.upper, axis="y"))
    points = []
    for i, left in enumerate(planes):
        for right in planes[i + 1 :]:
            point = _intersect(left, right)
            if point is None or not _inside(point, planes):
                continue
            points.append(point)
    hull = _hull(points)
    if len(hull) < 3:
        return None
    return {
        "x": x_var.key,
        "y": y_var.key,
        "polygon": [[point[0], point[1]] for point in hull],
        "lines": _clipped_lines(planes, hull),
        "optimum": None,
    }


def pareto_front(model: Model, solver: str = "highs") -> dict | None:
    if len(model.objectives) < 2:
        return None
    first, second = model.objectives[0], model.objectives[1]
    points = []
    seen: set[tuple[float, float]] = set()
    for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
        cloned = model.copy()
        cloned.objectives[0].weight = weight if weight > 0 else 0.0
        cloned.objectives[1].weight = 1.0 - weight if weight < 1 else 0.0
        if cloned.objectives[0].weight == 0 and cloned.objectives[1].weight == 0:
            continue
        solved = solve_model(cloned, solver)
        if solved.objective is None or solved.status not in {"optimal", "feasible"}:
            continue
        components = objective_components(cloned, solved.variables)
        if len(components) < 2:
            continue
        pair = (round(float(components[0]["value"]), 6), round(float(components[1]["value"]), 6))
        if pair in seen:
            continue
        seen.add(pair)
        points.append({"weight": weight, "x": pair[0], "y": pair[1]})
    if len(points) < 2:
        return None
    return {"x": first.name, "y": second.name, "x_sense": first.sense, "y_sense": second.sense, "points": points}


def _bound_planes(name: str, lower: float | None, upper: float | None, axis: str) -> list[tuple[float, float, float, str]]:
    planes = []
    if axis == "x":
        if lower is not None:
            planes.append((-1.0, 0.0, -float(lower), f"{name}>="))
        if upper is not None:
            planes.append((1.0, 0.0, float(upper), f"{name}<="))
    else:
        if lower is not None:
            planes.append((0.0, -1.0, -float(lower), f"{name}>="))
        if upper is not None:
            planes.append((0.0, 1.0, float(upper), f"{name}<="))
    return planes


def _intersect(left: tuple[float, float, float, str], right: tuple[float, float, float, str]) -> tuple[float, float] | None:
    a1, b1, c1, _name1 = left
    a2, b2, c2, _name2 = right
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-10:
        return None
    return ((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det)


def _inside(point: tuple[float, float], planes: list[tuple[float, float, float, str]]) -> bool:
    x, y = point
    return all(a * x + b * y <= c + 1e-6 for a, b, c, _name in planes)


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted({(round(x, 8), round(y, 8)) for x, y in points})
    if len(unique) < 3:
        return unique

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _clipped_lines(planes: list[tuple[float, float, float, str]], hull: list[tuple[float, float]]) -> list[dict]:
    xs = [point[0] for point in hull]
    ys = [point[1] for point in hull]
    pad_x = max((max(xs) - min(xs)) * 0.08, 0.5)
    pad_y = max((max(ys) - min(ys)) * 0.08, 0.5)
    box = (min(xs) - pad_x, max(xs) + pad_x, min(ys) - pad_y, max(ys) + pad_y)
    lines = []
    for a, b, c, name in planes:
        if name.endswith(">=") or name.endswith("<="):
            continue
        segment = _clip_line(a, b, c, box)
        if segment is None:
            continue
        lines.append({"name": name.split("[")[0], "points": [[segment[0][0], segment[0][1]], [segment[1][0], segment[1][1]]]})
    return lines


def _clip_line(a: float, b: float, c: float, box: tuple[float, float, float, float]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    x0, x1, y0, y1 = box
    hits: list[tuple[float, float]] = []
    if abs(b) > 1e-10:
        for x in (x0, x1):
            y = (c - a * x) / b
            if y0 - 1e-6 <= y <= y1 + 1e-6:
                hits.append((x, y))
    if abs(a) > 1e-10:
        for y in (y0, y1):
            x = (c - b * y) / a
            if x0 - 1e-6 <= x <= x1 + 1e-6:
                hits.append((x, y))
    dedup = []
    for point in hits:
        if all(abs(point[0] - other[0]) > 1e-6 or abs(point[1] - other[1]) > 1e-6 for other in dedup):
            dedup.append(point)
    if len(dedup) < 2:
        return None
    return dedup[0], dedup[1]


def _maybe(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)
