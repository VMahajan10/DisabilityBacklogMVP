"""Missing-evidence agent.

1. The LLM extracts dated evidence items (with citations) and proposes clinical gaps.
2. Deterministic rules decide the date/presence-based flags from VERIFIED items only
   (no recent imaging, no treating source opinion, stale records), so those flags are
   reproducible and auditable.
3. Listing-match criteria marked insufficient become "undocumented criteria" flags.
4. The LLM drafts an editable records-request letter.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config
from app.llm.base import LLMProvider
from app.models import AIRun, Citation, Claim, RecordsRequest
from app.prompts import load_prompt
from app.services.audit import log_ai_run_event, record_ai_run
from app.llm.usage import pmap
from app.models import Document, Page
from app.services import records_index
from app.services.citations import CitationIn, citation_dict, doc_labels, verification_stats, verify_and_store
from app.services.context import claim_pages

INVENTORY_ALL_PAGES_MAX = 60
INVENTORY_MAX_PAGES = 90
INVENTORY_BATCH = 25
KEY_DOC_TYPES = {"imaging", "medical_source_statement", "consultative_exam", "operative_note", "pathology"}
EXAM_DOC_TYPES = {"progress_note", "emergency", "consultative_exam", "physical_therapy"}
INVENTORY_QUERIES = [
    "imaging report MRI CT X-ray findings impression",
    "medical source statement opinion functional capacity stand walk lift",
    "treating physician opinion work restrictions limitations",
    "physical examination strength reflexes sensation straight leg raise gait range of motion",
    "assistive device prescribed walker cane crutches wheelchair",
    "referral to specialist surgery consultation EMG nerve conduction",
]

Category = Literal["imaging", "clinical_exam", "treating_source_opinion", "consultative_exam_opinion",
                   "treatment", "claimant_report", "other"]
AIGap = Literal["consultative_exam_needed", "missing_test", "missing_specialist_records",
                "insufficient_exam_detail", "other"]
RULE_TYPES = ("no_recent_imaging", "no_treating_source_opinion", "stale_records")


class EvidenceItem(BaseModel):
    category: Category
    date: str | None = Field(description="Date of service as YYYY-MM-DD, or null if not stated")
    source: str = Field(description="Provider or facility name as written")
    description: str
    includes_musculoskeletal_or_neuro_exam: bool = Field(
        description="True only if this record documents an actual musculoskeletal or neurological examination")
    citations: list[CitationIn]


class Gap(BaseModel):
    gap_type: AIGap
    explanation: str = Field(description="ONE plain-language line explaining the gap")
    suggested_action: str
    provider_to_contact: str | None
    citations: list[CitationIn] = Field(description="Evidence that shows the gap (e.g. the limited exam); may be empty")


class Extraction(BaseModel):
    evidence_items: list[EvidenceItem]
    gaps: list[Gap]


class Letter(BaseModel):
    recipient: str
    subject: str
    body: str


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _months_between(a: date, b: date) -> float:
    return (b - a).days / 30.44


def rule_flags(items: list[dict], filed: date) -> list[dict]:
    """items: extracted evidence items with a 'verified' bool. Only verified items count."""
    v = [i for i in items if i["verified"]]
    flags = []
    imaging = sorted([d for i in v if i["category"] == "imaging" and (d := _d(i["date"]))], reverse=True)
    if not imaging:
        flags.append({"type": "no_recent_imaging", "explanation": "No imaging study is documented in the file.",
                      "suggested_action": "Request recent imaging reports from treating sources, or order imaging with a CE."})
    elif _months_between(imaging[0], filed) > config.IMAGING_RECENCY_MONTHS:
        flags.append({"type": "no_recent_imaging",
                      "explanation": f"Most recent imaging is dated {imaging[0].isoformat()}, more than "
                                     f"{config.IMAGING_RECENCY_MONTHS} months before the {filed.isoformat()} filing date.",
                      "suggested_action": "Request any newer imaging; if none exists, consider imaging with a consultative exam.",
                      "evidence_date": imaging[0].isoformat()})
    if not any(i["category"] == "treating_source_opinion" for i in v):
        flags.append({"type": "no_treating_source_opinion",
                      "explanation": "No medical source statement or functional opinion from a treating source is in the file.",
                      "suggested_action": "Request a medical source statement from the primary treating provider."})
    exams = sorted([d for i in v if i["includes_musculoskeletal_or_neuro_exam"] and (d := _d(i["date"]))], reverse=True)
    if not exams:
        flags.append({"type": "stale_records", "explanation": "No dated musculoskeletal or neurological examination is documented.",
                      "suggested_action": "Request current treatment records or schedule a consultative examination."})
    elif _months_between(exams[0], filed) > config.STALE_RECORD_MONTHS:
        flags.append({"type": "stale_records",
                      "explanation": f"Most recent documented musculoskeletal/neurological exam is {exams[0].isoformat()}, more than "
                                     f"{config.STALE_RECORD_MONTHS} months before filing.",
                      "suggested_action": "Request current treatment records; if none, schedule a consultative examination.",
                      "evidence_date": exams[0].isoformat()})
    return flags


def listing_gap_flags(db: Session, claim_id: int) -> list[dict]:
    from app.services.listing_match import latest_batch, listing_view
    view = listing_view(db, latest_batch(db, claim_id))
    if not view or not view["listings"]:
        return []
    top = view["listings"][0]
    missing = [r["criterion_id"] for r in top["criteria"]
               if r["level"] == "criterion" and r["status"] in ("insufficient_evidence", "unverified", "unsupported", "not_documented")]
    if not missing or top["overall"] == "criteria_not_met":
        return []
    return [{"type": "listing_criteria_undocumented",
             "explanation": f"Listing {top['listing_code']} criteria {', '.join(missing)} lack sufficient documented evidence.",
             "suggested_action": "Request records addressing these criteria or obtain a consultative examination.",
             "listing_code": top["listing_code"], "criteria": missing}]


def inventory_pages(db: Session, claim_id: int, provider: LLMProvider) -> tuple[list[Page], dict]:
    """Raw pages to inventory: everything for small files; for large files, every page tagged as
    imaging/opinion/CE/operative/pathology, the most recent exam pages (for staleness), and raw-chunk
    search hits for each evidence type. Never uses AI summaries."""
    in_scope = (db.query(Page).join(Document).filter(Document.claim_id == claim_id, Page.duplicate_of_page_id.is_(None),
                                                     Page.is_admin.isnot(True)).all())
    if len(in_scope) <= INVENTORY_ALL_PAGES_MAX:
        return sorted(in_scope, key=lambda p: (p.document_id, p.page_number)), {"mode": "all_pages", "pages": len(in_scope)}
    chosen = {(p.document_id, p.page_number): "tag" for p in in_scope if p.doc_type in KEY_DOC_TYPES}
    recent = sorted([p for p in in_scope if p.doc_type in EXAM_DOC_TYPES and p.service_date],
                    key=lambda p: p.service_date, reverse=True)[:12]
    for p in recent:
        chosen.setdefault((p.document_id, p.page_number), "recent_exam")
    for hits in records_index.search(db, claim_id, provider, INVENTORY_QUERIES, k=6):
        for h in hits:
            chosen.setdefault((h.document_id, h.page_number), "search")
    pages = claim_pages(db, claim_id)
    keys = list(chosen)[:INVENTORY_MAX_PAGES]
    out = sorted([pages[k] for k in keys if k in pages], key=lambda p: (p.document_id, p.page_number))
    from collections import Counter
    return out, {"mode": "retrieved", "pages": len(out), "by_reason": dict(Counter(chosen[k] for k in keys))}


def run_missing_evidence(db: Session, claim_id: int, provider: LLMProvider, progress=None) -> AIRun:
    from app.services.listing_match import render_evidence
    prog = progress or (lambda **kw: None)
    claim = db.get(Claim, claim_id)
    prompt = load_prompt("missing_evidence")
    prog(stage="retrieving")
    pages, inv_meta = inventory_pages(db, claim_id, provider)
    batches = [pages[i:i + INVENTORY_BATCH] for i in range(0, len(pages), INVENTORY_BATCH)] or [[]]
    prog(stage="extracting_evidence", batches_total=len(batches), batches_done=0, pages_in_scope=len(pages))
    done = {"n": 0}

    def call(batch):
        user = prompt.render_user(filed_date=claim.filed_date, alleged_onset=claim.alleged_onset_date,
                                  evidence=render_evidence(db, claim_id, batch))
        r = provider.complete_structured(prompt.system, user, Extraction)
        done["n"] += 1
        prog(batches_done=done["n"])
        return user, r

    results = pmap(call, batches)
    users = [u for u, _ in results]
    res = results[0][1]
    items_all = [it for _, r in results for it in r.parsed.evidence_items]
    gaps_all, per_type = [], {}
    for _, r in results:
        for g in r.parsed.gaps:
            if per_type.get(g.gap_type, 0) < 2:
                per_type[g.gap_type] = per_type.get(g.gap_type, 0) + 1
                gaps_all.append(g)
    for _, r in results[1:]:
        res.input_tokens += r.input_tokens
        res.output_tokens += r.output_tokens
    parsed = Extraction(evidence_items=items_all, gaps=gaps_all)
    run = record_ai_run(db, claim_id, "missing_evidence", prompt, res, "\n\n".join(users), parsed.model_dump())
    page_map = claim_pages(db, claim_id)
    all_c: list[Citation] = []
    items = []
    for i, it in enumerate(parsed.evidence_items):
        cs = verify_and_store(db, claim_id, run.id, f"item:{i}", it.description, it.citations, page_map)
        all_c += cs
        items.append({**it.model_dump(exclude={"citations"}), "verified": bool(cs) and all(c.verified for c in cs)})
    for i, g in enumerate(parsed.gaps):
        all_c += verify_and_store(db, claim_id, run.id, f"gap:{i}", g.explanation, g.citations, page_map)

    flags = [{**f, "source": "rule"} for f in rule_flags(items, claim.filed_date or date.today())]
    flags += [{**f, "source": "listing_match"} for f in listing_gap_flags(db, claim_id)]
    for i, g in enumerate(parsed.gaps):
        flags.append({"type": g.gap_type, "explanation": g.explanation, "suggested_action": g.suggested_action,
                      "provider_to_contact": g.provider_to_contact, "source": "ai", "gap_ref": f"gap:{i}"})
    run.output_json = {**run.output_json, "items_verified": items, "flags": flags, "inventory": inv_meta,
                       "thresholds": {"imaging_recency_months": config.IMAGING_RECENCY_MONTHS,
                                      "stale_record_months": config.STALE_RECORD_MONTHS}}
    log_ai_run_event(db, run, {**verification_stats(all_c), "flags": [f["type"] for f in flags], "inventory": inv_meta})

    if flags:
        prog(stage="drafting")
        lp = load_prompt("records_request")
        providers = sorted({it["source"] for it in items if it["category"] != "claimant_report"})
        luser = lp.render_user(claimant=claim.claimant_name, dob=claim.dob, claim_number=claim.claim_number,
                               providers="\n".join(f"- {p}" for p in providers) or "(none identified)",
                               flags="\n".join(f"- {f['explanation']} Suggested: {f['suggested_action']}" for f in flags))
        lres = provider.complete_structured(lp.system, luser, Letter)
        lrun = record_ai_run(db, claim_id, "records_request", lp, lres, luser, lres.parsed.model_dump())
        log_ai_run_event(db, lrun, {})
        text = f"To: {lres.parsed.recipient}\nRe: {lres.parsed.subject}\n\n{lres.parsed.body}"
        db.add(RecordsRequest(claim_id=claim_id, ai_run_id=lrun.id, draft_text=text))
    db.commit()
    return run


def missing_view(db: Session, run: AIRun) -> dict:
    from app.services.summary import run_meta
    labels = doc_labels(db, run.claim_id)
    cites = db.query(Citation).filter_by(ai_run_id=run.id).order_by(Citation.id).all()
    by = {}
    for c in cites:
        by.setdefault(c.item_ref, []).append(citation_dict(c, labels))
    flags = []
    for f in run.output_json.get("flags", []):
        flags.append({**f, "citations": by.get(f.get("gap_ref", ""), [])})
    items = []
    for i, it in enumerate(run.output_json.get("items_verified", [])):
        items.append({**it, "citations": by.get(f"item:{i}", [])})
    letter = (db.query(RecordsRequest).filter_by(claim_id=run.claim_id).order_by(RecordsRequest.id.desc()).first())
    return {"run": run_meta(run), "flags": flags, "evidence_items": items,
            "thresholds": run.output_json.get("thresholds"),
            "letter": {"id": letter.id, "draft_text": letter.draft_text, "edited_text": letter.edited_text,
                       "updated_at": letter.updated_at.isoformat() + "Z"} if letter else None,
            "verification": verification_stats(cites)}
