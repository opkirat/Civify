"""Decide what kind of record a PDF is, and who wrote it.

The brief requires us to distinguish staff recommendations from committee and
council decisions, and to show the source for every explanation. That starts
with knowing what each file *is*. Toronto's documents follow fixed templates,
so this is plain pattern matching on page 1. No AI is involved, which means the
classification itself is checkable by anyone reading this file.

Rules are ordered from most to least specific. Each rule says what evidence it
looked at, so the staff console can show "classified as staff report because
page 1 starts with 'REPORT FOR ACTION'".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from civify.extract import Document


class DocType(str, Enum):
    STAFF_REPORT = "staff_report"          # written by City staff; the "staff recommendation" stage
    PUBLIC_NOTICE = "public_notice"        # City Clerk; the official participation details
    DRAFT_BYLAW = "draft_bylaw"            # staff's proposed by-law text (attachment to the report)
    COUNCIL_BILL = "council_bill"          # by-law text as put before / adopted by Council
    ITEM_PAGE = "item_page"                # saved TMMIS page: tracking status, decisions, votes
    DECLARATION = "declaration_of_interest"
    PUBLIC_LETTER = "public_letter"        # correspondence from the public; never summarised
    UNKNOWN = "unknown"


@dataclass
class Classification:
    doc_type: DocType
    author: str | None            # as printed in the document, or None if not stated
    evidence: str                 # the line(s) on page 1 that decided it
    fields: dict[str, str] = field(default_factory=dict)  # dates, ward, etc. as printed


_DATE = r"(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"


def classify(doc: Document) -> Classification:
    lines = doc.first_lines(20)
    flat = doc.first_page_flat
    head = " ".join(lines[:3])

    # 1. Staff report: fixed template "REPORT FOR ACTION / INFORMATION" then Date/To/From/Ward.
    if re.search(r"\bREPORT FOR (ACTION|INFORMATION)\b", head):
        f = _labelled(lines, ["Date", "To", "From", "Ward", "Planning Application Number"])
        return Classification(DocType.STAFF_REPORT, f.get("From"), _first_match(lines, r"REPORT FOR"), f)

    # 2. Clerk's public notice: Clerk's letterhead and the heading.
    if "NOTICE OF PUBLIC MEETING" in flat and "City Clerk" in flat:
        f = _labelled(lines, ["Date", "Time", "Place", "Location of Application", "Applicant"])
        f.update(_notice_participation(doc.text))
        return Classification(DocType.PUBLIC_NOTICE, "City Clerk's Office", "NOTICE OF PUBLIC MEETING", f)

    # 3/4. By-law text. The draft has placeholders ("[-]", "[Clerks to insert ...]") in its
    #      authority line; the council-stage bill names the adopting meeting dates.
    if re.search(r"\bBY-LAW\b", flat) and "CITY OF TORONTO" in flat:
        authority = _first_match(lines, r"^Authority:")
        auth_text = " ".join(lines[: lines.index(authority) + 2]) if authority in lines else flat[:300]
        if "[-]" in auth_text or "Clerks to insert" in flat.split("enacts")[0]:
            return Classification(DocType.DRAFT_BYLAW, "City Planning (attachment to staff report)",
                                  auth_text, {"authority": auth_text})
        return Classification(DocType.COUNCIL_BILL, "City Clerk (bill before Council)",
                              auth_text, {"authority": auth_text})

    # 5. Saved item page from TMMIS.
    m = re.search(r"Item - (\d{4}\.[A-Z]{2,4}\d+\.\d+)", flat)
    if m and "Tracking Status" in flat:
        f = {"item_id": m.group(1)}
        status = re.search(r"Tracking Status (.*?)(?:See also|City Council consideration)", flat)
        if status:
            f["tracking_status"] = status.group(1).strip()
        return Classification(DocType.ITEM_PAGE, "City Clerk (TMMIS)", m.group(0), f)

    # 6. Declaration of interest: a one-line Clerk's-office stamp.
    if "City Clerk's Office" in flat and len(flat) < 300:
        return Classification(DocType.DECLARATION, "City Clerk's Office", flat)

    # 7. Public correspondence. Letters have no fixed layout, so the only signal we
    #    trust is the City's own file naming ("communicationfile-..."). Anything else
    #    we don't recognise is returned as UNKNOWN for staff, never guessed.
    if doc.filename.startswith("communicationfile-"):
        f = {}
        d = re.search(_DATE, flat)
        if d:
            f["date"] = d.group(0)
        # Deliberately no author extraction: the brief says not to display
        # unnecessary personal information from public correspondence.
        return Classification(DocType.PUBLIC_LETTER, None, "City filename prefix 'communicationfile-'", f)

    if not flat:
        return Classification(DocType.UNKNOWN, None, "no extractable text on page 1; the PDF may be a scan and need OCR")
    return Classification(DocType.UNKNOWN, None, head)


def _labelled(lines: list[str], labels: list[str]) -> dict[str, str]:
    """Pull 'Label: value' lines, e.g. 'Ward: 11 - University-Rosedale'."""
    out = {}
    for l in lines:
        for lab in labels:
            if l.startswith(lab + ":") and lab not in out:
                out[lab] = l[len(lab) + 1:].strip()
    return out


def _first_match(lines: list[str], pattern: str) -> str:
    return next((l for l in lines if re.search(pattern, l)), "")


def _notice_participation(text: str) -> dict[str, str]:
    """Quote, verbatim, the sentences in a public notice that say how to take part.

    We copy the sentences rather than interpret them: the brief says to verify
    participation details on the official record, not infer them.
    """
    flat = re.sub(r"\s+", " ", text)
    out = {}
    m = re.search(r"You can submit written comments[^.]*\.", flat)
    if m:
        out["written_comments"] = m.group(0)
    # "12:00 p.m." contains full stops, so end the sentence at the year instead.
    m = re.search(r"please register.*?no later than.*?\d{4}\.", flat)
    if m:
        out["speaker_registration"] = m.group(0)
    return out
