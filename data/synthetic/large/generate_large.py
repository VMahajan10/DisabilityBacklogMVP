"""Generate the large synthetic claim files (~150 / ~500 / ~1,500 pages).

Usage (from repo root): backend/.venv/bin/python data/synthetic/large/generate_large.py [case_id ...]
Clinical note bodies are written once by the fast LLM model and cached in large/cache/<case>.json, so
re-running is free and deterministic. Routine/admin pages come from templates. KEY evidence and CONFLICT
pages are hand-written (see large_cases.py) so the eval knows exactly where they are.
"""
import hashlib
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(HERE.parent), str(ROOT / "backend")]

import templates as T  # noqa: E402
from cases_def import function_report_pages, imaging, visit  # noqa: E402
from large_cases import LARGE_CASES  # noqa: E402
from pdfkit import build_pdf  # noqa: E402
from pydantic import BaseModel  # noqa: E402

OUT = HERE.parent / "cases"
CACHE = HERE / "cache"

FOCUS = {
    "pcp": "Primary care follow-up mainly about chronic conditions (blood pressure, labs, refills, preventive care). Mention the musculoskeletal problem briefly only if active in the storyline, deferring to the specialist.",
    "ortho": "Orthopedic specialist follow-up for the musculoskeletal problem in the storyline, with a focused exam.",
    "er": "Emergency or urgent care visit: either an acute flare or fall related to the storyline, or an unrelated minor complaint (viral illness, minor laceration, chest wall strain).",
    "pain": "Interventional pain management clinic visit or procedure note (epidural steroid injection, medication management).",
    "neuro": "Neurology consultation or follow-up for leg symptoms, including a focused neurologic exam.",
    "pt": "Physical therapy evaluation or re-evaluation with objective measures and goals.",
}


class NoteOut(BaseModel):
    chief_complaint: str
    subjective: str
    objective: str
    assessment: str
    plan: str


def phase_at(spec, dt):
    for a, b, text in spec["storyline"]:
        if a <= dt <= b:
            return text
    return spec["storyline"][-1][2]


def rand_date(rng, a, b):
    return a + timedelta(days=rng.randint(0, max(0, (b - a).days)))


def every(a, b, step_days, rng):
    out, x = [], a + timedelta(days=rng.randint(0, step_days // 2))
    while x <= b:
        out.append(x)
        x += timedelta(days=step_days + rng.randint(-10, 10))
    return out


# ----------------------------------------------------------------------------- build item list
def build_items(spec, rng):
    """Items: dict(provider, date, kind, blocks|llm, ref, clinical)."""
    P, (a, b) = spec["providers"], spec["span"]
    items, llm_jobs = [], []
    onset = date.fromisoformat(spec["claimant"]["alleged_onset_date"])

    def llm_item(prov, dt, visit_type):
        jid = f"{prov}-{dt.isoformat()}-{visit_type}"
        llm_jobs.append({"id": jid, "provider": prov, "date": dt, "visit_type": visit_type})
        items.append({"provider": prov, "date": dt, "kind": "llm", "llm_id": jid, "clinical": True})

    cad = spec["cadence"]
    for dt in every(a, b, cad["pcp"], rng):
        llm_item("pcp", dt, rng.choice(["Office Visit", "Chronic Care Follow-up", "Annual Wellness Visit", "Medication Follow-up"]))
    for prov in ("ortho", "pain", "neuro"):
        if prov in cad and prov in P:
            start = onset - timedelta(days=30) if prov == "ortho" else onset + timedelta(days=40)
            for dt in every(max(a, start), b, cad[prov], rng):
                llm_item(prov, dt, {"ortho": "Spine Follow-up" if "Spine" in P[prov]["facility"] else "Orthopedic Follow-up",
                                    "pain": rng.choice(["Pain Management Follow-up", "Procedure Note - Epidural Steroid Injection"]),
                                    "neuro": "Neurology Follow-up"}[prov])
    for key, n in (("er", cad.get("er_visits", 0)), ("uc", cad.get("uc_visits", 0))):
        for _ in range(n):
            llm_item(key, rand_date(rng, a, b), "Emergency Department Visit" if key == "er" else "Urgent Care Visit")
    for i, (start, nvis) in enumerate(cad.get("pt_episodes", [])):
        llm_item("pt", start, "Physical Therapy Initial Evaluation")
        for v in range(1, nvis):
            dt = start + timedelta(days=3 * v + rng.randint(0, 1))
            items.append({"provider": "pt", "date": dt, "kind": "fixed", "clinical": False,
                          "blocks": T.pt_daily(rng, P["pt"]["clinician"], dt, v + 1,
                                               rng.choice(["Tolerated session with moderate pain.", "Symptoms unchanged after session.",
                                                           "Mild improvement in mobility after treatment.", "Fatigued by end of session."]))})
        llm_item("pt", start + timedelta(days=3 * nvis + 2), "Physical Therapy Discharge Summary")
    # routine imaging (not decisive)
    early = a + timedelta(days=rng.randint(60, 200))
    items.append({"provider": "img", "date": early, "kind": "fixed", "clinical": True,
                  "blocks": imaging(T.fmt(early), "XR Chest, 2 views", "Cough", "PA and lateral views.",
                                    "Lungs clear. Heart size normal. No effusion.", "No acute cardiopulmonary process.",
                                    spec["providers"]["img"]["clinician"])})
    # hand-written key + conflict pages
    for ref, (prov, dt, blocks) in {**spec["key"], **spec["conflict"]}.items():
        items.append({"provider": prov, "date": dt, "kind": "fixed", "blocks": blocks, "ref": ref, "clinical": True})
    return items, llm_jobs


def write_llm_notes(spec, jobs):
    """Write note bodies with the fast model, cached by job id + inputs."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{spec['case_id']}.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    from app.llm.registry import get_provider
    from app.llm.usage import pmap, track
    from app.prompts import load_prompt
    prompt = load_prompt("synthetic_note")
    todo = []
    for j in jobs:
        prov = spec["providers"][j["provider"]]
        kind = prov["kind"] if prov["kind"] in FOCUS else "er"
        inputs = dict(provider=f"{prov.get('clinician', '')} at {prov['facility']}", visit_type=j["visit_type"],
                      date=T.fmt(j["date"]), focus=FOCUS[kind], phase=phase_at(spec, j["date"]))
        j["key"] = j["id"] + ":" + hashlib.sha1(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:10]
        j["inputs"] = inputs
        if j["key"] not in cache:
            todo.append(j)
    if todo:
        provider = get_provider()
        print(f"  writing {len(todo)} notes with {provider.fast_model} ...", flush=True)
        with track(None, "synthetic_generation") as t:
            res = pmap(lambda j: provider.complete_structured(prompt.system, prompt.render_user(**j["inputs"]), NoteOut,
                                                             model=provider.fast_model).parsed.model_dump(), todo)
        for j, r in zip(todo, res):
            cache[j["key"]] = r
        path.write_text(json.dumps(cache, indent=1))
        print(f"  note generation cost ~${t.cost():.3f}", flush=True)
    return {j["id"]: cache[j["key"]] for j in jobs}


def admin_pad(spec, rng, prov, dt):
    P = spec["providers"]
    p = P[prov]
    kind = p["kind"]
    if kind == "pharmacy":
        meds = [m for m in T.MEDS if rng.random() < 0.6] or T.MEDS[:3]
        return T.pharmacy_fills(rng, p["facility"], dt, 6, meds), "pharmacy"
    choices = {"pcp": ["vitals", "billing", "reminder", "medlist", "lab", "vitals", "billing"],
               "pt": ["ptdaily", "ptdaily", "billing", "reminder"]}.get(kind, ["billing", "reminder", "billing"])
    c = rng.choice(choices)
    if c == "vitals":
        return T.vitals_visit(rng, p["clinician"], p.get("nurse", "Clinic RN"), dt,
                              rng.choice(["Blood pressure check", "Vaccination", "Medication refill check", "Weight check"])), c
    if c == "billing":
        return T.billing(rng, p["facility"], dt, kind), c
    if c == "reminder":
        return T.reminder(rng, p.get("clinician", p["facility"]), dt), c
    if c == "medlist":
        return T.medication_list(rng, p["facility"], dt), c
    if c == "lab":
        return T.lab(rng, p["clinician"], dt), c
    return T.pt_daily(rng, p["clinician"], dt, rng.randint(2, 20), "Tolerated session; home program reviewed."), c


def note_blocks(spec, it, notes):
    p = spec["providers"][it["provider"]]
    n = notes[it["llm_id"]]
    vt = it["llm_id"].split("-", 4)[-1]
    return visit(T.fmt(it["date"]), p.get("clinician", p["facility"]), vt, n["chief_complaint"], n["subjective"],
                 n["objective"], n["assessment"], n["plan"])


# ----------------------------------------------------------------------------- assemble
def generate(spec_fn):
    spec = spec_fn()
    rng = random.Random(spec["seed"])
    P, (a, b) = spec["providers"], spec["span"]
    print(f"{spec['case_id']}: building", flush=True)
    items, jobs = build_items(spec, rng)
    notes = write_llm_notes(spec, jobs)
    for it in items:
        if it["kind"] == "llm":
            it["blocks"] = note_blocks(spec, it, notes)

    order = spec["doc_order"]
    prov_keys = [k for k in order if k in P]
    cover_pages = 3 * len(prov_keys)  # fax cover + certification + privacy notice per provider
    claimant_pages = 2
    fax = spec["fax_copies"]
    n_fax = fax["n"] + len(fax["include"]) + 1  # +1 fax cover
    pad = spec["target_pages"] - len(items) - cover_pages - claimant_pages - n_fax
    weights = spec["padding_weights"]
    pool = [k for k in prov_keys for _ in range(weights.get(k, 1))]
    for _ in range(max(0, pad)):
        prov = rng.choice(pool)
        dt = rand_date(rng, a, b)
        blocks, kind = admin_pad(spec, rng, prov, dt)
        items.append({"provider": prov, "date": dt, "kind": "pad", "blocks": blocks, "clinical": kind in ("vitals", "lab", "ptdaily")})

    # Per-provider documents, pages in date order, preceded by records-production cover pages.
    docs = []
    for k in prov_keys:
        p = P[k]
        its = sorted([i for i in items if i["provider"] == k], key=lambda i: i["date"])
        if not its:
            continue
        first, last = its[0]["date"], its[-1]["date"]
        prod = b + timedelta(days=rng.randint(20, 40))
        pages = [{"blocks": T.fax_cover(rng, p["facility"], prod, len(its) + 3)},
                 {"blocks": T.records_certification(p["facility"], prod, len(its) + 3)},
                 {"blocks": T.privacy_notice(p["facility"])}] + [{"blocks": i["blocks"], "ref": i.get("ref"), "item": i} for i in its]
        title = f"Records - {p['facility'].replace(' (fictional)', '')} ({first.year}-{last.year})"
        docs.append({"key": k, "title": title, "facility": p["facility"], "address": p["address"], "pages": pages})

    # Duplicate set: the same records re-sent by fax from another source.
    candidates = [(di, pi) for di, dd in enumerate(docs) if dd["key"] in fax["from_providers"]
                  for pi, pg in enumerate(dd["pages"]) if pg.get("item", {}).get("clinical") and not pg.get("ref")]
    picks = rng.sample(candidates, min(fax["n"], len(candidates)))
    for ref in fax["include"]:
        picks += [(di, pi) for di, dd in enumerate(docs) for pi, pg in enumerate(dd["pages"]) if pg.get("ref") == ref]
    picks.sort(key=lambda x: (docs[x[0]]["pages"][x[1]]["item"]["date"]))
    prod = b + timedelta(days=45)
    fax_pages = [{"blocks": T.fax_cover(rng, fax["sender"], prod, len(picks) + 1)}]
    for n, (di, pi) in enumerate(picks, start=2):
        src = docs[di]["pages"][pi]
        fax_pages.append({"blocks": T.fax_banner_page(src["blocks"], fax["sender"], prod, n, len(picks) + 1),
                          "dup_of": (di, pi), "ref": (src.get("ref") + "_faxcopy") if src.get("ref") else None})
    fax_doc = {"key": "fax", "title": f"Records received by fax from {fax['sender'].replace(' (fictional)', '')} (re-sent set)",
               "facility": "State DDS Records Intake (fictional)", "address": "Records received by fax", "pages": fax_pages}
    claimant_doc = {"key": "claimant", "title": "Function Report - Adult (claimant)",
                    "facility": "Claimant-completed form (fictional facsimile)", "address": "",
                    "pages": [{"blocks": bl} for bl in function_report_pages(spec["claimant"]["name"], T.fmt(b), [
                        ("How do your conditions limit your ability to work?", "I cannot stand or walk for long and I have fallen several times."),
                        ("Describe your day.", "I rest most of the day and my family helps with shopping and chores.")],
                        [("Do you use any of the following?", "See my doctors' records."),
                         ("How far can you walk?", "Not far without stopping.")])]}
    # order documents
    by_key = {dd["key"]: dd for dd in docs}
    final = [by_key[k] if k in by_key else (fax_doc if k == "fax" else claimant_doc) for k in order
             if k in by_key or k in ("fax", "claimant")]

    # Global numbering, scanned pages, files.
    total = sum(len(dd["pages"]) for dd in final)
    all_refs = [(dd, i) for dd in final for i in range(len(dd["pages"]))]
    force = set(spec["force_scan"])
    scan_global = set(rng.sample(range(total), int(total * spec["scan_fraction"])))
    out_dir = OUT / spec["case_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.pdf"):
        old.unlink()
    meta_docs, key_pages, gidx = [], {}, 0
    page_loc = {}  # (id(doc), index) -> (file, page)
    for n, dd in enumerate(final, start=1):
        fname = f"{n:02d}_{dd['key']}.pdf"
        scans = set()
        for i, pg in enumerate(dd["pages"]):
            g = gidx + i
            ref = pg.get("ref")
            is_key = bool(ref) and (ref in spec["key"] or ref in spec["conflict"])
            if (g in scan_global and not is_key) or (ref in force):
                scans.add(i + 1)
            page_loc[(id(dd), i)] = (fname, i + 1)
            if ref:
                key_pages[ref] = {"file": fname, "page": i + 1, "global_page": g + 1, "scanned": (i + 1) in scans}
        header = {"facility": dd["facility"], "address": dd["address"], "patient": spec["claimant"]["name"],
                  "dob": T.fmt(date.fromisoformat(spec["claimant"]["dob"])), "mrn": "SYN-" + spec["claimant"]["claim_number"][-6:],
                  "doc_title": dd["title"]}
        build_pdf(str(out_dir / fname), header, [pg["blocks"] for pg in dd["pages"]], scan_pages=scans)
        meta_docs.append({"file": fname, "title": dd["title"], "logical_pages": len(dd["pages"]), "scanned_pages": sorted(scans)})
        gidx += len(dd["pages"])
        print(f"  {fname}: {len(dd['pages'])} pages ({len(scans)} scanned)", flush=True)

    dup_pairs = []
    for i, pg in enumerate(fax_doc["pages"]):
        if "dup_of" in pg:
            di, pi = pg["dup_of"]
            dup_pairs.append({"copy": page_loc[(id(fax_doc), i)], "original": page_loc[(id(docs[di]), pi)]})
    descr = {"K1_mri": "MRI report with nerve root compression", "K1_xray": "Weight-bearing X-ray with severe joint space loss",
             "K2_walker": "Treating note prescribing walker with documented medical need", "K2_canes": "Treating note prescribing bilateral canes",
             "K3_mss": "Treating source statement on walker need and function", "K3_ce": "Consultative exam: device not necessary"}
    expected = {**spec["expected"],
                "total_pages": total,
                "key_evidence": [{"id": k, "description": descr.get(k, k), **key_pages[k]} for k in spec["key"]],
                "conflict_pages": {k: key_pages[k] for k in spec["conflict"]},
                "planted_duplicates": len(dup_pairs), "duplicate_pairs": dup_pairs,
                "scanned_pages": sum(len(m["scanned_pages"]) for m in meta_docs)}
    for c in expected["expected_conflicts"]:
        c["pages"] = [key_pages[r] for r in c["refs"]]
    (out_dir / "expected.json").write_text(json.dumps(expected, indent=2, default=str))
    (out_dir / "case.json").write_text(json.dumps({"case_id": spec["case_id"], "title": spec["title"], "claimant": spec["claimant"],
                                                   "documents": meta_docs, "total_pages": total, "size": "large"}, indent=2))
    print(f"  total {total} pages; keys: " + ", ".join(f"{k}@{v['global_page']}{'(scan)' if v['scanned'] else ''}"
                                                     for k, v in key_pages.items()), flush=True)


if __name__ == "__main__":
    wanted = set(sys.argv[1:])
    for fn in LARGE_CASES:
        if not wanted or fn().get("case_id") in wanted:
            generate(fn)
