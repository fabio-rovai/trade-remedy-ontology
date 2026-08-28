"""The repair file is the deliverable. These tests lock its shape, offline."""
import csv, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP = 200

def _rows():
    with open(os.path.join(ROOT, "repairs", "legal_act_url_repairs.csv")) as f:
        return list(csv.DictReader(f))

def test_thirteen_repairs():
    assert len(_rows()) == 13

def test_every_published_url_sits_exactly_at_the_cap_and_is_dead():
    for r in _rows():
        assert int(r["published_url_length"]) == CAP
        assert r["published_url_status"] == "404"

def test_every_repair_was_accepted_and_resolves():
    for r in _rows():
        assert r["repaired_url"].startswith("https://www.gov.uk/")
        assert r["repaired_status"] == "200"

def test_every_repair_extends_the_truncated_string():
    """A repair must be a continuation of what was published, never a substitution."""
    for r in _rows():
        assert r["repaired_url"].startswith(r["published_url"])
        assert len(r["repaired_url"]) > CAP

def test_headline_figures_agree_across_both_computation_paths():
    p = os.path.join(ROOT, "graph", "headline_figures.json")
    if not os.path.exists(p):
        return  # graph not built in this checkout
    d = json.load(open(p))
    assert d["set_based"] == d["sparql"]


def test_case_code_repairs_restore_a_leading_zero():
    import json
    p = os.path.join(ROOT, "repairs", "tra_case_code_repairs.json")
    rs = json.load(open(p))
    assert len(rs) == 12
    for r in rs:
        assert r["accepted"] is True
        assert len(r["published_code"]) == 9
        assert r["published_code_status"] == 404
        assert r["repaired_code"] == "0" + r["published_code"]
        assert r["repaired_code_status"] == 200
        assert r["repaired_description"]


def test_case_code_repairs_only_touch_invalid_granularities():
    import json
    rs = json.load(open(os.path.join(ROOT, "repairs", "tra_case_code_repairs.json")))
    for r in rs:
        assert len(r["published_code"]) not in (6, 8, 10)
        assert len(r["repaired_code"]) == 10
