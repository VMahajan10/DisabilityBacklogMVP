"""Run the full pipeline on every synthetic case and score it against expected.json.

Per case: ingestion (OCR, duplicates), map-reduce summary + chronology + conflicts, listing match,
missing evidence, triage. Reports key-evidence recall, citation verification, listing/triage accuracy,
duplicates and conflicts found vs planted, processing time, and approximate API cost.
Uses a throwaway SQLite DB. Calls the configured LLM provider.

Usage: make eval                         (all cases)
       make eval CASES=case07_medium_lumbar,case01_lumbar_radiculopathy
"""
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "eval.db")

from app.db import SessionLocal, init_db  # noqa: E402
from app.llm.registry import get_provider  # noqa: E402
from app.llm.usage import cost_of, track  # noqa: E402
from app.models import AIRun, Citation, Document, Page  # noqa: E402
from app.services import listing_match as lm  # noqa: E402
from app.services import missing_evidence as me  # noqa: E402
from app.services import summary as sm  # noqa: E402
from app.services import triage as tr  # noqa: E402
from app.services.intake import SYNTHETIC_DIR, create_synthetic_claim, ingest  # noqa: E402
from app.services.reference_data import ensure_reference_data  # noqa: E402

RESULTS = Path(__file__).parent / "results"
ORDER = {"criteria_appear_met": 0, "insufficient_evidence": 1, "criteria_not_met": 2}


def size_of(pages: int) -> str:
    return "small" if pages < 50 else "medium" if pages < 300 else "large" if pages < 1000 else "xl"


def listing_check(view: dict, exp: dict) -> tuple[bool, str]:
    listings = view["listings"]
    accepted = exp["listing_outcome"]
    if exp["listings"]:
        hit = [l for l in listings if l["listing_code"] in exp["listings"]]
        if not hit:
            return False, f"expected {exp['listings']} not assessed (got {[l['listing_code'] for l in listings]})"
        best = min(hit, key=lambda l: ORDER.get(l["overall"], 3))
        return best["overall"] in accepted, f"{best['listing_code']}={best['overall']}"
    top = listings[0]
    return top["overall"] in accepted, f"top {top['listing_code']}={top['overall']}"


def page_equivalents(db, claim_id) -> dict[tuple[int, int], set]:
    """(doc,page) -> set of (doc,page) that are the same record (itself + detected duplicates)."""
    pages = db.query(Page).join(Document).filter(Document.claim_id == claim_id).all()
    by_id = {p.id: (p.document_id, p.page_number) for p in pages}
    groups = defaultdict(set)
    for p in pages:
        root = by_id.get(p.duplicate_of_page_id, by_id[p.id])
        groups[root].add(by_id[p.id])
    out = {}
    for root, members in groups.items():
        members = members | {root}
        for m in members:
            out[m] = members
    return out


def conflicts_found(flagged, exp, docs, eq) -> int:
    n = 0
    for pc in exp.get("expected_conflicts", []):
        a0 = pc["pages"][0]
        anchor = eq.get((docs[a0["file"]], a0["page"]), {(docs[a0["file"]], a0["page"])})
        for cf in flagged:
            sa = {(c["doc_id"], c["page"]) for c in cf["side_a"]["citations"] if c["verified"]}
            sb = {(c["doc_id"], c["page"]) for c in cf["side_b"]["citations"] if c["verified"]}
            if (sa & anchor and sb) or (sb & anchor and sa):
                n += 1
                break
    return n


def main():
    init_db()
    db = SessionLocal()
    p = get_provider()
    ensure_reference_data(db, p)
    only = set(filter(None, os.getenv("CASES", "").split(",")))
    cases = [d for d in sorted(SYNTHETIC_DIR.glob("case*")) if (d / "case.json").exists() and (not only or d.name in only)]
    rows = []
    for d in cases:
        exp = json.loads((d / "expected.json").read_text())
        meta = json.loads((d / "case.json").read_text())
        n_pages = meta.get("total_pages") or sum(x["logical_pages"] for x in meta["documents"])
        stage_s, t_case = {}, time.monotonic()
        with track(None, "case") as t:
            claim = create_synthetic_claim(db, d.name)
            counters = {}
            for stage, fn in [
                ("ingest", lambda: counters.update(ingest(db, claim.id, lambda **kw: None, p))),
                ("summary", lambda: sm.run_summary(db, claim.id, p)),
                ("listing", lambda: lm.run_listing_match(db, claim.id, p)),
                ("missing", lambda: me.run_missing_evidence(db, claim.id, p)),
                ("triage", lambda: tr.run_triage(db, claim.id, p)),
            ]:
                t0 = time.monotonic()
                with track(claim.id, stage):
                    fn()
                stage_s[stage] = round(time.monotonic() - t0, 1)
        cost_by_stage = defaultdict(float)
        tokens_in = tokens_out = 0
        for r in t.records:
            cost_by_stage[r.stage] += cost_of(r.model, r.input_tokens, r.output_tokens)
            tokens_in += r.input_tokens
            tokens_out += r.output_tokens

        summ = db.query(AIRun).filter_by(claim_id=claim.id, kind="summary").order_by(AIRun.id.desc()).first()
        lruns = lm.latest_batch(db, claim.id)
        lview = lm.listing_view(db, lruns)
        me_run = db.query(AIRun).filter_by(claim_id=claim.id, kind="missing_evidence").order_by(AIRun.id.desc()).first()
        tr_run = db.query(AIRun).filter_by(claim_id=claim.id, kind="triage").order_by(AIRun.id.desc()).first()
        conf_run = db.get(AIRun, summ.output_json.get("conflicts_run_id")) if summ.output_json.get("conflicts_run_id") else None

        final_ids = {summ.id, me_run.id, tr_run.id, *[r.id for r in lruns]} | ({conf_run.id} if conf_run else set())
        final_cites = db.query(Citation).filter(Citation.ai_run_id.in_(final_ids)).all()
        map_ids = summ.output_json.get("map_run_ids", [])
        map_cites = db.query(Citation).filter(Citation.ai_run_id.in_(map_ids)).all()
        v_final = sum(c.verified for c in final_cites)

        # Key-evidence recall (large cases): a verified citation on the key page or a detected duplicate of it.
        docs = {x.filename: x.id for x in db.query(Document).filter_by(claim_id=claim.id)}
        eq = page_equivalents(db, claim.id)
        listing_ids = {r.id for r in lruns}

        def cited(run_filter):
            return {(c.document_id, c.page_number) for c in final_cites + map_cites
                    if c.verified and run_filter(c) and (c.ai_run_id not in listing_ids or c.relevant is not False)}

        any_cited = cited(lambda c: c.ai_run_id in final_ids)
        sum_cited = cited(lambda c: c.ai_run_id == summ.id)
        lst_cited = cited(lambda c: c.ai_run_id in listing_ids)
        keys = []
        for k in exp.get("key_evidence", []):
            dp = (docs[k["file"]], k["page"])
            same = eq.get(dp, {dp})
            keys.append({"id": k["id"], "page": k["global_page"], "scanned": k["scanned"],
                         "any": bool(same & any_cited), "summary": bool(same & sum_cited), "listing": bool(same & lst_cited)})

        # Duplicates found vs planted.
        dup_found = sum(1 for x in db.query(Page).join(Document).filter(Document.claim_id == claim.id) if x.duplicate_of_page_id)
        pairs_ok = 0
        for pair in exp.get("duplicate_pairs", []):
            cp = (docs[pair["copy"][0]], pair["copy"][1])
            op = (docs[pair["original"][0]], pair["original"][1])
            pairs_ok += int(op in eq.get(cp, set()))

        # Conflicts flagged vs planted. A planted conflict counts as found if a flagged conflict cites its
        # ANCHOR page (refs[0]: the "improved" note of a reversal, or the CE report) on one side, with
        # verified citations on the opposing side. The model may pick other pages for the opposing side.
        cview = sm.chronology_view(db, summ)
        flagged = cview["conflicts"]
        conf_found = conflicts_found(flagged, exp, docs, eq)

        l_ok, l_detail = listing_check(lview, exp)
        rule_flags = {f["type"] for f in me_run.output_json["flags"] if f["source"] == "rule"}
        queue = tr_run.output_json["suggested_queue"]
        cal = tr_run.output_json["cal_verified"]
        rows.append({
            "case": d.name, "size": size_of(n_pages), "pages": n_pages,
            "ocr_pages": counters.get("ocr_pages", 0), "scanned_planted": exp.get("scanned_pages", 0),
            "duplicates_found": dup_found, "duplicates_planted": exp.get("planted_duplicates", 0),
            "duplicate_pairs_matched": pairs_ok,
            "conflicts_flagged": len(flagged), "conflicts_planted": len(exp.get("expected_conflicts", [])), "conflicts_found": conf_found,
            "key_evidence": keys, "key_recall": f"{sum(k['any'] for k in keys)}/{len(keys)}" if keys else "n/a",
            "citations": len(final_cites), "verified": v_final, "verification_rate": round(v_final / max(1, len(final_cites)), 4),
            "map_citations": len(map_cites), "map_verified": sum(c.verified for c in map_cites),
            "listing_ok": l_ok, "listing_detail": l_detail, "expected_listing_outcome": exp["listing_outcome"],
            "listings_assessed": [{"code": l["listing_code"], "overall": l["overall"]} for l in lview["listings"]],
            "listing_evidence_pages": [r.output_json.get("evidence_pages", {}).get("pages") for r in lruns],
            "triage": queue, "expected_triage": exp["triage"], "triage_ok": queue == exp["triage"],
            "cal_ok": bool(cal) == exp["cal"], "cal_match": cal,
            "rule_flags": sorted(rule_flags), "expected_flags": exp["missing_flags"],
            "flags_ok": set(exp["missing_flags"]) <= rule_flags,
            "seconds": round(time.monotonic() - t_case, 1), "seconds_by_stage": stage_s,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": round(sum(cost_by_stage.values()), 4),
            "cost_by_stage": {k: round(v, 4) for k, v in cost_by_stage.items()},
        })
        r = rows[-1]
        keystr = " ".join(f"{k['id']}@p{k['page']}{'(scan)' if k['scanned'] else ''}={'HIT' if k['any'] else 'MISS'}" for k in keys)
        print(f"{d.name:32} {n_pages:>5}p  cites {r['verified']}/{r['citations']}  listing {'PASS' if l_ok else 'FAIL'} ({l_detail})  "
              f"triage {'PASS' if r['triage_ok'] else 'FAIL'} ({queue})  dup {dup_found}/{r['duplicates_planted']}  "
              f"conf {conf_found}/{r['conflicts_planted']} (flagged {len(flagged)})  {r['seconds']}s ${r['cost_usd']:.3f}  {keystr}",
              flush=True)

    print_table(rows)
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"), "provider": p.name, "model": p.model,
        "fast_model": p.fast_model, "embedding_model": p.embedding_model, "cases": len(rows),
        "citation_verification_rate": round(sum(r["verified"] for r in rows) / max(1, sum(r["citations"] for r in rows)), 4),
        "listing_accuracy": f"{sum(r['listing_ok'] for r in rows)}/{len(rows)}",
        "triage_accuracy": f"{sum(r['triage_ok'] for r in rows)}/{len(rows)}",
        "cal_accuracy": f"{sum(r['cal_ok'] for r in rows)}/{len(rows)}",
        "missing_flag_recall": f"{sum(r['flags_ok'] for r in rows)}/{len(rows)}",
        "key_evidence_recall": f"{sum(k['any'] for r in rows for k in r['key_evidence'])}/{sum(len(r['key_evidence']) for r in rows)}",
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 3),
    }
    print("\n" + "\n".join(f"{k:28} {v}" for k, v in summary.items()))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))
    print(f"\nWrote {out}")
    return 0 if all(r["listing_ok"] and r["triage_ok"] for r in rows) else 1


def print_table(rows):
    print("\n| Size | Case | Pages | Key-evidence recall | Citations verified | Listing | Triage | Duplicates found/planted | Conflicts found/planted (flagged) | OCR pages | Time | Cost |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (["small", "medium", "large", "xl"].index(r["size"]), r["case"])):
        print(f"| {r['size']} | {r['case']} | {r['pages']} | {r['key_recall']} | {r['verification_rate']:.1%} | "
              f"{'✅' if r['listing_ok'] else '❌'} {r['listing_detail']} | {'✅' if r['triage_ok'] else '❌'} {r['triage']} | "
              f"{r['duplicates_found']}/{r['duplicates_planted']} | {r['conflicts_found']}/{r['conflicts_planted']} ({r['conflicts_flagged']}) | "
              f"{r['ocr_pages']}/{r['scanned_planted']} | {r['seconds']:.0f}s | ${r['cost_usd']:.2f} |")


if __name__ == "__main__":
    sys.exit(main())
