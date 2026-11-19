"""AMPL-ASL executable adapters for IPOPT, Bonmin, and Couenne.

The Windows package ships the COIN-OR IPOPT executable and its DLLs when the
official release archive can be unpacked. Bonmin and Couenne no longer publish
a current Windows executable, so those two stay detected: if ``bonmin`` or
``couenne`` is on PATH or under the solver directory, the same NL driver is used.
cyipopt has no Windows wheel; the in-process IPOPT adapter remains separate.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from axiom.modeling.flatten import FlatModel
from axiom.modeling.exchange import nl_variable_keys, write_nl
from axiom.modeling.ir import Model
from axiom.solvers.bundled import executable
from axiom.solvers.common import assemble, failure, not_applicable


class _AslSolver:
    name = "ipopt-asl"
    label = "IPOPT"
    binary = "ipopt"
    capabilities = {"nlp"}
    license = "open"
    minlp = False

    def available(self) -> bool:
        binary = executable(self.binary) or executable(f"{self.binary}.exe")
        if not binary:
            return False
        # The Windows package stores ipopt.exe next to the other solvers. A Linux
        # process cannot launch that PE binary, so it stays not installed here.
        if binary.lower().endswith(".exe") and os.name != "nt":
            return False
        return True

    def version(self) -> str:
        binary = executable(self.binary) or executable(f"{self.binary}.exe")
        if not binary:
            return ""
        try:
            proc = subprocess.run([binary, "-v"], capture_output=True, text=True, timeout=20)
        except Exception:
            return "asl"
        text = (proc.stdout or "") + (proc.stderr or "")
        match = re.search(r"(\d+\.\d+\.\d+)", text)
        return match.group(1) if match else "asl"

    def detail(self) -> str:
        if self.available():
            return f"{self.label} AMPL executable at {executable(self.binary) or executable(self.binary + '.exe')}."
        if self.name == "ipopt-asl":
            return "The Windows build bundles Ipopt's ASL executable. This process cannot see ipopt.exe. cyipopt has no Windows wheel."
        return (
            f"{self.label} has no current official Windows executable. "
            "Place the binary on PATH or in the solver directory to enable it."
        )

    def solve(self, model: Model, flat: FlatModel, options: dict[str, Any]):
        started = time.perf_counter()
        binary = executable(self.binary) or executable(f"{self.binary}.exe")
        if not binary:
            return failure(self.name, started, f"未找到 {self.binary}。", f"{self.binary} was not found.", "missing")
        if not self.minlp and any(var.domain in {"integer", "binary"} for var in flat.variables):
            return not_applicable(self.name, started, f"{self.label} 不求解整数变量。", f"{self.label} does not solve integer variables.")
        try:
            with tempfile.TemporaryDirectory(prefix="axiom-asl-") as folder:
                path = Path(folder) / "model.nl"
                keys = nl_variable_keys(flat)
                path.write_text(write_nl(flat, comments=False), encoding="utf-8")
                proc = subprocess.run([binary, str(path), "-AMPL"], capture_output=True, text=True, timeout=_timeout(options), cwd=folder)
                sol = path.with_suffix(".sol")
                if not sol.exists():
                    tail = (proc.stderr or proc.stdout or "no sol file")[-500:]
                    return failure(self.name, started, f"{self.label} 没有写出解文件：{tail}", f"{self.label} did not write a solution file: {tail}")
                values, raw, status = _read_sol(sol.read_text(encoding="utf-8", errors="replace"), keys)
            if status not in {"optimal", "feasible"}:
                return failure(
                    self.name,
                    started,
                    f"{self.label} 未返回可行解：{raw}",
                    f"{self.label} did not return a feasible solution: {raw}",
                    raw or status,
                )
            return assemble(
                solver=self.name,
                model=model,
                flat=flat,
                status=status,
                values=values,
                raw_status=raw[:180],
                started=started,
                message=f"{self.label} 已返回解。" if status == "optimal" else f"{self.label} 返回了可行解。",
                message_en=f"{self.label} returned an optimal solution." if status == "optimal" else f"{self.label} returned a feasible solution.",
            )
        except Exception as exc:
            return failure(self.name, started, f"{self.label} 求解失败：{exc}", f"{self.label} failed: {exc}")


class IpoptAslSolver(_AslSolver):
    name = "ipopt-asl"
    label = "IPOPT (ASL)"
    binary = "ipopt"
    capabilities = {"nlp", "lp"}
    minlp = False


class BonminSolver(_AslSolver):
    name = "bonmin"
    label = "Bonmin"
    binary = "bonmin"
    capabilities = {"minlp", "nlp"}
    minlp = True


class CouenneSolver(_AslSolver):
    name = "couenne"
    label = "Couenne"
    binary = "couenne"
    capabilities = {"minlp", "nlp"}
    minlp = True


def _timeout(options: dict[str, Any]) -> float:
    try:
        limit = float(options.get("time_limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    return max(5.0, limit + 5)


def _read_sol(text: str, keys: list[str]) -> tuple[dict[str, float], str, str]:
    """Read an ASL text solution file.

    The layout comes from ``writesol.c``: a message, an ``Options`` block,
    four integers ``(n_cons, n_duals, n_vars, n_primals)``, then that many
    duals and primals, then ``objno <index> <solve_code>``. Suffix blocks
    follow the primals and are not variable values.
    """
    lines = text.splitlines()
    cursor = 0
    message: list[str] = []
    while cursor < len(lines):
        stripped = lines[cursor].strip()
        cursor += 1
        if stripped == "Options":
            break
        if stripped:
            message.append(stripped)
    else:
        return {}, " ".join(message)[:180] or "no Options", "error"
    raw = " ".join(message)[:180]
    try:
        n_opts = int(lines[cursor].strip())
        cursor += 1
        if n_opts < 2:
            return {}, raw or "bad sol", "error"
        int(lines[cursor].strip())
        second = int(lines[cursor + 1].strip())
        cursor += 2
        read_vbtol = second == 3
        if read_vbtol:
            n_opts -= 2
        for _ in range(n_opts - 2):
            int(lines[cursor].strip())
            cursor += 1
        z = [int(lines[cursor + offset].strip()) for offset in range(4)]
        cursor += 4
        if read_vbtol:
            float(lines[cursor].strip())
            cursor += 1
        n_duals, n_primals = z[1], z[3]
        cursor += n_duals
        primals = [float(lines[cursor + offset].strip()) for offset in range(n_primals)]
        cursor += n_primals
    except (IndexError, ValueError):
        return {}, raw or "bad sol", "error"
    solve_code = None
    while cursor < len(lines):
        stripped = lines[cursor].strip()
        cursor += 1
        if stripped.startswith("objno"):
            parts = stripped.split()
            if len(parts) >= 3:
                try:
                    solve_code = int(parts[2])
                except ValueError:
                    solve_code = None
            break
    status = _status_from_code(solve_code, primals)
    if status in {"optimal", "feasible"} and len(primals) < len(keys):
        return {}, raw or "short sol", "error"
    values = {key: float(primals[i]) for i, key in enumerate(keys)} if status in {"optimal", "feasible"} else {}
    return values, raw or str(solve_code), status


def _status_from_code(code: int | None, primals: list[float]) -> str:
    if code is None:
        return "error"
    if 0 <= code <= 99 and primals:
        return "optimal"
    if 100 <= code <= 199 and primals:
        return "feasible"
    if 200 <= code <= 299:
        return "infeasible"
    if 300 <= code <= 399:
        return "unbounded"
    return "error"
