"""Map-reduce summary end to end with a fake provider: verified map items flow into the reduce step,
final citations point to original pages, unverified/unknown references never become facts."""
import json

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.llm.fake_provider import FakeProvider
from app.main import app
from app.services import summary as sm
from app.services.intake import load_synthetic_case


def _doc_page_with(db, claim_id, needle):
    for (doc_id, pg), p in sm.claim_pages(db, claim_id).items():
        if needle in p.text:
            return doc_id, pg
    raise AssertionError(needle)


def test_map_reduce_chronology_conflicts():
    db = SessionLocal()
    claim = load_synthetic_case(db, "case01_lumbar_radiculopathy", FakeProvider())
    walker = _doc_page_with(db, claim.id, "Prescribed a front-wheeled walker")
    mri = _doc_page_with(db, claim.id, "compression of the traversing left L5 nerve root")
    pt = _doc_page_with(db, claim.id, "Goals not met")

    def map_resp(system, user):
        out = {"bullets": [], "events": [], "statements": []}
        if f"[DOC {walker[0]} " in user and f"PAGE {walker[1]}" in user:
            q = {"doc_id": walker[0], "page": walker[1], "quote": "Prescribed a front-wheeled walker"}
            out["bullets"].append({"section": "treatment_history", "text": "Walker prescribed 11/18/2025.", "citations": [q]})
            out["bullets"].append({"section": "functional_limitations", "text": "Walks a mile.",  # fabricated
                                   "citations": [{**q, "quote": "Patient walks a mile daily without difficulty"}]})
            out["events"].append({"date": "2025-11-18", "event_type": "assistive_device", "description": "Front-wheeled walker prescribed", "citations": [q]})
            out["statements"].append({"topic": "walking_ability", "stance": "worsened", "date": "2025-11-18", "source": "ortho",
                                      "text": "Falls; walker needed", "citations": [q]})
        if f"[DOC {mri[0]} " in user and f"PAGE {mri[1]}" in user:
            q = {"doc_id": mri[0], "page": mri[1], "quote": "compression of the traversing left L5 nerve root"}
            out["bullets"].append({"section": "imaging", "text": "MRI 06/12/2026: L4-L5 extrusion compressing left L5 root.", "citations": [q]})
            out["events"].append({"date": "2026-06-12", "event_type": "imaging", "description": "MRI lumbar: L4-L5 extrusion", "citations": [q]})
        if f"[DOC {pt[0]} " in user and f"PAGE {pt[1]}" in user:
            q = {"doc_id": pt[0], "page": pt[1], "quote": "Goals not met"}
            out["statements"].append({"topic": "walking_ability", "stance": "not improved", "date": "2025-09-12", "source": "PT",
                                      "text": "PT goals not met", "citations": [q]})
        return json.dumps(out)

    def reduce_resp(system, user):
        ids = [ln.split("]")[0][1:] for ln in user.splitlines() if ln.startswith("[B")]
        bullets = [{"text": "Fact", "source_ids": ids}] if ids else []
        if "Treatment history" in user:
            bullets.append({"text": "Invented fact", "source_ids": ["B999.9"]})
        return json.dumps({"bullets": bullets})

    def conflict_resp(system, user):
        ids = [ln.split("]")[0][1:] for ln in user.splitlines() if ln.startswith("[S")]
        return json.dumps({"conflicts": [
            {"topic": "walking", "description": "PT vs ortho", "side_a": {"summary": "a", "statement_ids": ids[:1]},
             "side_b": {"summary": "b", "statement_ids": ids[1:2]}},
            {"topic": "bogus", "description": "unsupported", "side_a": {"summary": "a", "statement_ids": ["S0.0"]},
             "side_b": {"summary": "b", "statement_ids": ids[:1]}}]})

    fp = FakeProvider({"MapOut": map_resp, "ReduceOut": reduce_resp, "ConflictsOut": conflict_resp})
    seen = []
    run = sm.run_summary(db, claim.id, fp, progress=lambda **kw: seen.append(kw.get("stage")))
    assert {"mapping", "reducing", "chronology", "conflicts"} <= set(seen)
    assert all(c["model"] == "fake-fast" for c in fp.calls if c["schema"] == "MapOut")
    assert all(c["model"] == "fake-model" for c in fp.calls if c["schema"] != "MapOut")
    # The fabricated map bullet never reaches the reduce step.
    assert not any("Walks a mile" in c["user"] for c in fp.calls if c["schema"] == "ReduceOut")

    view = sm.summary_view(db, run)
    th = next(s for s in view["sections"] if s["key"] == "treatment_history")["bullets"]
    assert th[0]["verified"] and (th[0]["citations"][0]["doc_id"], th[0]["citations"][0]["page"]) == walker
    assert th[0]["citations"][0]["match_start"] is not None
    assert th[1]["verified"] is False  # reduce referenced an id that does not exist
    img = next(s for s in view["sections"] if s["key"] == "imaging")["bullets"]
    assert (img[0]["citations"][0]["doc_id"], img[0]["citations"][0]["page"]) == mri

    chron = sm.chronology_view(db, run)
    assert [e["date"] for e in chron["events"]] == ["2025-11-18", "2026-06-12"]
    assert chron["events"][0]["citations"][0]["page"] == walker[1]
    assert len(chron["conflicts"]) == 1  # the unsupported one is dropped
    cf = chron["conflicts"][0]
    assert cf["side_a"]["citations"] and cf["side_b"]["citations"]

    client = TestClient(app)
    assert client.get(f"/api/claims/{claim.id}/chronology").json()["events"]
    db.close()


def test_therapy_sessions_collapse_but_milestones_stay():
    c = [object()]
    ev = lambda d, t, desc: {"date": d, "event_type": t, "description": desc, "cites": c}  # noqa: E731
    events = [ev("2025-03-01", "therapy", "Physical therapy initial evaluation"),
              ev("2025-03-05", "therapy", "PT session, manual therapy"), ev("2025-03-08", "therapy", "PT session, exercises"),
              ev("2025-03-12", "therapy", "PT session, heat"), ev("2025-04-02", "imaging", "MRI lumbar"),
              ev("2025-06-10", "therapy", "PT progress report: 50% improved"), ev("2025-09-01", "therapy", "PT session")]
    out = sm.collapse_therapy(events)
    descs = [e["description"] for e in out]
    assert "Physical therapy initial evaluation" in descs and "PT progress report: 50% improved" in descs
    assert any(d.startswith("Therapy course 2025-03-05 to 2025-03-12: 3") for d in descs)
    assert len(out) == 5


def test_conflict_guardrails():
    st = lambda src, stance, types=None: {"source": src, "stance": stance, "doc_types": types}  # noqa: E731
    assert sm.conflict_is_valid([st("PT", "improved")], [st("ortho", "worsened")])[0]
    assert sm.conflict_is_valid([st("CE", "device not needed")], [st("treating source", "device needed")])[0]
    assert not sm.conflict_is_valid([st("PT", "device needed")], [st("ortho", "device needed")])[0]
    assert not sm.conflict_is_valid([st("Dr. Q", "improved", ["progress_note"])], [st("claimant", "worsened", ["function_report"])])[0]
    # A patient report documented in a clinician's note is medical evidence, not self-report.
    assert sm.conflict_is_valid([st("claimant", "improved", ["progress_note"])], [st("ortho", "worsened", ["progress_note"])])[0]
    assert sm.stance_polarity("not medically necessary") == 1 and sm.stance_polarity("normal exam") == 1
    assert sm.stance_polarity("abnormal exam") == -1 and sm.stance_polarity("requires walker") == -1
