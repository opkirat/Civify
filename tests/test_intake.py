"""Intake and processing, end to end, in a temporary data folder.

A worker uploads the real saved item page for 2027.PB1.6, the app validates it,
the pipeline fetches the linked staff report (from a fake HTTP call that serves
the local copy) and replays the saved AI replies, so no network or key is needed.
"""

import json
import shutil
from pathlib import Path

import pytest

from civify import db, intake, pipeline, record

SRC = Path("data/2027.PB1.6")
pytestmark = pytest.mark.skipif(not (SRC / "Agenda_Item_History.pdf").exists(), reason="source PDFs not in this checkout")


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(db, "DATA", data)
    monkeypatch.setattr(record, "lookup", lambda _a: None)                     # no network
    monkeypatch.setattr(pipeline, "FETCH_HTTP", lambda url: (SRC / url.rsplit("/", 1)[-1]).read_bytes())
    monkeypatch.setattr(pipeline, "DRAFT_CALL", lambda _p: (SRC / "draft_response.json").read_text())
    monkeypatch.setattr(pipeline, "MEANING_CALL", lambda _p: (SRC / "meaning_response.json").read_text())
    monkeypatch.setattr(pipeline, "CONFIRM_CALL", lambda _p: (SRC / "confirm_response.json").read_text())
    return data


def upload(staff, *names, item_id=""):
    files = [("files", (n, (SRC / n).read_bytes() if (SRC / n).exists() else n.encode(), "application/pdf")) for n in names]
    r = staff.post("/staff/intake", files=files, data={"item_id": item_id}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"].rsplit("/", 1)[-1]


def test_intake_validates_reads_item_id_and_flags_non_pdfs(staff, tmp_data):
    uid = upload(staff, "Agenda_Item_History.pdf", "notes.pdf")       # notes.pdf is plain text pretending to be a PDF
    m = intake.load(uid)
    by = {f["filename"]: f for f in m["files"]}
    assert by["Agenda_Item_History.pdf"]["state"] == "valid" and by["Agenda_Item_History.pdf"]["doc_type"] == "item_page"
    assert by["Agenda_Item_History.pdf"]["pages"] == 2
    assert by["notes.pdf"]["state"] == "invalid" and by["notes.pdf"]["error"] == "not a PDF file"
    assert m["item_id"] == "2027.PB1.6" and m["ready"]
    page = staff.get(f"/staff/intake/{uid}").text
    assert "not a PDF file" in page and "read from the item page: 2027.PB1.6" in page


def test_remove_file_and_missing_item_id_blocks_start(staff, tmp_data):
    uid = upload(staff, "backgroundfile-290746.pdf")
    m = intake.load(uid)
    assert not m["ready"] and any("agenda item number" in p for p in m["problems"])
    staff.post(f"/staff/intake/{uid}/remove", data={"filename": "backgroundfile-290746.pdf"})
    assert intake.load(uid)["files"] == []
    r = staff.post(f"/staff/intake/{uid}/start", follow_redirects=False)
    assert r.headers["location"] == f"/staff/intake/{uid}"                     # refused, back to intake


def test_duplicate_of_file_already_on_file_is_warned(staff, tmp_data):
    (tmp_data / "2027.PB1.6").mkdir()
    shutil.copy(SRC / "backgroundfile-290746.pdf", tmp_data / "2027.PB1.6")
    uid = upload(staff, "backgroundfile-290746.pdf", item_id="2027.PB1.6")
    assert any("already on file" in w for w in intake.load(uid)["files"][0]["warnings"])


def test_full_processing_run_then_review(staff, tmp_data):
    uid = upload(staff, "Agenda_Item_History.pdf")
    r = staff.post(f"/staff/intake/{uid}/start", follow_redirects=False)
    job_url = r.headers["location"]
    assert job_url.startswith("/staff/processing/")
    page = staff.get(job_url).text                                           # background task has run
    assert "Processing finished" in page and "Begin review" in page
    j = pipeline.job(db.connect(__import__("civify.app", fromlist=["DB_PATH"]).DB_PATH), int(job_url.rsplit("/", 1)[-1]))
    assert [s["status"] for s in j["steps"]] == ["done"] * 6
    assert "backgroundfile-290746.pdf" in j["steps"][1]["output"]["files"]     # fetched from the item page's link
    assert "11 sentences" in j["steps"][3]["detail"]
    rec = json.loads((tmp_data / "2027.PB1.6" / "record.json").read_text())
    assert rec["item_id"] == "2027.PB1.6" and len(rec["claims"]) == 11 and all("lane" in c for c in rec["claims"])
    page = staff.get("/staff/2027.PB1.6").text
    assert "Live for residents (8)" in page and "Needs you" in page
    assert "8 sentence(s) approved automatically · version 1 live" in j["steps"][5]["detail"]
    assert rec["claims"][next(i for i, c in enumerate(rec["claims"]) if c.get("auto"))]["sentence"] in staff.get("/items/2027.PB1.6").text


def test_missing_staff_report_blocks_and_retry_resumes(staff, tmp_data, monkeypatch):
    monkeypatch.setattr(pipeline, "FETCH_HTTP", lambda url: (_ for _ in ()).throw(OSError("offline")))
    uid = upload(staff, "Agenda_Item_History.pdf")
    job_url = staff.post(f"/staff/intake/{uid}/start", follow_redirects=False).headers["location"]
    page = staff.get(job_url).text
    assert "Failed" in page and "offline" in page and "Retry from the failed step" in page
    monkeypatch.setattr(pipeline, "FETCH_HTTP", lambda url: (SRC / url.rsplit("/", 1)[-1]).read_bytes())
    staff.post(job_url + "/retry")
    assert "Processing finished" in staff.get(job_url).text


def test_no_ai_key_is_shown_as_blocked_not_failed(staff, tmp_data, monkeypatch):
    monkeypatch.setattr(pipeline, "DRAFT_CALL", None)
    monkeypatch.setattr(pipeline, "load_env", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    uid = upload(staff, "Agenda_Item_History.pdf")
    page = staff.get(staff.post(f"/staff/intake/{uid}/start", follow_redirects=False).headers["location"]).text
    assert "Blocked" in page and "No AI key configured" in page


def test_intake_requires_sign_in(client):
    assert "/login" in client.get("/staff/intake", follow_redirects=False).headers["location"]
    assert "/login" in client.post("/staff/intake", follow_redirects=False).headers["location"]
