"""MDF, IDF, collaborative optimization, and a BLISS-style bilevel cycle.

MDF closes the couplings with Gauss-Seidel or a Newton multidisciplinary
analysis, then optimizes the design. IDF lifts the couplings into the
optimizer and enforces consistency. Collaborative optimization gives each
discipline its own target-matching subproblem. BLISS alternates local and
shared optimizations around a fresh analysis.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from axiom.mdo.problem import MDOProblem, State


def solve(problem: MDOProblem, architecture: str = "mdf", mda: str = "gauss-seidel", cancel=None) -> dict:
    architecture = (architecture or "mdf").lower().strip()
    if architecture in {"mdf", "mdf-gs"}:
        return _mdf(problem, "gauss-seidel" if architecture == "mdf-gs" else mda, cancel)
    if architecture in {"idf"}:
        return _idf(problem, cancel)
    if architecture in {"co", "collaborative"}:
        return _collaborative(problem, cancel)
    if architecture in {"bliss"}:
        return _bliss(problem, cancel)
    if architecture in {"openmdao", "om"}:
        from axiom.mdo.openmdao_backend import solve_openmdao

        return solve_openmdao(problem, mda, cancel)
    return {
        "ok": False,
        "architecture": architecture,
        "message": f"没有这个 MDO 架构：{architecture}。",
        "message_en": f"Unknown MDO architecture: {architecture}.",
    }


def analyze(problem: MDOProblem, design: State, method: str = "gauss-seidel", tol: float = 1e-9, iters: int = 40) -> dict:
    if method in {"newton", "newton-raphson"}:
        couplings, residual = _newton(problem, design, tol, iters)
    else:
        couplings, residual = _gauss_seidel(problem, design, tol, iters)
    state = {**design, **couplings}
    for disc in problem.disciplines:
        for key, value in disc.evaluate(state).items():
            if key not in problem.couplings:
                state[key] = float(value)
    return {
        "state": state,
        "couplings": couplings,
        "residuals": residual,
        "converged": bool(residual) and residual[-1] <= tol * 10,
        "objective": float(problem.objective(state)),
        "constraints": _constraints(problem, state),
        "disciplines": breakdown(problem, state),
    }


def n2_diagram(problem: MDOProblem) -> dict:
    labels = [item.name for item in problem.disciplines]
    producer = {}
    for disc in problem.disciplines:
        for name in disc.outputs:
            producer[name] = disc.name
    matrix = []
    cells = []
    for row, dest in enumerate(problem.disciplines):
        line = []
        for col, src in enumerate(problem.disciplines):
            if row == col:
                variables = list(src.outputs)
                kind = "discipline"
            else:
                variables = [name for name in dest.inputs if producer.get(name) == src.name]
                kind = "coupling" if variables else "empty"
            line.append(variables)
            if variables:
                cells.append({"row": row, "col": col, "from": src.name, "to": dest.name, "variables": variables, "kind": kind})
        matrix.append(line)
    return {"labels": labels, "matrix": matrix, "cells": cells}


def breakdown(problem: MDOProblem, state: State) -> list[dict]:
    rows = []
    shares = problem.contributions(state) if problem.contributions else {}
    for disc in problem.disciplines:
        produced = disc.evaluate(state)
        local = []
        if disc.constraints:
            local = [{"name": name, "value": float(value)} for name, value in disc.constraints(state)]
        rows.append({"name": disc.name, "outputs": {key: float(value) for key, value in produced.items()}, "constraints": local})
    if shares:
        rows.append({"name": "objective", "outputs": {key: float(value) for key, value in shares.items()}, "constraints": []})
    return rows


def _mdf(problem: MDOProblem, method: str, cancel) -> dict:
    names = problem.design_names()
    start = np.array([problem.initial_state()[name] for name in names], dtype=float)
    history = []
    last = {}

    def objective(vec):
        if cancel and cancel():
            raise RuntimeError("cancelled")
        design = _design_state(problem, vec)
        analysis = analyze(problem, design, method)
        value = _minimize(problem, analysis["objective"])
        violation = _violation(analysis["constraints"])
        history.append({"objective": analysis["objective"], "violation": violation, "residual": analysis["residuals"][-1] if analysis["residuals"] else None})
        last["analysis"] = analysis
        return value

    constraints = [_ineq(problem, names, method, index) for index in range(_constraint_count(problem))]
    result = minimize(objective, start, method="SLSQP", bounds=_bounds(problem), constraints=constraints, options={"maxiter": 80, "ftol": 1e-10})
    design = _design_state(problem, result.x)
    final = analyze(problem, design, method)
    return _payload(problem, "mdf", final, result.success, history, {"mda": method, "message": str(result.message)})


def _idf(problem: MDOProblem, cancel) -> dict:
    design_names = problem.design_names()
    couplings = list(problem.couplings)
    initial = problem.initial_state()
    warm = analyze(problem, initial, "gauss-seidel")
    start = np.array([initial[name] for name in design_names] + [warm["couplings"].get(name, 1.0) for name in couplings], dtype=float)
    history = []

    def unpack(vec):
        design = {name: float(vec[index]) for index, name in enumerate(design_names)}
        targets = {name: float(vec[len(design_names) + index]) for index, name in enumerate(couplings)}
        return {**design, **targets}

    def objective(vec):
        if cancel and cancel():
            raise RuntimeError("cancelled")
        state = unpack(vec)
        value = float(problem.objective(state))
        history.append({"objective": value, "violation": _violation(_constraints(problem, state)), "residual": _consistency_norm(problem, state)})
        return _minimize(problem, value)

    constraints = []
    for index in range(_constraint_count(problem)):
        constraints.append({"type": "ineq", "fun": lambda vec, index=index: -_constraints(problem, unpack(vec))[index][1]})
    for name in couplings:
        constraints.append({"type": "eq", "fun": lambda vec, name=name: _produced(problem, unpack(vec), name) - unpack(vec)[name]})
    lower = [var.lower for var in problem.design] + [-1e3] * len(couplings)
    upper = [var.upper for var in problem.design] + [1e3] * len(couplings)
    result = minimize(objective, start, method="SLSQP", bounds=list(zip(lower, upper)), constraints=constraints, options={"maxiter": 100, "ftol": 1e-10})
    state = unpack(result.x)
    # Report the consistent analysis at the optimized design, not a drifted target.
    final = analyze(problem, {name: state[name] for name in design_names}, "newton")
    return _payload(problem, "idf", final, result.success and final["converged"], history, {"consistency": _consistency_norm(problem, state), "message": str(result.message)})


def _collaborative(problem: MDOProblem, cancel) -> dict:
    design_names = problem.design_names()
    couplings = list(problem.couplings)
    initial = problem.initial_state()
    warm = analyze(problem, initial, "gauss-seidel")
    start = np.array([initial[name] for name in design_names] + [warm["couplings"].get(name, 1.0) for name in couplings], dtype=float)
    history = []

    def targets_of(vec) -> State:
        state = {name: float(vec[index]) for index, name in enumerate(design_names)}
        state.update({name: float(vec[len(design_names) + index]) for index, name in enumerate(couplings)})
        return state

    def objective(vec):
        if cancel and cancel():
            raise RuntimeError("cancelled")
        targets = targets_of(vec)
        gaps = [_discipline_gap(problem, disc, targets) for disc in problem.disciplines]
        value = float(problem.objective(targets)) + 50.0 * sum(gaps)
        history.append({"objective": float(problem.objective(targets)), "violation": float(sum(gaps)), "residual": float(max(gaps) if gaps else 0.0)})
        return _minimize(problem, value)

    lower = [var.lower for var in problem.design] + [-1e3] * len(couplings)
    upper = [var.upper for var in problem.design] + [1e3] * len(couplings)
    result = minimize(objective, start, method="SLSQP", bounds=list(zip(lower, upper)), options={"maxiter": 40, "ftol": 1e-9})
    targets = targets_of(result.x)
    design = {name: targets[name] for name in design_names}
    final = analyze(problem, design, "gauss-seidel")
    gaps = [_discipline_gap(problem, disc, targets) for disc in problem.disciplines]
    return _payload(
        problem,
        "co",
        final,
        result.success,
        history,
        {"discrepancy": gaps, "message": "系统层最小化原目标加各学科对目标值的偏差。", "message_en": "The system level minimizes the original objective plus each discipline's squared distance to the targets."},
    )


def _bliss(problem: MDOProblem, cancel) -> dict:
    values = problem.initial_state()
    history = []
    for _ in range(5):
        if cancel and cancel():
            break
        for disc in problem.disciplines:
            owned = [var for var in problem.design if var.owner == disc.name]
            if not owned:
                continue
            start = np.array([values[var.name] for var in owned], dtype=float)

            def local_obj(vec, owned=owned):
                trial = dict(values)
                for var, number in zip(owned, vec, strict=True):
                    trial[var.name] = float(number)
                closed = analyze(problem, trial, "gauss-seidel")
                return _minimize(problem, closed["objective"])

            bounds = [(var.lower, var.upper) for var in owned]
            preview = disc.constraints({**values, **{name: 1.0 for name in problem.couplings}}) if disc.constraints else []
            constraints = []
            for index in range(len(preview)):
                def local_ineq(vec, index=index, owned=owned, disc=disc):
                    trial = dict(values)
                    for var, number in zip(owned, vec, strict=True):
                        trial[var.name] = float(number)
                    closed = analyze(problem, trial, "gauss-seidel")
                    rows = disc.constraints(closed["state"]) if disc.constraints else []
                    if index >= len(rows):
                        return 0.0
                    return -float(rows[index][1])

                constraints.append({"type": "ineq", "fun": local_ineq})
            result = minimize(local_obj, start, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 25, "ftol": 1e-10})
            for var, number in zip(owned, result.x, strict=True):
                values[var.name] = float(number)
        shared = [var for var in problem.design if var.owner is None]
        if shared:
            start = np.array([values[var.name] for var in shared], dtype=float)

            def shared_obj(vec, shared=shared):
                trial = dict(values)
                for var, number in zip(shared, vec, strict=True):
                    trial[var.name] = float(number)
                closed = analyze(problem, trial, "gauss-seidel")
                return _minimize(problem, closed["objective"])

            preview = analyze(problem, dict(values), "gauss-seidel")["constraints"]
            constraints = []
            for index in range(len(preview)):
                def shared_ineq(vec, index=index, shared=shared):
                    trial = dict(values)
                    for var, number in zip(shared, vec, strict=True):
                        trial[var.name] = float(number)
                    rows = analyze(problem, trial, "gauss-seidel")["constraints"]
                    if index >= len(rows):
                        return 0.0
                    return -float(rows[index][1])

                constraints.append({"type": "ineq", "fun": shared_ineq})
            result = minimize(
                shared_obj,
                start,
                method="SLSQP",
                bounds=[(var.lower, var.upper) for var in shared],
                constraints=constraints,
                options={"maxiter": 30, "ftol": 1e-10},
            )
            for var, number in zip(shared, result.x, strict=True):
                values[var.name] = float(number)
        closed = analyze(problem, values, "gauss-seidel")
        history.append({"objective": closed["objective"], "violation": _violation(closed["constraints"]), "residual": closed["residuals"][-1] if closed["residuals"] else None})
    final = analyze(problem, values, "gauss-seidel")
    return _payload(problem, "bliss", final, final["converged"], history, {"cycles": len(history)})


def _discipline_gap(problem: MDOProblem, disc, targets: State) -> float:
    involved = []
    for var in problem.design:
        if var.name in disc.inputs or var.owner == disc.name:
            involved.append(var.name)
    for name in list(disc.inputs) + list(disc.outputs):
        if name not in involved:
            involved.append(name)
    if not involved:
        return 0.0
    start = np.array([float(targets.get(name, 1.0)) for name in involved], dtype=float)

    def gap(vec):
        return float(np.sum((vec - np.array([targets.get(name, 0.0) for name in involved])) ** 2))

    constraints = []
    for output in disc.outputs:
        def residual(vec, output=output):
            state = _filled(problem, targets, involved, vec)
            return float(disc.evaluate(state)[output]) - float(state[output])

        constraints.append({"type": "eq", "fun": residual})
    if disc.constraints:
        preview = disc.constraints(_filled(problem, targets, involved, start))
        for index in range(len(preview)):
            def ineq(vec, index=index):
                state = _filled(problem, targets, involved, vec)
                state.update(disc.evaluate(state))
                return -float(disc.constraints(state)[index][1])

            constraints.append({"type": "ineq", "fun": ineq})
    bounds = []
    lookup = {var.name: var for var in problem.design}
    for name in involved:
        if name in lookup:
            bounds.append((lookup[name].lower, lookup[name].upper))
        else:
            bounds.append((-1e3, 1e3))
    result = minimize(gap, start, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 40, "ftol": 1e-12})
    return float(result.fun)


def _filled(problem: MDOProblem, targets: State, involved: list[str], vec) -> State:
    state = dict(targets)
    for name, number in zip(involved, vec, strict=True):
        state[name] = float(number)
    return state


def _gauss_seidel(problem: MDOProblem, design: State, tol: float, iters: int):
    state = dict(design)
    for name in problem.couplings:
        state.setdefault(name, 1.0)
    residual = []
    for _ in range(iters):
        previous = {name: float(state.get(name, 0.0)) for name in problem.couplings}
        for disc in problem.disciplines:
            state.update(disc.evaluate(state))
        change = max((abs(state[name] - previous[name]) for name in problem.couplings), default=0.0)
        residual.append(float(change))
        if change <= tol:
            break
    return {name: float(state[name]) for name in problem.couplings}, residual


def _newton(problem: MDOProblem, design: State, tol: float, iters: int):
    names = list(problem.couplings)
    if not names:
        return {}, [0.0]
    guess = np.ones(len(names))
    residual_hist = []
    for _ in range(iters):
        residual, _ = _residual(problem, design, names, guess)
        residual_hist.append(float(np.max(np.abs(residual))))
        if residual_hist[-1] <= tol:
            break
        jacobian = np.zeros((len(names), len(names)))
        for column in range(len(names)):
            step = 1e-6 * max(1.0, abs(guess[column]))
            moved = guess.copy()
            moved[column] += step
            shifted, _ = _residual(problem, design, names, moved)
            jacobian[:, column] = (shifted - residual) / step
        try:
            delta = np.linalg.solve(jacobian, -residual)
        except np.linalg.LinAlgError:
            delta = np.linalg.lstsq(jacobian, -residual, rcond=None)[0]
        guess = guess + delta
        if not np.all(np.isfinite(guess)):
            break
    return {name: float(guess[index]) for index, name in enumerate(names)}, residual_hist


def _residual(problem, design, names, guess: np.ndarray):
    state = dict(design)
    state.update({name: float(guess[index]) for index, name in enumerate(names)})
    produced = {}
    for disc in problem.disciplines:
        produced.update(disc.evaluate(state))
    vector = np.array([float(produced[name]) - float(guess[index]) for index, name in enumerate(names)])
    return vector, produced


def _produced(problem: MDOProblem, state: State, name: str) -> float:
    produced = {}
    for disc in problem.disciplines:
        produced.update(disc.evaluate(state))
    return float(produced[name])


def _consistency_norm(problem: MDOProblem, state: State) -> float:
    if not problem.couplings:
        return 0.0
    gaps = [abs(_produced(problem, state, name) - float(state[name])) for name in problem.couplings]
    return float(max(gaps))


def _constraints(problem: MDOProblem, state: State) -> list[tuple[str, float]]:
    rows = []
    for disc in problem.disciplines:
        if disc.constraints:
            rows.extend(disc.constraints(state))
    return rows


def _constraint_count(problem: MDOProblem) -> int:
    return len(_constraints(problem, {**problem.initial_state(), **{name: 1.0 for name in problem.couplings}}))


def _violation(rows: list[tuple[str, float]]) -> float:
    return float(sum(max(0.0, value) for _, value in rows))


def _minimize(problem: MDOProblem, value: float) -> float:
    return float(value) if problem.sense == "minimize" else -float(value)


def _bounds(problem: MDOProblem):
    return [(var.lower, var.upper) for var in problem.design]


def _design_state(problem: MDOProblem, vec) -> State:
    return {name: float(vec[index]) for index, name in enumerate(problem.design_names())}


def _ineq(problem, names, method, index):
    def fun(vec, index=index):
        analysis = analyze(problem, _design_state(problem, vec), method)
        rows = analysis["constraints"]
        if index >= len(rows):
            return 0.0
        return -rows[index][1]

    return {"type": "ineq", "fun": fun}


def _payload(problem: MDOProblem, architecture: str, final: dict, success: bool, history: list[dict], extra: dict) -> dict:
    state = final["state"]
    design = {name: float(state[name]) for name in problem.design_names()}
    return {
        "ok": bool(success) or final["constraints"] and _violation(final["constraints"]) <= 1e-4,
        "architecture": architecture,
        "mda": extra.get("mda"),
        "objective": final["objective"],
        "sense": problem.sense,
        "design": design,
        "couplings": final["couplings"],
        "state": {key: float(value) for key, value in state.items()},
        "constraints": [{"name": name, "value": float(value)} for name, value in final["constraints"]],
        "violation": _violation(final["constraints"]),
        "residuals": final["residuals"],
        "converged": final["converged"],
        "disciplines": final["disciplines"],
        "n2": n2_diagram(problem),
        "history": history,
        "units": problem.units,
        "title_zh": problem.title_zh,
        "title_en": problem.title_en,
        **{key: value for key, value in extra.items() if key != "mda"},
    }
