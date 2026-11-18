import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_claim, provider_dep
from app.llm.base import LLMProvider
from app.models import AIRun, Claim, Determination, Document, ProcessingJob, QueueAssignment
from app.services.audit import log_event
from app.services.intake import create_synthetic_claim, ingest, list_synthetic_cases, store_document
from app.services.jobs import job_dict, start_job

router = APIRouter(prefix="/api", tags=["claims"])


class ClaimCreate(BaseModel):
    claimant_name: str
    claim_number: str | None = None
    dob: date | None = None
    alleged_onset_date: date | None = None
    filed_date: date | None = None


def claim_row(db: Session, c: Claim) -> dict:
    q = db.query(QueueAssignment).filter_by(claim_id=c.id).order_by(QueueAssignment.id.desc()).first()
    d = db.query(Determination).filter_by(claim_id=c.id).order_by(Determination.id.desc()).first()
    return {
        "id": c.id, "claim_number": c.claim_number, "claimant_name": c.claimant_name,
        "dob": c.dob, "alleged_onset_date": c.alleged_onset_date, "filed_date": c.filed_date,
        "status": c.status, "created_at": c.created_at.isoformat() + "Z",
        "decided_at": c.decided_at.isoformat() + "Z" if c.decided_at else None,
        "synthetic_case_id": c.synthetic_case_id,
        "ai_suggested_queue": q.ai_suggested_queue if q else None,
        "final_queue": q.final_queue if q else None,
        "decision": d.decision if d else None,
    }


@router.get("/claims")
def list_claims(db: Session = Depends(get_db)):
    rows = db.query(Claim).filter(Claim.is_demo_seed.is_(False)).order_by(Claim.id.desc()).all()
    return [claim_row(db, c) for c in rows]


@router.post("/claims")
def create_claim(body: ClaimCreate, db: Session = Depends(get_db)):
    n = body.claim_number or f"SYN-{db.query(Claim).count() + 1:06d}"
    c = Claim(claim_number=n, claimant_name=body.claimant_name, dob=body.dob,
              alleged_onset_date=body.alleged_onset_date, filed_date=body.filed_date)
    db.add(c)
    db.flush()
    log_event(db, c.id, "human", "claim_created", {"source": "manual"})
    db.commit()
    return claim_row(db, c)


@router.get("/synthetic-cases")
def synthetic_cases():
    return list_synthetic_cases()


@router.post("/synthetic-cases/{case_id}/load")
def load_case(case_id: str, db: Session = Depends(get_db), provider: LLMProvider = Depends(provider_dep)):
    if case_id not in {c["case_id"] for c in list_synthetic_cases()}:
        raise HTTPException(404, "Unknown synthetic case")
    c = create_synthetic_claim(db, case_id)
    job_id = start_job(c.id, "ingest", ingest, provider)
    return {**claim_row(db, c), "job_id": job_id}


@router.get("/claims/{claim_id}")
def get_claim_detail(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    docs = db.query(Document).filter_by(claim_id=claim.id).order_by(Document.id).all()
    runs = db.query(AIRun).filter_by(claim_id=claim.id).all()
    return {
        **claim_row(db, claim),
        "documents": [{"id": d.id, "filename": d.filename, "doc_label": d.doc_label, "page_count": d.page_count,
                       "status": d.status or "ready", "sha256": d.sha256,
                       "uploaded_at": d.uploaded_at.isoformat() + "Z"} for d in docs],
        "ai_runs": sorted({r.kind for r in runs}),
        "page_count": sum(d.page_count for d in docs),
        "processing": any(d.status == "processing" for d in docs),
    }


@router.post("/claims/{claim_id}/documents")
async def upload_documents(files: list[UploadFile] = File(...), claim: Claim = Depends(get_claim),
                           db: Session = Depends(get_db), provider: LLMProvider = Depends(provider_dep)):
    """Store PDFs immediately; extraction/OCR/dedupe/tagging/embedding run as a background job."""
    if db.query(ProcessingJob).filter_by(claim_id=claim.id, kind="ingest", status="running").count():
        raise HTTPException(409, "Documents are still being processed for this claim; try again when it finishes")
    added = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"{f.filename}: only PDF files are accepted")
        data = await f.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, f"{f.filename}: not a valid PDF")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
        try:
            doc = store_document(db, claim, Path(tmp.name), f.filename)
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        added.append({"id": doc.id, "doc_label": doc.doc_label})
    db.commit()
    job_id = start_job(claim.id, "ingest", ingest, provider, [d["id"] for d in added])
    return {"documents": added, "job_id": job_id}


@router.get("/claims/{claim_id}/jobs")
def claim_jobs(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    jobs = db.query(ProcessingJob).filter_by(claim_id=claim.id).order_by(ProcessingJob.id.desc()).limit(20).all()
    return [job_dict(j) for j in jobs]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(ProcessingJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return job_dict(j)
