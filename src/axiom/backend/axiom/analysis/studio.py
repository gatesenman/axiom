"""One entry point for the analysis workbench, the agents, and the tests."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from axiom.analysis.compatibility import compatibility_matrix
from axiom.analysis.designs import generate
from axiom.analysis.multiobj import optimize
from axiom.analysis.quality import quality_report
from axiom.analysis.ranging import local_sensitivity
from axiom.analysis.response import evaluate_design, grid, windows
from axiom.analysis.robustopt import chance, stochastic
from axiom.analysis.screening import morris, sobol
from axiom.analysis.service import present
from axiom.analysis.surrogates import fit
from axiom.analysis.sweeps import sweep
from axiom.analysis.uncertainty import form, propagate
from axiom.errors import AxiomError
from axiom.modeling import parse_aml
from axiom.modeling.ir import Model
from axiom.mdo.architectures import solve as solve_mdo
from axiom.mdo.templates import get_problem, list_problems
from axiom.solvers.registry import solve_model

Cancel = Callable[[], bool] | None


def run_study(kind: str, dsl: str = "", options: dict | None = None, cancel: Cancel = None) -> dict[str, Any]:
    options = dict(options or {})
    kind = (kind or "").lower().strip().replace("_", "-")
    aliases = {
        "sensitivity": "local",
        "local-sensitivity": "local",
        "global": "sobol",
        "what-if": "sweep",
        "parametric": "sweep",
        "rsm": "doe",
        "response-surface": "doe",
        "monte-carlo": "uq",
        "uncertainty": "uq",
        "reliability": "form",
        "robust": "robust",
        "stochastic": "robust",
        "chance-constraint": "chance",
        "multi-objective": "multi",
        "nsga": "multi",
        "nsga2": "multi",
        "nsga3": "multi",
        "pareto": "multi",
        "infeasibility": "iis",
        "quality": "quality",
        "schedule": "schedule",
        "gantt": "schedule",
        "compatibility": "compatibility",
        "matrix": "compatibility",
    }
    kind = aliases.get(kind, kind)
    if kind == "compatibility":
        report = compatibility_matrix(execute=bool(options.get("execute")), cancel=cancel)
        report["kind"] = "compatibility"
        report["summary_metrics"] = report["summary"]
        return report
    if kind == "mdo":
        return _mdo(options, cancel)
    if kind == "schedule":
        return _schedule(dsl)
    model = _load_model(dsl, options)
    if kind == "local":
        return _local(model, options)
    if kind == "morris":
        return _global(model, "morris", options, cancel)
    if kind == "sobol":
        return _global(model, "sobol", options, cancel)
    if kind == "sweep":
        return _sweep(model, options, cancel)
    if kind == "doe":
        return _doe(model, options, cancel)
    if kind == "uq":
        return _uq(model, options, cancel)
    if kind == "form":
        payload = form(model, cv=float(options.get("cv", 0.08)), solver=options.get("solver") or "highs", limit=options.get("limit"))
        payload["kind"] = "form"
        return payload
    if kind == "robust":
        payload = stochastic(model, options.get("scenarios"), options.get("mode") or "two-stage", float(options.get("penalty", 1000)), options.get("solver") or "highs")
        payload["kind"] = "robust"
        return payload
    if kind == "chance":
        payload = chance(model, float(options.get("alpha", 0.05)), float(options.get("cv", 0.05)), options.get("solver") or "highs")
        payload["kind"] = "chance"
        return payload
    if kind == "multi":
        return _multi(model, options)
    if kind in {"iis", "quality"}:
        payload = quality_report(model, options.get("solver") or "highs")
        payload["kind"] = kind
        return payload
    raise AxiomError(f"未知分析 {kind}。", f"Unknown analysis {kind}.", code="analysis")


def _load_model(dsl: str, options: dict) -> Model:
    template = str(options.get("template") or "")
    if template in {"sellar", "wing", "aircraft", "supply", "supply-chain"}:
        raise AxiomError("这个分析要在多学科模板上运行，请选择 MDO。", "Run this template from the MDO wizard.", code="analysis")
    text = dsl.strip()
    if template == "scheduling" or (not text and template == "schedule"):
        text = _schedule_dsl()
    if not text:
        raise AxiomError("先打开一个模型，或在向导里选择模板。", "Open a model, or pick a template in the wizard.", code="analysis")
    return parse_aml(text)


def _local(model: Model, options: dict) -> dict:
    payload = local_sensitivity(model, options.get("solver") or "highs")
    payload["kind"] = "local"
    if payload.get("ok"):
        payload["tornado"] = [
            {"name": row["name"], "low": row["allowable_min"], "high": row["allowable_max"], "base": row["coefficient"], "span": abs((row["allowable_max"] or 0) - (row["allowable_min"] or 0))}
            for row in payload["objective_ranging"]
        ]
        payload["points"] = [
            {"id": f"dual-{index}", "values": {"dual": row["dual"], "rhs": row["rhs"]}, "objectives": {"name": row["name"]}, "feasible": True, "label": row["name"]}
            for index, row in enumerate(payload["rhs_ranging"])
        ]
    payload["summary_metrics"] = {"objective": payload.get("objective"), "status": payload.get("status")}
    return payload


def _global(model: Model, method: str, options: dict, cancel: Cancel) -> dict:
    factor_rows = windows(model)
    if not factor_rows:
        return {"ok": False, "kind": method, "message": "模型没有变量。", "message_en": "The model has no variables."}
    names = [row["name"] for row in factor_rows]
    bounds = [(row["lower"], row["upper"]) for row in factor_rows]

    def function(sample):
        if cancel and cancel():
            raise AxiomError("已取消。", "Cancelled.", code="cancelled")
        point = {name: float(sample[index]) for index, name in enumerate(names)}
        response = evaluate_design(model, point)
        return float(response["penalized"] if response["penalized"] is not None else 0.0)

    if method == "morris":
        result = morris(function, names, bounds, int(options.get("trajectories", 6)), int(options.get("levels", 4)), int(options.get("seed", 1)))
    else:
        result = sobol(function, names, bounds, int(options.get("samples", 16)), int(options.get("seed", 1)))
    result["kind"] = method
    result["units"] = {row["name"]: row["unit"] for row in factor_rows}
    result["points"] = [
        {"id": f"{method}-{index}", "values": {row["name"]: row.get("mu_star", row.get("S1", 0.0))}, "objectives": row, "feasible": True, "label": row["name"]}
        for index, row in enumerate(result.get("rows") or [])
    ]
    result["summary_metrics"] = {"samples": result.get("samples"), "library": result.get("library")}
    return result


def _sweep(model: Model, options: dict, cancel: Cancel) -> dict:
    payload = sweep(model, options.get("factors"), int(options.get("steps", 7)), options.get("solver") or "highs", cancel)
    payload["kind"] = "sweep"
    points = []
    for index, point in enumerate(payload.get("points") or []):
        values = {"x": point.get("x")}
        if "y" in point:
            values["y"] = point.get("y")
        points.append({"id": point.get("id") or f"sweep-{index}", "values": values, "objectives": {"objective": point.get("objective")}, "feasible": point.get("status") in {"optimal", "feasible"}, "label": point.get("id")})
    payload["points"] = points
    payload["summary_metrics"] = {"samples": len(points)}
    return payload


def _doe(model: Model, options: dict, cancel: Cancel) -> dict:
    factor_rows = windows(model)[:6]
    if len(factor_rows) < 1:
        return {"ok": False, "kind": "doe", "message": "模型没有变量。", "message_en": "The model has no variables."}
    method = options.get("method") or ("box-behnken" if len(factor_rows) >= 3 else "lhs")
    design = generate(method, [(row["lower"], row["upper"]) for row in factor_rows], int(options.get("samples", 16)), int(options.get("levels", 2)), int(options.get("seed", 1)))
    names = [row["name"] for row in factor_rows]
    points = []
    responses = []
    for index, row in enumerate(design["natural"]):
        if cancel and cancel():
            break
        values = {name: float(row[pos]) for pos, name in enumerate(names)}
        response = evaluate_design(model, values)
        objective = response["objective"]
        responses.append(np.nan if objective is None else float(objective))
        points.append(
            {
                "id": f"doe-{index}",
                "values": values,
                "objectives": {"objective": objective},
                "feasible": response["feasible"],
                "violation": response["violation"],
                "label": f"{index + 1}",
            }
        )
    y_values = np.array([0.0 if not np.isfinite(value) else value for value in responses], dtype=float)
    x_values = np.array(design["natural"], dtype=float)
    surrogate_kind = options.get("surrogate") or "polynomial"
    fitted = None
    surface = None
    try:
        fitted = fit(surrogate_kind, x_values, y_values)
        surface = _surface(fitted["model"], factor_rows, names)
    except AxiomError as exc:
        fitted = {"error": exc.message, "error_en": exc.message_en}
    effects = _effects(points, names)
    return {
        "ok": True,
        "kind": "doe",
        "method": design["method"],
        "note": design["note"],
        "note_en": design["note_en"],
        "columns": [{"key": row["name"], "label": row["name"], "unit": row["unit"]} for row in factor_rows],
        "points": points,
        "surrogate": {key: value for key, value in (fitted or {}).items() if key != "model"},
        "surface": surface,
        "effects": effects,
        "correlation": _correlation(points, names),
        "summary_metrics": {"samples": len(points), "r2": None if not isinstance(fitted, dict) else (fitted.get("cv") or {}).get("r2")},
    }


def _uq(model: Model, options: dict, cancel: Cancel) -> dict:
    payload = propagate(model, options.get("method") or "monte-carlo", int(options.get("samples", 24)), float(options.get("cv", 0.08)), int(options.get("seed", 1)), options.get("solver") or "highs", cancel)
    payload["kind"] = "uq"
    if options.get("form"):
        payload["form"] = form(model, cv=float(options.get("cv", 0.08)), solver=options.get("solver") or "highs", limit=options.get("limit"))
    payload["points"] = [
        {"id": f"uq-{index}", "values": {"objective": value}, "objectives": {"objective": value}, "feasible": True, "label": str(index + 1)}
        for index, value in enumerate(payload.get("values") or [])
    ]
    payload["summary_metrics"] = {"mean": payload.get("mean"), "std": payload.get("std"), "samples": payload.get("samples")}
    return payload


def _multi(model: Model, options: dict) -> dict:
    method = options.get("method") or "nsga2"
    payload = optimize(
        model,
        method,
        options.get("weights"),
        int(options.get("steps", 6)),
        options.get("solver") or "highs",
        int(options.get("seed", 1)),
        int(options.get("generations", 25)),
        int(options.get("population", 32)),
    )
    payload["kind"] = "multi"
    payload["summary_metrics"] = {"hypervolume": payload.get("hypervolume"), "points": len(payload.get("pareto") or payload.get("points") or [])}
    return payload


def _mdo(options: dict, cancel: Cancel) -> dict:
    problem = get_problem(str(options.get("template") or "sellar"))
    architecture = options.get("architecture") or "mdf"
    result = solve_mdo(problem, architecture, options.get("mda") or "gauss-seidel", cancel)
    result["kind"] = "mdo"
    result["templates"] = list_problems()
    state = result.get("state") or {}
    result["points"] = [
        {
            "id": "design",
            "values": {key: float(value) for key, value in (result.get("design") or {}).items()},
            "objectives": {"objective": result.get("objective")},
            "feasible": (result.get("violation") or 0) <= 1e-4,
            "label": result.get("architecture") or architecture,
        }
    ]
    result["convergence"] = result.get("history") or []
    result["summary_metrics"] = {"objective": result.get("objective"), "violation": result.get("violation"), "architecture": result.get("architecture")}
    result["state_rows"] = [{"name": key, "value": value, "unit": (result.get("units") or {}).get(key, "")} for key, value in state.items()]
    return result


def _schedule(dsl: str) -> dict:
    text = dsl.strip() or _schedule_dsl()
    model = parse_aml(text)
    solved = solve_model(model, "highs", {"time_limit": 8})
    view = present(model, solved.variables, solved.objective)
    return {
        "ok": solved.feasible,
        "kind": "schedule",
        "status": solved.status,
        "objective": solved.objective,
        "variables": solved.variables,
        "gantt": view.get("gantt") or [],
        "message": solved.message,
        "message_en": solved.message_en,
        "summary_metrics": {"makespan": solved.objective, "jobs": len(view.get("gantt") or [])},
        "points": [
            {"id": row["id"], "values": {"start": row["start"], "end": row["end"], "duration": row["duration"]}, "objectives": {}, "feasible": True, "label": row["id"]}
            for row in (view.get("gantt") or [])
        ],
    }


def _schedule_dsl() -> str:
    from axiom.templates.library import get_template

    item = get_template("scheduling")
    if item is None:
        raise AxiomError("没有调度模板。", "The scheduling template is missing.", code="analysis")
    return item["dsl"]


def _surface(model, factor_rows: list[dict], names: list[str]) -> dict | None:
    if len(factor_rows) < 2:
        return None
    xs = grid(factor_rows[0]["lower"], factor_rows[0]["upper"], 21)
    ys = grid(factor_rows[1]["lower"], factor_rows[1]["upper"], 21)
    mids = [(row["lower"] + row["upper"]) / 2 for row in factor_rows]
    rows = []
    for y in ys:
        line = []
        for x in xs:
            point = list(mids)
            point[0] = float(x)
            point[1] = float(y)
            line.append(float(model.predict(np.array([point]))["mean"][0]))
        rows.append(line)
    return {
        "x": [float(item) for item in xs],
        "y": [float(item) for item in ys],
        "z": rows,
        "xlabel": names[0],
        "ylabel": names[1],
        "zlabel": "objective",
    }


def _effects(points: list[dict], names: list[str]) -> dict:
    factors = []
    for name in names:
        pairs = [(float(point["values"][name]), point["objectives"].get("objective")) for point in points if point["objectives"].get("objective") is not None]
        if len(pairs) < 3:
            continue
        ordered = sorted(pairs, key=lambda item: item[0])
        bins = np.array_split(np.array(ordered, dtype=float), min(5, len(ordered)))
        levels = []
        for chunk in bins:
            if len(chunk) == 0:
                continue
            levels.append({"x": float(np.mean(chunk[:, 0])), "mean": float(np.mean(chunk[:, 1]))})
        factors.append({"name": name, "levels": levels})
    interaction = None
    if len(names) >= 2 and points:
        a, b = names[0], names[1]
        b_values = sorted(float(point["values"][b]) for point in points)
        mid = b_values[len(b_values) // 2]
        low = [point for point in points if float(point["values"][b]) <= mid and point["objectives"].get("objective") is not None]
        high = [point for point in points if float(point["values"][b]) > mid and point["objectives"].get("objective") is not None]
        interaction = {
            "a": a,
            "b": b,
            "low": [{"x": float(point["values"][a]), "y": float(point["objectives"]["objective"])} for point in low],
            "high": [{"x": float(point["values"][a]), "y": float(point["objectives"]["objective"])} for point in high],
        }
    return {"main": factors, "interaction": interaction}


def _correlation(points: list[dict], names: list[str]) -> dict:
    columns = []
    labels = list(names)
    usable = [point for point in points if point["objectives"].get("objective") is not None]
    if len(usable) < 3:
        return {"labels": labels, "matrix": []}
    for name in names:
        columns.append([float(point["values"][name]) for point in usable])
    labels.append("objective")
    columns.append([float(point["objectives"]["objective"]) for point in usable])
    matrix = np.corrcoef(np.array(columns, dtype=float))
    if matrix.ndim == 0:
        matrix = np.array([[1.0]])
    matrix = np.nan_to_num(matrix, nan=0.0)
    return {"labels": labels, "matrix": [[float(value) for value in row] for row in matrix]}
