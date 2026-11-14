"""Web app tests: the approval gate and the edit re-check, on the real TE34.21 record."""

import json
from pathlib import Path

import pytest
from civify import app as appmod
from civify import db

pytestmark = pytest.mark.skipif(not Path("data/2026.TE34.21/backgroundfile-288412.pdf").exists(), reason="source PDFs not in this checkout")
ITEM = "2026.TE34.21"


def test_index_lists_the_item(client):
    r = client.get("/")
    assert r.status_code == 200 and "191-199 College Street" in r.text


def test_approving_puts_a_sentence_live_straight_away(staff):
    assert "No explanation yet" in staff.get(f"/items/{ITEM}").text
    r = staff.post(f"/staff/{ITEM}/1", data={"action": "approve"}, follow_redirects=False)
    assert "now%20live" in r.headers["location"] and "version%201" in r.headers["location"]
    page = staff.get(f"/items/{ITEM}").text
    assert "31 storeys to 45 storeys" in page and "No explanation yet" not in page
    assert "Clerk A" not in page                                                       # reviewer names stay internal


def test_rejected_claim_never_shows_and_reviewer_comes_from_login(staff):
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})
    assert "31 storeys to 45 storeys" not in staff.get(f"/items/{ITEM}").text
    assert "Rejected by Clerk A" in staff.get(f"/staff/{ITEM}").text


def test_edit_is_rechecked_against_the_quote(staff):
    bad = staff.post(f"/staff/{ITEM}/1", data={"action": "edit", "sentence": "The height goes from 31 to 54 storeys."}, follow_redirects=False)
    assert bad.status_code == 303 and "Not+saved" in bad.headers["location"] and "54" in bad.headers["location"]
    assert "No explanation yet" in staff.get(f"/items/{ITEM}").text
    staff.post(f"/staff/{ITEM}/1", data={"action": "edit", "sentence": "The building would go from 31 to 45 storeys."})
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
    assert "No explanation yet" in client.get(f"/items/{ITEM}").text   # nothing slipped through
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
    assert f"Approved+{len(ready)}+sentence" in r.headers["location"]
    page = staff.get(f"/items/{ITEM}").text
    assert all(c["sentence"] in page for c in ready)
    assert not any(c["sentence"] in page for c in other)


def test_staff_page_groups_sentences_by_lane_with_reasons(staff):
    t = staff.get(f"/staff/{ITEM}").text
    assert "Needs you" in t and "passed the checks" in t and "Approve all" in t
    assert "context check: held" in t and "Approve suggested wording" in t
    assert "Documents saved" in t and "Meaning check" in t


def test_approval_stops_counting_when_the_sentence_changes(staff, monkeypatch):
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    rec = db.load_record(ITEM)
    changed = {**rec, "claims": [dict(c) for c in rec["claims"]]}
    changed["claims"][1]["sentence"] = "A redrafted sentence about 31 and 45 storeys."
    monkeypatch.setattr(appmod.db, "load_record", lambda item_id: changed)
    con = db.connect(appmod.DB_PATH)
    assert db.approved_claims(con, changed) == []
    db.sync_publication(con, changed, db.AUTO_REVIEWER)                  # what a pipeline re-run does
    assert "31 storeys to 45 storeys" not in staff.get(f"/items/{ITEM}").text
    assert "Changed since last review" in staff.get(f"/staff/{ITEM}").text


def test_every_decision_is_kept_in_the_audit_log(staff):
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})
    rows = db.connect(appmod.DB_PATH).execute("SELECT action, reviewer FROM audit ORDER BY id").fetchall()
    assert [(r["action"], r["reviewer"]) for r in rows] == [("approved", "Clerk A"), ("published", "Clerk A"),
                                                            ("rejected", "Clerk A"), ("published", "Clerk A")]


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
    monkeypatch.setattr(appmod.geo, "search_address", lambda a: {"status": "matched", "candidates": [], "match": {"address": "100 Queen St W", "ward": "10",
                                                        "ward_name": "Spadina-Fort York", "lat": 43.6534, "lon": -79.3841}})
    r = client.get("/near", params={"address": "100 Queen St W"})
    assert "Ward 10, Spadina-Fort York" in r.text and "km from your address" in r.text


def test_near_unknown_address_explains(client, monkeypatch):
    monkeypatch.setattr(appmod.geo, "search_address", lambda a: {"status":"not_found", "match":None, "candidates":[]})
    r = client.get("/near", params={"address": "1 Nowhere Rd"})
    assert "couldn't find that address" in r.text


@pytest.mark.skipif(not Path("data/notices.json").exists(), reason="feed not built")
def test_near_lists_public_notices_and_notice_page_quotes_the_clerk(client):
    r = client.get("/near", params={"ward": "13"})
    assert "Public notices from the City Clerk" in r.text and "In your ward" in r.text
    import json
    n = json.loads(Path("data/notices.json").read_text())[0]
    page = client.get(f"/notices/{n['notice_id']}")
    assert page.status_code == 200 and n["title"].split(" - ")[-1].strip() in page.text and "as published by the City Clerk" in page.text
    assert client.get("/notices/1").status_code == 404


@pytest.mark.skipif(not Path("data/agendas/2026-11-16-PB1.json").exists(), reason="agenda not parsed")
def test_meetings_page_and_upcoming_items_in_ward(client):
    t = client.get("/meetings").text
    assert "Toronto Preservation Board" in t and "2027.PB1.6" in t and "1337 Queen Street West" in t
    assert "register by 12:00 p.m. the day before" in t
    near = client.get("/near", params={"ward": "13"}).text
    assert "Coming up at a meeting, in your ward" in near
    # Other wards can appear in the separate collapsed browse section.
    upcoming = near.split("Coming up at a meeting, in your ward", 1)[1].split("</details>", 1)[0]
    assert "66 Gerrard Street East" in upcoming and "8 Arnold Avenue" not in upcoming


# --- publishing versions, escalation, dashboard ------------------------------------

def test_every_decision_makes_a_new_frozen_version(staff):
    rec = db.load_record(ITEM)
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    staff.post(f"/staff/{ITEM}/2", data={"action": "approve"})
    page = staff.get(f"/items/{ITEM}").text
    assert rec["claims"][2]["sentence"] in page
    staff.post(f"/staff/{ITEM}/2", data={"action": "reject"})
    page = staff.get(f"/items/{ITEM}").text
    assert rec["claims"][2]["sentence"] not in page
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})               # last one gone: page goes back to empty
    assert "No explanation yet" in staff.get(f"/items/{ITEM}").text
    staff.post(f"/staff/{ITEM}/1", data={"action": "escalate", "note": "x"})
    assert db.latest_publication(db.connect(appmod.DB_PATH), ITEM)["version"] == 4   # escalating publishes nothing


def test_publish_with_nothing_approved_is_refused(staff):
    r = staff.post(f"/staff/{ITEM}/publish", follow_redirects=False)
    assert "Approve+at+least+one" in r.headers["location"]


def test_escalate_needs_a_note_stays_internal_and_resolves_on_decision(staff):
    r = staff.post(f"/staff/{ITEM}/1", data={"action": "escalate"}, follow_redirects=False)
    assert "Add+a+note" in r.headers["location"]
    staff.post(f"/staff/{ITEM}/1", data={"action": "escalate", "note": "Check the storey count with planning"})
    t = staff.get(f"/staff/{ITEM}").text
    assert "Escalated by" in t and "Check the storey count with planning" in t
    assert "Check the storey count" in staff.get("/staff").text                      # shows on the dashboard
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    assert "Escalated by" not in staff.get(f"/staff/{ITEM}").text
    assert "Check the storey count" not in staff.get(f"/items/{ITEM}").text          # notes never reach residents


def test_dashboard_search_and_filters(staff):
    t = staff.get("/staff", params={"q": "College"}).text
    assert "191-199 College Street" in t and "1337 Queen Street West" not in t
    assert "1337 Queen Street West" not in staff.get("/staff", params={"show": "published"}).text
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    t = staff.get("/staff", params={"show": "published"}).text
    assert "191-199 College Street" in t and "Version 1 live" in t


def test_review_cards_link_to_the_pdf_page_and_show_the_quote_in_context(staff):
    page = staff.get(f"/staff/{ITEM}").text
    assert f"/staff/{ITEM}/source/" in page and "#page=" in page
    assert "<mark>" in page and "Read it in context" in page
    rec = json.loads((Path("data") / ITEM / "record.json").read_text())
    c = next(c for c in rec["claims"] if c.get("verified"))
    r = staff.get(f"/staff/{ITEM}/source/{c['source_file']}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    assert staff.get(f"/staff/{ITEM}/source/..%2F..%2Fcivify.db").status_code == 404
    assert staff.get(f"/staff/{ITEM}/source/record.json").status_code == 404
    staff.post("/logout")                                        # signed out: the PDF is staff-only
    r = staff.get(f"/staff/{ITEM}/source/{c['source_file']}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_auto_approved_sentences_go_live_and_a_person_can_take_them_down(staff):
    rec = db.load_record(ITEM)
    con = db.connect(appmod.DB_PATH)
    n = db.auto_approve(con, rec)
    assert n == sum(1 for c in rec["claims"] if c.get("auto")) and n > 0
    assert db.auto_approve(con, rec) == 0                                    # idempotent
    assert db.sync_publication(con, rec, db.AUTO_REVIEWER) == 1              # what the pipeline does next
    page = staff.get(f"/staff/{ITEM}").text
    assert f"Live for residents ({n})" in page and "approved automatically" in page
    auto_sentence = next(c["sentence"] for c in rec["claims"] if c.get("auto"))
    resident = staff.get(f"/items/{ITEM}").text
    assert auto_sentence in resident and "auto-check" not in resident
    assert not any(c["sentence"] in resident for c in rec["claims"] if not c.get("auto"))   # unsure ones stay off
    i = next(i for i, c in enumerate(rec["claims"]) if c.get("auto"))
    staff.post(f"/staff/{ITEM}/{i}", data={"action": "reject"})               # a person can overrule it
    assert db.current_review(db.reviews_for(con, ITEM)[i], rec["claims"][i])["status"] == "rejected"
    assert rec["claims"][i]["sentence"] not in staff.get(f"/items/{ITEM}").text
    assert db.auto_approve(con, rec) == 0                                     # and it is not re-approved


def test_held_sentence_offers_suggested_wording(staff):
    rec = db.load_record(ITEM)
    held = [c for c in rec["claims"] if c.get("confirm") and c["confirm"]["verdict"] == "hold" and c["confirm"]["suggestion"]]
    if held:
        assert "Approve suggested wording" in staff.get(f"/staff/{ITEM}").text


def test_citywide_item_shows_for_every_ward(client, monkeypatch):
    rec = {**db.load_record(ITEM), "item_id": "2026.CC38.1", "ward": None, "citywide": True, "location": None}
    monkeypatch.setattr(appmod.db, "list_items", lambda: [rec])
    for ward in ("1", "25"):
        page = client.get("/near", params={"ward": ward}).text
        assert "City-wide" in page and "/items/2026.CC38.1" in page


def test_resident_page_shows_labelled_ai_summary_over_verified_sentences(staff, monkeypatch, tmp_path):
    from civify import summary
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    rec = db.load_record(ITEM)
    live = rec["claims"][1]["sentence"]
    page = staff.get(f"/items/{ITEM}").text
    assert "AI-generated" not in page and live in page                              # no summary yet: sentences shown directly
    monkeypatch.setattr(summary, "path_for", lambda item_id: tmp_path / "summary.json")
    (tmp_path / "summary.json").write_text(json.dumps({"status": "ok", "based_on": [live],
        "sentences": [{"text": "A plain summary of the change.", "uses": [live]}], "issues": []}))
    page = staff.get(f"/items/{ITEM}").text
    assert "AI-generated" in page and "A plain summary of the change." in page and "written by AI" in page
    assert "See each sentence with its source (1)" in page and live in page
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})                        # its source is gone: summary withdrawn
    assert "A plain summary of the change." not in staff.get(f"/items/{ITEM}").text


def test_printable_notice_carries_the_same_ai_summary(staff, monkeypatch, tmp_path):
    from civify import summary
    staff.post(f"/staff/{ITEM}/1", data={"action": "approve"})
    live = db.load_record(ITEM)["claims"][1]["sentence"]
    monkeypatch.setattr(summary, "path_for", lambda item_id: tmp_path / "summary.json")
    page = staff.get(f"/items/{ITEM}/print").text
    assert "AI-generated" not in page and live in page                              # no summary: sentences only
    (tmp_path / "summary.json").write_text(json.dumps({"status": "ok", "based_on": [live],
        "sentences": [{"text": "A plain summary of the change.", "uses": [live]}], "issues": []}))
    page = staff.get(f"/items/{ITEM}/print").text
    assert "AI-generated" in page and "A plain summary of the change." in page
    assert page.index("A plain summary of the change.") < page.index(live)        # summary first, then the evidence
    (tmp_path / "summary.json").write_text(json.dumps({"status": "held", "based_on": [live],
        "sentences": [{"text": "A held summary.", "uses": [live]}], "issues": ["guardrail held"]}))
    assert "A held summary." not in staff.get(f"/items/{ITEM}/print").text          # held summaries never print
    (tmp_path / "summary.json").write_text(json.dumps({"status": "ok", "based_on": [live],
        "sentences": [{"text": "A plain summary of the change.", "uses": [live]}], "issues": []}))
    staff.post(f"/staff/{ITEM}/1", data={"action": "reject"})                        # its source is gone: not printed
    assert "A plain summary of the change." not in staff.get(f"/items/{ITEM}/print").text


def test_pipeline_view_is_visible_on_dashboard_and_item_page(staff):
    for path in ("/staff", f"/staff/{ITEM}"):
        t = staff.get(path).text
        assert 'class="pipeline' in t and "AI summary" in t and "Live for residents" in t
        assert t.index('class="pipeline') < t.index("Item details" if path == "/staff" else "Record details")
    assert "What needs a person" in staff.get(f"/staff/{ITEM}").text


def test_issue_page_counts_public_submissions_without_names(client):
    rec = db.load_record(ITEM)
    page = client.get(f"/items/{ITEM}").text
    assert rec["public_letters"] > 0 and f"received {rec['public_letters']} written submission" in page


def test_auto_approval_can_be_switched_off(staff, monkeypatch):
    monkeypatch.setenv("CIVIFY_AUTO_APPROVE", "0")
    assert db.auto_approve(db.connect(appmod.DB_PATH), db.load_record(ITEM)) == 0
