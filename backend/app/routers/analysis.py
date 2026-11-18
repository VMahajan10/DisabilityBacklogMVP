from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_claim, provider_dep
from app.llm.base import LLMProvider, LLMValidationError
from app.models import AIRun, Claim, Document
from app.services import summary as summary_svc

router = APIRouter(prefix="/api/claims/{claim_id}", tags=["analysis"])


def latest_run(db: Session, claim_id: int, kind: str) -> AIRun | None:
    return db.query(AIRun).filter_by(claim_id=claim_id, kind=kind).order_by(AIRun.id.desc()).first()


def require_docs(db: Session, claim: Claim):
    if not db.query(Document).filter_by(claim_id=claim.id).count():
        raise HTTPException(400, "Upload at least one document first")


def run_llm(fn, *args):
    try:
        return fn(*args)
    except LLMValidationError as e:
        raise HTTPException(502, f"AI output failed validation: {e}")
    except Exception as e:  # provider/network errors -> readable message in UI
        if e.__class__.__module__.startswith("openai"):
            raise HTTPException(502, f"LLM provider error: {e}")
        raise


from app.models import ProcessingJob  # noqa: E402
from app.services.jobs import start_job  # noqa: E402


def start_analysis(db: Session, claim: Claim, kind: str, fn, provider: LLMProvider) -> dict:
    """Run an AI step as a background job (large files take minutes); the UI polls /api/jobs/{id}."""
    require_docs(db, claim)
    if db.query(Document).filter_by(claim_id=claim.id, status="processing").count():
        raise HTTPException(409, "Documents are still being processed; wait for intake to finish")
    if db.query(ProcessingJob).filter_by(claim_id=claim.id, kind=kind, status="running").count():
        raise HTTPException(409, f"A {kind.replace('_', ' ')} job is already running for this claim")
    return {"job_id": start_job(claim.id, kind, lambda db2, cid, prog: fn(db2, cid, provider, prog))}


@router.post("/summary")
def create_summary(claim: Claim = Depends(get_claim), db: Session = Depends(get_db),
                   provider: LLMProvider = Depends(provider_dep)):
    return start_analysis(db, claim, "summary", summary_svc.run_summary, provider)


@router.get("/chronology")
def get_chronology(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    run = latest_run(db, claim.id, "summary")
    return summary_svc.chronology_view(db, run) if run else None


@router.get("/summary")
def get_summary(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    run = latest_run(db, claim.id, "summary")
    return summary_svc.summary_view(db, run) if run else None


from app.services import listing_match as lm_svc  # noqa: E402


def _listing_job(db, claim_id, provider, prog):
    if not latest_run(db, claim_id, "summary"):  # listing selection also uses the verified summary
        summary_svc.run_summary(db, claim_id, provider, prog)
    lm_svc.run_listing_match(db, claim_id, provider, prog)


@router.post("/listing-match")
def create_listing_match(claim: Claim = Depends(get_claim), db: Session = Depends(get_db),
                         provider: LLMProvider = Depends(provider_dep)):
    return start_analysis(db, claim, "listing_match", _listing_job, provider)


@router.get("/listing-match")
def get_listing_match(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    return lm_svc.listing_view(db, lm_svc.latest_batch(db, claim.id))


from pydantic import BaseModel  # noqa: E402

from app.models import RecordsRequest  # noqa: E402
from app.services import missing_evidence as me_svc  # noqa: E402
from app.services.audit import log_event  # noqa: E402
from app.models import utcnow  # noqa: E402


@router.post("/missing-evidence")
def create_missing(claim: Claim = Depends(get_claim), db: Session = Depends(get_db),
                   provider: LLMProvider = Depends(provider_dep)):
    return start_analysis(db, claim, "missing_evidence", me_svc.run_missing_evidence, provider)


@router.get("/missing-evidence")
def get_missing(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    run = latest_run(db, claim.id, "missing_evidence")
    return me_svc.missing_view(db, run) if run else None


class LetterEdit(BaseModel):
    text: str


@router.put("/records-request")
def save_letter(body: LetterEdit, claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    rr = db.query(RecordsRequest).filter_by(claim_id=claim.id).order_by(RecordsRequest.id.desc()).first()
    if not rr:
        raise HTTPException(404, "No draft letter yet")
    rr.edited_text, rr.updated_at = body.text, utcnow()
    log_event(db, claim.id, "human", "records_request_edited",
              {"records_request_id": rr.id, "chars": len(body.text), "changed_from_draft": body.text != rr.draft_text})
    db.commit()
    return {"ok": True, "updated_at": rr.updated_at.isoformat() + "Z"}


from typing import Literal  # noqa: E402

from app import config  # noqa: E402
from app.models import Determination, QueueAssignment  # noqa: E402
from app.services import triage as tr_svc  # noqa: E402


@router.post("/triage")
def create_triage(claim: Claim = Depends(get_claim), db: Session = Depends(get_db),
                  provider: LLMProvider = Depends(provider_dep)):
    return start_analysis(db, claim, "triage", tr_svc.run_triage, provider)


@router.get("/triage")
def get_triage(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    run = latest_run(db, claim.id, "triage")
    return tr_svc.triage_view(db, run) if run else None


class QueueDecision(BaseModel):
    final_queue: Literal["fast_track", "standard", "senior_examiner"]
    override_reason: str | None = None


@router.put("/queue")
def set_queue(body: QueueDecision, claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    qa = db.query(QueueAssignment).filter_by(claim_id=claim.id).order_by(QueueAssignment.id.desc()).first()
    if not qa:
        raise HTTPException(400, "Run triage first")
    overridden = body.final_queue != qa.ai_suggested_queue
    if overridden and not (body.override_reason or "").strip():
        raise HTTPException(400, "A reason is required when overriding the AI suggestion")
    qa.final_queue, qa.overridden = body.final_queue, overridden
    qa.override_reason = body.override_reason if overridden else None
    qa.examiner_id, qa.decided_at = config.DEMO_EXAMINER["id"], utcnow()
    log_event(db, claim.id, "human", "triage_overridden" if overridden else "triage_accepted",
              {"ai_suggested_queue": qa.ai_suggested_queue, "final_queue": body.final_queue,
               "override_reason": qa.override_reason, "queue_assignment_id": qa.id})
    db.commit()
    return {"ok": True, "final_queue": qa.final_queue, "overridden": overridden}


class DeterminationIn(BaseModel):
    decision: Literal["allowed", "denied", "needs_development"]
    notes: str = ""
    evidence_reviewed_confirmed: bool


@router.get("/determination")
def get_determination(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    d = db.query(Determination).filter_by(claim_id=claim.id).order_by(Determination.id.desc()).first()
    return {"decision": d.decision, "notes": d.notes, "created_at": d.created_at.isoformat() + "Z",
            "examiner": config.DEMO_EXAMINER["name"]} if d else None


@router.post("/determination")
def record_determination(body: DeterminationIn, claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    """Human-only. No AI code path writes to this table."""
    if not body.evidence_reviewed_confirmed:
        raise HTTPException(400, "Confirm that you reviewed the cited evidence before recording a determination")
    d = Determination(claim_id=claim.id, examiner_id=config.DEMO_EXAMINER["id"], decision=body.decision,
                      notes=body.notes, evidence_reviewed_confirmed=True)
    db.add(d)
    if body.decision in ("allowed", "denied"):
        claim.status, claim.decided_at = "decided", utcnow()
    else:
        claim.status, claim.decided_at = "in_review", None
    lm = latest_run(db, claim.id, "listing_match")
    tr = latest_run(db, claim.id, "triage")
    log_event(db, claim.id, "human", "determination_recorded",
              {"decision": body.decision, "notes": body.notes, "evidence_reviewed_confirmed": True,
               "ai_context_at_decision": {
                   "triage_suggestion": tr.output_json.get("suggested_queue") if tr else None,
                   "listing_match_run_id": lm.id if lm else None}})
    db.commit()
    return {"ok": True, "decision": d.decision, "status": claim.status}
