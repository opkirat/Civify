"""Record builder tests against the real 2026.TE34.21 files."""

import json
from pathlib import Path

import pytest

from civify.record import build, parse_vote

DATA = Path("data/2026.TE34.21")
pytestmark = pytest.mark.skipif(not (DATA / "Agenda_Item_History.pdf").exists(), reason="source PDFs not in this checkout")


@pytest.fixture(scope="module")
def rec():
    return build(DATA)


def test_title_and_ids(rec):
    assert rec["item_id"] == "2026.TE34.21"
    assert rec["title"] == ("TE34.21 - 191-199 College Street and 74-76 Henry Street - Official Plan and "
                            "Zoning By-law Amendment Application - Decision Report - Approval")
    assert rec["official_url"].endswith("item=2026.TE34.21")


def test_three_stages_in_order_with_dates_from_the_record(rec):
    s = rec["stages"]
    assert [x["stage"] for x in s] == ["staff_recommendation", "committee_decision", "council_decision", "enacted"]
    assert s[0]["date"] == "June 19, 2026" and s[0]["body"].startswith("Acting Director, Community Planning")
    assert s[1]["date"] == "July 8 and 9, 2026" and s[1]["status"] == "Amended"
    assert s[2]["date"] == "July 29 and 30, 2026"
    assert s[2]["outcome"] == "City Council adopted this item on July 29 and 30, 2026 with amendments."
    assert rec["current_stage"] == "enacted"
    assert s[3]["date"] == "July 30, 2026" and s[3]["mayoral_decision"] == "13-2026"
    assert [b["number"] for b in s[3]["bylaws"]] == ["1064-2026", "1234-2026"]


def test_each_stage_names_its_source_file(rec):
    for s in rec["stages"]:
        assert s["source"]["file"].endswith(".pdf") and len(s["source"]["sha256"]) == 64


def test_council_votes_and_declared_interest(rec):
    c = rec["stages"][2]
    assert c["stage"] == "council_decision"
    by = {v["on"]: v for v in c["votes"]}
    assert by["Amend Item"]["yes"]["count"] == 22 and by["Amend Item"]["no"]["count"] == 0
    assert by["Adopt Item as Amended"]["yes"]["count"] == 23
    assert "Olivia Chow" in by["Adopt Item as Amended"]["absent"]["members"]
    assert "Mayor Olivia Chow" in c["declared_interests"]
    assert any(m["moved_by"] == "Councillor Dianne Saxe" and m["result"] == "Carried" for m in c["motions"])


def test_participation_is_quoted_not_computed(rec):
    p = rec["participation"]
    assert p["written_comments_rule"].startswith("You can submit written comments up until City Council")
    assert "no later than 12:00 p.m. on July 7, 2026" in p["speaker_registration_rule"]
    assert p["council_has_decided"] is True
    assert p["source"]["file"] == "backgroundfile-288413.pdf"
    assert "deadline" not in json.dumps(p).lower()  # we never emit a computed deadline


def test_letters_are_counted_not_named(rec):
    assert rec["public_letters"] == 4
    assert "Ramkhalawansingh" not in json.dumps(rec)


def test_claims_attached(rec):
    assert len(rec["claims"]) == 19 and all(c["verified"] for c in rec["claims"])


def test_parse_vote_on_controlled_text():
    block = "Result:\nCarried Majority Required\nYes: 2 A, B\nNo: 1 C\nAbsent: 0\n"
    v = parse_vote(block)
    assert v["yes"] == {"count": 2, "members": "A, B"} and v["no"]["count"] == 1 and v["absent"]["count"] == 0


def test_council_motions_carry_their_text(rec):
    motions = rec["stages"][2]["motions"]
    assert [m["motion"] for m in motions] == ["Motion to Amend Item", "Motion to Amend Item (Additional)"]
    assert "Attachment 1 to this motion" in motions[0]["text"]
    assert "Transportation Impact Study" in motions[1]["text"]
    assert "12:34 AM" not in rec["stages"][2]["decision_text"]  # browser print header stripped
