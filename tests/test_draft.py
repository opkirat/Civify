"""Drafter tests. The model is replaced by a canned response, so no key is needed and
the result is the same every run. What is tested is our code: parsing the response and
making sure every claim is checked."""

import json

import pytest
from pydantic import ValidationError

from civify.draft import build_prompt, draft
from civify.extract import Document, Page

REPORT = Document("report.pdf", "a" * 64, [
    Page(1, "REPORT FOR ACTION\nThis Report recommends approval of an application to permit a "
            "45-storey building with 684 residential dwelling units."),
    Page(2, "The owner will provide 545 affordable rental units, subject to the conditions in this report."),
])


def fake_model(*claims):
    return lambda _prompt: json.dumps({"claims": [{"sentence": s, "quote": q} for s, q in claims]})


def test_prompt_marks_pages_and_states_the_rules():
    p = build_prompt(REPORT)
    assert "=== PAGE 1 ===" in p and "=== PAGE 2 ===" in p
    assert "EXACTLY" in p and "deadlines" in p


def test_good_claim_is_verified_with_its_page_and_source_checksum():
    _, out = draft(REPORT, fake_model((
        "Staff recommend approving a 45-storey building with 684 homes.",
        "recommends approval of an application to permit a 45-storey building with 684 residential dwelling units")))
    assert out[0]["verified"] and out[0]["page"] == 1
    assert out[0]["source_sha256"] == "a" * 64


def test_invented_quote_is_flagged_not_dropped():
    _, out = draft(REPORT, fake_model((
        "Staff recommend refusing the application.",
        "This Report recommends refusal of an application to permit a 45-storey building")))
    assert not out[0]["verified"] and "not found" in out[0]["reason"]


def test_wrong_number_is_flagged():
    _, out = draft(REPORT, fake_model((
        "The owner will provide 554 affordable rental units.",
        "The owner will provide 545 affordable rental units, subject to the conditions in this report")))
    assert not out[0]["verified"] and "554" in out[0]["reason"]


def test_every_claim_comes_back_checked_in_order():
    _, out = draft(REPORT, fake_model(
        ("Good.", "The owner will provide 545 affordable rental units, subject to the conditions"),
        ("Bad.", "this quote does not appear anywhere in the report at all")))
    assert [c["verified"] for c in out] == [True, False]


def test_malformed_model_output_raises_instead_of_passing_silently():
    with pytest.raises(ValidationError):
        draft(REPORT, lambda _p: '{"claims": [{"sentence": "no quote field"}]}')
