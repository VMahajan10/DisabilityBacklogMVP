"""One-time comparison: map summaries with the fast model vs the main model on one case.

Reports key-evidence recall (did a VERIFIED map citation land on each known key page), citation
verification rate, items extracted, time, and approximate cost. Uses a throwaway DB.
Usage: make compare-map   (default case07_medium_lumbar)
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "compare.db")

from app import config  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.llm.registry import get_provider  # noqa: E402
from app.llm.usage import track  # noqa: E402
from app.models import Citation, Document  # noqa: E402
from app.services.intake import SYNTHETIC_DIR, load_synthetic_case  # noqa: E402
from app.services.summary import run_map  # noqa: E402


def key_recall(db, claim_id, run_ids, keys):
    docs = {d.filename: d.id for d in db.query(Document).filter_by(claim_id=claim_id)}
    cited = {(c.document_id, c.page_number) for c in db.query(Citation)
             .filter(Citation.ai_run_id.in_(run_ids), Citation.verified.is_(True))}
    hits = {k["id"]: (docs[k["file"]], k["page"]) in cited for k in keys}
    return hits


def main(case_id="case07_medium_lumbar"):
    init_db()
    db = SessionLocal()
    p = get_provider()
    exp = json.loads((SYNTHETIC_DIR / case_id / "expected.json").read_text())
    t0 = time.monotonic()
    with track(None, "ingest") as t_ing:
        claim = load_synthetic_case(db, case_id, p)
    print(f"Ingested {case_id}: {exp['total_pages']} pages in {time.monotonic() - t0:.1f}s (~${t_ing.cost():.4f})")
    rows = []
    for model in (config.OPENAI_FAST_MODEL, config.OPENAI_MODEL):
        t0 = time.monotonic()
        with track(claim.id, f"map:{model}") as t:
            runs = run_map(db, claim.id, p, model=model, kind=f"map_compare")
        ids = [r.id for r in runs]
        cites = db.query(Citation).filter(Citation.ai_run_id.in_(ids)).all()
        v = sum(c.verified for c in cites)
        hits = key_recall(db, claim.id, ids, exp["key_evidence"])
        n_items = sum(len(r.output_json["bullets"]) + len(r.output_json["events"]) + len(r.output_json["statements"]) for r in runs)
        rows.append({"model": model, "batches": len(runs), "items": n_items, "citations": len(cites), "verified": v,
                     "verification_rate": round(v / max(1, len(cites)), 3),
                     "key_recall": f"{sum(hits.values())}/{len(hits)}", "key_hits": hits,
                     "input_tokens": sum(r.input_tokens for r in t.records), "output_tokens": sum(r.output_tokens for r in t.records),
                     "cost_usd": round(t.cost(), 4), "seconds": round(time.monotonic() - t0, 1)})
    print(f"\n{'model':16} {'key recall':>10} {'verified':>14} {'items':>6} {'tokens in/out':>16} {'cost':>8} {'time':>7}")
    for r in rows:
        print(f"{r['model']:16} {r['key_recall']:>10} {r['verified']:>5}/{r['citations']:<4} ({r['verification_rate']:.0%}) "
              f"{r['items']:>6} {r['input_tokens']:>8}/{r['output_tokens']:<7} ${r['cost_usd']:>7.4f} {r['seconds']:>6}s")
        print(f"{'':16} keys: " + ", ".join(f"{k}={'HIT' if h else 'MISS'}" for k, h in r["key_hits"].items()))
    out = Path(__file__).parent / "results" / f"map_compare_{case_id}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"case": case_id, "rows": rows}, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
