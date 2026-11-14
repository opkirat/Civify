"""Civify web app: a staff review screen and a resident view.

Run:  uvicorn civify.app:app --reload   then open http://127.0.0.1:8000

Routes (staff routes require sign-in; resident routes are public)
  GET  /                         list of items
  GET  /login, POST /login, POST /logout
  GET  /staff                    pipeline view: every item's progress and what needs a person
  GET  /staff/{item_id}          review screen, sorted by lane: needs a look, blocked, ready
  POST /staff/{item_id}/approve-ready   publish every "ready" sentence in one click
  POST /staff/{item_id}/{index}  save one decision
  GET  /items/{item_id}          resident view: approved claims only
  GET  /near?address=|ward=      items and public notices in the resident's ward (address looked up live, never stored)
  GET  /notices/{notice_id}      one public notice: the Clerk's text as published, with how to take part
  GET  /meetings                 upcoming meetings from saved agendas: every item, by ward, with the City's rules quoted

Rules enforced here: nothing reaches the resident view until a signed-in
reviewer approved it; an approval counts only for the exact sentence and
evidence it was made on; and an edited sentence must still pass the verifier
against the same quote (so an edit cannot introduce an unsupported number).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from io import BytesIO

import segno

from fastapi import FastAPI, Form, HTTPException, Request
from urllib.parse import quote
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from civify import agenda, auth, db, geo, notices, workflow
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


@lru_cache(maxsize=16)
def verifier_for(item_id: str, filename: str) -> Verifier:
    return Verifier(extract(db.DATA / item_id / filename))


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

@app.get("/staff", response_class=HTMLResponse)
def staff_queue(request: Request):
    user = staff_user(request)
    con = db.connect(DB_PATH)
    items = []
    for rec in db.list_items():
        st = workflow.status(rec, db.load_item(rec["item_id"]), db.reviews_for(con, rec["item_id"]))
        items.append({**rec, "pipeline": st})
    items.sort(key=lambda it: -len(it["pipeline"]["attention"]))
    return templates.TemplateResponse(request, "staff_queue.html", {"items": items, "user": user})


@app.get("/staff/{item_id}", response_class=HTMLResponse)
def staff(request: Request, item_id: str):
    user = staff_user(request)
    rec = record_or_404(item_id)
    reviews = db.reviews_for(db.connect(DB_PATH), item_id)
    rows = []
    for c in workflow.lanes(rec):
        raw = reviews.get(c["index"])
        rows.append({**c, "review": db.current_review(raw, c), "stale": raw is not None and db.current_review(raw, c) is None})
    groups = {
        "review": [r for r in rows if not r["review"] and r["lane"] == "review"],
        "blocked": [r for r in rows if not r["review"] and r["lane"] == "blocked"],
        "ready": [r for r in rows if not r["review"] and r["lane"] == "ready"],
        "done": [r for r in rows if r["review"]],
    }
    pipeline = workflow.status(rec, db.load_item(item_id), reviews)
    return templates.TemplateResponse(request, "staff.html", {"rec": rec, "groups": groups, "pipeline": pipeline, "user": user,
                                                              "error": request.query_params.get("error"), "notice": request.query_params.get("notice")})


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
    return RedirectResponse(f"/staff/{item_id}?notice=Published+{n}+ready+sentence(s)", status_code=303)


@app.post("/staff/{item_id}/{index}")
def decide(request: Request, item_id: str, index: int, action: str = Form(...), sentence: str = Form("")):
    user = staff_user(request)
    rec = record_or_404(item_id)
    if not 0 <= index < len(rec["claims"]):
        raise HTTPException(404, "no such claim")
    claim = rec["claims"][index]
    con = db.connect(DB_PATH)
    if action == "reject":
        db.save_review(con, item_id, index, claim, "rejected", claim["sentence"], user["name"])
    elif action in ("approve", "edit"):
        final = sentence.strip() if action == "edit" else claim["sentence"]
        if not final:
            return RedirectResponse(f"/staff/{item_id}?error=Edited+sentence+is+empty#claim-{index}", status_code=303)
        check = verifier_for(item_id, claim["source_file"]).check(final, claim["quote"])
        if not check.verified:
            return RedirectResponse(f"/staff/{item_id}?error=Not+saved:+{quote(check.reason)}#claim-{index}", status_code=303)
        db.save_review(con, item_id, index, claim, "approved", final, user["name"])
    else:
        raise HTTPException(400, "unknown action")
    return RedirectResponse(f"/staff/{item_id}#claim-{index}", status_code=303)


@app.get("/items/{item_id}", response_class=HTMLResponse)
def item(request: Request, item_id: str):
    rec = record_or_404(item_id)
    claims = db.approved_claims(db.connect(DB_PATH), rec)
    return templates.TemplateResponse(request, "item.html", {"rec": rec, "claims": claims})


@app.get("/items/{item_id}/print", response_class=HTMLResponse)
def print_item(request: Request, item_id: str):
    rec = record_or_404(item_id)
    claims = db.approved_claims(db.connect(DB_PATH), rec)
    return templates.TemplateResponse(request, "print.html", {"rec": rec, "claims": claims})


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
