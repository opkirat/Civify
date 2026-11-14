"""Pending items, report revisions, agenda identity and publication boundaries."""
import copy
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from civify import agenda, app as appmod, db, record


@pytest.mark.parametrize("item_id,ward,versions,source", [
    ("2027.PB1.5", "15", 3, "backgroundfile-290992.pdf"),
    ("2027.PB1.6", "4", 1, "backgroundfile-290746.pdf"),
])
def test_pending_records_choose_latest_report(item_id, ward, versions, source, monkeypatch):
    folder = Path("data") / item_id
    if not (folder / "Agenda_Item_History.pdf").exists():
        pytest.skip("source PDFs not in this checkout")
    monkeypatch.setattr(record, "lookup", lambda _: None)
    rec = record.build(folder)
    assert rec["current_stage"] == "staff_recommendation"
    assert rec["ward"] == ward
    assert len(rec["stages"][0]["versions"]) == versions
    assert rec["stages"][0]["source"]["file"] == source
    assert rec["stages"][1]["status"] == "pending"
    assert rec["stages"][2]["outcome"] is None
    assert not rec["participation"]["council_has_decided"]
    assert rec["participation"]["next_meeting"]["date"] == "November 16, 2026"
    assert rec["participation"]["speaker_registration_rule"] is None
    assert {c["source_file"] for c in rec["claims"]} == {source}


def test_latest_report_uses_date_not_filename_order():
    reports = [
        {"filename": "z.pdf", "fields": {"Date": "October 28, 2026"}},
        {"filename": "a.pdf", "fields": {"Date": "November 13, 2026"}},
    ]
    assert record.latest_report(reports)["filename"] == "a.pdf"


def test_council_status_is_not_a_pending_boards_status():
    text = "City Council consideration on November 19, 2026\nStatus: Adopted\n" \
           "Toronto Preservation Board consideration on November 16, 2026\nRecommendations\nStaff recommend..."
    assert record.committee_stage(text, {})["status"] == "pending"


def test_agenda_does_not_guess_item_year_and_requires_matching_meeting(tmp_path):
    path = tmp_path / "agenda.html"
    path.write_text("<p>Toronto Preservation Board</p><p>November 16, 2026 - 9:30 AM - Scheduled (Preview)</p>"
                    "<p>Committee Room 1</p><p>Agenda Published</p><p>PB1.5</p><p>19 Don Ridge Drive (Ward 15)</p>")
    meeting = agenda.parse(path, "2026-11-13")
    assert meeting["items"][0]["official_url"] is None
    rec = db.load_record("2027.PB1.5")
    resolved = agenda.resolve_items(copy.deepcopy(meeting), [rec])["items"][0]
    assert resolved["id"] == "2027.PB1.5"
    assert resolved["local_url"] == "/items/2027.PB1.5"
    wrong = copy.deepcopy(rec)
    wrong["participation"]["next_meeting"]["date"] = "November 16, 2027"
    assert agenda.resolve_items(copy.deepcopy(meeting), [wrong])["items"][0]["official_url"] is None
    # Full IDs in HTML links survive stripping HTML tags.
    path.write_text(path.read_text() + '<a href="https://secure.toronto.ca/council/agenda-item.do?item=2027.PB1.5">Item</a>')
    assert agenda.parse(path, "2026-11-13")["items"][0]["id"] == "2027.PB1.5"


@pytest.mark.parametrize("item_id", ["2027.PB1.5", "2027.PB1.6"])
def test_pending_pages_show_unknown_participation_without_publishing_drafts(staff, item_id):
    rec = db.load_record(item_id)
    for suffix in ("", "/print"):
        page = staff.get(f"/items/{item_id}{suffix}")
        assert page.status_code == 200
        assert "November 16, 2026" in page.text
        assert "An open comment window has not been verified" in page.text
        assert "None" not in page.text
        assert "No explanation yet" in page.text
        assert rec["claims"][0]["sentence"] not in page.text
    if item_id == "2027.PB1.5":
        assert "3 report versions" in staff.get("/staff/2027.PB1.5").text


def test_print_shares_review_gate_and_preserves_full_quotes(client):
    item_id = "2027.PB1.6"
    rec = db.load_record(item_id)
    con = db.connect(appmod.DB_PATH)
    approved, rejected = rec["claims"][0], rec["claims"][1]
    db.save_review(con, item_id, 0, approved, "approved", approved["sentence"], "Test reviewer")
    db.save_review(con, item_id, 1, rejected, "rejected", rejected["sentence"], "Test reviewer")
    db.publish(con, rec, "Test reviewer")
    page = client.get(f"/items/{item_id}/print").text
    assert approved["sentence"] in page
    assert approved["quote"] in page
    assert rejected["sentence"] not in page
    assert approved["source_file"] in page
    assert f'/items/{item_id}/qr.svg' in page
    assert "not an official City notice" in page
    db.save_review(con, item_id, 0, approved, "rejected", approved["sentence"], "Test reviewer")
    db.save_review(con, item_id, 2, rec["claims"][2], "approved", rec["claims"][2]["sentence"], "Test reviewer")
    db.publish(con, rec, "Test reviewer")                       # version 2 drops the now-rejected sentence
    assert approved["sentence"] not in client.get(f"/items/{item_id}/print").text


def test_qr_targets_official_item_not_localhost(client, monkeypatch):
    seen = []
    original = appmod.segno.make_qr
    def capture(value, **kwargs):
        seen.append(value)
        return original(value, **kwargs)
    monkeypatch.setattr(appmod.segno, "make_qr", capture)
    response = client.get("/items/2027.PB1.6/qr.svg")
    assert response.status_code == 200
    assert ElementTree.fromstring(response.content).tag.endswith("svg")
    assert seen == ["https://secure.toronto.ca/council/agenda-item.do?item=2027.PB1.6"]
    assert client.get("/items/missing/print").status_code == 404
    assert client.get("/items/missing/qr.svg").status_code == 404


def test_confirmed_items_are_linked_from_agenda_and_ward(client):
    page = client.get("/meetings").text
    assert '/items/2027.PB1.5' in page and '/items/2027.PB1.6' in page
    assert 'item=2026.PB1' not in page and 'href="None"' not in page
    assert '/items/2027.PB1.5' in client.get("/near?ward=15").text
