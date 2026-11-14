"""Locating a quote on its page: tolerant of line breaks, hyphenation and curly quotes; never fuzzy."""

from civify.extract import Document, Page
from civify.source import locate, pattern


def doc(*pages):
    return Document("r.pdf", "x" * 64, [Page(i, t) for i, t in enumerate(pages, 1)])


def test_finds_quote_across_line_breaks_hyphenation_and_quotes():
    d = doc("Intro.\nThe City Planning Division recom-\nmends that Council “amend” the plan – now.\nMore text.")
    hit = locate(d, 'The City Planning Division recommends that Council "amend" the plan - now.', page=1)
    assert hit and hit["page"] == 1 and hit["pages"] == "1"
    assert hit["match"].startswith("The City Planning Division recom") and hit["match"].endswith("now.")
    assert hit["before"].strip() == "Intro." and hit["after"].strip() == "More text."


def test_quote_straddling_pages_is_labelled_with_both():
    d = doc("page one text. The proposal increases the", "building height to 45 storeys. end", "unrelated")
    hit = locate(d, "The proposal increases the building height to 45 storeys.", page=1)
    assert hit and hit["page"] == 1 and hit["pages"] == "1–2"


def test_falls_back_to_other_pages_when_the_hint_is_wrong():
    d = doc("nothing here", "the quote is on page two of the document, here it is")
    assert locate(d, "quote is on page two", page=1)["page"] == 2


def test_no_match_is_none_not_a_guess():
    d = doc("the owner must pay cash-in-lieu for parkland")
    assert locate(d, "the owner may pay cash-in-lieu") is None
    assert locate(d, "   ") is None
    assert pattern("a-b c").pattern.count("a") == 1
