"""Verifier tests. Real claims come from the actual TE34.21 records; the noise
and edge-case tests use small synthetic documents so the behaviour is isolated."""

import json
from pathlib import Path

import pytest

from civify.extract import Document, Page, extract
from civify.verify import Verifier

DATA = Path("data/2026.TE34.21")


def make_doc(*page_texts: str) -> Document:
    return Document("synthetic.pdf", "0" * 64, [Page(i, t) for i, t in enumerate(page_texts, 1)])


# --- the demo claims, run against the real documents -------------------------

HAVE_PDFS = (DATA / "backgroundfile-288412.pdf").exists()
needs_pdfs = pytest.mark.skipif(not HAVE_PDFS, reason="source PDFs not in this checkout")
DEMO_CLAIMS = json.loads((DATA / "demo_claims.json").read_text()) if HAVE_PDFS else []


@needs_pdfs
@pytest.mark.parametrize("claim", DEMO_CLAIMS, ids=lambda c: c["sentence"][:40])
def test_demo_claims_behave_as_expected(claim):
    result = Verifier(extract(DATA / claim["file"])).check(claim["sentence"], claim["quote"])
    assert result.verified == claim["expect_verified"], result.reason


@needs_pdfs
def test_verified_claim_reports_its_page():
    doc = extract(DATA / "backgroundfile-288412.pdf")
    r = Verifier(doc).check("Staff recommend approval.", "This Report recommends approval of an application")
    assert r.verified and r.page == 1


@needs_pdfs
def test_wrong_number_is_named_in_the_reason():
    doc = extract(DATA / "backgroundfile-288412.pdf")
    r = Verifier(doc).check(
        "Homes would rise from 490 to 864.", "an increase from 490 to 684 residential dwelling units"
    )
    assert not r.verified and "864" in r.reason


# --- behaviour on controlled text ---------------------------------------------

def test_ignores_line_breaks_hyphenation_curly_quotes_and_case():
    doc = make_doc("The tower has 310 resi-\ndential units, subject to the “holding provision”.")
    r = Verifier(doc).check("310 homes.", 'THE TOWER HAS 310 residential units, subject to the "holding provision"')
    assert r.verified, r.reason


def test_quote_spanning_a_page_break_with_footer_in_between():
    """Real reports put a running footer between the two halves of a sentence."""
    footer = "Decision Report - 191 College Street Page {} of 4"
    doc = make_doc(
        "Intro.\n" + footer.format(1),
        "More.\n" + footer.format(2),
        "The owner will secure 62 affordable\n" + footer.format(3),
        "rental units for a period of 40 years.\n" + footer.format(4),
    )
    r = Verifier(doc).check("62 affordable rentals for 40 years.",
                            "secure 62 affordable rental units for a period of 40 years")
    assert r.verified, r.reason
    assert r.page == 3  # reported under the page where the quote starts


def test_quote_wholly_on_a_later_page_is_not_attributed_to_the_page_before():
    doc = make_doc("page one has nothing relevant on it at all", "the requested reduction in parking spaces is not supported")
    r = Verifier(doc).check("x", "the requested reduction in parking spaces is not supported")
    assert r.verified and r.page == 2


def test_quote_cannot_span_more_than_one_page_break():
    doc = make_doc("one two three four five six", "seven eight nine ten eleven", "twelve thirteen fourteen fifteen")
    r = Verifier(doc).check("x", "three four five six seven eight nine ten eleven twelve thirteen")
    assert not r.verified


def test_one_changed_word_is_not_close_enough():
    doc = make_doc("Staff do not support the requested reduction in parking spaces.")
    r = Verifier(doc).check("Staff support the cut.", "Staff do support the requested reduction in parking spaces")
    assert not r.verified


def test_known_limit_meaning_flip_with_real_quote_passes():
    """Documents the gap: a real quote under a sentence that contradicts it is NOT caught
    by code. Only staff review catches this. If this test ever fails, the verifier has
    gained a semantic check and the docs should be updated."""
    doc = make_doc("Staff do not support the requested reduction in parking spaces.")
    r = Verifier(doc).check("Staff support the parking reduction.",
                            "Staff do not support the requested reduction in parking spaces")
    assert r.verified


@pytest.mark.parametrize("quote,why", [
    ("the requested reduction in parking", "too short"),  # 30 chars normalised, under the 40 minimum
    ("Staff do not support ... the requested reduction in parking spaces", "ellipsis"),
])
def test_unusable_quotes_rejected(quote, why):
    r = Verifier(make_doc("Staff do not support the requested reduction in parking spaces.")).check("x", quote)
    assert not r.verified and why in r.reason


def test_number_formatting_differences_are_allowed():
    doc = make_doc("The charge is $1,250,000 payable before the first permit.")
    r = Verifier(doc).check("They pay $1250000.", "The charge is $1,250,000 payable before the first permit")
    assert r.verified, r.reason
