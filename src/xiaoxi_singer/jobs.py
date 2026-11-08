"""Job model: a tiny FIFO worker so one GPU is never used by two renders at once."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    status: str = "queued"  # queued | running | done | error
    progress: float = 0.0
    stage: str = "queued"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(self.progress, 3),
            "stage": self.stage,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobRunner:
    """Single background thread + in-memory job table (enough for one machine)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._q: "queue.Queue[tuple[Job, Callable[[Job], None]]]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- public
    def submit(self, kind: str, params: dict[str, Any], fn: Callable[[Job], None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, params=params)
        with self._lock:
            self._jobs[job.id] = job
        self._ensure_worker()
        self._q.put((job, fn))
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    # --------------------------------------------------------------- worker
    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._loop, name="xiaoxi-singer-worker", daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while True:
            job, fn = self._q.get()
            job.status, job.stage, job.updated_at = "running", "starting", time.time()
            try:
                fn(job)
                job.status, job.stage = "done", "finished"
                job.progress = 1.0
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller
                job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
            finally:
                job.updated_at = time.time()
                self._q.task_done()


def output_path(work_dir: Path, prefix: str = "cover") -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir / f"{prefix}_{time.strftime('%Y%m%d-%H%M%S')}.wav"


runner = JobRunner()
