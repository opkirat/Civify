"""Classification tests against the real 2026.TE34.21 files.

These are integration tests on the actual Toronto records, not synthetic
fixtures, because the point is that the templates we match really are what the
City publishes.
"""

from pathlib import Path

import pytest

from civify.classify import DocType, classify
from civify.extract import extract

DATA = Path("data/2026.TE34.21")

EXPECTED = {
    "Agenda_Item_History.pdf": DocType.ITEM_PAGE,
    "DI13226.pdf": DocType.DECLARATION,
    "backgroundfile-288412.pdf": DocType.STAFF_REPORT,
    "backgroundfile-288413.pdf": DocType.PUBLIC_NOTICE,
    "backgroundfile-288508.pdf": DocType.DRAFT_BYLAW,
    "backgroundfile-289954.pdf": DocType.COUNCIL_BILL,
    "communicationfile-215691.pdf": DocType.PUBLIC_LETTER,
    "communicationfile-216766.pdf": DocType.PUBLIC_LETTER,
    "communicationfile-216982.pdf": DocType.PUBLIC_LETTER,
    "communicationfile-216987.pdf": DocType.PUBLIC_LETTER,
    "law1064.pdf": DocType.ENACTED_BYLAW,
    "law1234.pdf": DocType.ENACTED_BYLAW,
}

pytestmark = pytest.mark.skipif(
    not (DATA / "backgroundfile-288412.pdf").exists(),
    reason="source PDFs not in this checkout (see data/2026.TE34.21/item.json for the ingest output)",
)


@pytest.mark.parametrize("filename,expected", EXPECTED.items())
def test_every_file_classified(filename, expected):
    c = classify(extract(DATA / filename))
    assert c.doc_type is expected, c.evidence


def test_staff_report_fields_come_from_the_document():
    c = classify(extract(DATA / "backgroundfile-288412.pdf"))
    assert c.author == "Acting Director, Community Planning, Toronto and East York District"
    assert c.fields["Date"] == "June 19, 2026"
    assert c.fields["Ward"] == "11 - University-Rosedale"
    assert c.fields["Planning Application Number"] == "26 120321 STE 11 OZ"


def test_notice_quotes_participation_rules_verbatim():
    c = classify(extract(DATA / "backgroundfile-288413.pdf"))
    assert c.author == "City Clerk's Office"
    assert c.fields["Date"] == "July 8, 2026"
    assert c.fields["written_comments"] == (
        "You can submit written comments up until City Council gives final consideration to the proposal."
    )
    assert "no later than 12:00 p.m. on July 7, 2026." in c.fields["speaker_registration"]


def test_draft_and_bill_are_distinguished_by_authority_line():
    draft = classify(extract(DATA / "backgroundfile-288508.pdf"))
    bill = classify(extract(DATA / "backgroundfile-289954.pdf"))
    assert "[-]" in draft.fields["authority"]
    assert "July 29, 30 and 31, 2026" in bill.fields["authority"]


def test_item_page_yields_item_id_and_tracking_status():
    c = classify(extract(DATA / "Agenda_Item_History.pdf"))
    assert c.fields["item_id"] == "2026.TE34.21"
    assert c.fields["tracking_status"].startswith("City Council adopted this item on July 29 and 30, 2026 with amendments.")


def test_public_letters_carry_no_author():
    for f in DATA.glob("communicationfile-*.pdf"):
        c = classify(extract(f))
        assert c.author is None, f.name
        assert "name" not in c.fields


def test_sha256_is_recorded():
    doc = extract(DATA / "DI13226.pdf")
    assert len(doc.sha256) == 64


def test_enacted_bylaw_records_vote_date_and_mayoral_approval():
    c = classify(extract(DATA / "law1234.pdf"))
    assert c.fields["bylaw_number"] == "1234-2026"
    assert c.fields["council_vote_date"] == "July 30, 2026"
    assert c.fields["mayoral_decision"] == "13-2026" and c.fields["mayoral_decision_date"] == "July 30, 2026"


def test_appendix_is_recognised_not_unknown():
    from civify.extract import Document, Page
    d = Document("backgroundfile-1.pdf", "x" * 64, [Page(1, "~TORONTO\nAppendix D\nLauren Birch\nDirector")])
    c = classify(d)
    assert c.doc_type is DocType.APPENDIX and c.fields["label"] == "Appendix D"
    d = Document("backgroundfile-2.pdf", "x" * 64, [Page(1, "APPENDIX A\nSummary of New Chapter 441 Fees")])
    assert classify(d).doc_type is DocType.APPENDIX
