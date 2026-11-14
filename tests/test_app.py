"""Web app tests: the approval gate and the edit re-check, on the real TE34.21 record."""

from pathlib import Path

import pytest
from civify import app as appmod
from civify import db

pytestmark = pytest.mark.skipif(not Path("data/2026.TE34.21/backgroundfile-288412.pdf").exists(), reason="source PDFs not in this checkout")
ITEM = "2026.TE34.21"


def test_index_lists_the_item(client):
    r = client.get("/")
    assert r.status_code == 200 and "191-199 College Street" in r.text


def test_residents_see_nothing_until_staff_approve_and_publish(staff):
    assert "No approved explanation yet" in staff.get(f"/items/{ITEM}").text
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    assert "31 storeys to 45 storeys" not in staff.get(f"/items/{ITEM}").text      # approved but not published
    r = staff.post(f"/staff/{ITEM}/publish", follow_redirects=False)
    assert "Version+1" in r.headers["location"]
    page = staff.get(f"/items/{ITEM}").text
    assert "31 storeys to 45 storeys" in page and "Version 1, published" in page and "No approved explanation yet" not in page
    assert "Clerk A" not in page                                                       # reviewer names stay internal


def test_rejected_claim_never_shows_and_reviewer_comes_from_login(staff):
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})
    assert "31 storeys to 45 storeys" not in staff.get(f"/items/{ITEM}").text
    assert "Rejected by Clerk A" in staff.get(f"/staff/{ITEM}").text


def test_edit_is_rechecked_against_the_quote(staff):
    bad = staff.post(f"/staff/{ITEM}/1", data={"action": "edit", "sentence": "The height goes from 31 to 54 storeys."}, follow_redirects=False)
    assert bad.status_code == 303 and "Not+saved" in bad.headers["location"] and "54" in bad.headers["location"]
    assert "No approved explanation yet" in staff.get(f"/items/{ITEM}").text
    staff.post(f"/staff/{ITEM}/1", data={"action": "edit", "sentence": "The building would go from 31 to 45 storeys."})
    staff.post(f"/staff/{ITEM}/publish")
    assert "The building would go from 31 to 45 storeys." in staff.get(f"/items/{ITEM}").text


def test_staff_page_shows_stages_and_quoted_rules(staff):
    t = staff.get(f"/staff/{ITEM}").text
    assert "Proposed" in t and "Council decided" in t
    assert "no later than 12:00 p.m. on July 7, 2026" in t
    assert "Council has decided: <strong>yes</strong>" in t


# --- sign-in ---------------------------------------------------------------------

def test_staff_pages_and_actions_require_sign_in(client):
    for path in ("/staff", f"/staff/{ITEM}"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    r = client.post(f"/staff/{ITEM}/1", data={"action": "approve"}, follow_redirects=False)
    assert r.status_code == 303 and "/login" in r.headers["location"]
    r = client.post(f"/staff/{ITEM}/approve-ready", follow_redirects=False)
    assert "/login" in r.headers["location"]
    assert "No approved explanation yet" in client.get(f"/items/{ITEM}").text   # nothing slipped through
    assert client.get("/").status_code == 200 and client.get(f"/items/{ITEM}").status_code == 200  # residents unaffected


def test_wrong_password_is_refused_and_logout_ends_the_session(staff, client):
    client.post("/logout")
    assert client.get("/staff", follow_redirects=False).status_code == 303
    r = client.post("/login", data={"username": "clerka", "password": "wrong password!!"})
    assert r.status_code == 401 and "username and password" in r.text


def test_login_redirect_cannot_leave_the_staff_area(staff):
    r = staff.post("/login", data={"username": "clerka", "password": "correct horse battery", "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/staff"


# --- lanes, one-click publishing, and approvals bound to content ------------------

def test_approve_ready_publishes_only_ready_sentences(staff):
    rec = db.load_record(ITEM)
    ready = [c for c in rec["claims"] if c.get("lane") == "ready"]
    other = [c for c in rec["claims"] if c.get("lane") != "ready"]
    assert ready and other
    r = staff.post(f"/staff/{ITEM}/approve-ready", follow_redirects=False)
    assert f"Published+{len(ready)}+ready" in r.headers["location"]
    staff.post(f"/staff/{ITEM}/publish")
    page = staff.get(f"/items/{ITEM}").text
    assert all(c["sentence"] in page for c in ready)
    assert not any(c["sentence"] in page for c in other)


def test_staff_page_groups_sentences_by_lane_with_reasons(staff):
    t = staff.get(f"/staff/{ITEM}").text
    assert "Needs a look (" in t and "Ready (" in t and "Approve all" in t
    assert "states a recommendation or decision" in t
    assert "Documents saved" in t and "Meaning check" in t


def test_approval_stops_counting_when_the_sentence_changes(staff, monkeypatch):
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    rec = db.load_record(ITEM)
    changed = {**rec, "claims": [dict(c) for c in rec["claims"]]}
    changed["claims"][1]["sentence"] = "A redrafted sentence about 31 and 45 storeys."
    monkeypatch.setattr(appmod.db, "load_record", lambda item_id: changed)
    assert "31 storeys to 45 storeys" not in staff.get(f"/items/{ITEM}").text
    assert "Changed since last review" in staff.get(f"/staff/{ITEM}").text


def test_every_decision_is_kept_in_the_audit_log(staff):
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})
    rows = db.connect(appmod.DB_PATH).execute("SELECT action, reviewer FROM audit ORDER BY id").fetchall()
    assert [(r["action"], r["reviewer"]) for r in rows] == [("approved", "Clerk A"), ("rejected", "Clerk A")]


def test_pipeline_view_lists_what_needs_a_person(staff):
    t = staff.get("/staff").text
    assert "What needs you today" in t and "Next:" in t and "Plain-language draft" in t and "Add documents" in t


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
    assert "Toronto Preservation Board" in t and "2027.PB1.6" in t and "1337 Queen Street West" in t
    assert "register by 12:00 p.m. the day before" in t
    near = client.get("/near", params={"ward": "13"}).text
    assert "Coming up at a meeting, in your ward" in near and "66 Gerrard Street East" in near and "8 Arnold Avenue" not in near


# --- publishing versions, escalation, dashboard ------------------------------------

def test_publishing_freezes_a_version_and_later_approvals_wait_for_the_next(staff):
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    staff.post(f"/staff/{ITEM}/publish")
    rec = db.load_record(ITEM)
    staff.post(f"/staff/{ITEM}/2", data={"action": "approve"})
    assert rec["claims"][2]["sentence"] not in staff.get(f"/items/{ITEM}").text   # still version 1
    assert "Publish version 2" in staff.get(f"/staff/{ITEM}").text
    staff.post(f"/staff/{ITEM}/publish")
    page = staff.get(f"/items/{ITEM}").text
    assert rec["claims"][2]["sentence"] in page and "Version 2" in page


def test_publish_with_nothing_approved_is_refused(staff):
    r = staff.post(f"/staff/{ITEM}/publish", follow_redirects=False)
    assert "Approve+at+least+one" in r.headers["location"]


def test_escalate_needs_a_note_stays_internal_and_resolves_on_decision(staff):
    r = staff.post(f"/staff/{ITEM}/1", data={"action": "escalate"}, follow_redirects=False)
    assert "Add+a+note" in r.headers["location"]
    staff.post(f"/staff/{ITEM}/1", data={"action": "escalate", "note": "Check the storey count with planning"})
    t = staff.get(f"/staff/{ITEM}").text
    assert "Escalated (1)" in t and "Check the storey count with planning" in t
    assert "Check the storey count" in staff.get("/staff").text                      # shows on the dashboard
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    staff.post(f"/staff/{ITEM}/publish")
    assert "Escalated (" not in staff.get(f"/staff/{ITEM}").text
    assert "Check the storey count" not in staff.get(f"/items/{ITEM}").text          # notes never reach residents


def test_dashboard_search_and_filters(staff):
    t = staff.get("/staff", params={"q": "College"}).text
    assert "191-199 College Street" in t and "1337 Queen Street West" not in t
    assert "1337 Queen Street West" not in staff.get("/staff", params={"show": "published"}).text
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"}); staff.post(f"/staff/{ITEM}/publish")
    t = staff.get("/staff", params={"show": "published"}).text
    assert "191-199 College Street" in t and "Version 1 live" in t
