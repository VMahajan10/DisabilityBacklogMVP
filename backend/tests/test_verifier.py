from app.services.verifier import normalize, verify_quote

PAGE = """Riverbend Orthopedic & Spine Associates (fictional)
Objective / Examination
Gait slow and unsteady; left foot slap noted. Positive straight leg raise on the left at 30 degrees supine and seated.
Decreased sensation in left L5 distribution. Left EHL 4-/5, left ankle dorsiflexion 4-/5. Unable to heel walk on the
left. Romberg negative.
Plan: Prescribed a front-wheeled walker; patient requires a walker for all ambulation outside the home."""


def test_exact_match_returns_original_offsets():
    q = "Positive straight leg raise on the left at 30 degrees"
    r = verify_quote(PAGE, q)
    assert r.verified and r.score == 1.0
    assert PAGE[r.start:r.end] == q


def test_match_across_line_break_and_case():
    r = verify_quote(PAGE, "unable to heel walk on the left. romberg negative")
    assert r.verified
    assert "Unable to heel walk on the\nleft" in PAGE[r.start:r.end]


def test_smart_quotes_and_dashes_normalized():
    r = verify_quote(PAGE, "Left EHL 4–/5, left ankle dorsiflexion 4–/5")
    assert r.verified


def test_fuzzy_match_minor_typo():
    r = verify_quote(PAGE, "patient requires a walker for all ambulation outside of the home")
    assert r.verified and 0.85 <= r.score < 1.0


def test_fabricated_quote_fails():
    r = verify_quote(PAGE, "Patient ambulates normally without any assistive device")
    assert not r.verified
    assert "not found" in r.reason


def test_quote_from_other_page_fails():
    other = "MRI shows left paracentral disc extrusion at L4-L5 compressing the L5 nerve root."
    assert verify_quote(other, "Positive straight leg raise on the left at 30 degrees").verified is False


def test_missing_page_fails():
    r = verify_quote(None, "anything at all here")
    assert not r.verified and r.reason == "cited page does not exist"


def test_too_short_quote_fails():
    assert not verify_quote(PAGE, "left").verified


def test_normalize_collapses_whitespace():
    assert normalize("  A\n\tB   C ") == "a b c"


def test_ellipsis_fragments_all_present_verifies_and_spans():
    q = "Gait slow and unsteady; left foot slap noted...Decreased sensation in left L5 distribution."
    r = verify_quote(PAGE, q)
    assert r.verified
    assert PAGE[r.start:r.end].startswith("Gait slow") and PAGE[r.start:r.end].endswith("distribution")


def test_ellipsis_with_one_fabricated_fragment_fails():
    q = "Gait slow and unsteady; left foot slap noted... Patient denies any numbness in either leg."
    r = verify_quote(PAGE, q)
    assert not r.verified and "1 of 2" in r.reason


def test_unicode_ellipsis_handled():
    assert verify_quote(PAGE, "Romberg negative… Prescribed a front-wheeled walker").verified
