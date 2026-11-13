"""Notices tests: normalisation on a canned City row (offline), plus the real feed when present."""

import datetime as dt
import json
from pathlib import Path

import pytest

from civify.notices import build, normalize, plain_text

ROW = {
    "noticeId": 9001, "title": "Notice of Public Meeting - 1 Example Rd", "noticeDate": "1762128000000",
    "noticeHeadingType": "Public Notice", "decisionBody": "Scarborough Community Council", "signedBy": "City Clerk",
    "noticeDescription": "<p><strong>MAKE YOUR VIEWS KNOWN</strong></p><p>Ward 20 &ndash; Scarborough Southwest</p>"
                         "<p>please register by e-mail, no later than 12:00 p.m. on November 24, 2026 . If you register, we will contact you.</p>",
    "eventList": json.dumps([{"startDateTime": 1764000000000, "locationName": "Scarborough Civic Centre", "streetAddress": "150 Borough Dr"}]),
    "addressList": json.dumps([{"streetAddress": "1 Example Rd", "postalCode": "M1K 1A1", "latitudeCoordinate": "43.7157,", "longitudeCoordinate": "-79.2608"},
                               {"streetAddress": "bad", "latitudeCoordinate": "n/a", "longitudeCoordinate": ""}]),
    "otherReferenceList": json.dumps([{"description": "2026.SC1.5 - 1 Example Rd", "url": "https://secure.toronto.ca/council/agenda-item.do?item=2026.SC1.5"}]),
    "topics": json.dumps(["Meetings > Notice of meeting"]), "planningApplicationNumbers": "[]",
}


def test_normalize_reads_ward_coords_item_and_quotes_the_deadline_sentence_whole():
    n = normalize(ROW, "2026-11-13")
    assert n["ward"] == "20" and n["posted"] == "2026-11-03"
    assert n["addresses"] == [{"address": "1 Example Rd", "postal_code": "M1K 1A1", "lat": 43.7157, "lon": -79.2608}]  # junk row dropped
    assert n["agenda_items"][0]["id"] == "2026.SC1.5"
    assert n["events"][0]["date"] == "2026-11-24" and n["events"][0]["location"] == "Scarborough Civic Centre"
    assert any(s.endswith("no later than 12:00 p.m. on November 24, 2026 .") for s in n["participation"])  # not cut at "p.m."
    assert "<" not in n["text"] and "Ward 20 – Scarborough Southwest" in n["text"]


def test_build_keeps_recent_or_upcoming_only():
    old = dict(ROW, noticeId=1, noticeDate="1700000000000", eventList="[]")      # 2023, no event
    today = dt.date(2026, 11, 13)
    kept = build([ROW, old], days=60, today=today, retrieved="2026-11-13")
    assert [n["notice_id"] for n in kept] == [9001]
    # an old notice with a future event is still kept
    old_future = dict(old, eventList=ROW["eventList"])
    assert [n["notice_id"] for n in build([old_future], 60, today, "x")] == [1]


def test_plain_text_strips_html_and_entities():
    assert plain_text("<p>A &amp; B</p><p>C</p>") == "A & B\nC"


@pytest.mark.skipif(not Path("data/notices.json").exists(), reason="feed not built")
def test_live_feed_has_coordinates_and_official_source():
    ns = json.loads(Path("data/notices.json").read_text())
    assert ns and all(n["addresses"] for n in ns)
    assert all(n["source"]["dataset"].startswith("https://open.toronto.ca/dataset/public-notices") for n in ns)
