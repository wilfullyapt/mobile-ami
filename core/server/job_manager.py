"""
Lightweight async job manager for long-running server operations
(plugin installs, test runs).  Jobs run in daemon threads; their
output and status are stored in-memory and polled via the API.
"""

import logging
import threading
import uuid
from typing import Callable

logger = logging.getLogger(__name__)

# Job status constants
RUNNING = "running"
DONE = "done"
ERROR = "error"


class JobManager:
    """
    Tracks background jobs keyed by a unique job ID.

    Usage:
        job_id = manager.start(fn)    # fn() → str output
        status = manager.get(job_id)  # {"status", "output", "error"}
    """

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, fn: Callable[[], str], label: str = "") -> str:
        """
        Start fn() in a background daemon thread.
        Returns a unique job_id for status polling.
        fn must return a string (captured as output) or raise an exception.
        """
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "label": label,
                "status": RUNNING,
                "output": "",
                "error": None,
            }

        def _run():
            try:
                output = fn()
                with self._lock:
                    self._jobs[job_id]["status"] = DONE
                    self._jobs[job_id]["output"] = output or ""
                logger.info("Job %s (%s) completed", job_id, label)
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id]["status"] = ERROR
                    self._jobs[job_id]["error"] = str(exc)
                logger.error("Job %s (%s) failed: %s", job_id, label, exc)

        threading.Thread(target=_run, daemon=True).start()
        return job_id

    def get(self, job_id: str) -> dict | None:
        """Return a copy of the job status dict, or None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list_all(self) -> list[dict]:
        """Return all tracked jobs (most recently started last)."""
        with self._lock:
            return [dict(j) for j in self._jobs.values()]
