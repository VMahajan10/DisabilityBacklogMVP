from pathlib import Path

import pytest

from app.services import bluebook
from app.services.bluebook import parse_bluebook, referenced_sections
from app.services.cal import parse_cal


@pytest.fixture(scope="module")
def html():
    if not bluebook.HTML_PATH.exists():
        pytest.skip("Blue Book HTML not saved in data/bluebook/")
    return bluebook.HTML_PATH.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def chunks(html):
    return {c.criterion_id: c for c in parse_bluebook(html)}


def test_one_chunk_per_pilot_listing(chunks):
    listings = [c for c in chunks.values() if c.level == "listing"]
    assert [c.criterion_id for c in listings] == bluebook.PILOT_LISTINGS


def test_every_ssa_anchor_becomes_a_chunk(html, chunks):
    import re
    ids = set(re.findall(r'id="(1_(?:00|1[5-9]|2[0-3])[A-Za-z0-9]*)"', html))
    assert {i.replace("_", ".", 1) for i in ids} <= {k.split("#")[0] for k in chunks}


def test_hierarchy(chunks):
    assert chunks["1.15B3a"].parent_id == "1.15B3"
    assert chunks["1.15B3"].parent_id == "1.15B"
    assert chunks["1.15B"].parent_id == "1.15"
    assert chunks["1.15"].parent_id is None
    assert chunks["1.00C6ei"].parent_id == "1.00C6e"
    assert chunks["1.18D1"].level == "subcriterion" and chunks["1.18D"].level == "criterion"
    assert set(chunks["1.18"].children) == {"1.18A", "1.18B", "1.18C", "1.18D"}


def test_text_is_verbatim_from_page(html, chunks):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for cid in ["1.15A", "1.17C", "1.22A", "1.00C6a"]:
        el = soup.find(id=cid.replace(".", "_", 1))
        assert chunks[cid].heading == bluebook.clean(el.get_text(""))


def test_listing_text_keeps_and_or_structure(chunks):
    t = chunks["1.17"].text.split("\n")
    assert t[0].startswith("1.17 Reconstructive surgery")
    assert t[1].startswith("A.") and t[2] == "AND" and t[3].startswith("B.") and t[4] == "AND"
    assert "OR" in chunks["1.20"].text.split("\n")


def test_criterion_text_includes_subcriteria_only(chunks):
    t = chunks["1.15B"].text
    assert "1. Muscle weakness" in t and "a. Decreased sensation" in t
    assert "Findings on imaging" not in t  # that's 1.15C


def test_referenced_sections():
    assert referenced_sections("(see 1.00C6a) ... (see 1.00C6e(i)) and 1.00C6a again") == ["1.00C6a", "1.00C6ei"]


def test_cal_parse():
    p = Path(__file__).resolve().parents[2] / "data/cal/conditions.html"
    if not p.exists():
        pytest.skip("CAL page not saved")
    conds = parse_cal(p.read_text(encoding="utf-8", errors="replace"))
    names = [c["name"] for c in conds]
    assert len(names) > 250
    assert any(n.startswith("Osteosarcoma") for n in names)
    assert all(c["poms_url"].startswith("https://secure.ssa.gov/") for c in conds)


# --- Display labels: never "1.15AA" / "1.15A11" -------------------------------------------
def test_display_labels_have_no_doubled_markers(chunks):
    from app.services.bluebook import criterion_body, display_label
    assert display_label("1.15A", chunks["1.15A"].heading).startswith("1.15A Neuro-anatomic (radicular)")
    assert display_label("1.15A1", chunks["1.15A1"].heading) == "1.15A1 Pain; or"
    assert display_label("1.15B3a", chunks["1.15B3a"].heading) == "1.15B3a Decreased sensation; or"
    assert display_label("1.00C6ei", chunks["1.00C6ei"].heading).startswith("1.00C6ei Wheeled and seated")
    import re
    for cid, c in chunks.items():
        if c.level in ("criterion", "subcriterion"):
            body = criterion_body(c.heading)
            assert not re.match(r"^(?:[A-Z]|\d{1,2}|[a-z])\.\s", body), (cid, body)
            label = display_label(cid, c.heading)
            assert not label.startswith(cid + cid[-1]), label  # e.g. "1.15AA", "1.15A11"


def test_listing_name_and_logic(chunks):
    from app.services.bluebook import listing_logic, listing_name
    assert listing_name(chunks["1.15"].heading) == "Disorders of the skeletal spine resulting in compromise of a nerve root(s)"
    assert listing_logic(chunks["1.17"].heading) == ("all", ["A", "B", "C"])
    assert listing_logic(chunks["1.20"].heading) == ("any", ["A", "B", "C", "D"])


def test_subcriteria_carry_parent_context():
    from app.db import SessionLocal, init_db
    from app.services.listing_match import listing_bundle, render_criteria
    from app.services.reference_data import ingest_bluebook
    init_db()
    db = SessionLocal()
    ingest_bluebook(db, None)
    b = listing_bundle(db, "1.16")
    b1 = next(c for c in b["criteria"] if c["criterion_id"] == "1.16B1")
    assert [p["criterion_id"] for p in b1["context"]] == ["1.16B"]
    assert "Nonradicular" in b1["context"][0]["text"]
    text = render_criteria(b)
    assert "- 1.16B1: 1. Muscle weakness" in text
    assert 'CONTEXT (judge this sub-criterion only as part of): 1.16B "B. Nonradicular' in text
    b3a = next(c for c in listing_bundle(db, "1.15")["criteria"] if c["criterion_id"] == "1.15B3a")
    assert [p["criterion_id"] for p in b3a["context"]] == ["1.15B", "1.15B3"]
