"""OpenMDAO driver and Gauss-Seidel MDA for the same discipline objects.

The Windows wheel of OpenMDAO is pure Python. If the import fails, the
architecture reports that and the built-in MDF / IDF / CO solvers remain available.
"""

from __future__ import annotations

import contextlib
import io

import numpy as np

from axiom.mdo.architectures import analyze, n2_diagram
from axiom.mdo.problem import MDOProblem


def available() -> tuple[bool, str]:
    try:
        import openmdao.api as om

        return True, getattr(om, "__version__", "openmdao")
    except Exception as exc:
        return False, str(exc)


def solve_openmdao(problem: MDOProblem, mda: str = "gauss-seidel", cancel=None) -> dict:
    ok, detail = available()
    if not ok:
        return {
            "ok": False,
            "architecture": "openmdao",
            "message": f"OpenMDAO 未能加载：{detail}",
            "message_en": f"OpenMDAO did not import: {detail}",
            "n2": n2_diagram(problem),
        }
    import openmdao.api as om

    group = om.Group()
    indeps = group.add_subsystem("indeps", om.IndepVarComp())
    for var in problem.design:
        indeps.add_output(var.name, val=float(var.initial))
    for disc in problem.disciplines:
        group.add_subsystem(disc.name, _component(disc))
    group.add_subsystem("objective", _objective_component(problem))
    for disc in problem.disciplines:
        for name in disc.inputs:
            source = _source(problem, name)
            if source is None:
                group.connect(f"indeps.{name}", f"{disc.name}.{name}")
            else:
                group.connect(f"{source}.{name}", f"{disc.name}.{name}")
        for name in disc.outputs:
            if name in _objective_inputs(problem):
                group.connect(f"{disc.name}.{name}", f"objective.{name}")
    for var in problem.design:
        if var.name in _objective_inputs(problem):
            group.connect(f"indeps.{var.name}", f"objective.{var.name}")
    solver = om.NonlinearBlockGS(maxiter=40, atol=1e-10, rtol=1e-10, use_aitken=True)
    if mda in {"newton", "newton-raphson"}:
        solver = om.NewtonSolver(solve_subsystems=True, maxiter=20, atol=1e-10, rtol=1e-10)
        group.linear_solver = om.DirectSolver()
    group.nonlinear_solver = solver
    prob = om.Problem(model=group)
    for var in problem.design:
        prob.model.add_design_var(f"indeps.{var.name}", lower=var.lower, upper=var.upper)
    prob.model.add_objective("objective.f", scaler=1.0)
    for index in range(_constraint_count(problem)):
        prob.model.add_constraint(f"objective.g{index}", upper=0.0)
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["tol"] = 1e-8
    prob.driver.options["maxiter"] = 80
    prob.driver.options["disp"] = False
    history: list[float] = []
    if cancel and cancel():
        return {"ok": False, "architecture": "openmdao", "message": "已取消。", "message_en": "Cancelled.", "n2": n2_diagram(problem)}
    prob.model.approx_totals(method="fd", step=1e-6)
    quiet = io.StringIO()
    failed = None
    try:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            prob.setup()
            prob.set_solver_print(level=0)
            prob.run_driver()
    except Exception as exc:
        failed = exc
    design = {var.name: float(np.ravel(prob.get_val(f"indeps.{var.name}"))[0]) for var in problem.design}
    final = analyze(problem, design, "gauss-seidel" if mda not in {"newton", "newton-raphson"} else "newton")
    violation = float(sum(max(0.0, value) for _, value in final["constraints"]))
    return {
        "ok": failed is None and violation <= 1e-3,
        "architecture": "openmdao",
        "library": f"openmdao {detail}",
        "mda": "Newton" if mda in {"newton", "newton-raphson"} else "NonlinearBlockGS",
        "objective": final["objective"],
        "sense": problem.sense,
        "design": design,
        "couplings": final["couplings"],
        "state": final["state"],
        "constraints": [{"name": name, "value": float(value)} for name, value in final["constraints"]],
        "violation": violation,
        "residuals": final["residuals"],
        "converged": final["converged"],
        "disciplines": final["disciplines"],
        "n2": n2_diagram(problem),
        "history": [{"objective": value, "violation": None, "residual": None} for value in history[-40:]],
        "units": problem.units,
        "title_zh": problem.title_zh,
        "title_en": problem.title_en,
        "message": "" if failed is None else str(failed),
        "message_en": "" if failed is None else str(failed),
    }


def _component(disc):
    import openmdao.api as om

    class _Disc(om.ExplicitComponent):
        def setup(self):
            for name in disc.inputs:
                self.add_input(name, val=1.0)
            for name in disc.outputs:
                self.add_output(name, val=1.0)

        def compute(self, inputs, outputs):
            state = {name: float(np.ravel(inputs[name])[0]) for name in disc.inputs}
            produced = disc.evaluate(state)
            for name in disc.outputs:
                outputs[name] = float(np.ravel(produced[name])[0])

    return _Disc()


def _objective_component(problem: MDOProblem):
    import openmdao.api as om

    names = _objective_inputs(problem)
    count = _constraint_count(problem)

    class _Obj(om.ExplicitComponent):
        def setup(self):
            for name in names:
                self.add_input(name, val=1.0)
            self.add_output("f", val=1.0)
            for index in range(count):
                self.add_output(f"g{index}", val=0.0)

        def compute(self, inputs, outputs):
            state = {name: float(np.ravel(inputs[name])[0]) for name in names}
            raw = float(problem.objective(state))
            outputs["f"] = raw if problem.sense == "minimize" else -raw
            rows = []
            for disc in problem.disciplines:
                if disc.constraints:
                    rows.extend(disc.constraints(state))
            for index in range(count):
                outputs[f"g{index}"] = float(rows[index][1]) if index < len(rows) else 0.0

    return _Obj()


def _objective_inputs(problem: MDOProblem) -> list[str]:
    names = [var.name for var in problem.design]
    for name in problem.couplings:
        if name not in names:
            names.append(name)
    return names


def _source(problem: MDOProblem, name: str) -> str | None:
    for disc in problem.disciplines:
        if name in disc.outputs:
            return disc.name
    return None


def _constraint_count(problem: MDOProblem) -> int:
    state = problem.initial_state()
    for name in problem.couplings:
        state.setdefault(name, 1.0)
    count = 0
    for disc in problem.disciplines:
        if disc.constraints:
            count += len(disc.constraints(state))
    return count
