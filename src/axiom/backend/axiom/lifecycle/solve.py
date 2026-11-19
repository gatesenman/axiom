"""Solve an AML model in a child process.

HiGHS and OR-Tools must not share one interpreter. The comparison requested
from the lifecycle runs each solver in its own process and returns a plain dict.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def solve_aml(aml: str, solver: str, seed: int | None = None) -> dict:
    code = (
        "import json, sys\n"
        "name = sys.argv[1]\n"
        "raw_seed = sys.argv[2]\n"
        "aml = sys.stdin.read()\n"
        "try:\n"
        "    from axiom.modeling.parser import parse_aml\n"
        "    from axiom.solvers.registry import solve_model\n"
        "    options = {}\n"
        "    if raw_seed not in {'', 'None'}:\n"
        "        options['seed'] = int(raw_seed)\n"
        "    result = solve_model(parse_aml(aml), name, options or None)\n"
        "    payload = result.to_dict()\n"
        "except Exception as exc:\n"
        "    payload = {\n"
        "        'solver': name,\n"
        "        'status': 'error',\n"
        "        'objective': None,\n"
        "        'variables': {},\n"
        "        'duals': {},\n"
        "        'message': str(exc),\n"
        "        'message_en': str(exc),\n"
        "        'runtime_sec': 0,\n"
        "        'feasible': False,\n"
        "    }\n"
        "print(json.dumps(payload, ensure_ascii=False))\n"
    )
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("AXIOM_SKIP_EXAMPLE", "1")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, solver, "" if seed is None else str(seed)],
            input=aml,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "solver": solver,
            "status": "error",
            "objective": None,
            "variables": {},
            "duals": {},
            "message": "求解超时。",
            "message_en": "The solve timed out.",
            "runtime_sec": 120,
            "feasible": False,
        }
    line = ""
    for candidate in reversed((proc.stdout or "").splitlines()):
        if candidate.strip().startswith("{"):
            line = candidate.strip()
            break
    if not line:
        message = (proc.stderr or proc.stdout or "solver produced no result").strip()[:500]
        return {
            "solver": solver,
            "status": "error",
            "objective": None,
            "variables": {},
            "duals": {},
            "message": message,
            "message_en": message,
            "runtime_sec": 0,
            "feasible": False,
        }
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return {
            "solver": solver,
            "status": "error",
            "objective": None,
            "variables": {},
            "duals": {},
            "message": line[:500],
            "message_en": line[:500],
            "runtime_sec": 0,
            "feasible": False,
        }
    if isinstance(payload, dict):
        payload.setdefault("solver", solver)
        return payload
    return {"solver": solver, "status": "error", "objective": None, "variables": {}, "duals": {}, "message": "bad payload", "message_en": "bad payload", "runtime_sec": 0, "feasible": False}
