"""Sensitivity, scenarios, infeasibility diagnosis, and chart payloads."""

from __future__ import annotations

import copy

from axiom.errors import AxiomError
from axiom.modeling.evaluate import objective_components
from axiom.modeling.ir import Constraint, Expr, Model, VarDecl, const, ref
from axiom.solvers.registry import solve_model


def sensitivity(model: Model, solver: str = "highs", widths: tuple[float, ...] = (-0.2, -0.1, 0.1, 0.2)) -> dict:
    base = solve_model(model, _solver_for(model, solver))
    if base.status not in {"optimal", "feasible"}:
        return {"base": base.to_dict(), "rows": [], "note": base.message}
    rows = []
    for label, apply in _knobs(model)[:10]:
        low = high = base.objective or 0.0
        points = []
        for width in widths:
            mutated = apply(model, width)
            try:
                solved = solve_model(mutated, _solver_for(mutated, solver))
            except AxiomError:
                continue
            if solved.objective is None:
                continue
            points.append({"width": width, "objective": solved.objective})
            low = min(low, solved.objective)
            high = max(high, solved.objective)
        rows.append(
            {
                "name": label,
                "base": base.objective,
                "low": low,
                "high": high,
                "span": high - low,
                "points": points,
            }
        )
    rows.sort(key=lambda item: item["span"], reverse=True)
    return {"base": base.objective, "rows": rows}


def scenarios(model: Model, cases: list[dict], solver: str = "highs") -> list[dict]:
    rows = []
    for case in cases:
        mutated = model.copy()
        _apply_overrides(mutated, case.get("parameters") or {})
        if case.get("rhs_scale"):
            _scale_rhs(mutated, case["rhs_scale"])
        solved = solve_model(mutated, _solver_for(mutated, solver))
        rows.append(
            {
                "name": case.get("name") or "scenario",
                "status": solved.status,
                "objective": solved.objective,
                "variables": solved.variables,
            }
        )
    return rows


def diagnose(model: Model) -> dict:
    """Minimize nonnegative slack that relaxes inequalities, then explain the conflict."""
    elastic = model.copy()
    slacks: list[str] = []
    origins: dict[str, tuple[str, str, float | None]] = {}
    rewritten: list[Constraint] = []
    for con in elastic.constraints:
        if con.kind != "comparison" or con.relation not in {"<=", ">="} or con.lhs is None or con.rhs is None:
            rewritten.append(con)
            continue
        name = f"diag_{con.name}"
        suffix = 2
        while name in elastic.variables:
            name = f"diag_{con.name}_{suffix}"
            suffix += 1
        sets = [quant.set_name for quant in con.quants]
        elastic.variables[name] = VarDecl(name=name, index_sets=sets, domain="continuous", lower=0.0)
        from axiom.modeling.ir import Index

        slack_expr = ref(name, tuple(Index("symbol", quant.index) for quant in con.quants)) if sets else ref(name)
        # <= relaxes by raising the right-hand side; >= relaxes by lowering it.
        if con.relation == "<=":
            lhs = Expr("sub", args=(con.lhs, slack_expr))
            relation = "<="
        else:
            lhs = Expr("add", args=(con.lhs, slack_expr))
            relation = ">="
        rhs_value = float(con.rhs.value) if con.rhs.op == "const" and con.rhs.value is not None else None
        rewritten.append(Constraint(name=con.name, quants=con.quants, kind="comparison", relation=relation, lhs=lhs, rhs=con.rhs))
        slacks.append(name)
        origins[name] = (con.name, con.relation or "<=", rhs_value)
    elastic.constraints = rewritten
    if not slacks:
        return {
            "feasible_without_slacks": True,
            "slacks": [],
            "conflicts": [],
            "message": "没有可松弛的不等式。",
            "message_en": "There is no inequality that can be relaxed.",
        }
    total: Expr | None = None
    for name in slacks:
        term = ref(name) if not elastic.variables[name].index_sets else _sum_var(elastic, name)
        total = term if total is None else Expr("add", args=(total, term))
    from axiom.modeling.ir import Objective

    elastic.objectives = [Objective(name="violation", sense="minimize", expr=total or const(0))]
    try:
        solved = solve_model(elastic, "highs")
    except AxiomError as exc:
        return {
            "status": "error",
            "feasible_without_slacks": False,
            "slacks": [],
            "conflicts": [],
            "message": f"没能完成不可行诊断：{exc.message}",
            "message_en": f"Infeasibility diagnosis did not finish: {exc.message_en}",
        }
    conflicts = []
    for key, value in solved.variables.items():
        if value <= 1e-6:
            continue
        owner = next((name for name in origins if key == name or key.startswith(name + "[")), None)
        if owner is None:
            continue
        constraint, sense, rhs = origins[owner]
        label = key[len(owner) :] or constraint
        shown = constraint if label in {"", constraint} else f"{constraint}{label}" if label.startswith("[") else key.replace(owner, constraint, 1)
        if not shown.startswith(constraint):
            shown = constraint
        suggested = None if rhs is None else (rhs + value if sense == "<=" else rhs - value)
        if sense == "<=" and rhs is not None and suggested is not None:
            suggestion = f"把约束 {shown} 的右端从 {_num(rhs)} 提高到 {_num(suggested)}，相当于放松 {_num(value)}。"
            suggestion_en = f"Raise the right-hand side of {shown} from {_num(rhs)} to {_num(suggested)}, a relaxation of {_num(value)}."
        elif sense == ">=" and rhs is not None and suggested is not None:
            suggestion = f"把约束 {shown} 的右端从 {_num(rhs)} 降到 {_num(suggested)}，相当于放松 {_num(value)}。"
            suggestion_en = f"Lower the right-hand side of {shown} from {_num(rhs)} to {_num(suggested)}, a relaxation of {_num(value)}."
        else:
            suggestion = f"约束 {shown} 需要约 {_num(value)} 的松弛才可能成立。"
            suggestion_en = f"Constraint {shown} needs about {_num(value)} of slack before it can hold."
        conflicts.append(
            {
                "name": key,
                "constraint": constraint,
                "label": shown,
                "sense": sense,
                "rhs": rhs,
                "slack": value,
                "suggested_rhs": suggested,
                "suggestion": suggestion,
                "suggestion_en": suggestion_en,
            }
        )
    feasible = solved.objective is not None and solved.objective <= 1e-6 and not conflicts
    if feasible:
        message = "模型可行，不需要松弛。"
        message_en = "The model is feasible without slacks."
    elif conflicts:
        names = "、".join(item["label"] for item in conflicts[:6])
        names_en = ", ".join(item["label"] for item in conflicts[:6])
        message = f"这些要求互相冲突：{names}。{conflicts[0]['suggestion']}"
        message_en = f"These requirements conflict: {names_en}. {conflicts[0]['suggestion_en']}"
    else:
        message = "不等式放开之后仍然不可行，冲突更可能来自等式或变量界。"
        message_en = "The model stays infeasible after inequalities are relaxed, so an equality or a variable bound is the more likely source."
    return {
        "status": solved.status,
        "total_violation": solved.objective,
        "feasible_without_slacks": feasible,
        "slacks": [{"name": item["name"], "value": item["slack"]} for item in conflicts],
        "conflicts": conflicts,
        "message": message,
        "message_en": message_en,
    }


def monte_carlo(model: Model, samples: int = 40, cv: float = 0.1, seed: int = 1, solver: str = "highs") -> dict:
    import numpy as np

    rng = np.random.default_rng(seed)
    values: list[float] = []
    count = max(5, min(int(samples), 200))
    for _ in range(count):
        mutated = model.copy()
        touched = _perturb(mutated, rng, cv)
        if not touched:
            break
        try:
            solved = solve_model(mutated, _solver_for(mutated, solver))
        except AxiomError:
            continue
        if solved.objective is not None and solved.status in {"optimal", "feasible"}:
            values.append(float(solved.objective))
    if not values:
        return {"samples": 0, "values": [], "message": "没有可扰动的数据。", "message_en": "Nothing to perturb."}
    array = np.array(values)
    return {
        "samples": len(values),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "p05": float(np.quantile(array, 0.05)),
        "p50": float(np.quantile(array, 0.50)),
        "p95": float(np.quantile(array, 0.95)),
        "min": float(array.min()),
        "max": float(array.max()),
        "values": values,
    }


def present(model: Model, variables: dict[str, float], objective: float | None) -> dict:
    # Insertion order matches the variable table. Magnitude order made the chart labels disagree with that table.
    bars = [
        {"name": key, "value": value}
        for key, value in variables.items()
        if not key.startswith("_") and not key.startswith("s_")
    ]
    payload = {
        "bars": bars[:16],
        "gantt": _gantt(model, variables),
        "network": _network(model, variables),
        "objectives": objective_components(model, variables) if variables else [],
        "objective": objective,
    }
    return payload


def statistics(variables: dict[str, float], constraints: list[dict]) -> dict:
    nums = [value for key, value in variables.items() if not key.startswith("_")]
    binding = [row for row in constraints if row.get("binding")]
    violated = [row for row in constraints if row.get("violated")]
    return {
        "variable_count": len(nums),
        "nonzero_variables": sum(1 for value in nums if abs(value) > 1e-8),
        "max_variable": max(nums) if nums else None,
        "binding_constraints": len(binding),
        "violated_constraints": len(violated),
    }


def _solver_for(model: Model, requested: str) -> str:
    from axiom.modeling.flatten import flatten

    try:
        flat = flatten(model)
    except AxiomError:
        return requested
    if flat.nonlinear and requested in {"highs", "cbc", "glpk", "scip", "glop", "cp-sat"}:
        return "ipopt"
    return requested


def _knobs(model: Model):
    knobs = []
    for param in model.parameters.values():
        for key, value in list(param.values.items())[:4]:
            label = param.name if not key else f"{param.name}[{','.join(key)}]"

            def apply(source: Model, width: float, param_name=param.name, index=key, base=value) -> Model:
                cloned = source.copy()
                cloned.parameters[param_name].values[index] = base * (1 + width)
                return cloned

            knobs.append((label, apply))
    for con in model.constraints:
        if con.kind == "comparison" and con.rhs is not None and con.rhs.op == "const":
            label = f"rhs:{con.name}"
            base = float(con.rhs.value or 0)

            def apply_rhs(source: Model, width: float, cname=con.name, origin=base) -> Model:
                cloned = source.copy()
                for item in cloned.constraints:
                    if item.name == cname and item.rhs is not None and item.rhs.op == "const":
                        item.rhs = const(origin * (1 + width))
                return cloned

            knobs.append((label, apply_rhs))
    return knobs


def _apply_overrides(model: Model, overrides: dict) -> None:
    for name, payload in overrides.items():
        if name not in model.parameters:
            continue
        param = model.parameters[name]
        if isinstance(payload, (int, float)):
            param.values[()] = float(payload)
        elif isinstance(payload, dict):
            for key, value in payload.items():
                index = tuple(part.strip() for part in str(key).split(",")) if not isinstance(key, (list, tuple)) else tuple(map(str, key))
                if len(index) == 1 and not param.index_sets:
                    param.values[()] = float(value)
                else:
                    param.values[index] = float(value)


def _scale_rhs(model: Model, scales: dict) -> None:
    for con in model.constraints:
        factor = scales.get(con.name)
        if factor is None or con.rhs is None or con.rhs.op != "const":
            continue
        con.rhs = const(float(con.rhs.value or 0) * float(factor))


def _perturb(model: Model, rng, cv: float) -> bool:
    touched = False
    for param in model.parameters.values():
        for key, value in list(param.values.items()):
            param.values[key] = float(value) * (1 + float(rng.normal(0, cv)))
            touched = True
    if touched:
        return True
    for con in model.constraints:
        if con.rhs is not None and con.rhs.op == "const":
            con.rhs = const(float(con.rhs.value or 0) * (1 + float(rng.normal(0, cv))))
            touched = True
    return touched


def _num(value: float) -> str:
    if abs(value - round(value)) < 1e-6 and abs(value) < 1e12:
        return str(int(round(value)))
    return format(value, ".6g")


def _sum_var(model: Model, name: str) -> Expr:
    from axiom.modeling.ir import Quantifier

    decl = model.variables[name]
    quants = tuple(Quantifier(index=f"i{i}", set_name=set_name) for i, set_name in enumerate(decl.index_sets))
    from axiom.modeling.ir import Index

    body = ref(name, tuple(Index("symbol", quant.index) for quant in quants))
    return Expr("sum", quants=quants, args=(body,))


def _gantt(model: Model, variables: dict[str, float]):
    if model.meta.get("view") != "gantt":
        return None
    set_name = model.meta.get("gantt_job_set")
    start_name = model.meta.get("gantt_start", "start")
    duration_name = model.meta.get("gantt_duration", "p")
    if set_name not in model.sets or duration_name not in model.parameters:
        return None
    rows = []
    for job in model.sets[set_name].elements:
        start = float(variables.get(f"{start_name}[{job}]", variables.get(start_name, 0.0)))
        duration = model.parameters[duration_name].get((job,))
        rows.append({"id": job, "start": start, "end": start + duration, "duration": duration})
    return rows


def recommend(model: Model) -> dict:
    """One sentence that names the solver family, plus the algorithm the studio should offer."""
    from axiom.analysis.algorithms import choose

    try:
        picked = choose(model)
    except AxiomError as exc:
        return {
            "solver": "highs",
            "family": "lp",
            "algorithm": "auto",
            "label_zh": "自动",
            "label_en": "Auto",
            "reason_zh": f"还不能判断算法：{exc.message} 在模型完整之前，先用 HiGHS。",
            "reason_en": f"The algorithm is not settled yet: {exc.message_en} HiGHS is the placeholder until the model is complete.",
        }
    return {
        "solver": picked["solver"],
        "family": picked["family"],
        "algorithm": picked["id"],
        "label_zh": picked["label_zh"],
        "label_en": picked["label_en"],
        "reason_zh": picked["reason_zh"],
        "reason_en": picked["reason_en"],
    }


def what_if_knobs(model: Model) -> list[dict]:
    knobs = []
    for con in model.constraints:
        if con.kind == "comparison" and con.rhs is not None and con.rhs.op == "const" and not con.quants:
            value = float(con.rhs.value or 0)
            knobs.append(
                {
                    "id": f"rhs:{con.name}",
                    "target": "rhs",
                    "name": con.name,
                    "index": [],
                    "label": con.name,
                    "value": value,
                    "min": value * 0.5,
                    "max": value * 1.5 if value else 10,
                }
            )
    for param in list(model.parameters.values())[:8]:
        for key, value in list(param.values.items())[:6]:
            label = param.name if not key else f"{param.name}[{','.join(key)}]"
            knobs.append(
                {
                    "id": f"param:{label}",
                    "target": "param",
                    "name": param.name,
                    "index": list(key),
                    "label": label,
                    "value": float(value),
                    "min": float(value) * 0.5,
                    "max": float(value) * 1.5 if value else 10,
                }
            )
    return knobs[:16]


def what_if(model: Model, changes: list[dict], solver: str = "highs") -> dict:
    chosen = _solver_for(model, solver or "highs")
    baseline = solve_model(model, chosen)
    mutated = model.copy()
    _apply_changes(mutated, changes)
    scenario = solve_model(mutated, _solver_for(mutated, chosen))
    return {
        "solver": chosen,
        "baseline": _solution(baseline),
        "scenario": _solution(scenario),
        "objective_delta": None
        if baseline.objective is None or scenario.objective is None
        else scenario.objective - baseline.objective,
        "rows": compare_solutions(
            {"objective": baseline.objective, "variables": baseline.variables},
            {"objective": scenario.objective, "variables": scenario.variables},
        )["rows"],
    }


def compare_solutions(left: dict, right: dict) -> dict:
    left_vars = {str(key): float(value) for key, value in (left.get("variables") or {}).items() if not str(key).startswith("_")}
    right_vars = {str(key): float(value) for key, value in (right.get("variables") or {}).items() if not str(key).startswith("_")}
    left_obj = _optional_float(left.get("objective"))
    right_obj = _optional_float(right.get("objective"))
    rows = []
    for name in list(dict.fromkeys([*left_vars, *right_vars])):
        before = left_vars.get(name)
        after = right_vars.get(name)
        delta = None if before is None or after is None else after - before
        rows.append({"name": name, "left": before, "right": after, "delta": delta})
    return {
        "objective_left": left_obj,
        "objective_right": right_obj,
        "objective_delta": None if left_obj is None or right_obj is None else right_obj - left_obj,
        "rows": rows,
    }


def _apply_changes(model: Model, changes: list[dict]) -> None:
    for change in changes:
        target = str(change.get("target") or "")
        name = str(change.get("name") or "")
        value = float(change.get("value"))
        if target == "rhs":
            found = False
            for con in model.constraints:
                if con.name == name and con.rhs is not None and con.rhs.op == "const":
                    con.rhs = const(value)
                    found = True
            if not found:
                raise AxiomError(f"没有可改的右端 {name}。", f"There is no constant right-hand side named {name}.", code="missing_rhs")
        elif target == "param":
            if name not in model.parameters:
                raise AxiomError(f"没有参数 {name}。", f"Parameter {name} is missing.", code="missing_data")
            index = tuple(str(part) for part in change.get("index") or [])
            model.parameters[name].values[index] = value
        else:
            raise AxiomError("情景只能改右端或参数。", "A scenario changes a right-hand side or a parameter.", code="bad_change")


def _solution(solved) -> dict:
    return {"status": solved.status, "objective": solved.objective, "variables": solved.variables}


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _network(model: Model, variables: dict[str, float]):
    if model.meta.get("view") != "network":
        return None
    flow = model.meta.get("network_flow", "x")
    origins = model.meta.get("network_origin_set")
    destinations = model.meta.get("network_dest_set")
    if origins not in model.sets or destinations not in model.sets:
        return None
    nodes = [{"id": name, "group": "origin"} for name in model.sets[origins].elements]
    nodes += [{"id": name, "group": "destination"} for name in model.sets[destinations].elements]
    edges = []
    for origin in model.sets[origins].elements:
        for dest in model.sets[destinations].elements:
            value = float(variables.get(f"{flow}[{origin},{dest}]", 0.0))
            if value > 1e-6:
                edges.append({"source": origin, "target": dest, "value": value})
    return {"nodes": nodes, "edges": edges}
