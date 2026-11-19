"""Locate solver executables shipped next to the app."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def executable(name: str) -> str | None:
    filenames = [f"{name}.exe", name] if os.name == "nt" else [name]
    roots: list[Path] = []
    env = os.environ.get("AXIOM_SOLVER_DIR")
    if env:
        roots.append(Path(env))
    here = Path(__file__).resolve()
    if len(here.parents) > 3:
        roots.append(here.parents[3] / "solvers")
        roots.append(here.parents[3] / "vendor" / "windows" / "solvers")
    runtime = Path(sys.executable).resolve().parent
    roots.append(runtime.parent / "solvers")
    roots.append(runtime / "solvers")
    for root in roots:
        for filename in filenames:
            candidate = root / filename
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name) or shutil.which(f"{name}.exe")
