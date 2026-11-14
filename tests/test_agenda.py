"""Agenda tests: the real saved Preservation Board agenda, plus the rules fetch on canned HTML."""

from pathlib import Path

import pytest

from civify.agenda import fetch_rules, parse

AGENDA = Path("data/agendas/2026-11-16-PB1.pdf")
pytestmark = pytest.mark.skipif(not AGENDA.exists(), reason="saved agenda not in this checkout")


def test_meeting_details_and_all_items_with_wards():
    m = parse(AGENDA, "2026-11-13")
    assert m["body"] == "Toronto Preservation Board"
    assert (m["meeting_date"], m["meeting_time"], m["agenda_status"]) == ("2026-11-16", "9:30 AM", "Agenda Published")
    assert m["location"] == "Committee Room 1, City Hall/Video Conference"
    assert [i["id"] for i in m["items"]] == [f"2026.PB1.{n}" for n in range(1, 7)]
    assert [i["ward"] for i in m["items"]] == ["5", "10", "13", "13", "15", "4"]
    assert m["items"][5]["title"].startswith("1337 Queen Street West - Demolition and New Construction")
    assert m["items"][5]["official_url"].endswith("item=2026.PB1.6")


def test_posted_notes_are_captured_whole():
    item = parse(AGENDA, "x")["items"][4]
    assert item["id"] == "2026.PB1.5" and len(item["notes"]) == 3
    assert item["notes"][0]["date"] == "2026-11-10" and item["notes"][0]["note"].endswith("corrections were made to Pages 1 and 7.")
    assert item["notes"][2]["note"] == "A communication was posted."


def test_members_list_is_not_mistaken_for_notes():
    item = parse(AGENDA, "x")["items"][5]
    assert item["notes"] == [] and "Julia Rady" not in item["title"]


def test_rules_are_quoted_verbatim_including_the_pm_time():
    page = "<p>You should register by 12:00 p.m. the day before the meeting at the latest. Other text.</p>" \
           "<p>If we receive your comments after a matter has been decided, they will not be accepted.</p>"
    r = fetch_rules(lambda url: page)
    assert "You should register by 12:00 p.m. the day before the meeting at the latest." in r["quotes"]
    assert r["source"].endswith("/participate/")
