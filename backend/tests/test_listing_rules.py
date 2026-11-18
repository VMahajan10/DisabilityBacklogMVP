from types import SimpleNamespace as C

from app.services.listing_match import compute_overall, effective_status


def cite(verified, relevant):
    return C(verified=verified, relevant=relevant)


def test_effective_status_three_states():
    assert effective_status("met", [cite(True, True)]) == ("met", None)
    s, note = effective_status("met", [cite(True, False)])
    assert s == "unsupported" and "does not clearly support" in note
    assert effective_status("met", [cite(False, None)])[0] == "unverified"
    assert effective_status("met", [])[0] == "unverified"
    # one relevant citation among irrelevant ones is enough
    assert effective_status("not_met", [cite(True, False), cite(True, True)])[0] == "not_met"


def test_not_documented_and_insufficient_pass_through():
    assert effective_status("not_documented", []) == ("not_documented", None)
    assert effective_status("insufficient_evidence", [cite(False, None)]) == ("insufficient_evidence", None)


def test_and_listing_gate():
    st = {"1.17A": "not_met", "1.17B": "met", "1.17C": "met"}
    assert compute_overall("all", ["A", "B", "C"], "1.17", st) == ("criteria_not_met", "1.17A")


def test_and_listing_all_met_and_insufficient():
    ok = {"1.15A": "met", "1.15B": "met", "1.15C": "met", "1.15D": "met"}
    assert compute_overall("all", ["A", "B", "C", "D"], "1.15", ok) == ("criteria_appear_met", None)
    weak = {**ok, "1.15D": "unsupported"}
    assert compute_overall("all", ["A", "B", "C", "D"], "1.15", weak) == ("insufficient_evidence", None)
    nd = {**ok, "1.15C": "not_documented"}
    assert compute_overall("all", ["A", "B", "C", "D"], "1.15", nd) == ("insufficient_evidence", None)


def test_or_listing():
    assert compute_overall("any", ["A", "B"], "1.20", {"1.20A": "not_met", "1.20B": "met"})[0] == "criteria_appear_met"
    assert compute_overall("any", ["A", "B"], "1.20", {"1.20A": "not_met", "1.20B": "not_met"})[0] == "criteria_not_met"
    assert compute_overall("any", ["A", "B"], "1.20", {"1.20A": "not_met", "1.20B": "not_documented"}) == ("insufficient_evidence", None)
