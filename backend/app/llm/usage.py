"""Token-usage tracking. Services wrap work in `track(claim_id, stage)`; providers call `record()`.
Uses contextvars so it works across threads started with `pmap` (which copies the context)."""
import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock

from app import config


@dataclass
class UsageRec:
    stage: str
    model: str
    kind: str
    input_tokens: int
    output_tokens: int


@dataclass
class Tracker:
    claim_id: int | None
    stage: str
    records: list[UsageRec] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    def cost(self) -> float:
        return sum(cost_of(r.model, r.input_tokens, r.output_tokens) for r in self.records)


_current: contextvars.ContextVar[Tracker | None] = contextvars.ContextVar("usage_tracker", default=None)
_stage: contextvars.ContextVar[str | None] = contextvars.ContextVar("usage_stage", default=None)


def cost_of(model: str, inp: int, out: int) -> float:
    pi, po = config.price_for(model)
    return inp / 1e6 * pi + out / 1e6 * po


def record(model: str, kind: str, input_tokens: int, output_tokens: int = 0) -> None:
    t = _current.get()
    if t is None:
        return
    with t.lock:
        t.records.append(UsageRec(_stage.get() or t.stage, model, kind, input_tokens or 0, output_tokens or 0))


@contextmanager
def track(claim_id: int | None, stage: str, db=None):
    """Collect usage for the block; if `db` is given, persist to usage_log on exit."""
    parent = _current.get()
    t = parent or Tracker(claim_id, stage)
    tok_t = _current.set(t)
    tok_s = _stage.set(stage)
    try:
        yield t
    finally:
        _stage.reset(tok_s)
        _current.reset(tok_t)
        if parent is None and db is not None:
            persist(db, t)


def persist(db, t: Tracker) -> None:
    from app.models import UsageLog
    for r in t.records:
        db.add(UsageLog(claim_id=t.claim_id, stage=r.stage, model=r.model, kind=r.kind,
                        input_tokens=r.input_tokens, output_tokens=r.output_tokens))
    db.commit()
    t.records.clear()


def pmap(fn, items, workers: int | None = None):
    """ThreadPool map that propagates the usage-tracking context into worker threads."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(workers or config.LLM_WORKERS, len(items))) as ex:
        futs = [ex.submit(contextvars.copy_context().run, fn, it) for it in items]
        return [f.result() for f in futs]
