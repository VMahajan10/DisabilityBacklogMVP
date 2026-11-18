"""Shared citation schema + verification/persistence used by every AI feature."""
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Citation, Document
from app.services.context import claim_pages
from app.services.verifier import verify_quote


class CitationIn(BaseModel):
    doc_id: int = Field(description="DOC id from the evidence header")
    page: int = Field(description="PAGE number from the evidence header")
    quote: str = Field(description="Short verbatim quote (5-30 words) copied exactly from that page")


def verify_and_store(db: Session, claim_id: int, ai_run_id: int, item_ref: str, statement: str,
                     cites: list[CitationIn], pages=None) -> list[Citation]:
    pages = pages if pages is not None else claim_pages(db, claim_id)
    out = []
    for c in cites:
        page = pages.get((c.doc_id, c.page))
        res = verify_quote(page.text if page else None, c.quote)
        row = Citation(ai_run_id=ai_run_id, claim_id=claim_id, item_ref=item_ref, statement=statement,
                       document_id=c.doc_id, page_number=c.page, quote=c.quote, verified=res.verified,
                       match_score=res.score, match_start=res.start, match_end=res.end, failure_reason=res.reason)
        db.add(row)
        out.append(row)
    db.flush()
    return out


def citation_dict(c: Citation, labels: dict[int, str]) -> dict:
    return {"id": c.id, "doc_id": c.document_id, "doc_label": labels.get(c.document_id, "Unknown document"),
            "page": c.page_number, "quote": c.quote, "verified": c.verified, "score": c.match_score,
            "match_start": c.match_start, "match_end": c.match_end, "failure_reason": c.failure_reason,
            "relevant": c.relevant, "relevance_reason": c.relevance_reason}


def doc_labels(db: Session, claim_id: int) -> dict[int, str]:
    return {d.id: d.doc_label for d in db.query(Document).filter(Document.claim_id == claim_id)}


def verification_stats(cites: list[Citation]) -> dict:
    n = len(cites)
    v = sum(1 for c in cites if c.verified)
    return {"citations": n, "verified": v, "unverified": n - v, "rate": round(v / n, 3) if n else None}
