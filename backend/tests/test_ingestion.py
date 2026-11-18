"""Scale-pipeline ingestion: OCR, duplicate detection, tagging, chunking, record search."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data/synthetic"))

from app.services import dedupe, tagging  # noqa: E402
from app.services.records_index import chunk_page_text  # noqa: E402

NOTE = """Riverbend Orthopedic & Spine Associates (fictional) Patient: Test Claimant
100 Example Way DOB: 01/01/1970 MRN: SYN-1
Follow-up - 11/18/2025
Date of service 11/18/2025
Provider Priya N. Adebayo, MD (Orthopedic Spine)
Gait slow and unsteady; left foot slap noted. Positive straight leg raise on the left at 30 degrees supine and
seated. Decreased sensation in left L5 distribution. Left EHL 4-/5, left ankle dorsiflexion 4-/5. Unable to heel
walk on the left. Prescribed a front-wheeled walker; patient requires a walker for all ambulation outside the home.
SYNTHETIC TEST DATA - fictional record, not a real patient Progress Notes | Page 2 of 4"""


def sig(pid, order, text):
    return dedupe.build_sig(pid, order, text)


def test_exact_duplicate_ignores_footer_and_header():
    copy = NOTE.replace("Page 2 of 4", "Page 7 of 30").replace("Patient: Test Claimant", "Patient: Test Claimant ")
    d = dedupe.find_duplicates([sig(1, (1, 2), NOTE), sig(2, (5, 7), copy)])
    assert d == {2: (1, "exact", 1.0)}


LONG = NOTE + """
Subjective: Completed 10 sessions of physical therapy without lasting benefit. Epidural steroid injection at L4-L5 on
09/22/2025 gave about 2 weeks of partial relief. Reports two falls at home in October when the left leg gave way. Now
unable to walk more than half a block. Using a borrowed cane, which has not prevented falls. Sleeps poorly because of
pain, rated 8 out of 10, worse with sitting and standing. Uses ice and heat with little relief. Denies bowel or bladder
changes. Has not returned to work since the injury and requires help from family for shopping and yard work.
Assessment: Left L5 radiculopathy with progressive motor deficit and falls. Single cane inadequate for safe gait.
Plan: Continue gabapentin, increase to 300 mg three times daily. Order lumbar MRI. Surgical consultation discussed."""


def test_near_duplicate_faxed_copy():
    # Re-sent by fax: fax banner line + one OCR-style character difference.
    faxed = "FAX RECEIVED 03/14/2026 10:42 FROM: Riverbend Ortho P. 3/12\n" + LONG.replace("falls at home", "falis at home")
    d = dedupe.find_duplicates([sig(1, (1, 2), LONG), sig(2, (5, 3), faxed)])
    assert 2 in d and d[2][0] == 1 and d[2][1] == "near" and d[2][2] >= 0.9


def test_different_visit_same_template_not_duplicate():
    other = LONG.replace("11/18/2025", "03/24/2026")
    assert dedupe.find_duplicates([sig(1, (1, 2), LONG), sig(2, (1, 3), other)]) == {}


def test_same_template_different_dates_not_duplicate():
    rem = ("Harbor Clinic (fictional) Patient: Test Claimant\nAppointment Reminder\nThis is a reminder of your upcoming "
           "appointment on {d} at 9:30 AM with the orthopedic clinic. Please arrive 15 minutes early, bring your "
           "insurance card, a photo ID, and a list of current medications. Call the clinic at least 24 hours in "
           "advance to cancel or reschedule. Thank you for choosing our clinic for your care.")
    d = dedupe.find_duplicates([sig(1, (1, 1), rem.format(d="03/02/2026")), sig(2, (1, 2), rem.format(d="04/06/2026"))])
    assert d == {}


def test_earlier_page_is_the_original():
    d = dedupe.find_duplicates([sig(9, (3, 1), NOTE), sig(4, (1, 5), NOTE)])
    assert d == {9: (4, "exact", 1.0)}


def test_rule_tagging():
    t = tagging.rule_tag(NOTE)
    assert t["doc_type"] == "progress_note"
    assert t["provider"] == "Riverbend Orthopedic & Spine Associates (fictional)"
    assert t["service_date"].isoformat() == "2025-11-18"
    assert tagging.rule_tag("FAX COVER SHEET\nTo: DDS\nPages: 12")["doc_type"] == "fax_cover"
    narrative_mentions_pt = NOTE.replace("Follow-up - 11/18/2025", "Follow-up - 11/18/2025\nCompleted 10 sessions of physical therapy")
    assert tagging.rule_tag(narrative_mentions_pt)["doc_type"] == "progress_note"
    assert tagging.rule_tag("Midtown Rehab (fictional) Patient: X\nPhysical Therapy Initial Evaluation - 07/08/2025")["doc_type"] == "physical_therapy"
    assert tagging.rule_tag("Statement of Account\nAmount Due $45.00")["doc_type"] == "billing"
    assert "fax_cover" in tagging.ADMIN_TYPES and "imaging" not in tagging.ADMIN_TYPES


def test_chunks_stay_within_page_and_overlap():
    text = " ".join(f"word{i}" for i in range(800))
    chunks = chunk_page_text(text)
    assert len(chunks) > 1 and all(len(c) <= 1200 for c in chunks)
    assert chunks[0].split()[-1] in chunks[1]  # overlap
    assert chunk_page_text("") == [] and chunk_page_text("short") == ["short"]


@pytest.fixture(scope="module")
def scanned_pdf(tmp_path_factory):
    from cases_def import CASES
    from pdfkit import build_pdf
    d = CASES[0]["documents"][0]
    p = tmp_path_factory.mktemp("scan") / "scan.pdf"
    build_pdf(str(p), {"facility": d["facility"], "address": d["address"], "patient": "Test Claimant",
                       "dob": "01/01/1970", "mrn": "SYN-1", "doc_title": d["title"]}, d["pages"], scan_pages={2})
    return p


def test_scanned_page_has_no_text_layer_and_ocr_recovers_it(scanned_pdf):
    import pdfplumber
    from app.services.extraction import _is_body_char
    from app.services.ocr import ocr_page
    from app.services.verifier import verify_quote
    with pdfplumber.open(scanned_pdf) as pdf:
        assert len(pdf.pages) == 4
        assert (pdf.pages[1].filter(_is_body_char).extract_text() or "").strip() == ""
        assert len(pdf.pages[0].filter(_is_body_char).extract_text() or "") > 500
        text, conf = ocr_page(pdf.pages[1])
    assert conf > 50
    assert verify_quote(text, "Prescribed a front-wheeled walker").verified


def test_full_ingest_with_ocr_dupes_and_search(scanned_pdf, tmp_path):
    import shutil
    from app.db import SessionLocal, init_db
    from app.llm.fake_provider import FakeProvider
    from app.models import Claim, Page
    from app.services import records_index
    from app.services.intake import ingest, store_document
    init_db()
    db = SessionLocal()
    claim = Claim(claim_number="T-INGEST-1", claimant_name="Test Claimant")
    db.add(claim)
    db.flush()
    copy = tmp_path / "copy.pdf"
    shutil.copy(scanned_pdf, copy)
    store_document(db, claim, scanned_pdf, "a.pdf", "Notes A")
    store_document(db, claim, copy, "b.pdf", "Notes B (resent)")
    db.commit()
    seen = []
    c = ingest(db, claim.id, lambda **kw: seen.append(kw.get("stage")), FakeProvider())
    assert c["pages_extracted"] == 8 and c["ocr_pages"] == 2
    assert c["duplicates"] >= 3  # the 3 text pages of the resent copy (OCR'd page may differ slightly)
    assert {"extracting", "ocr", "deduplicating", "tagging", "embedding", "done"} <= set(seen)
    pages = db.query(Page).all()
    assert all(p.doc_type for p in pages)
    hits = records_index.search(db, claim.id, FakeProvider(), ["front-wheeled walker prescribed falls"], k=3)[0]
    assert hits and all(not db.query(Page).filter_by(document_id=h.document_id, page_number=h.page_number)
                        .first().duplicate_of_page_id for h in hits)
