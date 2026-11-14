"""Web app tests: the approval gate and the edit re-check, on the real TE34.21 record."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civify import app as appmod

pytestmark = pytest.mark.skipif(not Path("data/2026.TE34.21/backgroundfile-288412.pdf").exists(), reason="source PDFs not in this checkout")
ITEM = "2026.TE34.21"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "test.db"))  # fresh database per test
    return TestClient(appmod.app)


def test_index_lists_the_item(client):
    r = client.get("/")
    assert r.status_code == 200 and "191-199 College Street" in r.text


def test_resident_view_is_empty_until_staff_approve(client):
    r = client.get(f"/items/{ITEM}")
    assert "No approved explanation yet" in r.text
    client.post(f"/staff/{ITEM}/1", data={"action": "approve", "reviewer": "Clerk A"})
    r = client.get(f"/items/{ITEM}")
    assert "31 storeys to 45 storeys" in r.text and "No approved explanation yet" not in r.text


def test_rejected_claim_never_shows(client):
    client.post(f"/staff/{ITEM}/1", data={"action": "reject", "reviewer": "Clerk A"})
    assert "31 storeys to 45 storeys" not in client.get(f"/items/{ITEM}").text
    assert "rejected by Clerk A" in client.get(f"/staff/{ITEM}").text


def test_edit_is_rechecked_against_the_quote(client):
    bad = client.post(f"/staff/{ITEM}/1", data={"action": "edit", "reviewer": "Clerk A",
                      "sentence": "The height goes from 31 to 54 storeys."}, follow_redirects=False)
    assert bad.status_code == 303 and "Edit+not+saved" in bad.headers["location"] and "54" in bad.headers["location"]
    assert "No approved explanation yet" in client.get(f"/items/{ITEM}").text

    good = client.post(f"/staff/{ITEM}/1", data={"action": "edit", "reviewer": "Clerk A",
                       "sentence": "The building would go from 31 to 45 storeys."})
    assert "The building would go from 31 to 45 storeys." in client.get(f"/items/{ITEM}").text


def test_reviewer_name_is_required(client):
    r = client.post(f"/staff/{ITEM}/1", data={"action": "approve", "reviewer": "  "}, follow_redirects=False)
    assert "Enter+your+name" in r.headers["location"]
    assert "No approved explanation yet" in client.get(f"/items/{ITEM}").text


def test_staff_page_shows_stages_and_quoted_rules(client):
    t = client.get(f"/staff/{ITEM}").text
    assert "Staff recommendation" in t and "Council decision" in t
    assert "no later than 12:00 p.m. on July 7, 2026" in t
    assert "Council has decided: <strong>yes</strong>" in t


def test_near_by_ward_lists_item_in_that_ward_and_stores_nothing(client, tmp_path):
    r = client.get("/near", params={"ward": "11"})
    assert r.status_code == 200 and "In your ward" in r.text and "191-199 College Street" in r.text
    r = client.get("/near", params={"ward": "1"})
    assert "In your ward" not in r.text and "Ward 11" in r.text
    assert not (tmp_path / "test.db").exists()  # the lookup never even opened the database


def test_near_by_address_uses_city_lookup(client, monkeypatch):
    monkeypatch.setattr(appmod.geo, "lookup", lambda a: {"address": "100 Queen St W", "ward": "10",
                                                        "ward_name": "Spadina-Fort York", "lat": 43.6534, "lon": -79.3841})
    r = client.get("/near", params={"address": "100 Queen St W"})
    assert "Ward 10, Spadina-Fort York" in r.text and "km from your address" in r.text


def test_near_unknown_address_explains(client, monkeypatch):
    monkeypatch.setattr(appmod.geo, "lookup", lambda a: None)
    r = client.get("/near", params={"address": "1 Nowhere Rd"})
    assert "couldn't find that address" in r.text


@pytest.mark.skipif(not Path("data/notices.json").exists(), reason="feed not built")
def test_near_lists_public_notices_and_notice_page_quotes_the_clerk(client):
    r = client.get("/near", params={"ward": "13"})
    assert "Public notices from the City Clerk" in r.text and "In your ward" in r.text
    import json
    n = json.loads(Path("data/notices.json").read_text())[0]
    page = client.get(f"/notices/{n['notice_id']}")
    assert page.status_code == 200 and n["title"] in page.text and "as published by the City Clerk" in page.text
    assert client.get("/notices/1").status_code == 404


@pytest.mark.skipif(not Path("data/agendas/2026-11-16-PB1.json").exists(), reason="agenda not parsed")
def test_meetings_page_and_upcoming_items_in_ward(client):
    t = client.get("/meetings").text
    assert "Toronto Preservation Board" in t and "2026.PB1.6" in t and "1337 Queen Street West" in t
    assert "register by 12:00 p.m. the day before" in t
    near = client.get("/near", params={"ward": "13"}).text
    assert "Coming up at a meeting, in your ward" in near and "66 Gerrard Street East" in near and "8 Arnold Avenue" not in near
