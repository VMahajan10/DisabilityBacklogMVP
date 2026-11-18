from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, Page

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _doc(db: Session, doc_id: int) -> Document:
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@router.get("/{doc_id}/pages")
def pages(doc_id: int, db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    return {"id": d.id, "doc_label": d.doc_label, "page_count": d.page_count,
            "pages": [{"page": p.page_number, "chars": len(p.text), "doc_type": p.doc_type, "ocr": bool(p.ocr),
                       "duplicate": bool(p.duplicate_of_page_id)} for p in d.pages]}


@router.get("/{doc_id}/pages/{page_number}")
def page(doc_id: int, page_number: int, db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    p = db.query(Page).filter_by(document_id=doc_id, page_number=page_number).first()
    if not p:
        raise HTTPException(404, "Page not found")
    dup = None
    if p.duplicate_of_page_id:
        o = db.get(Page, p.duplicate_of_page_id)
        if o:
            dup = {"doc_id": o.document_id, "page": o.page_number, "kind": p.duplicate_kind,
                   "doc_label": db.get(Document, o.document_id).doc_label}
    return {"doc_id": d.id, "doc_label": d.doc_label, "page": p.page_number, "page_count": d.page_count, "text": p.text,
            "tags": {"doc_type": p.doc_type, "provider": p.provider,
                     "service_date": p.service_date.isoformat() if p.service_date else None,
                     "ocr": bool(p.ocr), "ocr_confidence": p.ocr_confidence, "is_admin": bool(p.is_admin),
                     "tag_source": p.tag_source, "duplicate_of": dup}}


@router.get("/{doc_id}/file")
def file(doc_id: int, db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    return FileResponse(d.file_path, media_type="application/pdf", filename=d.filename,
                        content_disposition_type="inline")
