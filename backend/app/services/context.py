"""Build the page-labelled evidence context that every LLM prompt receives."""
from sqlalchemy.orm import Session

from app.models import Claim, Document, Page


def claim_pages(db: Session, claim_id: int) -> dict[tuple[int, int], Page]:
    rows = (db.query(Page).join(Document).filter(Document.claim_id == claim_id)
            .order_by(Document.id, Page.page_number).all())
    return {(p.document_id, p.page_number): p for p in rows}


def evidence_context(db: Session, claim_id: int) -> str:
    claim = db.get(Claim, claim_id)
    parts = [f"CLAIM {claim.claim_number}: claimant {claim.claimant_name}, DOB {claim.dob}, "
             f"alleged onset {claim.alleged_onset_date}, application filed {claim.filed_date}.\n"]
    for doc in db.query(Document).filter(Document.claim_id == claim_id).order_by(Document.id):
        for p in doc.pages:
            parts.append(f'[DOC {doc.id} "{doc.doc_label}" | PAGE {p.page_number}]\n{p.text}\n')
    return "\n".join(parts)
