"""Load Blue Book chunks and CAL conditions into SQLite (with embeddings)."""
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.models import CalCondition, ListingChunk
from app.services import bluebook, cal


def ingest_bluebook(db: Session, provider: LLMProvider | None) -> int:
    if not bluebook.HTML_PATH.exists():
        raise FileNotFoundError(
            f"{bluebook.HTML_PATH} not found. Save {bluebook.SOURCE_URL} from your browser to that path.")
    meta = bluebook.source_meta()
    chunks = bluebook.parse_bluebook(bluebook.HTML_PATH.read_text(encoding="utf-8", errors="replace"))
    embs = provider.embed([c.text[:6000] for c in chunks]) if provider else [None] * len(chunks)
    db.query(ListingChunk).delete()
    for c, e in zip(chunks, embs):
        db.add(ListingChunk(listing_code=c.listing_code, criterion_id=c.criterion_id, parent_id=c.parent_id,
                            level=c.level, seq=c.seq, heading=c.heading[:500], text=c.text,
                            source_url=meta["source_url"], fetched_at=meta["retrieved_at"], embedding=e))
    db.commit()
    return len(chunks)


def ingest_cal(db: Session, provider: LLMProvider | None) -> int:
    if not cal.HTML_PATH.exists():
        raise FileNotFoundError(f"{cal.HTML_PATH} not found. Save {cal.SOURCE_URL} from your browser to that path.")
    meta = cal.source_meta()
    conds = cal.parse_cal(cal.HTML_PATH.read_text(encoding="utf-8", errors="replace"))
    embs = provider.embed([c["name"] for c in conds]) if provider else [None] * len(conds)
    db.query(CalCondition).delete()
    for c, e in zip(conds, embs):
        db.add(CalCondition(name=c["name"], poms_url=c["poms_url"], source_url=meta["source_url"],
                            fetched_at=meta["retrieved_at"], embedding=e))
    db.commit()
    return len(conds)


def ensure_reference_data(db: Session, provider: LLMProvider) -> None:
    if not db.query(ListingChunk).filter(ListingChunk.embedding.isnot(None)).count():
        ingest_bluebook(db, provider)
    if not db.query(CalCondition).filter(CalCondition.embedding.isnot(None)).count():
        ingest_cal(db, provider)
