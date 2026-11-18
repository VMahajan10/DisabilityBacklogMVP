from datetime import date

from app.services.missing_evidence import rule_flags
from app.services.triage import decide_queue


def item(cat, d, exam=False, verified=True):
    return {"category": cat, "date": d, "includes_musculoskeletal_or_neuro_exam": exam, "verified": verified}


def test_stale_imaging_and_exam_flagged():
    items = [item("imaging", "2024-08-05"), item("clinical_exam", "2025-01-18", exam=True),
             item("clinical_exam", "2026-09-16", exam=False)]
    types = {f["type"] for f in rule_flags(items, date(2026, 10, 6))}
    assert types == {"no_recent_imaging", "no_treating_source_opinion", "stale_records"}


def test_recent_complete_file_has_no_rule_flags():
    items = [item("imaging", "2026-06-12"), item("clinical_exam", "2026-08-19", exam=True),
             item("treating_source_opinion", "2026-08-19")]
    assert rule_flags(items, date(2026, 9, 8)) == []


def test_unverified_items_are_ignored():
    items = [item("imaging", "2026-06-12", verified=False), item("clinical_exam", "2026-08-19", exam=True),
             item("treating_source_opinion", "2026-08-19")]
    assert {f["type"] for f in rule_flags(items, date(2026, 9, 8))} == {"no_recent_imaging"}


def test_queue_rules():
    met = {"listing_code": "1.15", "overall": "criteria_appear_met"}
    ins = {"listing_code": "1.18", "overall": "insufficient_evidence"}
    assert decide_queue(None, met, [], 0.0, 0)[0] == "fast_track"
    assert decide_queue("Osteosarcoma, formerly known as Bone Cancer", ins, [], 0.0, 0)[0] == "fast_track"
    assert decide_queue(None, ins, ["treating vs CE on canes"], 0.0, 0)[0] == "senior_examiner"
    assert decide_queue(None, ins, [], 0.35, 0)[0] == "senior_examiner"
    q, reasons = decide_queue(None, ins, [], 0.02, 3)
    assert q == "standard" and "3 evidence gap" in reasons[1]
