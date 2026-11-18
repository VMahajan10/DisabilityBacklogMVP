"""Generate synthetic claim files: PDFs + case.json (claimant metadata) + expected.json.

Usage: python data/synthetic/generate.py   (run from repo root with the backend venv)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases_def import CASES  # noqa: E402
from pdfkit import build_pdf  # noqa: E402


def main():
    out_root = HERE / "cases"
    for case in CASES:
        d = out_root / case["case_id"]
        d.mkdir(parents=True, exist_ok=True)
        docs = []
        for doc in case["documents"]:
            header = {"facility": doc["facility"], "address": doc["address"], "patient": case["claimant"]["name"],
                      "dob": "{1}/{2}/{0}".format(*case["claimant"]["dob"].split("-")),
                      "mrn": "SYN-" + case["claimant"]["claim_number"][-6:], "doc_title": doc["title"]}
            n = build_pdf(str(d / doc["file"]), header, doc["pages"])
            docs.append({"file": doc["file"], "title": doc["title"], "logical_pages": n})
        (d / "case.json").write_text(json.dumps(
            {"case_id": case["case_id"], "title": case["title"], "claimant": case["claimant"], "documents": docs}, indent=2))
        (d / "expected.json").write_text(json.dumps(case["expected"], indent=2))
        print(f"{case['case_id']}: {len(docs)} docs, {sum(x['logical_pages'] for x in docs)} pages")


if __name__ == "__main__":
    main()
