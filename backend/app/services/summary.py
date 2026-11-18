"""Evidence summary at scale: MAP (per document batch, fast model) -> REDUCE (per section, main model).

- Map: each batch of pages yields cited bullets, dated events (for the chronology) and status
  statements (for conflict detection). Every quote is verified immediately against its page.
- Reduce: the main model merges VERIFIED map bullets per section. It may only reference map bullet
  ids, never write new quotes, so final citations always point to the original pages.
- Chronology: deterministic merge of verified events, sorted by date.
- Conflicts: the main model compares verified status statements and must cite both sides.
Duplicate and administrative pages are excluded from the map step (they remain searchable).
"""
import re
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config
from app.llm.base import LLMProvider, StructuredResult
from app.llm.usage import pmap
from app.models import AIRun, Citation, Claim, Document, Page
from app.prompts import load_prompt
from app.services.audit import log_ai_run_event, record_ai_run
from app.services.citations import CitationIn, citation_dict, doc_labels, verification_stats, verify_and_store
from app.services.context import claim_pages

SECTIONS = [
    ("diagnoses", "Diagnoses"),
    ("objective_findings", "Objective findings"),
    ("imaging", "Imaging"),
    ("treatment_history", "Treatment history"),
    ("functional_limitations", "Functional limitations"),
    ("treating_source_opinions", "Treating and medical source opinions"),
]
SectionKey = Literal["diagnoses", "objective_findings", "imaging", "treatment_history", "functional_limitations",
                     "treating_source_opinions"]
EventType = Literal["diagnosis", "imaging", "surgery", "procedure", "assistive_device", "emergency_visit",
                    "hospitalization", "medical_opinion", "therapy", "medication_change", "fall_or_injury", "other"]
Topic = Literal["walking_ability", "assistive_device", "pain_trend", "symptom_trend", "neurologic_findings",
                "work_or_functional_capacity", "other"]


# ----------------------------------------------------------------------------- schemas
class MapBullet(BaseModel):
    section: SectionKey
    text: str
    citations: list[CitationIn]


class MapEvent(BaseModel):
    date: str | None = Field(description="YYYY-MM-DD date of the event, or null")
    event_type: EventType
    description: str = Field(description="Short description, e.g. 'MRI lumbar spine: L4-L5 extrusion compressing L5 root'")
    citations: list[CitationIn]


class MapStatement(BaseModel):
    topic: Topic
    stance: str = Field(description="2-4 words, e.g. 'improved', 'worsened', 'device needed', 'device not needed', 'normal exam'")
    date: str | None = Field(description="YYYY-MM-DD or null")
    source: str = Field(description="Who said it: provider name/role, or 'claimant'")
    text: str
    citations: list[CitationIn]


class MapOut(BaseModel):
    bullets: list[MapBullet]
    events: list[MapEvent]
    statements: list[MapStatement]


class ReducedBullet(BaseModel):
    text: str
    source_ids: list[str] = Field(description="Ids of the evidence items that support this bullet, e.g. ['B12', 'B40']")


class ReduceOut(BaseModel):
    bullets: list[ReducedBullet]


class ConflictSide(BaseModel):
    summary: str
    statement_ids: list[str]


class ConflictOut(BaseModel):
    topic: str
    description: str = Field(description="One line naming who disagrees about what")
    side_a: ConflictSide
    side_b: ConflictSide


class ConflictsOut(BaseModel):
    conflicts: list[ConflictOut]


# ----------------------------------------------------------------------------- helpers
def _iso(s: str | None) -> date | None:
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s.strip())
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


def pages_in_scope(db: Session, claim_id: int) -> list[Page]:
    return (db.query(Page).join(Document).filter(Document.claim_id == claim_id, Page.duplicate_of_page_id.is_(None),
                                                 Page.is_admin.isnot(True))
            .order_by(Document.id, Page.page_number).all())


def make_batches(pages: list[Page]) -> list[list[Page]]:
    batches, cur, chars, cur_doc = [], [], 0, None
    for p in pages:
        if cur and (p.document_id != cur_doc or len(cur) >= config.MAP_BATCH_PAGES or chars + len(p.text) > config.MAP_BATCH_CHARS):
            batches.append(cur)
            cur, chars = [], 0
        cur.append(p)
        chars += len(p.text)
        cur_doc = p.document_id
    if cur:
        batches.append(cur)
    return batches


def render_pages(pages: list[Page], labels: dict[int, str]) -> str:
    out = []
    for p in pages:
        meta = " | ".join(x for x in [p.doc_type, p.service_date.isoformat() if p.service_date else None,
                                      "OCR" if p.ocr else None] if x)
        out.append(f'[DOC {p.document_id} "{labels.get(p.document_id, "")}" | PAGE {p.page_number}'
                   f'{" | " + meta if meta else ""}]\n{p.text}\n')
    return "\n".join(out)


def claim_header(db: Session, claim_id: int) -> str:
    c = db.get(Claim, claim_id)
    return (f"Claimant {c.claimant_name}, DOB {c.dob}, alleged onset {c.alleged_onset_date}, "
            f"application filed {c.filed_date}.")


# ----------------------------------------------------------------------------- map
def run_map(db: Session, claim_id: int, provider: LLMProvider, progress=None, model: str | None = None,
            kind: str = "summary_map") -> list[AIRun]:
    model = model or provider.fast_model
    prompt = load_prompt("map_summary")
    labels = doc_labels(db, claim_id)
    batches = make_batches(pages_in_scope(db, claim_id))
    head = claim_header(db, claim_id)
    if progress:
        progress(stage="mapping", batches_total=len(batches), batches_done=0,
                 pages_in_scope=sum(len(b) for b in batches))
    done = {"n": 0}

    def call(batch):
        user = prompt.render_user(claim=head, evidence=render_pages(batch, labels))
        res = provider.complete_structured(prompt.system, user, MapOut, model=model)
        done["n"] += 1
        if progress:
            progress(batches_done=done["n"])
        return user, res

    results = pmap(call, batches)
    pages = claim_pages(db, claim_id)
    runs = []
    for batch, (user, res) in zip(batches, results):
        out = res.parsed
        run = record_ai_run(db, claim_id, kind, prompt, res, user,
                            {**out.model_dump(), "pages": [[p.document_id, p.page_number] for p in batch]})
        cites = []
        for i, b in enumerate(out.bullets):
            cites += verify_and_store(db, claim_id, run.id, f"b:{i}", b.text, b.citations, pages)
        for i, e in enumerate(out.events):
            cites += verify_and_store(db, claim_id, run.id, f"e:{i}", e.description, e.citations, pages)
        for i, s in enumerate(out.statements):
            cites += verify_and_store(db, claim_id, run.id, f"s:{i}", s.text, s.citations, pages)
        run.output_json = {**run.output_json, "verification": verification_stats(cites)}
        runs.append(run)
    db.commit()
    return runs


def _verified_by_ref(db: Session, run_ids: list[int]) -> dict[tuple[int, str], list[Citation]]:
    out = defaultdict(list)
    for c in db.query(Citation).filter(Citation.ai_run_id.in_(run_ids), Citation.verified.is_(True)):
        out[(c.ai_run_id, c.item_ref)].append(c)
    return out


# ----------------------------------------------------------------------------- reduce + chronology + conflicts
def run_summary(db: Session, claim_id: int, provider: LLMProvider, progress=None) -> AIRun:
    prog = progress or (lambda **kw: None)
    map_runs = run_map(db, claim_id, provider, prog)
    vref = _verified_by_ref(db, [r.id for r in map_runs])
    page_map = claim_pages(db, claim_id)

    # Evidence items usable downstream = map items with at least one VERIFIED citation.
    bullets_by_section, events, statements = defaultdict(list), [], []
    for r in map_runs:
        o = r.output_json
        for i, b in enumerate(o["bullets"]):
            cs = vref.get((r.id, f"b:{i}"))
            if cs:
                bullets_by_section[b["section"]].append({"id": f"B{r.id}.{i}", "text": b["text"], "cites": cs})
        for i, e in enumerate(o["events"]):
            cs = vref.get((r.id, f"e:{i}"))
            if cs:
                events.append({**e, "cites": cs})
        for i, s in enumerate(o["statements"]):
            cs = vref.get((r.id, f"s:{i}"))
            if cs:
                statements.append({**s, "id": f"S{r.id}.{i}", "cites": cs,
                                   "doc_types": sorted({getattr(page_map.get((c.document_id, c.page_number)), "doc_type", None) or ""
                                                        for c in cs})})

    prog(stage="reducing", sections_total=len(SECTIONS))
    rprompt = load_prompt("reduce_summary")
    head = claim_header(db, claim_id)

    def reduce_section(sec):
        key, title = sec
        items = bullets_by_section.get(key, [])
        if not items:
            return key, None, None
        listing = "\n".join(f"[{b['id']}] ({_cite_hint(b['cites'])}) {b['text']}" for b in items)
        user = rprompt.render_user(claim=head, section=title, items=listing)
        return key, user, provider.complete_structured(rprompt.system, user, ReduceOut)

    reduced = pmap(reduce_section, SECTIONS)
    by_id = {b["id"]: b for items in bullets_by_section.values() for b in items}
    out_sections, total_res = {}, None
    for key, user, res in reduced:
        out_sections[key] = [{"text": b.text, "source_ids": b.source_ids} for b in res.parsed.bullets] if res else []
        if res:
            total_res = _merge_res(total_res, res)
    total_res = total_res or StructuredResult(ReduceOut(bullets=[]), "{}", provider.name, provider.model, 1, 0)

    prog(stage="chronology")
    chronology = build_chronology(events)
    prog(stage="conflicts", events=len(chronology))

    run = record_ai_run(db, claim_id, "summary", rprompt, total_res, head,
                        {**out_sections, "map_run_ids": [r.id for r in map_runs], "map_model": map_runs[0].model if map_runs else None,
                         "chronology": [{k: v for k, v in e.items() if k != "cites"} for e in chronology],
                         "stats": {"map_batches": len(map_runs), "pages_in_scope": sum(len(r.output_json["pages"]) for r in map_runs),
                                   "map_bullets_verified": len(by_id), "events": len(chronology), "statements": len(statements)}})
    all_c = []
    for key, _ in SECTIONS:
        for i, b in enumerate(out_sections.get(key, [])):
            all_c += _copy_cites(db, run, f"{key}:{i}", b["text"], [by_id.get(sid) for sid in b["source_ids"]])
    for i, e in enumerate(chronology):
        all_c += _copy_cites(db, run, f"event:{i}", e["description"], [{"cites": e["cites"]}])

    conflicts_run = run_conflicts(db, claim_id, provider, statements, head)
    run.output_json = {**run.output_json, "conflicts_run_id": conflicts_run.id if conflicts_run else None}
    log_ai_run_event(db, run, {**verification_stats(all_c), **run.output_json["stats"]})
    db.commit()
    prog(stage="done", force=True, conflicts=len(conflicts_run.output_json["conflicts"]) if conflicts_run else 0)
    return run


def _cite_hint(cites: list[Citation]) -> str:
    return ", ".join(sorted({f"doc {c.document_id} p.{c.page_number}" for c in cites}))


def _merge_res(a, b):
    if a is None:
        return b
    a.input_tokens += b.input_tokens
    a.output_tokens += b.output_tokens
    a.latency_ms = max(a.latency_ms, b.latency_ms)
    a.attempts = max(a.attempts, b.attempts)
    return a


def _copy_cites(db: Session, run: AIRun, ref: str, statement: str, sources: list[dict | None]) -> list[Citation]:
    """Final citations are copies of VERIFIED map citations (same doc/page/quote/offsets)."""
    out = []
    for src in sources:
        if src is None:
            c = Citation(ai_run_id=run.id, claim_id=run.claim_id, item_ref=ref, statement=statement, document_id=None,
                         page_number=None, quote="", verified=False, match_score=0,
                         failure_reason="reduce step referenced evidence that does not exist")
            db.add(c)
            out.append(c)
            continue
        for m in src["cites"]:
            c = Citation(ai_run_id=run.id, claim_id=run.claim_id, item_ref=ref, statement=statement,
                         document_id=m.document_id, page_number=m.page_number, quote=m.quote, verified=m.verified,
                         match_score=m.match_score, match_start=m.match_start, match_end=m.match_end)
            db.add(c)
            out.append(c)
    if not sources:
        c = Citation(ai_run_id=run.id, claim_id=run.claim_id, item_ref=ref, statement=statement, quote="",
                     verified=False, failure_reason="no supporting evidence referenced")
        db.add(c)
        out.append(c)
    db.flush()
    return out


def build_chronology(events: list[dict]) -> list[dict]:
    """Merge the same event reported in several places (same date + type + similar text)."""
    items = sorted(events, key=lambda e: (_iso(e["date"]) or date.max, e["event_type"]))
    merged: list[dict] = []
    for e in items:
        dup = next((m for m in merged[-12:] if m["date"] == e["date"] and m["event_type"] == e["event_type"]
                    and SequenceMatcher(None, m["description"].lower(), e["description"].lower()).ratio() > 0.55), None)
        if dup:
            seen = {(c.document_id, c.page_number) for c in dup["cites"]}
            dup["cites"] += [c for c in e["cites"] if (c.document_id, c.page_number) not in seen]
        else:
            merged.append({"date": e["date"], "event_type": e["event_type"], "description": e["description"],
                           "cites": list(e["cites"])})
    return collapse_therapy(merged)


_MILESTONE = re.compile(r"evaluat|progress|discharg|re-?eval|initiat|start|complet|plateau", re.I)


def collapse_therapy(events: list[dict], gap_days: int = 21) -> list[dict]:
    """Routine therapy sessions -> one 'course' entry per run of sessions; evaluations, progress
    reports and discharges stay as their own events."""
    out, run = [], []

    def flush():
        if not run:
            return
        if len(run) == 1:
            out.append(run[0])
        else:
            first, last = run[0], run[-1]
            out.append({"date": first["date"], "event_type": "therapy",
                        "description": f"Therapy course {first['date']} to {last['date']}: {len(run)} documented sessions",
                        "cites": first["cites"][:1] + last["cites"][:1]})
        run.clear()

    for e in events:
        routine = e["event_type"] == "therapy" and not _MILESTONE.search(e["description"]) and _iso(e["date"])
        if routine and run and (_iso(e["date"]) - _iso(run[-1]["date"])).days > gap_days:
            flush()
        if routine:
            run.append(e)
        else:
            flush()
            out.append(e)
    flush()
    return sorted(out, key=lambda e: (_iso(e["date"]) or date.max))


def run_conflicts(db: Session, claim_id: int, provider: LLMProvider, statements: list[dict], head: str) -> AIRun | None:
    prompt = load_prompt("conflicts")
    by_topic = defaultdict(list)
    for s in statements:
        by_topic[s["topic"]].append(s)
    listing = "\n\n".join(
        f"## {topic}\n" + "\n".join(f"[{s['id']}] {s['date'] or 'undated'} | {s['source']} | {s['stance']}: {s['text']}"
                                    for s in sorted(ss, key=lambda x: x["date"] or ""))
        for topic, ss in by_topic.items())
    user = prompt.render_user(claim=head, statements=listing or "(no statements)")
    res = provider.complete_structured(prompt.system, user, ConflictsOut)
    run = record_ai_run(db, claim_id, "conflicts", prompt, res, user, {"conflicts": [], "raw": res.parsed.model_dump()})
    sid = {s["id"]: s for s in statements}
    kept, cites_all, seen_sets, rejected = [], [], [], []
    for i, cf in enumerate(res.parsed.conflicts):
        a = [sid[x] for x in cf.side_a.statement_ids if x in sid]
        b = [sid[x] for x in cf.side_b.statement_ids if x in sid]
        if not a or not b:  # both sides must be backed by verified evidence
            continue
        ok, why = conflict_is_valid(a, b)
        if not ok:
            rejected.append({"description": cf.description, "reason": why})
            continue
        ids = {s["id"] for s in a + b}
        if any(ids <= prev or prev <= ids for prev in seen_sets):  # same disagreement reported twice
            continue
        seen_sets.append(ids)
        ca = _copy_cites(db, run, f"conflict:{len(kept)}:a", cf.side_a.summary, [{"cites": s["cites"]} for s in a])
        cb = _copy_cites(db, run, f"conflict:{len(kept)}:b", cf.side_b.summary, [{"cites": s["cites"]} for s in b])
        cites_all += ca + cb
        kept.append({"topic": cf.topic, "description": cf.description,
                     "side_a": {"summary": cf.side_a.summary, "statements": [_stmt(s) for s in a]},
                     "side_b": {"summary": cf.side_b.summary, "statements": [_stmt(s) for s in b]}})
    run.output_json = {"conflicts": kept, "dropped_unsupported": len(res.parsed.conflicts) - len(kept),
                       "rejected_by_rules": rejected,
                       "statements_considered": len(statements)}
    log_ai_run_event(db, run, {**verification_stats(cites_all), "conflicts": len(kept)})
    return run


_POS_NEG = re.compile(r"not (?:medically )?(?:needed|necessary|required)|no (?:assistive )?device|without (?:an? )?(?:assistive )?device|independent", re.I)
_NEG = re.compile(r"wors|declin|deteriorat|abnormal|weak|unsteady|limit|fall|need|requir|depend|unable|decreas|absent", re.I)
_POS = re.compile(r"improv|better|resolv|normal|intact|steady|stable|full|good", re.I)


def stance_polarity(stance: str) -> int:
    """+1 favorable (improved, normal, no device), -1 unfavorable (worse, abnormal, device needed), 0 unknown."""
    if _POS_NEG.search(stance):
        return 1
    if _NEG.search(stance):
        return -1
    if _POS.search(stance):
        return 1
    return 0


def _is_self_report(s: dict) -> bool:
    """Only statements cited solely from the claimant's own forms (function report) count as
    self-report. A patient report documented in a clinician's note is medical evidence."""
    types = s.get("doc_types")
    if types:
        return all(t == "function_report" for t in types)
    return bool(re.search(r"function report|self-report", s.get("source") or "", re.I))


def conflict_is_valid(a: list[dict], b: list[dict]) -> tuple[bool, str | None]:
    """Code-level guardrails on model-proposed conflicts."""
    if all(_is_self_report(s) for s in a) or all(_is_self_report(s) for s in b):
        return False, "one side is only the claimant's own function report"
    pa = {stance_polarity(s["stance"]) for s in a} - {0}
    pb = {stance_polarity(s["stance"]) for s in b} - {0}
    if pa and pb and not any(x == -y for x in pa for y in pb):
        return False, "both sides take the same position"
    return True, None


def _stmt(s: dict) -> dict:
    return {"date": s["date"], "source": s["source"], "stance": s["stance"], "text": s["text"]}


# ----------------------------------------------------------------------------- views
def summary_view(db: Session, run: AIRun) -> dict:
    labels = doc_labels(db, run.claim_id)
    by_ref = defaultdict(list)
    for c in db.query(Citation).filter(Citation.ai_run_id == run.id).order_by(Citation.id):
        by_ref[c.item_ref].append(c)
    sections, all_c = [], []
    for key, title in SECTIONS:
        bullets = []
        for i, b in enumerate(run.output_json.get(key, [])):
            cites = by_ref.get(f"{key}:{i}", [])
            all_c += cites
            bullets.append({"text": b["text"], "verified": bool(cites) and all(c.verified for c in cites),
                            "citations": [citation_dict(c, labels) for c in cites]})
        sections.append({"key": key, "title": title, "bullets": bullets})
    return {"run": run_meta(run), "sections": sections, "verification": verification_stats(all_c),
            "stats": run.output_json.get("stats"), "map_model": run.output_json.get("map_model")}


def chronology_view(db: Session, run: AIRun) -> dict:
    labels = doc_labels(db, run.claim_id)
    by_ref = defaultdict(list)
    for c in db.query(Citation).filter(Citation.ai_run_id == run.id, Citation.item_ref.like("event:%")):
        by_ref[c.item_ref].append(c)
    events = [{**e, "citations": [citation_dict(c, labels) for c in by_ref.get(f"event:{i}", [])]}
              for i, e in enumerate(run.output_json.get("chronology", []))]
    conflicts = []
    cid = run.output_json.get("conflicts_run_id")
    if cid:
        crun = db.get(AIRun, cid)
        cref = defaultdict(list)
        for c in db.query(Citation).filter(Citation.ai_run_id == cid):
            cref[c.item_ref].append(c)
        for i, cf in enumerate(crun.output_json.get("conflicts", [])):
            conflicts.append({**cf,
                              "side_a": {**cf["side_a"], "citations": [citation_dict(c, labels) for c in cref.get(f"conflict:{i}:a", [])]},
                              "side_b": {**cf["side_b"], "citations": [citation_dict(c, labels) for c in cref.get(f"conflict:{i}:b", [])]}})
    return {"run": run_meta(run), "events": events, "conflicts": conflicts}


def run_meta(run: AIRun) -> dict:
    return {"id": run.id, "kind": run.kind, "provider": run.provider, "model": run.model,
            "prompt": f"{run.prompt_name}/{run.prompt_version}", "created_at": run.created_at.isoformat() + "Z",
            "attempts": run.attempts, "latency_ms": run.latency_ms}
