"""Background jobs with progress counters, polled by the UI."""
import threading
import traceback

from app.db import SessionLocal
from app.llm.usage import track
from app.models import ProcessingJob, utcnow


# Live progress for running jobs is kept in memory (single-process app). Writing it to SQLite from a
# second session while the job's own session holds the write lock deadlocks, so the DB row is only
# written at start and finish.
_live: dict[int, "Progress"] = {}


class Progress:
    """Callable progress reporter: progress(stage="ocr", pages_extracted=10, ...)."""

    def __init__(self, job_id: int | None):
        self.job_id = job_id
        self.counters: dict = {}
        self.stage = ""
        if job_id is not None:
            _live[job_id] = self

    def __call__(self, stage: str | None = None, force: bool = False, **counters):
        if stage:
            self.stage = stage
        self.counters.update(counters)


def start_job(claim_id: int, kind: str, fn, *args) -> int:
    """Run fn(db, claim_id, progress, *args) in a thread. Returns job id."""
    db = SessionLocal()
    job = ProcessingJob(claim_id=claim_id, kind=kind, stage="queued", counters={})
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    def runner():
        db = SessionLocal()
        prog = Progress(job_id)
        try:
            with track(claim_id, kind, db):
                fn(db, claim_id, prog, *args)
            status, msg = "done", None
        except Exception as e:  # surface readable errors in the UI
            db.rollback()
            status, msg = "error", f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            j = db.get(ProcessingJob, job_id)
            j.status, j.message, j.stage = status, msg, ("done" if status == "done" else j.stage)
            j.counters = {**prog.counters}
            j.finished_at = j.updated_at = utcnow()
            db.commit()
            db.close()
            _live.pop(job_id, None)

    threading.Thread(target=runner, daemon=True, name=f"job-{kind}-{job_id}").start()
    return job_id


def job_dict(j: ProcessingJob) -> dict:
    live = _live.get(j.id) if j.status == "running" else None
    stage, counters = (live.stage or j.stage, dict(live.counters)) if live else (j.stage, j.counters or {})
    return {"id": j.id, "kind": j.kind, "status": j.status, "stage": stage, "counters": counters,
            "message": j.message, "started_at": j.started_at.isoformat() + "Z",
            "finished_at": j.finished_at.isoformat() + "Z" if j.finished_at else None,
            "seconds": round(((j.finished_at or utcnow()) - j.started_at).total_seconds(), 1)}
