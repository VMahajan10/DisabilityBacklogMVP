"""Seed ~40 historical demo claims so the pilot metrics dashboard looks realistic.

All seeded rows are flagged claim.is_demo_seed=True and use provider "demo-seed"; they contain no
documents and are hidden from the case list. Re-running replaces previous seed data.
Usage: make seed
"""
import random
from datetime import timedelta

from app.db import SessionLocal, init_db
from app.models import AIRun, AuditEvent, Citation, Claim, Determination, QueueAssignment, utcnow

FIRST = ["Avery", "Jordan", "Riley", "Casey", "Morgan", "Quinn", "Rowan", "Sage", "Emerson", "Parker", "Reese", "Skyler",
         "Dakota", "Hayden", "Kendall", "Logan", "Peyton", "Sawyer", "Tatum", "Blair"]
LAST = ["Okafor-Lind", "Vasquez-Hale", "Brightwater", "Nakamura-Fell", "Osei-Grant", "Lindgren", "Abernathy", "Castellanos",
        "Whitfield", "Duchamp", "Yarrow", "Kowalski-Reed", "Thorne", "Ellery", "Marchetti"]
LISTINGS = ["1.15", "1.16", "1.18", "1.17", "1.22"]


def seed(n: int = 42, rng_seed: int = 7):
    rng = random.Random(rng_seed)
    init_db()
    db = SessionLocal()
    old = [c.id for c in db.query(Claim).filter_by(is_demo_seed=True)]
    for model in (Citation, AuditEvent, AIRun, QueueAssignment, Determination):
        db.query(model).filter(model.claim_id.in_(old)).delete(synchronize_session=False)
    db.query(Claim).filter(Claim.id.in_(old)).delete(synchronize_session=False)

    now = utcnow()
    for i in range(n):
        created = now - timedelta(days=rng.uniform(5, 70), hours=rng.uniform(0, 8))
        # Ground truth for the fake case drives realistic, mostly-consistent AI vs examiner outcomes.
        kind = rng.choices(["meets", "not_met", "insufficient", "cal"], [0.22, 0.43, 0.27, 0.08])[0]
        ai_overall = {"meets": "criteria_appear_met", "not_met": "criteria_not_met",
                      "insufficient": "insufficient_evidence", "cal": "insufficient_evidence"}[kind]
        if rng.random() < 0.1:  # AI sometimes disagrees with eventual decision
            ai_overall = rng.choice(["criteria_appear_met", "criteria_not_met", "insufficient_evidence"])
        suggested = {"meets": "fast_track", "cal": "fast_track", "not_met": "standard",
                     "insufficient": rng.choice(["standard", "standard", "senior_examiner"])}[kind]
        c = Claim(claim_number=f"DEMO-{26000 + i}", claimant_name=f"{rng.choice(FIRST)} {rng.choice(LAST)} (demo)",
                  status="in_review", created_at=created, is_demo_seed=True,
                  filed_date=(created - timedelta(days=rng.randint(20, 90))).date())
        db.add(c)
        db.flush()
        for kind_run in ("summary", "listing_match", "triage"):
            r = AIRun(claim_id=c.id, kind=kind_run, provider="demo-seed", model="demo-seed", prompt_name=kind_run,
                      prompt_version="seed", prompt_sha="seed", input_hash="seed", attempts=1,
                      latency_ms=rng.randint(6000, 30000), created_at=created + timedelta(minutes=5),
                      output_json={"batch_id": f"seed{i}", "overall": ai_overall, "listing_code": rng.choice(LISTINGS)}
                      if kind_run == "listing_match" else {"suggested_queue": suggested})
            db.add(r)
            db.flush()
            for _ in range(rng.randint(10, 30)):
                db.add(Citation(ai_run_id=r.id, claim_id=c.id, item_ref="seed", statement="seed", quote="seed",
                                verified=rng.random() > 0.035, match_score=1.0))
        final = suggested
        reason = None
        if rng.random() < 0.14:
            final = rng.choice([q for q in ("fast_track", "standard", "senior_examiner") if q != suggested])
            reason = rng.choice({
                "fast_track": ["Listing clearly met on review of imaging and exam; expedite.",
                               "Terminal diagnosis confirmed by pathology; expedite."],
                "senior_examiner": ["Treating and CE opinions conflict on assistive device need.",
                                    "Prior claim history requires senior review."],
                "standard": ["AI flagged conflict is minor variation over time; standard development is enough.",
                             "Fast-track not appropriate until updated imaging is received."],
            }[final])
        decided_days = {"fast_track": rng.uniform(1, 12), "standard": rng.uniform(10, 55),
                        "senior_examiner": rng.uniform(25, 70)}[final]
        done = created + timedelta(days=decided_days)
        db.add(QueueAssignment(claim_id=c.id, ai_suggested_queue=suggested, final_queue=final, overridden=final != suggested,
                               override_reason=reason, examiner_id=1, created_at=created, decided_at=created + timedelta(hours=2)))
        if done < now:
            decision = {"meets": "allowed", "cal": "allowed", "not_met": "denied",
                        "insufficient": rng.choice(["needs_development", "denied", "allowed"])}[kind]
            if rng.random() < 0.06:
                decision = rng.choice(["allowed", "denied"])
            db.add(Determination(claim_id=c.id, examiner_id=1, decision=decision, notes="(seeded demo record)",
                                 evidence_reviewed_confirmed=True, created_at=done))
            if decision != "needs_development":
                c.status, c.decided_at = "decided", done
    db.commit()
    print(f"Seeded {n} demo claims (is_demo_seed=True).")


if __name__ == "__main__":
    seed()
