import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import CalCondition, ListingChunk
from app.services import bluebook

router = APIRouter(prefix="/api", tags=["reference"])


def _meta(path):
    p = path.parent / "source.json"
    return json.loads(p.read_text()) if p.exists() else None


@router.get("/listings")
def listings(db: Session = Depends(get_db)):
    rows = db.query(ListingChunk).filter(ListingChunk.level == "listing").order_by(ListingChunk.seq).all()
    return {"source": _meta(bluebook.HTML_PATH),
            "chunk_count": db.query(ListingChunk).count(),
            "listings": [{"code": r.listing_code, "title": r.heading, "text": r.text,
                          "criteria": [{"criterion_id": c.criterion_id, "level": c.level, "text": c.heading}
                                       for c in db.query(ListingChunk).filter_by(listing_code=r.listing_code)
                                       .filter(ListingChunk.level != "listing").order_by(ListingChunk.seq)]}
                         for r in rows]}


@router.get("/cal-conditions")
def cal_conditions(db: Session = Depends(get_db)):
    from app.services import cal
    return {"source": _meta(cal.HTML_PATH),
            "conditions": [{"name": c.name, "poms_url": c.poms_url} for c in db.query(CalCondition).order_by(CalCondition.name)]}
