"""Run OR-Tools in a fresh process so it does not clash with highspy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.ir import Model
from axiom.solvers.common import assemble, failure, has_integer, integral_data, not_applicable


@lru_cache(maxsize=1)
def _env() -> dict[str, str]:
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    return env


@lru_cache(maxsize=1)
def ortools_available() -> bool:
    script = "import ortools; from ortools.linear_solver import pywraplp; from ortools.sat.python import cp_model; assert pywraplp.Solver.CreateSolver('SCIP')"
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, env=_env())
    return proc.returncode == 0


@lru_cache(maxsize=8)
def backend_available(name: str) -> bool:
    script = (
        "from ortools.linear_solver import pywraplp; "
        f"assert pywraplp.Solver.CreateSolver({name!r}) is not None"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, env=_env())
    return proc.returncode == 0


def ortools_version() -> str:
    proc = subprocess.run(
        [sys.executable, "-c", "import ortools; print(ortools.__version__)"],
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def solve_isolated(model: Model, flat: FlatModel, backend: str, options: dict[str, Any], solver_name: str, label: str):
    started = time.perf_counter()
    if flat.nonlinear:
        return not_applicable(solver_name, started, f"{label} 只求解线性模型。", f"{label} only solves linear models.")
    if backend in {"GLOP", "PDLP", "CLP"} and has_integer(flat):
        return not_applicable(
            solver_name,
            started,
            f"{label} 不求解整数变量。",
            f"{label} does not solve integer variables.",
        )
    if backend == "CP-SAT":
        if any(var.domain == "continuous" for var in flat.variables) or not integral_data(flat):
            return not_applicable(
                solver_name,
                started,
                "CP-SAT 需要整数变量和整数数据。",
                "CP-SAT requires integer variables and integral data.",
            )
    if not ortools_available():
        return failure(solver_name, started, "未安装 OR-Tools。", "OR-Tools is not installed.", "missing")
    payload = {
        "backend": backend,
        "sense": flat.sense,
        "constant": flat.objective_const,
        "time_limit": options.get("time_limit"),
        "variables": [
            {"key": var.key, "lower": var.lower, "upper": var.upper, "domain": var.domain}
            for var in flat.variables
        ],
        "objective": flat.objective,
        "constraints": [
            {"key": con.key, "sense": con.sense, "rhs": con.rhs, "coeffs": con.coeffs}
            for con in flat.constraints
        ],
    }
    proc = subprocess.run(
        [sys.executable, "-m", "axiom.solvers.ortools_worker"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=float(options.get("time_limit") or 120) + 30,
        env=_env(),
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        return failure(solver_name, started, proc.stderr[-500:] or "OR-Tools 子进程失败。", proc.stderr[-500:] or "OR-Tools subprocess failed.")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return failure(solver_name, started, proc.stderr[-500] or proc.stdout[-500], "Could not parse OR-Tools output.")
    return assemble(
        solver=solver_name,
        model=model,
        flat=flat,
        status=data.get("status", "error"),
        values=data.get("values") or {},
        raw_status=str(data.get("raw", "")),
        started=started,
        message=data.get("message") or f"{label} 状态：{data.get('status')}。",
        message_en=data.get("message") or f"{label} status: {data.get('status')}.",
    )
