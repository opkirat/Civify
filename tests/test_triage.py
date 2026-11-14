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


def test_risk_words_echoed_by_the_passage_do_not_need_a_person():
    """A 'must' the passage also states is for the meaning check; a 'must' the passage lacks is for a person."""
    assert risk_reasons("The owner must pay before the first permit.", "The owner shall pay prior to the first permit.") == []
    assert risk_reasons("The owner must pay before the first permit.", "The owner pays before the first permit.") == \
        ["states a condition or requirement that the source passage does not"]
    assert risk_reasons("Staff recommend amending the plan.", "City Planning recommends that Council amend the plan.") == []
    assert risk_reasons("The units may qualify for incentives.", "The units qualify for incentives.") == \
        ["states uncertainty that the source passage does not"]
    # participation is never delegated to the passage
    assert risk_reasons("Comments are accepted until Monday.", "Comments are accepted until Monday.") == ["mentions taking part or a deadline"]


def test_lane_uses_the_quote_when_judging_risk_words():
    c = {"sentence": "Staff recommend amending the plan.", "quote": "City Planning recommends that Council amend the plan.", "verified": True, "reason": "ok"}
    assert assign_lane(c, OK) == ("ready", [])
    c["quote"] = "The plan would be amended under this option."
    assert assign_lane(c, OK)[0] == "review"


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


from civify.triage import build_confirm_prompt, check_confirm

APPROVE = {"verdict": "approve", "neutral": True, "issue": "", "suggestion": ""}
HOLD = {"verdict": "hold", "neutral": True, "issue": "drops the condition", "suggestion": "Approval is subject to conditions."}


def test_auto_needs_both_ai_checks_and_never_covers_participation():
    plain = claim("The site is on Queen Street.")
    assert assign_lane(plain, OK, APPROVE) == ("ready", [])
    lane, reasons = assign_lane(plain, OK, HOLD)
    assert lane == "review" and "drops the condition" in reasons[0]
    lane, _ = assign_lane(plain, {"verdict": "unsure", "neutral": True, "issue": ""}, APPROVE)
    assert lane == "review"                                                   # meaning check must agree too
    lane, _ = assign_lane(claim("Comments are accepted until Monday."), OK, APPROVE)
    assert lane == "review"                                                   # taking part: always a person
    out = triage([plain, plain, claim("x", verified=False, reason="quote not found")], {0: OK, 1: OK}, {0: APPROVE})
    assert [t["auto"] for t in out] == [True, False, False]                  # no context check, no auto


def test_context_check_can_clear_a_word_the_quote_lacks_but_not_a_meaning_flag():
    c = {"sentence": "Staff recommend amending the plan.", "quote": "City Council amend the Official Plan for the site as set out.", "verified": True, "reason": "ok"}
    assert assign_lane(c, OK, None)[0] == "review"
    assert assign_lane(c, OK, APPROVE) == ("ready", [])                       # page says "City Planning recommends that"
    assert assign_lane(c, {"verdict": "not_supported", "neutral": True, "issue": "x"}, APPROVE)[0] == "review"


def test_confirm_prompt_skips_blocked_and_participation_and_maps_by_index():
    claims = [claim("The site is on Queen Street."), claim("x", verified=False), claim("Comments close Monday.")]
    ctx = [{"pages": "3", "before": "Intro. ", "match": "q" * 50, "after": " More."}, None, None]
    prompt, sent = build_confirm_prompt(claims, ctx, {0: OK})
    assert sent == [0] and "1. SENTENCE: The site is on Queen Street." in prompt and "[[" + "q" * 50 + "]]" in prompt
    reply = json.dumps({"results": [dict(APPROVE, index=1), dict(APPROVE, index=3)]})
    _, confirm = check_confirm(claims, ctx, {0: OK}, lambda p: reply)
    assert set(confirm) == {0}                                                # reply for an unsent item is ignored
