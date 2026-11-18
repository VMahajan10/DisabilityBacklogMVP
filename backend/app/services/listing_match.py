"""RAG listing match: retrieve candidate 1.00 listings, assess each criterion with citations,
verify every quote against the page, then check each verified quote's RELEVANCE to its claim.

Guardrails:
- Listing text comes only from SSA's Blue Book page (verbatim chunks).
- A Met / Not met call is shown only if at least one citation is verified AND judged relevant.
- "Not documented" calls carry no quotes (the model may not quote text to prove an absence).
- The listing-level result is computed by rules from the lettered criteria and the listing's
  own AND/OR wording ("documented by A, B, C, and D"), not taken from the model.
"""
import uuid
from typing import Literal

import numpy as np

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config
from app.llm.base import LLMProvider
from app.llm.usage import pmap
from app.models import AIRun, Citation, Document, ListingChunk, Page
from app.prompts import load_prompt
from app.services import bluebook
from app.services.audit import log_ai_run_event, record_ai_run
from app.services.citations import CitationIn, citation_dict, doc_labels, verification_stats, verify_and_store
from app.services import records_index
from app.services.context import claim_pages, evidence_context
from app.services.reference_data import ensure_reference_data
from app.services.vectorstore import top_k

TOP_LISTINGS = 3
MAX_REF_CHARS = 2500
RELEVANCE_CONTEXT_CHARS = 350

Status = Literal["met", "not_met", "insufficient_evidence", "not_documented"]


class CriterionAssessment(BaseModel):
    criterion_id: str = Field(description="Criterion id exactly as given, e.g. 1.15B2")
    status: Status
    rationale: str = Field(description="One or two plain sentences explaining the status")
    citations: list[CitationIn] = Field(
        description="Verbatim record quotes supporting the status. MUST be empty for not_documented.")


class ListingAssessment(BaseModel):
    listing_code: str
    overall: Literal["criteria_appear_met", "criteria_not_met", "insufficient_evidence"]
    overall_rationale: str
    criteria: list[CriterionAssessment]


class RelevanceJudgment(BaseModel):
    citation_id: int
    supports: bool = Field(description="True only if the quote, in context, directly supports the stated assessment")
    reason: str = Field(description="One short sentence")


class RelevanceResult(BaseModel):
    judgments: list[RelevanceJudgment]


# ----------------------------------------------------------------------------- retrieval
def retrieval_query(db: Session, claim_id: int) -> str:
    """Use the verified parts of the latest evidence summary as the retrieval query."""
    run = db.query(AIRun).filter_by(claim_id=claim_id, kind="summary").order_by(AIRun.id.desc()).first()
    if not run:
        return evidence_context(db, claim_id)[:6000]
    verified_refs = {c.item_ref for c in db.query(Citation).filter_by(ai_run_id=run.id, verified=True)}
    parts = []
    for key in ("diagnoses", "imaging", "objective_findings", "treating_source_opinions"):
        for i, b in enumerate(run.output_json.get(key, [])):
            if f"{key}:{i}" in verified_refs:
                parts.append(b["text"])
    return "\n".join(parts)[:6000] or evidence_context(db, claim_id)[:6000]


def retrieve_listings(db: Session, provider: LLMProvider, query: str, k: int = TOP_LISTINGS,
                      claim_id: int | None = None) -> list[dict]:
    """Rank pilot listings for assessment (see comment below for how the two signals combine).
    raw: listing descriptors vs the claimant's own page chunks (mean of top-5 chunk similarities).
    summ: verified summary text vs listing chunks."""
    chunks = db.query(ListingChunk).filter(ListingChunk.listing_code.in_(bluebook.PILOT_LISTINGS),
                                           ListingChunk.embedding.isnot(None)).all()
    raw: dict[str, tuple[float, str]] = {}
    if claim_id is not None:
        codes, vecs = listing_descriptors(db, provider)
        sims = records_index.similarity_matrix(db, claim_id, vecs)
        if sims is not None and sims.shape[1]:
            top = np.sort(sims, axis=1)[:, -min(5, sims.shape[1]):].mean(axis=1)
            raw = {code: (float(sc), code) for code, sc in zip(codes, top)}
    summ: dict[str, tuple[float, str]] = {}
    if query:
        qv = provider.embed([query])[0]
        for c, s in top_k(qv, [(c, c.embedding) for c in chunks], k=len(chunks)):
            if c.listing_code not in summ or s > summ[c.listing_code][0]:
                summ[c.listing_code] = (s, c.criterion_id)
    # Selection uses both signals: top-k from the verified summary (most reliable in testing) plus the
    # best raw-records listing as a safety net if the summary missed something. The EVIDENCE each
    # listing is assessed on always comes from raw page retrieval (listing_evidence_pages).
    primary = summ or raw
    ranked = [code for code, _ in sorted(primary.items(), key=lambda kv: kv[1][0], reverse=True)][:k]
    if raw and summ:
        best_raw = max(raw.items(), key=lambda kv: kv[1][0])[0]
        if best_raw not in ranked:
            ranked.append(best_raw)
    return [{"listing_code": code, "score": round((summ.get(code) or raw.get(code))[0], 4),
             "raw_score": round(raw[code][0], 4) if code in raw else None,
             "summary_score": round(summ[code][0], 4) if code in summ else None,
             "source": "summary" if code in ranked[:k] and summ else "raw_records",
             "best_chunk": (summ.get(code) or raw.get(code))[1]} for code in ranked]


_descriptor_cache: dict[str, tuple[list[str], list[list[float]]]] = {}


def listing_descriptors(db: Session, provider: LLMProvider) -> tuple[list[str], list[list[float]]]:
    """One retrieval descriptor per pilot listing: its name plus the criteria wording UNIQUE to that
    listing (verbatim SSA text). Shared language (the 12-month limitation, assistive-device clauses)
    appears in most listings and would match every case equally, so it is left out."""
    key = provider.embedding_model
    if key in _descriptor_cache:
        return _descriptor_cache[key]
    rows = db.query(ListingChunk).filter(ListingChunk.listing_code.in_(bluebook.PILOT_LISTINGS)).order_by(ListingChunk.seq).all()
    seen: dict[str, set] = {}
    for r in rows:
        if r.level in ("criterion", "subcriterion"):
            seen.setdefault(bluebook.criterion_body(r.heading).lower(), set()).add(r.listing_code)
    codes, texts = [], []
    for code in bluebook.PILOT_LISTINGS:
        head = next((r for r in rows if r.listing_code == code and r.level == "listing"), None)
        if not head:
            continue
        parts = [bluebook.listing_name(head.heading)]
        parts += [bluebook.criterion_body(r.heading) for r in rows if r.listing_code == code
                  and r.level in ("criterion", "subcriterion") and len(seen[bluebook.criterion_body(r.heading).lower()]) == 1
                  and "physical limitation of musculoskeletal functioning" not in r.heading]
        codes.append(code)
        texts.append(". ".join(parts))
    _descriptor_cache[key] = (codes, provider.embed(texts))
    return _descriptor_cache[key]


def listing_evidence_pages(db: Session, claim_id: int, code: str) -> tuple[list[Page], dict]:
    """Raw-page retrieval for one listing: each criterion pulls its own top pages from the claimant's
    page chunks (never from AI summaries). Small files simply include every in-scope page."""
    in_scope = (db.query(Page).join(Document).filter(Document.claim_id == claim_id, Page.duplicate_of_page_id.is_(None),
                                                     Page.is_admin.isnot(True)).all())
    if len(in_scope) <= config.LISTING_MAX_PAGES:
        return sorted(in_scope, key=lambda p: (p.document_id, p.page_number)), {"mode": "all_pages", "pages": len(in_scope)}
    crit = (db.query(ListingChunk).filter(ListingChunk.listing_code == code, ListingChunk.embedding.isnot(None),
                                          ListingChunk.level.in_(["listing", "criterion", "subcriterion"])).all())
    hits = records_index.search_vectors(db, claim_id, [c.embedding for c in crit], k=config.LISTING_PAGES_PER_CRITERION)
    best: dict[tuple[int, int], float] = {}
    per_crit = {}
    for c, hs in zip(crit, hits):
        per_crit[c.criterion_id] = [[h.document_id, h.page_number, round(h.score, 3)] for h in hs]
        for h in hs:
            key = (h.document_id, h.page_number)
            best[key] = max(best.get(key, -1), h.score)
    chosen = sorted(best, key=lambda k: -best[k])[:config.LISTING_MAX_PAGES]
    pages = claim_pages(db, claim_id)
    out = sorted([pages[k] for k in chosen if k in pages], key=lambda p: (p.document_id, p.page_number))
    return out, {"mode": "retrieved", "pages": len(out), "per_criterion": per_crit}


def render_evidence(db: Session, claim_id: int, pages: list[Page]) -> str:
    from app.services.summary import claim_header, render_pages
    labels = {d.id: d.doc_label for d in db.query(Document).filter_by(claim_id=claim_id)}
    return claim_header(db, claim_id) + "\n\n" + render_pages(pages, labels)


# ----------------------------------------------------------------------------- listing bundle
def listing_bundle(db: Session, code: str) -> dict:
    rows = db.query(ListingChunk).filter_by(listing_code=code).order_by(ListingChunk.seq).all()
    head = next(r for r in rows if r.level == "listing")
    by_id = {r.criterion_id: r for r in rows}
    logic, required = bluebook.listing_logic(head.heading)
    criteria = []
    for r in rows:
        if r.level not in ("criterion", "subcriterion"):
            continue
        chain, p = [], r.parent_id
        while p and p in by_id and by_id[p].level != "listing":
            chain.insert(0, {"criterion_id": p, "text": by_id[p].heading})
            p = by_id[p].parent_id
        criteria.append({"criterion_id": r.criterion_id, "parent_id": r.parent_id, "level": r.level,
                         "text": r.heading, "label": bluebook.display_label(r.criterion_id, r.heading),
                         "body": bluebook.criterion_body(r.heading), "context": chain})
    refs = []
    for ref_id in bluebook.referenced_sections(head.text):
        r = db.query(ListingChunk).filter_by(criterion_id=ref_id).first()
        if r:
            t = r.text if len(r.text) <= MAX_REF_CHARS else r.text[:MAX_REF_CHARS] + " [... truncated; see source]"
            refs.append({"criterion_id": r.criterion_id, "text": t})
    return {"code": code, "title": head.heading, "name": bluebook.listing_name(head.heading), "text": head.text,
            "source_url": head.source_url, "fetched_at": head.fetched_at, "logic": logic, "required": required,
            "criteria": criteria, "references": refs}


def render_criteria(bundle: dict) -> str:
    """One line per criterion. Sub-criteria carry their parent criteria's full text so they are
    judged in context (e.g. 1.16B1 'Muscle weakness' is part of NONradicular signs under 1.16B)."""
    lines = []
    for c in bundle["criteria"]:
        line = f"- {c['criterion_id']}: {c['text']}"
        if c["context"]:
            ctx = " > ".join(f"{p['criterion_id']} \"{p['text']}\"" for p in c["context"])
            line += f"\n    CONTEXT (judge this sub-criterion only as part of): {ctx}"
        lines.append(line)
    return "\n".join(lines)


def _criterion_context_text(c: dict) -> str:
    parts = [f"{p['criterion_id']}: {p['text']}" for p in c["context"]] + [f"{c['criterion_id']}: {c['text']}"]
    return " > ".join(parts)


# ----------------------------------------------------------------------------- run
def run_listing_match(db: Session, claim_id: int, provider: LLMProvider, progress=None) -> list[AIRun]:
    prog = progress or (lambda **kw: None)
    ensure_reference_data(db, provider)
    prompt = load_prompt("listing_match")
    prog(stage="retrieving")
    query = retrieval_query(db, claim_id)
    candidates = retrieve_listings(db, provider, query, claim_id=claim_id)
    batch = uuid.uuid4().hex[:12]
    jobs = []
    for cand in candidates:
        b = listing_bundle(db, cand["listing_code"])
        ev_pages, ev_meta = listing_evidence_pages(db, claim_id, b["code"])
        refs = "\n\n".join(f"[{r['criterion_id']}]\n{r['text']}" for r in b["references"]) or "(none)"
        user = prompt.render_user(listing_code=b["code"], listing_text=b["text"], criteria_list=render_criteria(b),
                                  references=refs, source_url=b["source_url"], evidence=render_evidence(db, claim_id, ev_pages))
        jobs.append((cand, b, user, ev_meta))
    prog(stage="assessing", listings_total=len(jobs), listings_done=0)
    done = {"n": 0}

    def assess(j):
        r = provider.complete_structured(prompt.system, j[2], ListingAssessment)
        done["n"] += 1
        prog(listings_done=done["n"])
        return r

    results = pmap(assess, jobs)

    pages = claim_pages(db, claim_id)
    runs, relevance_jobs = [], []
    for (cand, b, user, ev_meta), res in zip(jobs, results):
        valid = {c["criterion_id"]: c for c in b["criteria"]}
        stripped = []
        for ca in res.parsed.criteria:
            if ca.status == "not_documented" and ca.citations:  # never quote to "prove" an absence
                stripped.append(ca.criterion_id)
                ca.citations = []
        out = res.parsed.model_dump()
        out.update({"batch_id": batch, "retrieval": cand, "retrieval_query": query[:2000], "evidence_pages": ev_meta,
                    "listing_title": b["title"], "listing_name": b["name"], "listing_text": b["text"],
                    "source_url": b["source_url"], "listing_fetched_at": b["fetched_at"], "logic": b["logic"],
                    "required": b["required"], "criteria_defs": b["criteria"],
                    "citations_stripped_from_not_documented": stripped})
        run = record_ai_run(db, claim_id, "listing_match", prompt, res, user, out)
        cites = []
        for ca in res.parsed.criteria:
            if ca.criterion_id in valid:
                cs = verify_and_store(db, claim_id, run.id, ca.criterion_id, ca.rationale, ca.citations, pages)
                cites += cs
                for c in cs:
                    if c.verified:
                        relevance_jobs.append((run, c, valid[ca.criterion_id], ca))
        runs.append((run, cites, b))

    prog(stage="relevance")
    _run_relevance(db, claim_id, provider, relevance_jobs, pages)

    for run, cites, b in runs:
        stats = verification_stats(cites)
        stats["relevant"] = sum(1 for c in cites if c.verified and c.relevant)
        stats["not_relevant"] = sum(1 for c in cites if c.verified and c.relevant is False)
        log_ai_run_event(db, run, {**stats, "listing": b["code"], "ai_overall": run.output_json["overall"],
                                   "evidence_pages": run.output_json["evidence_pages"]["pages"]})
    db.commit()
    return [r for r, _, _ in runs]


def _run_relevance(db: Session, claim_id: int, provider: LLMProvider, jobs: list, pages: dict) -> None:
    """Second-stage check: one LLM call per listing judging every verified citation's relevance."""
    if not jobs:
        return
    prompt = load_prompt("citation_relevance")
    by_run: dict[int, list] = {}
    for job in jobs:
        by_run.setdefault(job[0].id, []).append(job)

    def render(items):
        blocks = []
        for run, c, crit, ca in items:
            page = pages.get((c.document_id, c.page_number))
            s, e = c.match_start or 0, c.match_end or 0
            ctx = page.text[max(0, s - RELEVANCE_CONTEXT_CHARS): e + RELEVANCE_CONTEXT_CHARS] if page else ""
            blocks.append(
                f"### citation_id {c.id}\nCRITERION (with parent context): {_criterion_context_text(crit)}\n"
                f"ASSESSMENT: {ca.status}\nRATIONALE: {ca.rationale}\nQUOTE: \"{c.quote}\"\n"
                f"SURROUNDING PAGE TEXT: ...{ctx}...")
        return "\n\n".join(blocks)

    groups = list(by_run.values())
    users = [prompt.render_user(listing_code=g[0][0].output_json["listing_code"], items=render(g)) for g in groups]
    results = pmap(lambda u: provider.complete_structured(prompt.system, u, RelevanceResult), users)
    for g, user, res in zip(groups, users, results):
        judged = {j.citation_id: j for j in res.parsed.judgments}
        for _, c, _, _ in g:
            j = judged.get(c.id)
            c.relevant = j.supports if j else False
            c.relevance_reason = j.reason if j else "Relevance was not assessed; treated as not supporting."
        rrun = record_ai_run(db, claim_id, "citation_relevance", prompt, res, user,
                             {**res.parsed.model_dump(), "for_listing_run": g[0][0].id})
        log_ai_run_event(db, rrun, {"checked": len(g), "relevant": sum(1 for _, c, _, _ in g if c.relevant),
                                    "for_listing_run": g[0][0].id})
    db.flush()


# ----------------------------------------------------------------------------- view logic
def effective_status(ai_status: str, cites: list[Citation]) -> tuple[str, str | None]:
    """Never present a Met / Not met call as fact unless a verified AND relevant citation supports it."""
    if ai_status not in ("met", "not_met"):
        return ai_status, None
    if any(c.verified and c.relevant is not False for c in cites):
        return ai_status, None
    if any(c.verified for c in cites):
        return "unsupported", "The quoted evidence exists but does not clearly support this call; treat as insufficient evidence."
    return "unverified", "No verified citation supports this call; treat as insufficient evidence."


def compute_overall(logic: str, required: list[str], code: str, letter_status: dict[str, str]) -> tuple[str, str | None]:
    """Listing result from lettered criteria + the listing's own AND/OR wording.
    Returns (overall, gate_criterion_id) where gate is the first required criterion that is Not met."""
    ids = [f"{code}{L}" for L in required] or list(letter_status)
    st = [letter_status.get(i, "not_assessed") for i in ids]
    if logic == "any":
        if any(s == "met" for s in st):
            return "criteria_appear_met", None
        if st and all(s == "not_met" for s in st):
            return "criteria_not_met", None
        return "insufficient_evidence", None
    for i, s in zip(ids, st):
        if s == "not_met":
            return "criteria_not_met", i
    if st and all(s == "met" for s in st):
        return "criteria_appear_met", None
    return "insufficient_evidence", None


ORDER = {"criteria_appear_met": 0, "insufficient_evidence": 1, "criteria_not_met": 2}


def listing_view(db: Session, runs: list[AIRun]) -> dict | None:
    if not runs:
        return None
    labels = doc_labels(db, runs[0].claim_id)
    listings, all_c = [], []
    for run in runs:
        o = run.output_json
        cites = db.query(Citation).filter_by(ai_run_id=run.id).order_by(Citation.id).all()
        all_c += cites
        by_crit: dict[str, list[Citation]] = {}
        for c in cites:
            by_crit.setdefault(c.item_ref, []).append(c)
        assessed = {a["criterion_id"]: a for a in o["criteria"]}
        rows, letter_status = [], {}
        for d in o["criteria_defs"]:
            a = assessed.get(d["criterion_id"])
            cc = by_crit.get(d["criterion_id"], [])
            if a:
                status, note = effective_status(a["status"], cc)
            else:
                status, note = "not_assessed", "The AI did not assess this criterion."
            if d["level"] == "criterion":
                letter_status[d["criterion_id"]] = status
            rows.append({"criterion_id": d["criterion_id"], "level": d["level"], "parent_id": d["parent_id"],
                         "criterion_text": d["text"], "body": d.get("body") or bluebook.criterion_body(d["text"]),
                         "ai_status": a["status"] if a else None, "status": status, "note": note,
                         "rationale": a["rationale"] if a else "", "citations": [citation_dict(c, labels) for c in cc]})
        logic = o.get("logic") or bluebook.listing_logic(o["listing_title"])[0]
        required = o.get("required") or bluebook.listing_logic(o["listing_title"])[1]
        overall, gate = compute_overall(logic, required, o["listing_code"], letter_status)
        gate_row = next((r for r in rows if r["criterion_id"] == gate), None)
        listings.append({
            "run_id": run.id, "listing_code": o["listing_code"], "title": o["listing_title"],
            "name": o.get("listing_name") or bluebook.listing_name(o["listing_title"]),
            "listing_text": o["listing_text"], "source_url": o["source_url"], "fetched_at": o["listing_fetched_at"],
            "retrieval_score": o["retrieval"]["score"], "logic": logic, "required": required,
            "ai_overall": o["overall"], "overall": overall, "overall_adjusted": overall != o["overall"],
            "overall_rationale": o["overall_rationale"],
            "gate": {"criterion_id": gate, "body": gate_row["body"], "rationale": gate_row["rationale"]} if gate_row else None,
            "criteria": rows,
        })
    listings.sort(key=lambda x: (ORDER.get(x["overall"], 3), -x["retrieval_score"]))
    met = [l for l in listings if l["overall"] == "criteria_appear_met"]
    from app.services.summary import run_meta
    stats = verification_stats(all_c)
    stats["relevant"] = sum(1 for c in all_c if c.verified and c.relevant)
    stats["not_relevant"] = sum(1 for c in all_c if c.verified and c.relevant is False)
    return {"run": run_meta(runs[0]), "batch_id": runs[0].output_json["batch_id"], "listings": listings,
            "banner": {"any_met": bool(met), "met": [{"code": l["listing_code"], "name": l["name"]} for l in met],
                       "others": [l["listing_code"] for l in listings if l not in met]},
            "verification": stats}


def latest_batch(db: Session, claim_id: int) -> list[AIRun]:
    last = db.query(AIRun).filter_by(claim_id=claim_id, kind="listing_match").order_by(AIRun.id.desc()).first()
    if not last:
        return []
    bid = last.output_json["batch_id"]
    runs = db.query(AIRun).filter_by(claim_id=claim_id, kind="listing_match").order_by(AIRun.id).all()
    return [r for r in runs if r.output_json.get("batch_id") == bid]
