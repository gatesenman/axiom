"""Background analysis jobs with progress and cancellation."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable

from axiom.analysis.studio import run_study
from axiom.errors import AxiomError

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def start_job(kind: str, dsl: str = "", options: dict | None = None, on_done: Callable[[dict], None] | None = None) -> dict:
    job_id = uuid.uuid4().hex[:12]
    cancel = threading.Event()
    job = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "progress": 0.05,
        "message": "正在运行",
        "message_en": "Running",
        "result": None,
        "error": "",
        "error_en": "",
        "_cancel": cancel,
    }
    with _LOCK:
        _JOBS[job_id] = job

    def worker() -> None:
        try:
            result = run_study(kind, dsl, options, cancel=cancel.is_set)
            if cancel.is_set():
                _finish(job, "cancelled", result, "已取消。", "Cancelled.")
            else:
                job["progress"] = 1.0
                _finish(job, "completed", result, "分析完成。", "Analysis finished.")
        except AxiomError as exc:
            _finish(job, "failed", None, exc.message, exc.message_en)
        except Exception as exc:
            _finish(job, "failed", None, str(exc), str(exc))
        if on_done is not None:
            try:
                on_done(job)
            except Exception:
                pass

    threading.Thread(target=worker, name=f"axiom-analysis-{job_id}", daemon=True).start()
    return public_job(job)


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return None if job is None else public_job(job)


def cancel_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        job["_cancel"].set()
        if job["status"] == "running":
            job["message"] = "正在取消"
            job["message_en"] = "Cancelling"
        return public_job(job)


def public_job(job: dict) -> dict:
    return {
        "id": job["id"],
        "kind": job["kind"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "message_en": job["message_en"],
        "error": job["error"],
        "error_en": job["error_en"],
        "result": job["result"],
    }


def _finish(job: dict, status: str, result, message: str, message_en: str) -> None:
    with _LOCK:
        job["status"] = status
        job["result"] = result
        job["message"] = message
        job["message_en"] = message_en
        job["progress"] = 1.0 if status == "completed" else job["progress"]
        if status == "failed":
            job["error"] = message
            job["error_en"] = message_en
