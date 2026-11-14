"""Civify web app: a staff review screen and a resident view.

Run:  uvicorn civify.app:app --reload   then open http://127.0.0.1:8000

Routes (staff routes require sign-in; resident routes are public)
  GET  /                         list of items
  GET  /login, POST /login, POST /logout
  GET  /staff                    dashboard: every item's progress, what needs a person, search and filters
  GET  /staff/intake, POST ...   upload PDFs, validate them, confirm the item, start processing
  GET  /staff/processing/{job}   watch each pipeline step run; preliminary outputs; retry
  POST /staff/{item_id}/publish  freeze the current approvals as the next version residents see
  GET  /staff/{item_id}          review screen: sentences that need a person, each beside the passage in context
  GET  /staff/{item_id}/source/{file}   the source PDF itself (open at a page with #page=N)
  POST /staff/{item_id}/approve-ready   publish every "ready" sentence in one click
  POST /staff/{item_id}/{index}  save one decision
  GET  /items/{item_id}          resident view: approved claims only
  GET  /near?address=|ward=      items and public notices in the resident's ward (address looked up live, never stored)
  GET  /notices/{notice_id}      one public notice: the Clerk's text as published, with how to take part
  GET  /meetings                 upcoming meetings from saved agendas: every item, by ward, with the City's rules quoted

Rules enforced here: residents see only a published version, made of sentences a
signed-in reviewer approved; an approval counts only for the exact sentence and
evidence it was made on; and an edited sentence must still pass the verifier
against the same quote (so an edit cannot introduce an unsupported number).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from io import BytesIO

import segno

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from urllib.parse import quote
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from civify import agenda, auth, db, geo, intake, notices, pipeline, source, workflow
from civify.extract import extract
from civify.verify import Verifier

app = FastAPI(title="Civify")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
DB_PATH = "civify.db"

STAGE_LABELS = {"staff_recommendation": "Proposed", "committee_decision": "Committee considered",
                "council_decision": "Council decided", "enacted": "By-laws enacted"}
templates.env.filters["stage_label"] = lambda value: STAGE_LABELS.get(value, value.replace("_", " "))
templates.env.filters["item_name"] = lambda title: (title or "Untitled item").split(" - ", 2)[1] if " - " in (title or "") else title
templates.env.filters["item_topic"] = lambda title: (title or "").split(" - ", 2)[2] if (title or "").count(" - ") >= 2 else ""


@lru_cache(maxsize=32)
def document_for(item_id: str, filename: str):
    return extract(db.DATA / item_id / filename)


@lru_cache(maxsize=16)
def verifier_for(item_id: str, filename: str) -> Verifier:
    return Verifier(document_for(item_id, filename))


def record_or_404(item_id: str) -> dict:
    rec = db.load_record(item_id)
    if rec is None:
        raise HTTPException(404, f"no record for {item_id}")
    return rec


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"items": db.list_items(), "wards": geo.WARDS})


# --- sign-in -----------------------------------------------------------------

COOKIE = "civify_session"


class LoginRequired(Exception):
    def __init__(self, path: str):
        self.path = path


@app.exception_handler(LoginRequired)
def _to_login(request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={quote(exc.path)}", status_code=303)


def staff_user(request: Request):
    user = auth.user_for(db.connect(DB_PATH), request.cookies.get(COOKIE))
    if user is None:
        raise LoginRequired(request.url.path)
    return user


def _safe_next(path: str) -> str:
    return path if path.startswith("/staff") and not path.startswith("//") else "/staff"


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/staff"):
    return templates.TemplateResponse(request, "login.html", {"next": _safe_next(next), "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/staff")):
    token = auth.sign_in(db.connect(DB_PATH), username, password)
    if token is None:
        return templates.TemplateResponse(request, "login.html", {"next": _safe_next(next), "error": "That username and password don't match."}, status_code=401)
    resp = RedirectResponse(_safe_next(next), status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=auth.SESSION_HOURS * 3600)
    return resp


@app.post("/logout")
def logout(request: Request):
    auth.sign_out(db.connect(DB_PATH), request.cookies.get(COOKIE))
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# --- staff ---------------------------------------------------------------------

def _item_state(con, rec: dict) -> dict:
    iid = rec["item_id"]
    pub = db.latest_publication(con, iid)
    esc = db.open_escalations(con, iid)
    changes = db.unpublished_changes(con, rec)
    st = workflow.status(rec, db.load_item(iid), db.reviews_for(con, iid), pub, esc, changes)
    last = con.execute("SELECT MAX(at) FROM audit WHERE item_id = ?", (iid,)).fetchone()[0]
    job = con.execute("SELECT * FROM jobs WHERE item_id = ? ORDER BY id DESC LIMIT 1", (iid,)).fetchone()
    stamps = [x for x in (last, job["finished_at"] or job["created_at"] if job else None) if x]
    c = st["counts"]
    tags = set()
    if c["blocked"] or (job and job["status"] in ("failed", "blocked")): tags.add("blocked")
    if c["review"] or c["stale"] or c["escalated"]: tags.add("review")
    if c["unpublished"]: tags.add("awaiting")
    if pub: tags.add("published")
    if job and job["status"] in ("queued", "running"): tags.add("processing")
    return {**rec, "pipeline": st, "publication": pub, "job": dict(job) if job else None, "tags": tags,
            "last_update": max(stamps) if stamps else rec.get("retrieved"),
            "last_by": con.execute("SELECT reviewer FROM audit WHERE item_id = ? ORDER BY id DESC LIMIT 1", (iid,)).fetchone(),
            "next_action": st["attention"][0]["text"] if st["attention"] else "Nothing to do."}


FILTERS = {"all": "All items", "review": "Needs review", "blocked": "Blocked or failed", "awaiting": "Awaiting publishing",
           "published": "Published", "processing": "Processing"}


@app.get("/staff", response_class=HTMLResponse)
def staff_queue(request: Request, q: str = "", show: str = "all", sort: str = "attention"):
    user = staff_user(request)
    con = db.connect(DB_PATH)
    items = [_item_state(con, rec) for rec in db.list_items()]
    counts = {k: (len(items) if k == "all" else sum(k in it["tags"] for it in items)) for k in FILTERS}
    if show in FILTERS and show != "all":
        items = [it for it in items if show in it["tags"]]
    if q.strip():
        needle = q.strip().lower()
        items = [it for it in items if needle in f"{it['item_id']} {it['title']} ward {it.get('ward')}".lower()]
    if sort == "updated":
        items.sort(key=lambda it: it["last_update"] or "", reverse=True)
    elif sort == "ward":
        items.sort(key=lambda it: int(it.get("ward") or 99))
    else:
        items.sort(key=lambda it: -len(it["pipeline"]["attention"]))
    jobs = [j for j in pipeline.recent_jobs(con, 8) if j]
    return templates.TemplateResponse(request, "staff_queue.html", {"items": items, "user": user, "q": q, "show": show,
                                      "sort": sort, "filters": FILTERS, "counts": counts, "jobs": jobs})


# --- intake: upload, validate, confirm, start --------------------------------------

@app.get("/staff/intake", response_class=HTMLResponse)
def intake_new(request: Request):
    return templates.TemplateResponse(request, "intake.html", {"user": staff_user(request), "m": None, "max_mb": intake.MAX_BYTES // 2**20})


async def _save_uploads(uid: str, files: list[UploadFile]) -> None:
    for f in files:
        if f.filename:
            intake.add_file(uid, f.filename, await f.read())


@app.post("/staff/intake")
async def intake_create(request: Request, files: list[UploadFile] = File(default=[]), item_id: str = Form("")):
    staff_user(request)
    uid = intake.new_upload()
    await _save_uploads(uid, files)
    intake.set_meta(uid, item_id)
    intake.validate(uid)
    return RedirectResponse(f"/staff/intake/{uid}", status_code=303)


@app.get("/staff/intake/{uid}", response_class=HTMLResponse)
def intake_view(request: Request, uid: str):
    user = staff_user(request)
    try:
        m = intake.load(uid)
    except ValueError:
        raise HTTPException(404, "no such upload")
    return templates.TemplateResponse(request, "intake.html", {"user": user, "m": m, "max_mb": intake.MAX_BYTES // 2**20})


@app.post("/staff/intake/{uid}/files")
async def intake_add(request: Request, uid: str, files: list[UploadFile] = File(default=[])):
    staff_user(request)
    await _save_uploads(uid, files)
    intake.validate(uid)
    return RedirectResponse(f"/staff/intake/{uid}", status_code=303)


@app.post("/staff/intake/{uid}/remove")
def intake_remove(request: Request, uid: str, filename: str = Form(...)):
    staff_user(request)
    intake.remove_file(uid, filename)
    intake.validate(uid)
    return RedirectResponse(f"/staff/intake/{uid}", status_code=303)


@app.post("/staff/intake/{uid}/meta")
def intake_meta(request: Request, uid: str, item_id: str = Form("")):
    staff_user(request)
    intake.set_meta(uid, item_id)
    intake.validate(uid)
    return RedirectResponse(f"/staff/intake/{uid}", status_code=303)


@app.post("/staff/intake/{uid}/start")
def intake_start(request: Request, uid: str, background: BackgroundTasks):
    user = staff_user(request)
    m = intake.validate(uid)
    if not m["ready"]:
        return RedirectResponse(f"/staff/intake/{uid}", status_code=303)
    con = db.connect(DB_PATH)
    job_id = pipeline.create_job(con, uid, m["item_id"], user["name"])
    background.add_task(pipeline.run, DB_PATH, job_id)
    return RedirectResponse(f"/staff/processing/{job_id}", status_code=303)


# --- processing: watch the steps, inspect preliminary outputs, retry ----------------

@app.get("/staff/processing", response_class=HTMLResponse)
def processing_list(request: Request):
    user = staff_user(request)
    return templates.TemplateResponse(request, "processing.html", {"user": user, "job": None, "jobs": pipeline.recent_jobs(db.connect(DB_PATH), 30)})


@app.get("/staff/processing/{job_id}", response_class=HTMLResponse)
def processing(request: Request, job_id: int):
    user = staff_user(request)
    j = pipeline.job(db.connect(DB_PATH), job_id)
    if j is None:
        raise HTTPException(404, "no such processing run")
    files = intake.load(j["upload_id"]).get("files", [])
    return templates.TemplateResponse(request, "processing.html", {"user": user, "job": j, "files": files, "jobs": None})


@app.post("/staff/processing/{job_id}/retry")
def processing_retry(request: Request, job_id: int, background: BackgroundTasks):
    staff_user(request)
    con = db.connect(DB_PATH)
    if pipeline.job(con, job_id) is None:
        raise HTTPException(404, "no such processing run")
    pipeline.retry(con, job_id)
    background.add_task(pipeline.run, DB_PATH, job_id)
    return RedirectResponse(f"/staff/processing/{job_id}", status_code=303)


@app.get("/staff/{item_id}", response_class=HTMLResponse)
def staff(request: Request, item_id: str):
    user = staff_user(request)
    rec = record_or_404(item_id)
    reviews = db.reviews_for(db.connect(DB_PATH), item_id)
    rows = []
    for c in workflow.lanes(rec):
        raw = reviews.get(c["index"])
        ctx = source.locate(document_for(item_id, c["source_file"]), c["quote"], c.get("page")) if c.get("source_file") else None
        rows.append({**c, "review": db.current_review(raw, c), "stale": raw is not None and db.current_review(raw, c) is None, "context": ctx})
    groups = {
        "review": [r for r in rows if not r["review"] and r["lane"] == "review"],
        "blocked": [r for r in rows if not r["review"] and r["lane"] == "blocked"],
        "ready": [r for r in rows if not r["review"] and r["lane"] == "ready"],
        "done": [r for r in rows if r["review"]],
    }
    con = db.connect(DB_PATH)
    esc = {e["claim_index"]: e for e in db.open_escalations(con, item_id)}
    for r in rows:
        r["escalation"] = esc.get(r["index"])
    groups["escalated"] = [r for r in rows if not r["review"] and r["escalation"]]
    groups["review"] = [r for r in groups["review"] if not r["escalation"]]
    pub = db.latest_publication(con, item_id)
    changes = db.unpublished_changes(con, rec)
    pipeline_status = workflow.status(rec, db.load_item(item_id), reviews, pub, list(esc.values()), changes)
    history = con.execute("SELECT * FROM audit WHERE item_id = ? ORDER BY id DESC LIMIT 40", (item_id,)).fetchall()
    return templates.TemplateResponse(request, "staff.html", {"rec": rec, "groups": groups, "pipeline": pipeline_status, "user": user,
                                                              "publication": pub, "changes": changes, "history": history,
                                                              "error": request.query_params.get("error"), "notice": request.query_params.get("notice")})


@app.get("/staff/{item_id}/source/{filename}")
def source_pdf(request: Request, item_id: str, filename: str):
    """The PDF a quote came from, for the reviewer's own eyes. Opened with #page=N by the review screen."""
    staff_user(request)
    path = db.DATA / item_id / filename
    if "/" in filename or filename.startswith(".") or path.suffix.lower() != ".pdf" or not path.is_file():
        raise HTTPException(404, "no such source file")
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@app.post("/staff/{item_id}/approve-ready")
def approve_ready(request: Request, item_id: str):
    """One click for every sentence that passed all checks and hasn't been reviewed yet.
    Each one is re-verified against its source before it is saved."""
    user = staff_user(request)
    rec = record_or_404(item_id)
    con = db.connect(DB_PATH)
    reviews = db.reviews_for(con, item_id)
    n = 0
    for c in workflow.lanes(rec):
        if c["lane"] != "ready" or db.current_review(reviews.get(c["index"]), c):
            continue
        if verifier_for(item_id, c["source_file"]).check(c["sentence"], c["quote"]).verified:
            db.save_review(con, item_id, c["index"], c, "approved", c["sentence"], user["name"])
            n += 1
    return RedirectResponse(f"/staff/{item_id}?notice=Approved+{n}+ready+sentence(s).+Publish+when+you+are+ready.#review", status_code=303)


@app.post("/staff/{item_id}/publish")
def publish(request: Request, item_id: str):
    user = staff_user(request)
    rec = record_or_404(item_id)
    try:
        version = db.publish(db.connect(DB_PATH), rec, user["name"])
    except ValueError:
        return RedirectResponse(f"/staff/{item_id}?error=Approve+at+least+one+sentence+before+publishing#publish", status_code=303)
    return RedirectResponse(f"/staff/{item_id}?notice=Version+{version}+is+now+visible+to+residents#publish", status_code=303)


@app.post("/staff/{item_id}/{index}")
def decide(request: Request, item_id: str, index: int, action: str = Form(...), sentence: str = Form(""), note: str = Form("")):
    user = staff_user(request)
    rec = record_or_404(item_id)
    if not 0 <= index < len(rec["claims"]):
        raise HTTPException(404, "no such claim")
    claim = rec["claims"][index]
    con = db.connect(DB_PATH)
    note = note.strip() or None
    if action == "escalate":
        if not note:
            return RedirectResponse(f"/staff/{item_id}?error=Add+a+note+saying+why+you+are+escalating#claim-{index}", status_code=303)
        db.escalate(con, item_id, index, claim, note, user["name"])
    elif action == "reject":
        db.save_review(con, item_id, index, claim, "rejected", claim["sentence"], user["name"], note)
    elif action in ("approve", "edit"):
        final = sentence.strip() if action == "edit" else claim["sentence"]
        if not final:
            return RedirectResponse(f"/staff/{item_id}?error=Edited+sentence+is+empty#claim-{index}", status_code=303)
        check = verifier_for(item_id, claim["source_file"]).check(final, claim["quote"])
        if not check.verified:
            return RedirectResponse(f"/staff/{item_id}?error=Not+saved:+{quote(check.reason)}#claim-{index}", status_code=303)
        db.save_review(con, item_id, index, claim, "approved", final, user["name"], note)
    else:
        raise HTTPException(400, "unknown action")
    message = "Second opinion requested." if action == "escalate" else "Review saved. It will appear to residents only after publishing."
    return RedirectResponse(f"/staff/{item_id}?notice={quote(message)}#review", status_code=303)


@app.get("/items/{item_id}", response_class=HTMLResponse)
def item(request: Request, item_id: str):
    rec = record_or_404(item_id)
    pub = db.latest_publication(db.connect(DB_PATH), item_id)
    return templates.TemplateResponse(request, "item.html", {"rec": rec, "claims": pub["claims"] if pub else [], "publication": pub})


@app.get("/items/{item_id}/print", response_class=HTMLResponse)
def print_item(request: Request, item_id: str):
    rec = record_or_404(item_id)
    pub = db.latest_publication(db.connect(DB_PATH), item_id)
    return templates.TemplateResponse(request, "print.html", {"rec": rec, "claims": pub["claims"] if pub else [], "publication": pub})


@app.get("/items/{item_id}/qr.svg")
def item_qr(item_id: str):
    rec = record_or_404(item_id)
    out = BytesIO()
    # The official URL works on a resident's phone even when this demo is local.
    segno.make_qr(rec["official_url"], error="m").save(out, kind="svg", scale=4, border=4)
    return Response(out.getvalue(), media_type="image/svg+xml")


@app.get("/near", response_class=HTMLResponse)
def near(request: Request, address: str = "", ward: str = ""):
    """Resident lookup. The address goes to the City's API for one request and is not kept."""
    address, ward = address.strip(), ward.strip()
    me = None
    if address:
        me = geo.lookup(address)
    elif ward:
        me = {"ward": ward.lstrip("0"), "ward_name": geo.WARDS.get(ward.zfill(2), ""), "address": None}
    results, nearby = [], []
    if me:
        for rec in db.list_items():
            km = geo.distance_km(me, rec["location"]) if rec.get("location") and "lat" in me else None
            results.append({"rec": rec, "same_ward": rec.get("ward") == me["ward"], "km": km})
        results.sort(key=lambda r: (not r["same_ward"], r["km"] if r["km"] is not None else 1e9))
        for n in notices.load():
            kms = [geo.distance_km(me, a) for a in n["addresses"]] if "lat" in me else []
            nearby.append({"n": n, "same_ward": n.get("ward") == me["ward"], "km": min(kms) if kms else None})
        nearby.sort(key=lambda r: (not r["same_ward"], r["km"] if r["km"] is not None else 1e9))
    upcoming = []
    if me:
        for m in agenda.load_meetings(db.list_items()):
            for it in m["items"]:
                if it.get("ward") == me["ward"]:
                    upcoming.append({"meeting": m, "item": it})
    return templates.TemplateResponse(request, "near.html", {
        "wards": geo.WARDS, "address": address, "ward": ward, "me": me, "results": results, "nearby": nearby,
        "upcoming": upcoming, "rules": agenda.load_rules(), "searched": bool(address or ward)})


@app.get("/meetings", response_class=HTMLResponse)
def meetings(request: Request):
    return templates.TemplateResponse(request, "meetings.html", {"meetings": agenda.load_meetings(db.list_items()), "rules": agenda.load_rules(), "wards": geo.WARDS})


@app.get("/notices/{notice_id}", response_class=HTMLResponse)
def notice(request: Request, notice_id: int):
    n = next((x for x in notices.load() if x["notice_id"] == notice_id), None)
    if n is None:
        raise HTTPException(404, "no such notice in the current feed")
    return templates.TemplateResponse(request, "notice.html", {"n": n})
