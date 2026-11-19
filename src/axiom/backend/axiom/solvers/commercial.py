"""Commercial solvers. None of these are bundled.

Each adapter imports its vendor package only inside ``available`` and ``solve``.
A missing import is the not-installed state. A successful import is reported as
licensed only when the vendor accepts a session; otherwise the state is unlicensed.
"""

from __future__ import annotations

import shutil
import time
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import INF, assemble, failure, has_integer, not_applicable, opt_float


def _quad(flat: FlatModel) -> bool:
    return bool(getattr(flat, "quadratic", None))


class _Commercial:
    name = "xpress"
    label = "Xpress"
    capabilities = {"lp", "mip", "qp"}
    license = "commercial"
    module = "xpress"

    def available(self) -> bool:
        return self.license_state() == "licensed"

    def license_state(self) -> str:
        if self.module and not _imports(self.module):
            return "not_installed"
        return "licensed"

    def version(self) -> str:
        return "installed" if self.license_state() != "not_installed" else ""

    def detail(self) -> str:
        state = self.license_state()
        if state == "not_installed":
            return f"{self.label} is not bundled. Install and license it to use this adapter."
        if state == "unlicensed":
            return f"{self.label} is installed but did not accept a license."
        return f"{self.label} is installed and licensed."

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        state = self.license_state()
        if state == "not_installed":
            return failure(self.name, started, f"未安装 {self.label}。", f"{self.label} is not installed.", "missing")
        if state == "unlicensed":
            return failure(self.name, started, f"{self.label} 没有可用许可证。", f"{self.label} has no license.", "unlicensed")
        return self._solve(model, flat, options, started)

    def _solve(self, model, flat, options, started):
        return failure(self.name, started, f"{self.label} 适配器未实现。", f"{self.label} adapter is missing.")


class XpressSolver(_Commercial):
    name = "xpress"
    label = "FICO Xpress"
    module = "xpress"
    capabilities = {"lp", "mip", "qp"}

    def license_state(self) -> str:
        if not _imports("xpress"):
            return "not_installed"
        try:
            import xpress as xp

            problem = xp.problem()
            problem.controls.outputlog = 0
            return "licensed"
        except Exception:
            return "unlicensed"

    def version(self) -> str:
        if self.license_state() == "not_installed":
            return ""
        try:
            import xpress as xp

            return str(getattr(xp, "__version__", "installed"))
        except Exception:
            return ""

    def _solve(self, model, flat, options, started):
        if flat.nonlinear and not _quad(flat):
            return not_applicable(self.name, started, "该 Xpress 适配器求解线性和二次模型。", "This Xpress adapter solves linear and quadratic models.")
        try:
            import xpress as xp

            problem = xp.problem(flat.name or "axiom")
            problem.controls.outputlog = 0
            limit = opt_float(options, "time_limit")
            if limit:
                problem.controls.maxtime = int(limit)
            columns = []
            for var in flat.variables:
                kind = xp.binary if var.domain == "binary" else xp.integer if var.domain == "integer" else xp.continuous
                columns.append(
                    xp.var(
                        name=var.key[:80],
                        lb=-xp.infinity if var.lower is None else float(var.lower),
                        ub=xp.infinity if var.upper is None else float(var.upper),
                        vartype=kind,
                    )
                )
            by_key = {var.key: columns[i] for i, var in enumerate(flat.variables)}
            problem.addVariable(*columns)
            expr = float(flat.objective_const)
            for key, coef in flat.objective.items():
                expr += float(coef) * by_key[key]
            for (left, right), coef in (getattr(flat, "quadratic", None) or {}).items():
                expr += float(coef) * by_key[left] * by_key[right]
            problem.setObjective(expr, sense=xp.maximize if flat.sense == "maximize" else xp.minimize)
            for con in flat.constraints:
                row = sum(float(coef) * by_key[key] for key, coef in con.coeffs.items())
                if con.sense == "<=":
                    problem.addConstraint(row <= float(con.rhs))
                elif con.sense == ">=":
                    problem.addConstraint(row >= float(con.rhs))
                else:
                    problem.addConstraint(row == float(con.rhs))
            problem.solve()
            raw = str(problem.getProbStatusString())
            status = "optimal" if "optimal" in raw.lower() else "infeasible" if "infeas" in raw.lower() else "error"
            values = {key: float(problem.getSolution(var)) for key, var in by_key.items()} if status == "optimal" else {}
            return assemble(solver=self.name, model=model, flat=flat, status=status, values=values, raw_status=raw, started=started, message=f"Xpress：{raw}", message_en=f"Xpress: {raw}")
        except Exception as exc:
            return failure(self.name, started, f"Xpress 求解失败：{exc}", f"Xpress failed: {exc}")


class MosekSolver(_Commercial):
    name = "mosek"
    label = "MOSEK"
    module = "mosek"
    capabilities = {"lp", "mip", "qp", "socp", "sdp"}

    def license_state(self) -> str:
        if not _imports("mosek"):
            return "not_installed"
        try:
            import mosek

            with mosek.Env() as env:
                env.echolevel = 0
            return "licensed"
        except Exception:
            return "unlicensed"

    def version(self) -> str:
        if self.license_state() == "not_installed":
            return ""
        try:
            import mosek

            return str(mosek.Env().getversion())
        except Exception:
            return "installed"

    def _solve(self, model, flat, options, started):
        if flat.nonlinear and not _quad(flat) and not getattr(flat, "cones", None):
            return not_applicable(self.name, started, "该 MOSEK 适配器求解线性、二次和二阶锥模型。", "This MOSEK adapter solves linear, quadratic, and second-order-cone models.")
        try:
            import mosek

            with mosek.Env() as env, env.Task(0, 0) as task:
                task.putintparam(mosek.iparam.log, 0)
                limit = opt_float(options, "time_limit")
                if limit:
                    task.putdouparam(mosek.dparam.optimizer_max_time, float(limit))
                keys = [var.key for var in flat.variables]
                task.appendvars(len(keys))
                for i, var in enumerate(flat.variables):
                    task.putvarname(i, var.key[:80])
                    task.putvarbound(
                        i,
                        mosek.boundkey.ra if var.lower is not None and var.upper is not None else mosek.boundkey.lo if var.lower is not None else mosek.boundkey.up if var.upper is not None else mosek.boundkey.fr,
                        -INF if var.lower is None else float(var.lower),
                        INF if var.upper is None else float(var.upper),
                    )
                    if var.domain == "binary":
                        task.putvartype(i, mosek.variabletype.type_int)
                        task.putvarbound(i, mosek.boundkey.ra, 0.0, 1.0)
                    elif var.domain == "integer":
                        task.putvartype(i, mosek.variabletype.type_int)
                    task.putcj(i, float(flat.objective.get(var.key, 0.0)))
                task.putobjsense(mosek.objsense.maximize if flat.sense == "maximize" else mosek.objsense.minimize)
                task.appendcons(len(flat.constraints))
                for row, con in enumerate(flat.constraints):
                    cols = list(range(len(keys)))
                    vals = [float(con.coeffs.get(key, 0.0)) for key in keys]
                    nonzero = [(col, val) for col, val in zip(cols, vals, strict=True) if abs(val) > 1e-15]
                    task.putarow(row, [col for col, _ in nonzero], [val for _, val in nonzero])
                    if con.sense == "<=":
                        task.putconbound(row, mosek.boundkey.up, -INF, float(con.rhs))
                    elif con.sense == ">=":
                        task.putconbound(row, mosek.boundkey.lo, float(con.rhs), INF)
                    else:
                        task.putconbound(row, mosek.boundkey.fx, float(con.rhs), float(con.rhs))
                if _quad(flat):
                    qsubi, qsubj, qval = [], [], []
                    index = {key: i for i, key in enumerate(keys)}
                    for (left, right), coef in flat.quadratic.items():
                        qsubi.append(index[left])
                        qsubj.append(index[right])
                        qval.append(float(coef))
                    task.putqobj(qsubi, qsubj, qval)
                task.optimize()
                raw = str(task.getsolsta(mosek.soltype.itr if not has_integer(flat) and not _quad(flat) else mosek.soltype.itg if has_integer(flat) else mosek.soltype.itr))
                sol = mosek.soltype.itg if has_integer(flat) else mosek.soltype.itr
                status = "optimal" if task.getsolsta(sol) in {mosek.solsta.optimal, mosek.solsta.integer_optimal} else "error"
                values = {}
                if status == "optimal":
                    xx = [0.0] * len(keys)
                    task.getxx(sol, xx)
                    values = {key: float(xx[i]) for i, key in enumerate(keys)}
                return assemble(solver=self.name, model=model, flat=flat, status=status, values=values, raw_status=raw, started=started, message=f"MOSEK：{raw}", message_en=f"MOSEK: {raw}")
        except Exception as exc:
            return failure(self.name, started, f"MOSEK 求解失败：{exc}", f"MOSEK failed: {exc}")


class CoptSolver(_Commercial):
    name = "copt"
    label = "COPT"
    module = "coptpy"
    capabilities = {"lp", "mip", "qp", "socp", "sdp"}

    def license_state(self) -> str:
        if not _imports("coptpy"):
            return "not_installed"
        try:
            import coptpy as cp

            env = cp.Envr()
            model = env.createModel("probe")
            model.setParam("Logging", 0)
            return "licensed"
        except Exception:
            return "unlicensed"

    def version(self) -> str:
        if self.license_state() == "not_installed":
            return ""
        try:
            import coptpy as cp

            return str(getattr(cp, "__version__", "installed"))
        except Exception:
            return ""

    def _solve(self, model, flat, options, started):
        if flat.nonlinear and not _quad(flat):
            return not_applicable(self.name, started, "该 COPT 适配器求解线性和二次模型。", "This COPT adapter solves linear and quadratic models.")
        try:
            import coptpy as cp

            env = cp.Envr()
            problem = env.createModel(flat.name or "axiom")
            problem.setParam("Logging", 0)
            limit = opt_float(options, "time_limit")
            if limit:
                problem.setParam("TimeLimit", float(limit))
            columns = {}
            for var in flat.variables:
                vtype = cp.COPT.BINARY if var.domain == "binary" else cp.COPT.INTEGER if var.domain == "integer" else cp.COPT.CONTINUOUS
                columns[var.key] = problem.addVar(lb=-cp.COPT.INFINITY if var.lower is None else float(var.lower), ub=cp.COPT.INFINITY if var.upper is None else float(var.upper), vtype=vtype, name=var.key[:80])
            linear = cp.quicksum(float(coef) * columns[key] for key, coef in flat.objective.items())
            problem.setObjective(linear, cp.COPT.MAXIMIZE if flat.sense == "maximize" else cp.COPT.MINIMIZE)
            for con in flat.constraints:
                row = cp.quicksum(float(coef) * columns[key] for key, coef in con.coeffs.items())
                if con.sense == "<=":
                    problem.addConstr(row <= float(con.rhs))
                elif con.sense == ">=":
                    problem.addConstr(row >= float(con.rhs))
                else:
                    problem.addConstr(row == float(con.rhs))
            problem.solve()
            raw = str(problem.status)
            status = "optimal" if problem.haslpsol or problem.status == cp.COPT.OPTIMAL else "error"
            try:
                if problem.status == cp.COPT.OPTIMAL:
                    status = "optimal"
            except Exception:
                pass
            values = {key: float(var.x) for key, var in columns.items()} if status == "optimal" else {}
            return assemble(solver=self.name, model=model, flat=flat, status=status, values=values, raw_status=raw, started=started, message=f"COPT：{raw}", message_en=f"COPT: {raw}")
        except Exception as exc:
            return failure(self.name, started, f"COPT 求解失败：{exc}", f"COPT failed: {exc}")


class KnitroSolver(_Commercial):
    name = "knitro"
    label = "Knitro"
    module = "knitro"
    capabilities = {"nlp", "lp", "qp"}

    def license_state(self) -> str:
        if not _imports("knitro"):
            return "not_installed"
        try:
            import knitro as kn

            kc = kn.KN_new()
            kn.KN_free(kc)
            return "licensed"
        except Exception:
            return "unlicensed"

    def _solve(self, model, flat, options, started):
        if has_integer(flat):
            return not_applicable(self.name, started, "该 Knitro 适配器求解连续模型。", "This Knitro adapter solves continuous models.")
        try:
            import knitro as kn

            kc = kn.KN_new()
            keys = [var.key for var in flat.variables]
            kn.KN_add_vars(kc, len(keys))
            lo = [-kn.KN_INFINITY if var.lower is None else float(var.lower) for var in flat.variables]
            hi = [kn.KN_INFINITY if var.upper is None else float(var.upper) for var in flat.variables]
            kn.KN_set_var_lobnds_all(kc, lo)
            kn.KN_set_var_upbnds_all(kc, hi)
            goal = kn.KN_OBJGOAL_MAXIMIZE if flat.sense == "maximize" else kn.KN_OBJGOAL_MINIMIZE
            kn.KN_set_obj_goal(kc, goal)
            idx = [i for i, key in enumerate(keys) if abs(flat.objective.get(key, 0.0)) > 1e-15]
            coef = [float(flat.objective[keys[i]]) for i in idx]
            if idx:
                kn.KN_add_obj_linear_struct(kc, idx, coef)
            if flat.constraints:
                kn.KN_add_cons(kc, len(flat.constraints))
                cl, cu = [], []
                for con in flat.constraints:
                    if con.sense == "<=":
                        cl.append(-kn.KN_INFINITY)
                        cu.append(float(con.rhs))
                    elif con.sense == ">=":
                        cl.append(float(con.rhs))
                        cu.append(kn.KN_INFINITY)
                    else:
                        cl.append(float(con.rhs))
                        cu.append(float(con.rhs))
                kn.KN_set_con_lobnds_all(kc, cl)
                kn.KN_set_con_upbnds_all(kc, cu)
                rows, cols, vals = [], [], []
                for r, con in enumerate(flat.constraints):
                    for key, coef in con.coeffs.items():
                        rows.append(r)
                        cols.append(keys.index(key))
                        vals.append(float(coef))
                if rows:
                    kn.KN_add_con_linear_struct(kc, rows, cols, vals)
            code = kn.KN_solve(kc)
            nStatus, obj, x, _lambda = kn.KN_get_solution(kc)
            kn.KN_free(kc)
            status = "optimal" if int(nStatus) == 0 else "error"
            values = {key: float(x[i]) for i, key in enumerate(keys)} if status == "optimal" else {}
            return assemble(solver=self.name, model=model, flat=flat, status=status, values=values, raw_status=str(code), started=started, message=f"Knitro 状态 {nStatus}。", message_en=f"Knitro status {nStatus}.")
        except Exception as exc:
            return failure(self.name, started, f"Knitro 求解失败：{exc}", f"Knitro failed: {exc}")


class BaronSolver(_Commercial):
    name = "baron"
    label = "BARON"
    module = ""
    capabilities = {"nlp", "minlp", "lp"}

    def license_state(self) -> str:
        binary = shutil.which("baron") or shutil.which("baron.exe")
        if not binary:
            return "not_installed"
        return "licensed"

    def version(self) -> str:
        return "executable" if self.license_state() != "not_installed" else ""

    def detail(self) -> str:
        if self.license_state() == "not_installed":
            return "BARON is not bundled. Install the baron executable and a license; Axiom writes a scalar BAR file and calls it."
        return "BARON executable detected on PATH."

    def _solve(self, model, flat, options, started):
        import subprocess
        import tempfile
        from pathlib import Path

        binary = shutil.which("baron") or shutil.which("baron.exe")
        if not binary:
            return failure(self.name, started, "未找到 baron。", "baron was not found.", "missing")
        try:
            text = _baron_file(flat, opt_float(options, "time_limit") or 30)
            with tempfile.TemporaryDirectory(prefix="axiom-baron-") as folder:
                path = Path(folder) / "model.bar"
                path.write_text(text, encoding="utf-8")
                proc = subprocess.run([binary, str(path)], capture_output=True, text=True, timeout=120, cwd=folder)
            output = proc.stdout + "\n" + proc.stderr
            values = _baron_values(output, flat)
            status = "optimal" if values and "optimal" in output.lower() else "error"
            return assemble(solver=self.name, model=model, flat=flat, status=status, values=values, raw_status=output[-180:], started=started, message="BARON 已返回解。" if values else "BARON 未返回可行解。", message_en="BARON returned a solution." if values else "BARON did not return a feasible solution.")
        except Exception as exc:
            return failure(self.name, started, f"BARON 求解失败：{exc}", f"BARON failed: {exc}")


class HexalySolver(_Commercial):
    name = "hexaly"
    label = "Hexaly"
    module = "hexaly"
    capabilities = {"lp", "mip", "nlp", "cp"}

    def license_state(self) -> str:
        if not _imports("hexaly.optimizer") and not _imports("hexaly"):
            return "not_installed"
        try:
            import hexaly.optimizer

            opt = hexaly.optimizer.HexalyOptimizer()
            opt.close()
            return "licensed"
        except Exception:
            return "unlicensed"

    def version(self) -> str:
        if self.license_state() == "not_installed":
            return ""
        try:
            import hexaly

            return str(getattr(hexaly, "__version__", "installed"))
        except Exception:
            return "installed"

    def _solve(self, model, flat, options, started):
        if flat.nonlinear or _quad(flat) or getattr(flat, "cones", None):
            return not_applicable(self.name, started, "该 Hexaly 适配器求解线性与整数模型。", "This Hexaly adapter solves linear and integer models.")
        try:
            import hexaly.optimizer

            with hexaly.optimizer.HexalyOptimizer() as opt:
                limit = opt_float(options, "time_limit")
                if limit:
                    opt.param.time_limit = int(limit)
                problem = opt.model
                columns = {}
                for var in flat.variables:
                    lo = -1e20 if var.lower is None else float(var.lower)
                    hi = 1e20 if var.upper is None else float(var.upper)
                    if var.domain in {"integer", "binary"}:
                        columns[var.key] = problem.int(int(lo), int(hi))
                    else:
                        columns[var.key] = problem.float(lo, hi)
                expr = float(flat.objective_const)
                for key, coef in flat.objective.items():
                    expr += float(coef) * columns[key]
                if flat.sense == "maximize":
                    problem.maximize(expr)
                else:
                    problem.minimize(expr)
                for con in flat.constraints:
                    row = sum(float(coef) * columns[key] for key, coef in con.coeffs.items())
                    if con.sense == "<=":
                        problem.constraint(row <= float(con.rhs))
                    elif con.sense == ">=":
                        problem.constraint(row >= float(con.rhs))
                    else:
                        problem.constraint(row == float(con.rhs))
                problem.close()
                opt.solve()
                values = {key: float(var.value) for key, var in columns.items()}
            return assemble(solver=self.name, model=model, flat=flat, status="optimal", values=values, raw_status="solved", started=started, message="Hexaly 求解完成。", message_en="Hexaly finished.")
        except Exception as exc:
            return failure(self.name, started, f"Hexaly 求解失败：{exc}", f"Hexaly failed: {exc}")


def _imports(name: str) -> bool:
    try:
        __import__(name)
    except Exception:
        return False
    return True


def _baron_file(flat: FlatModel, seconds: float) -> str:
    lines = ["OPTIONS {", f"  ResLim: {seconds};", "}"]
    binaries, integers, continuous = [], [], []
    for var in flat.variables:
        if var.domain == "binary":
            binaries.append(var.key)
        elif var.domain == "integer":
            integers.append(var.key)
        else:
            continuous.append(var.key)
    if continuous:
        lines.append("VARIABLES " + ", ".join(continuous) + ";")
    if integers:
        lines.append("INTEGER_VARIABLES " + ", ".join(integers) + ";")
    if binaries:
        lines.append("BINARY_VARIABLES " + ", ".join(binaries) + ";")
    bounds = []
    for var in flat.variables:
        if var.lower is not None:
            bounds.append(f"{var.key}: {var.lower}")
        if var.upper is not None:
            bounds.append(f"{var.key}: {var.upper}")
    if bounds:
        lines.append("LOWER_BOUNDS { " + "; ".join(f"{var.key}: {var.lower}" for var in flat.variables if var.lower is not None) + "; }")
        lines.append("UPPER_BOUNDS { " + "; ".join(f"{var.key}: {var.upper}" for var in flat.variables if var.upper is not None) + "; }")
    names = [con.key for con in flat.constraints]
    if names:
        lines.append("EQUATIONS " + ", ".join(names) + ";")
    for con in flat.constraints:
        lines.append(f"{con.key}: {_lin(con.coeffs)} {con.sense} {con.rhs};")
    sense = "maximize" if flat.sense == "maximize" else "minimize"
    lines.append(f"OBJ: {sense} {_lin(flat.objective, flat.objective_const)};")
    return "\n".join(lines) + "\n"


def _lin(coeffs: dict[str, float], constant: float = 0.0) -> str:
    parts = []
    for key, coef in coeffs.items():
        if abs(coef) < 1e-15:
            continue
        parts.append(f"({coef})*{key}")
    if abs(constant) > 1e-15 or not parts:
        parts.append(str(constant))
    return " + ".join(parts)


def _baron_values(output: str, flat: FlatModel) -> dict[str, float]:
    values = {}
    for var in flat.variables:
        import re

        match = re.search(rf"\b{re.escape(var.key)}\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", output)
        if match:
            values[var.key] = float(match.group(1))
    if len(values) != len(flat.variables):
        return {}
    return values
