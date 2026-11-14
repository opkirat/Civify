"""Triage tests: risk rules, lanes and the meaning check, with a canned model reply (offline)."""

import json

from civify.triage import assign_lane, build_prompt, check_meaning, risk_reasons, triage

OK = {"verdict": "supported", "neutral": True, "issue": ""}


def claim(sentence, verified=True, reason="ok"):
    return {"sentence": sentence, "quote": "q" * 50, "verified": verified, "reason": reason}


def test_risk_rules_catch_decisions_conditions_uncertainty_and_participation():
    assert risk_reasons("Staff recommend approving the plan.") == ["states a recommendation or decision"]
    assert "states a condition or requirement" in risk_reasons("This is subject to a holding provision.")
    assert "states uncertainty" in risk_reasons("The units may qualify for incentives.")
    assert "mentions taking part or a deadline" in risk_reasons("Written comments are accepted until Monday.")
    assert risk_reasons("The site is on the south side of Queen Street West.") == []


def test_lanes():
    assert assign_lane(claim("The site is on Queen Street."), OK) == ("ready", [])
    assert assign_lane(claim("The site is on Queen Street.", verified=False, reason="quote not found"), OK)[0] == "blocked"
    lane, reasons = assign_lane(claim("The site is on Queen Street."), None)
    assert lane == "review" and reasons == ["meaning check not run"]          # fails safe
    lane, reasons = assign_lane(claim("The site is on Queen Street."), {"verdict": "not_supported", "neutral": True, "issue": "adds a fact"})
    assert lane == "review" and "adds a fact" in reasons[0]
    lane, reasons = assign_lane(claim("The site is on Queen Street."), {"verdict": "supported", "neutral": False, "issue": ""})
    assert lane == "review" and "neutral" in reasons[0]


def test_meaning_flip_with_real_quote_goes_to_review():
    """The gap the code verifier can't close: a real quote under a contradicting sentence."""
    c = claim("Staff recommend refusing the application.")
    lane, reasons = assign_lane(c, {"verdict": "not_supported", "neutral": True, "issue": "the passage recommends approval"})
    assert lane == "review" and any("approval" in r for r in reasons)


def test_check_meaning_maps_numbered_pairs_and_ignores_out_of_range():
    claims = [claim("A."), claim("B.")]
    reply = json.dumps({"results": [
        {"index": 1, "verdict": "supported", "neutral": True, "issue": ""},
        {"index": 2, "verdict": "unsure", "neutral": True, "issue": "vague"},
        {"index": 9, "verdict": "supported", "neutral": True, "issue": ""}]})
    raw, meaning = check_meaning(claims, lambda prompt: reply)
    assert set(meaning) == {0, 1} and meaning[1]["verdict"] == "unsure"
    assert "1. SENTENCE: A." in build_prompt(claims) and "2. SENTENCE: B." in build_prompt(claims)


def test_triage_missing_result_falls_back_to_review():
    out = triage([claim("The site is on Queen Street."), claim("The site is on King Street.")], {0: OK})
    assert [t["lane"] for t in out] == ["ready", "review"]
