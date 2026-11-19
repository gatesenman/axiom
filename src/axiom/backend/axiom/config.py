"""Runtime paths, logging, and environment."""

from __future__ import annotations

import logging
import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("AXIOM_DATA_DIR")
    path = Path(override) if override else Path(__file__).resolve().parents[1] / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    return os.environ.get("AXIOM_DATABASE_URL", f"sqlite:///{data_dir() / 'axiom.db'}")


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    file_handler = logging.FileHandler(data_dir() / "axiom.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
