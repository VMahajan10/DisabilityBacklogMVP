from collections import Counter, defaultdict
from statistics import mean, median

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AIRun, Citation, Claim, Determination, QueueAssignment

router = APIRouter(prefix="/api", tags=["metrics"])
ORDER = {"criteria_appear_met": 0, "insufficient_evidence": 1, "criteria_not_met": 2}


def _top_listing_overall(runs: list[AIRun]) -> str | None:
    if not runs:
        return None
    bid = runs[-1].output_json.get("batch_id")
    batch = [r for r in runs if r.output_json.get("batch_id") == bid]
    return min((r.output_json.get("overall") for r in batch), key=lambda o: ORDER.get(o, 9), default=None)


@router.get("/metrics")
def metrics(include_seed: bool = True, db: Session = Depends(get_db)):
    q = db.query(Claim)
    if not include_seed:
        q = q.filter(Claim.is_demo_seed.is_(False))
    claims = q.all()
    ids = [c.id for c in claims]
    by_id = {c.id: c for c in claims}

    dets = {}
    for d in db.query(Determination).filter(Determination.claim_id.in_(ids)).order_by(Determination.id):
        dets[d.claim_id] = d  # latest wins
    decided = [c for c in claims if c.decided_at]
    days = [(c.decided_at - c.created_at).total_seconds() / 86400 for c in decided]

    qas = {}
    for qa in db.query(QueueAssignment).filter(QueueAssignment.claim_id.in_(ids)).order_by(QueueAssignment.id):
        qas[qa.claim_id] = qa
    assigned = [qa for qa in qas.values() if qa.final_queue]
    overrides = [qa for qa in assigned if qa.overridden]
    override_matrix = Counter((qa.ai_suggested_queue, qa.final_queue) for qa in assigned)

    cites = db.query(Citation).filter(Citation.claim_id.in_(ids)).all()
    unverified = sum(1 for c in cites if not c.verified)

    runs_by_claim = defaultdict(list)
    for r in db.query(AIRun).filter(AIRun.claim_id.in_(ids), AIRun.kind == "listing_match").order_by(AIRun.id):
        runs_by_claim[r.claim_id].append(r)
    agreement = Counter()
    for cid, d in dets.items():
        ai = _top_listing_overall(runs_by_claim.get(cid, []))
        if ai:
            agreement[(ai, d.decision)] += 1

    weekly = Counter()
    for c in decided:
        weekly[c.decided_at.date().isocalendar()[:2]] += 1
    weekly_series = [{"week": f"{y}-W{w:02d}", "decided": n} for (y, w), n in sorted(weekly.items())]

    return {
        "include_seed": include_seed,
        "cases_total": len(claims),
        "cases_decided": len(decided),
        "cases_in_review": len(claims) - len(decided),
        "decisions": Counter(d.decision for d in dets.values()),
        "intake_to_decision_days": {"median": round(median(days), 1) if days else None,
                                    "mean": round(mean(days), 1) if days else None,
                                    "buckets": _buckets(days)},
        "triage": {"assigned": len(assigned), "overridden": len(overrides),
                   "override_rate": round(len(overrides) / len(assigned), 3) if assigned else None,
                   "suggested": Counter(qa.ai_suggested_queue for qa in qas.values()),
                   "matrix": [{"ai": a, "final": f, "n": n} for (a, f), n in sorted(override_matrix.items())],
                   "recent_overrides": [{"claim_number": by_id[qa.claim_id].claim_number, "ai": qa.ai_suggested_queue,
                                         "final": qa.final_queue, "reason": qa.override_reason}
                                        for qa in sorted(overrides, key=lambda x: x.decided_at or x.created_at, reverse=True)[:5]]},
        "citations": {"total": len(cites), "unverified": unverified,
                      "unverified_rate": round(unverified / len(cites), 4) if cites else None},
        "listing_vs_decision": [{"ai": a, "decision": d, "n": n} for (a, d), n in sorted(agreement.items())],
        "weekly_decided": weekly_series,
    }


def _buckets(days: list[float]) -> list[dict]:
    edges = [(0, 7, "< 1 week"), (7, 30, "1-4 weeks"), (30, 60, "1-2 months"), (60, 120, "2-4 months"), (120, 10**6, "4+ months")]
    return [{"label": lab, "n": sum(1 for d in days if lo <= d < hi)} for lo, hi, lab in edges]
