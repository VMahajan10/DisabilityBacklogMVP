"""Triage suggestion. The LLM supplies a cited CAL signal (judged on pages retrieved from the raw
records) and complexity notes; conflicts come from the verified conflict check built with the summary.
Transparent rules map the signals to a queue. The examiner can always override."""
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.models import AIRun, CalCondition, Citation, Document, Page, QueueAssignment
from app.prompts import load_prompt
from app.services import records_index
from app.services.audit import log_ai_run_event, record_ai_run
from app.services.citations import CitationIn, citation_dict, doc_labels, verification_stats, verify_and_store
from app.services.context import claim_pages
from app.services.vectorstore import top_k

CAL_SHORTLIST = 10
CAL_MAX_PAGES = 20
UNVERIFIED_SENIOR_RATE = 0.2
QUEUES = ("fast_track", "standard", "senior_examiner")


class CalMatch(BaseModel):
    matched: bool
    cal_condition: str | None = Field(description="Exact name from the CAL shortlist, or null")
    reasoning: str
    citations: list[CitationIn] = Field(description="Claimant evidence of the diagnosis; required if matched")


class TriageSignals(BaseModel):
    cal: CalMatch
    complexity_notes: list[str] = Field(description="Short notes on other complexity, if any")


def cal_shortlist(db: Session, provider: LLMProvider, query: str) -> list[str]:
    conds = db.query(CalCondition).all()
    qv = provider.embed([query])[0]
    return [c.name for c, _ in top_k(qv, [(c, c.embedding) for c in conds], CAL_SHORTLIST)]


def _latest(db, claim_id, kind):
    return db.query(AIRun).filter_by(claim_id=claim_id, kind=kind).order_by(AIRun.id.desc()).first()


def decide_queue(cal_verified: str | None, top_listing: dict | None, conflicts_verified: list[str],
                 unverified_rate: float | None, n_gaps: int) -> tuple[str, list[str]]:
    reasons = []
    if cal_verified:
        reasons.append(f"Diagnosis matches Compassionate Allowances condition \"{cal_verified}\" (verified citation).")
    if top_listing and top_listing["overall"] == "criteria_appear_met":
        reasons.append(f"All criteria of listing {top_listing['listing_code']} appear met with verified citations.")
    if reasons:
        return "fast_track", reasons
    if conflicts_verified:
        return "senior_examiner", [f"Conflicting evidence: {c}" for c in conflicts_verified]
    if unverified_rate is not None and unverified_rate > UNVERIFIED_SENIOR_RATE:
        return "senior_examiner", [f"{unverified_rate:.0%} of AI citations could not be verified; needs closer review."]
    out = ["No CAL condition, no listing clearly met, and no conflicting medical opinions identified."]
    if n_gaps:
        out.append(f"{n_gaps} evidence gap(s) flagged for development.")
    return "standard", out


def cal_evidence_pages(db: Session, claim_id: int, provider: LLMProvider, shortlist: list[str], diag_text: str) -> list[Page]:
    """Raw-record pages most similar to each CAL shortlist name and to the diagnoses."""
    in_scope = (db.query(Page).join(Document).filter(Document.claim_id == claim_id, Page.duplicate_of_page_id.is_(None),
                                                     Page.is_admin.isnot(True)).all())
    if len(in_scope) <= CAL_MAX_PAGES:
        return sorted(in_scope, key=lambda p: (p.document_id, p.page_number))
    hits = records_index.search(db, claim_id, provider, shortlist + [diag_text[:2000] or "diagnosis assessment"], k=3)
    best: dict[tuple[int, int], float] = {}
    for hs in hits:
        for h in hs:
            best[(h.document_id, h.page_number)] = max(best.get((h.document_id, h.page_number), -1), h.score)
    pages = claim_pages(db, claim_id)
    keys = sorted(best, key=lambda k: -best[k])[:CAL_MAX_PAGES]
    return sorted([pages[k] for k in keys if k in pages], key=lambda p: (p.document_id, p.page_number))


def run_triage(db: Session, claim_id: int, provider: LLMProvider, progress=None) -> AIRun:
    from app.services import listing_match as lm
    from app.services import summary as sm
    from app.services.reference_data import ensure_reference_data

    prog = progress or (lambda **kw: None)
    if not _latest(db, claim_id, "summary"):
        sm.run_summary(db, claim_id, provider, prog)
    if not lm.latest_batch(db, claim_id):
        lm.run_listing_match(db, claim_id, provider, prog)
    ensure_reference_data(db, provider)
    prog(stage="signals")

    lview = lm.listing_view(db, lm.latest_batch(db, claim_id))
    top = lview["listings"][0] if lview and lview["listings"] else None
    summ = _latest(db, claim_id, "summary")
    diag_text = "\n".join(b["text"] for b in summ.output_json.get("diagnoses", []))
    shortlist = cal_shortlist(db, provider, diag_text or "diagnosis")
    pages = cal_evidence_pages(db, claim_id, provider, shortlist, diag_text)

    chron = sm.chronology_view(db, summ)
    conflicts = chron["conflicts"]
    prompt = load_prompt("triage")
    listing_brief = "\n".join(f"- {l['listing_code']}: {l['overall']}" for l in (lview or {}).get("listings", [])) or "(none)"
    user = prompt.render_user(cal_shortlist="\n".join(f"- {n}" for n in shortlist), listing_summary=listing_brief,
                              conflicts="\n".join(f"- {c['description']}" for c in conflicts) or "(none)",
                              evidence=lm.render_evidence(db, claim_id, pages))
    res = provider.complete_structured(prompt.system, user, TriageSignals)
    run = record_ai_run(db, claim_id, "triage", prompt, res, user, res.parsed.model_dump())

    all_c = []
    cal_ok = None
    cal = res.parsed.cal
    if cal.matched:
        cs = verify_and_store(db, claim_id, run.id, "cal", cal.reasoning, cal.citations, claim_pages(db, claim_id))
        all_c += cs
        if cal.cal_condition in shortlist and any(c.verified for c in cs):
            cal_ok = cal.cal_condition
    # Conflicts were already verified on both sides by the conflict check.
    conflicts_ok = [c["description"] for c in conflicts
                    if any(x["verified"] for x in c["side_a"]["citations"]) and any(x["verified"] for x in c["side_b"]["citations"])]

    prior = db.query(Citation).filter(Citation.claim_id == claim_id, Citation.ai_run_id != run.id).all()
    rate = (sum(1 for c in prior if not c.verified) / len(prior)) if prior else None
    me = _latest(db, claim_id, "missing_evidence")
    n_gaps = len(me.output_json.get("flags", [])) if me else 0
    queue, reasons = decide_queue(cal_ok, top, conflicts_ok, rate, n_gaps)

    run.output_json = {**run.output_json, "cal_shortlist": shortlist, "cal_verified": cal_ok,
                       "conflicts_verified": conflicts_ok, "conflicts_run_id": summ.output_json.get("conflicts_run_id"),
                       "summary_run_id": summ.id, "cal_evidence_pages": len(pages), "unverified_rate_prior": rate,
                       "n_gaps": n_gaps, "top_listing": {"code": top["listing_code"], "overall": top["overall"]} if top else None,
                       "suggested_queue": queue, "reasons": reasons}
    db.add(QueueAssignment(claim_id=claim_id, ai_suggested_queue=queue, ai_run_id=run.id))
    log_ai_run_event(db, run, {**verification_stats(all_c), "suggested_queue": queue})
    db.commit()
    return run


def triage_view(db: Session, run: AIRun) -> dict:
    from app.services import summary as sm
    from app.services.summary import run_meta
    labels = doc_labels(db, run.claim_id)
    cites = db.query(Citation).filter_by(ai_run_id=run.id).order_by(Citation.id).all()
    by = {}
    for c in cites:
        by.setdefault(c.item_ref, []).append(citation_dict(c, labels))
    o = run.output_json
    conflicts = []
    srun = db.get(AIRun, o["summary_run_id"]) if o.get("summary_run_id") else None
    if srun:
        for cf in sm.chronology_view(db, srun)["conflicts"]:
            conflicts.append({"description": cf["description"], "verified": cf["description"] in o["conflicts_verified"],
                              "citations": cf["side_a"]["citations"] + cf["side_b"]["citations"]})
    qa = db.query(QueueAssignment).filter_by(claim_id=run.claim_id).order_by(QueueAssignment.id.desc()).first()
    return {
        "run": run_meta(run), "suggested_queue": o["suggested_queue"], "reasons": o["reasons"],
        "cal": {**o["cal"], "verified_match": o["cal_verified"], "citations": by.get("cal", []), "shortlist": o["cal_shortlist"]},
        "conflicts": conflicts, "complexity_notes": o["complexity_notes"], "top_listing": o["top_listing"],
        "assignment": {"id": qa.id, "ai_suggested_queue": qa.ai_suggested_queue, "final_queue": qa.final_queue,
                       "overridden": qa.overridden, "override_reason": qa.override_reason,
                       "decided_at": qa.decided_at.isoformat() + "Z" if qa.decided_at else None} if qa else None,
        "verification": verification_stats(cites),
    }
