"""Claim intake: store PDFs, then ingest (extract -> OCR -> dedupe -> tag -> embed) with progress."""
import json
import shutil
import time
import uuid
from datetime import date
from pathlib import Path

import pdfplumber
from sqlalchemy.orm import Session

from app import config
from app.llm.base import LLMProvider
from app.models import Claim, Document, Page
from app.services import dedupe, records_index, tagging
from app.services.audit import log_event
from app.services.extraction import _is_body_char, pdf_title, sha256_file
from app.llm.usage import pmap
from app.services.ocr import ocr_image, render_page

SYNTHETIC_DIR = config.DATA_DIR / "synthetic" / "cases"


def store_document(db: Session, claim: Claim, src_path: Path, filename: str, label: str | None = None) -> Document:
    """Copy the file and create a Document in 'processing' state. Text extraction happens in ingest()."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOAD_DIR / f"{claim.id}_{uuid.uuid4().hex[:8]}_{Path(filename).name}"
    shutil.copyfile(src_path, dest)
    doc = Document(claim_id=claim.id, filename=Path(filename).name, file_path=str(dest), sha256=sha256_file(dest),
                   doc_label=label or pdf_title(dest) or Path(filename).stem, page_count=0, status="processing")
    db.add(doc)
    db.flush()
    log_event(db, claim.id, "human", "document_uploaded", {"document_id": doc.id, "filename": doc.filename, "sha256": doc.sha256})
    return doc


def ingest(db: Session, claim_id: int, progress, provider: LLMProvider, doc_ids: list[int] | None = None) -> dict:
    """Process documents still in 'processing' state (or the given ids)."""
    t0 = time.monotonic()
    q = db.query(Document).filter(Document.claim_id == claim_id)
    docs = [d for d in q.order_by(Document.id) if (d.id in doc_ids if doc_ids else d.status == "processing")]
    total = 0
    for d in docs:
        with pdfplumber.open(d.file_path) as pdf:
            total += len(pdf.pages)
    c = {"documents": len(docs), "pages_total": total, "pages_extracted": 0, "ocr_pages": 0, "duplicates": 0,
         "duplicates_exact": 0, "duplicates_near": 0, "tagged_rule": 0, "tagged_llm": 0, "admin_pages": 0,
         "chunks_total": 0, "chunks_embedded": 0}
    progress(stage="extracting", **c)

    new_pages: list[Page] = []
    for d in docs:
        need_ocr: list[tuple[Page, object]] = []
        with pdfplumber.open(d.file_path) as pdf:
            for i, pg in enumerate(pdf.pages, start=1):
                text = (pg.filter(_is_body_char).extract_text(layout=False) or "").strip()
                p = Page(document_id=d.id, page_number=i, text=text, ocr=False)
                if len(text) < config.OCR_MIN_CHARS:
                    need_ocr.append((p, render_page(pg)))
                db.add(p)
                new_pages.append(p)
                c["pages_extracted"] += 1
                if c["pages_extracted"] % 25 == 0:
                    progress(stage="extracting", **c)
                if len(need_ocr) >= 8:  # OCR in parallel batches to bound memory
                    _run_ocr(need_ocr, c, progress)
                    need_ocr = []
            d.page_count = len(pdf.pages)
        _run_ocr(need_ocr, c, progress)
        db.commit()
    progress(stage="deduplicating", **c)

    # Dedupe across ALL pages of the claim (new uploads may duplicate earlier ones).
    all_pages = (db.query(Page).join(Document).filter(Document.claim_id == claim_id).all())
    sigs = [dedupe.build_sig(p.id, (p.document_id, p.page_number), p.text) for p in all_pages]
    for p, s in zip(all_pages, sigs):
        p.text_hash = s.hash
    dups = dedupe.find_duplicates(sigs)
    new_ids = {p.id for p in new_pages}
    for p in all_pages:
        if p.id in dups and p.id in new_ids:
            orig, kind, _ = dups[p.id]
            p.duplicate_of_page_id, p.duplicate_kind = orig, kind
            c["duplicates"] += 1
            c["duplicates_exact" if kind == "exact" else "duplicates_near"] += 1
    db.commit()
    progress(stage="tagging", **c)

    untagged = []
    for p in new_pages:
        t = tagging.rule_tag(p.text)
        p.provider, p.service_date = t["provider"], t["service_date"]
        if t["doc_type"]:
            p.doc_type, p.tag_source = t["doc_type"], "rule"
            c["tagged_rule"] += 1
        else:
            untagged.append(p)
    if untagged:
        llm = tagging.llm_tag([(str(p.id), p.text) for p in untagged], provider)
        for p in untagged:
            t = llm.get(str(p.id), {"doc_type": "other", "provider": None, "service_date": None})
            p.doc_type, p.tag_source = t["doc_type"], "llm"
            p.provider = p.provider or t["provider"]
            p.service_date = p.service_date or t["service_date"]
            c["tagged_llm"] += 1
    prev = None
    for p in new_pages:  # continuation pages inherit the date of service from the page before
        if (not p.service_date and prev is not None and prev.document_id == p.document_id
                and prev.doc_type == p.doc_type):
            p.service_date = prev.service_date
        prev = p
    for p in new_pages:
        p.is_admin = p.doc_type in tagging.ADMIN_TYPES
        c["admin_pages"] += int(p.is_admin)
    db.commit()
    progress(stage="embedding", **c)

    c["chunks_total"] = records_index.index_pages(db, claim_id, new_pages, provider,
                                                  progress=lambda **kw: progress(**{**c, **kw}))
    c["chunks_embedded"] = c["chunks_total"]
    for d in docs:
        d.status = "ready"
    claim = db.get(Claim, claim_id)
    if claim.status == "intake":
        claim.status = "in_review"
    c["seconds"] = round(time.monotonic() - t0, 1)
    log_event(db, claim_id, "system", "ingestion_completed", c)
    db.commit()
    progress(stage="done", force=True, **c)
    return c


def _run_ocr(items: list, c: dict, progress) -> None:
    if not items:
        return
    progress(stage="ocr", **c)
    results = pmap(lambda it: ocr_image(it[1]), items, workers=4)
    for (p, _), (text, conf) in zip(items, results):
        p.ocr_confidence = conf
        if len(text) > len(p.text):
            p.text, p.ocr = text, True
            c["ocr_pages"] += 1
    progress(stage="extracting", **c)


# ----------------------------------------------------------------------------- synthetic cases
def list_synthetic_cases() -> list[dict]:
    out = []
    for d in sorted(SYNTHETIC_DIR.glob("case*")):
        if not (d / "case.json").exists():
            continue
        meta = json.loads((d / "case.json").read_text())
        out.append({"case_id": meta["case_id"], "title": meta["title"], "claimant": meta["claimant"]["name"],
                    "documents": len(meta["documents"]), "pages": meta.get("total_pages") or
                    sum(x.get("logical_pages", 0) for x in meta["documents"])})
    return out


def create_synthetic_claim(db: Session, case_id: str) -> Claim:
    """Create the claim + stored documents. Call ingest() afterwards (sync or as a job)."""
    d = SYNTHETIC_DIR / case_id
    meta = json.loads((d / "case.json").read_text())
    c = meta["claimant"]
    suffix = uuid.uuid4().hex[:4].upper()
    claim = Claim(claim_number=f"{c['claim_number']}-{suffix}", claimant_name=c["name"],
                  dob=date.fromisoformat(c["dob"]), alleged_onset_date=date.fromisoformat(c["alleged_onset_date"]),
                  filed_date=date.fromisoformat(c["filed_date"]), synthetic_case_id=case_id)
    db.add(claim)
    db.flush()
    log_event(db, claim.id, "human", "claim_created", {"source": "synthetic", "case_id": case_id})
    for doc in meta["documents"]:
        store_document(db, claim, d / doc["file"], doc["file"], doc["title"])
    db.commit()
    return claim


def load_synthetic_case(db: Session, case_id: str, provider: LLMProvider | None = None, progress=None) -> Claim:
    """Synchronous create + ingest (used by tests and the eval)."""
    from app.llm.registry import get_provider
    claim = create_synthetic_claim(db, case_id)
    ingest(db, claim.id, progress or (lambda **kw: None), provider or get_provider())
    return claim
