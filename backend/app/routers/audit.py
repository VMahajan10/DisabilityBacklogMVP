import json
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_claim
from app.models import AIRun, AuditEvent, Citation, Claim
from app.services.audit import log_event

router = APIRouter(prefix="/api/claims/{claim_id}", tags=["audit"])


class UIEvent(BaseModel):
    event_type: Literal["citation_viewed", "source_page_viewed", "listing_text_viewed"]
    payload: dict = {}


@router.post("/events")
def ui_event(body: UIEvent, claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    log_event(db, claim.id, "human", body.event_type, body.payload)
    db.commit()
    return {"ok": True}


def _events(db: Session, claim_id: int) -> list[dict]:
    out = []
    for e in db.query(AuditEvent).filter_by(claim_id=claim_id).order_by(AuditEvent.id):
        out.append({"id": e.id, "timestamp": e.created_at.isoformat() + "Z", "actor_type": e.actor_type,
                    "actor": e.actor, "event_type": e.event_type, "ai_run_id": e.ai_run_id, "payload": e.payload_json})
    return out


@router.get("/audit")
def audit(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    return _events(db, claim.id)


@router.get("/audit/export")
def audit_export(claim: Claim = Depends(get_claim), db: Session = Depends(get_db)):
    runs = []
    for r in db.query(AIRun).filter_by(claim_id=claim.id).order_by(AIRun.id):
        cites = db.query(Citation).filter_by(ai_run_id=r.id).all()
        runs.append({
            "ai_run_id": r.id, "kind": r.kind, "provider": r.provider, "model": r.model,
            "prompt_name": r.prompt_name, "prompt_version": r.prompt_version, "prompt_sha256": r.prompt_sha,
            "input_sha256": r.input_hash, "timestamp": r.created_at.isoformat() + "Z", "attempts": r.attempts,
            "latency_ms": r.latency_ms, "output": r.output_json,
            "citations": [{"item_ref": c.item_ref, "doc_id": c.document_id, "page": c.page_number, "quote": c.quote,
                           "verified": c.verified, "match_score": c.match_score, "failure_reason": c.failure_reason}
                          for c in cites],
        })
    body = {"claim_id": claim.id, "claim_number": claim.claim_number, "synthetic_data": True,
            "events": _events(db, claim.id), "ai_runs": runs}
    log_event(db, claim.id, "human", "audit_exported", {})
    db.commit()
    return Response(json.dumps(body, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="audit_{claim.claim_number}.json"'})
