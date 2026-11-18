from pathlib import Path

import pytest

from app.services.extraction import extract_pages, pdf_title

ROOT = Path(__file__).resolve().parents[2]
CASE1 = ROOT / "data/synthetic/cases/case01_lumbar_radiculopathy"


@pytest.fixture(scope="module")
def notes_pages():
    p = CASE1 / "01_progress_notes_riverbend_ortho.pdf"
    if not p.exists():
        pytest.skip("run `make synth` first")
    return extract_pages(p)


def test_page_count_matches_logical_pages(notes_pages):
    assert len(notes_pages) == 4


def test_pages_in_order_with_footer_numbers(notes_pages):
    for i, text in enumerate(notes_pages, start=1):
        assert f"Page {i} of 4" in text


def test_page_content_lands_on_correct_page(notes_pages):
    assert "06/10/2025" in notes_pages[0]
    assert "front-wheeled walker" in notes_pages[1]
    assert "08/19/2026" in notes_pages[3]


def test_watermark_stripped_footer_kept(notes_pages):
    for text in notes_pages:
        # Diagonal watermark removed; the plain footer notice remains.
        assert text.count("SYNTHETIC TEST DATA") == 1


def test_title_metadata():
    assert pdf_title(CASE1 / "02_imaging_lakeside.pdf") == "Imaging Reports - Lakeside Imaging Center"


def test_every_small_synthetic_pdf_has_text_on_every_page():
    pdfs = [p for p in (ROOT / "data/synthetic/cases").glob("case0[1-6]_*/*.pdf")]
    assert len(pdfs) >= 20
    for p in pdfs:
        for text in extract_pages(p):
            assert len(text) > 100, p.name


def test_large_case_scanned_pages_have_no_text_layer():
    import json
    case = ROOT / "data/synthetic/cases/case07_medium_lumbar"
    if not (case / "case.json").exists():
        pytest.skip("large cases not generated")
    for d in json.loads((case / "case.json").read_text())["documents"]:
        pages = extract_pages(case / d["file"])
        assert len(pages) == d["logical_pages"]
        for i, text in enumerate(pages, start=1):
            assert (len(text) == 0) == (i in d["scanned_pages"]), (d["file"], i)
