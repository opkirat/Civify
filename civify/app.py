"""Civify web app: a staff review screen and a resident view.

Run:  uvicorn civify.app:app --reload   then open http://127.0.0.1:8000

Routes
  GET  /                         list of items
  GET  /staff/{item_id}          review screen: each draft beside its quote; approve / edit / reject
  POST /staff/{item_id}/{index}  save one decision
  GET  /items/{item_id}          resident view: approved claims only
  GET  /near?address=|ward=      items and public notices in the resident's ward (address looked up live, never stored)
  GET  /notices/{notice_id}      one public notice: the Clerk's text as published, with how to take part

Rule enforced here: nothing reaches the resident view until a named reviewer
approved it, and an edited sentence must still pass the verifier against the
same quote (so an edit cannot introduce a number the record does not support).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from civify import db, geo, notices
from civify.extract import extract
from civify.verify import Verifier

app = FastAPI(title="Civify")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
DB_PATH = "civify.db"


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
    con = db.connect(DB_PATH)
    items = []
    for rec in db.list_items():
        reviews = db.reviews_for(con, rec["item_id"])
        items.append({**rec, "approved": sum(r["status"] == "approved" for r in reviews.values()),
                      "reviewed": len(reviews)})
    return templates.TemplateResponse(request, "index.html", {"items": items})


@app.get("/staff/{item_id}", response_class=HTMLResponse)
def staff(request: Request, item_id: str):
    rec = record_or_404(item_id)
    reviews = db.reviews_for(db.connect(DB_PATH), item_id)
    rows = [{"index": i, **c, "review": reviews.get(i)} for i, c in enumerate(rec["claims"])]
    return templates.TemplateResponse(request, "staff.html", {"rec": rec, "rows": rows, "error": request.query_params.get("error")})


@app.post("/staff/{item_id}/{index}")
def decide(item_id: str, index: int, action: str = Form(...), sentence: str = Form(""), reviewer: str = Form(...)):
    rec = record_or_404(item_id)
    if not 0 <= index < len(rec["claims"]):
        raise HTTPException(404, "no such claim")
    claim = rec["claims"][index]
    reviewer = reviewer.strip()
    if not reviewer:
        return RedirectResponse(f"/staff/{item_id}?error=Enter+your+name+as+reviewer", status_code=303)

    if action == "reject":
        db.save_review(db.connect(DB_PATH), item_id, index, "rejected", claim["sentence"], reviewer)
    elif action in ("approve", "edit"):
        final = sentence.strip() if action == "edit" else claim["sentence"]
        if not final:
            return RedirectResponse(f"/staff/{item_id}?error=Edited+sentence+is+empty", status_code=303)
        check = verifier_for(item_id, claim["source_file"]).check(final, claim["quote"])
        if not check.verified:
            return RedirectResponse(f"/staff/{item_id}?error=Edit+not+saved:+{check.reason.replace(' ', '+')}", status_code=303)
        db.save_review(db.connect(DB_PATH), item_id, index, "approved", final, reviewer)
    else:
        raise HTTPException(400, "unknown action")
    return RedirectResponse(f"/staff/{item_id}#claim-{index}", status_code=303)


@app.get("/items/{item_id}", response_class=HTMLResponse)
def item(request: Request, item_id: str):
    rec = record_or_404(item_id)
    claims = db.approved_claims(db.connect(DB_PATH), rec)
    return templates.TemplateResponse(request, "item.html", {"rec": rec, "claims": claims})


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
    return templates.TemplateResponse(request, "near.html", {
        "wards": geo.WARDS, "address": address, "ward": ward, "me": me, "results": results, "nearby": nearby,
        "searched": bool(address or ward)})


@app.get("/notices/{notice_id}", response_class=HTMLResponse)
def notice(request: Request, notice_id: int):
    n = next((x for x in notices.load() if x["notice_id"] == notice_id), None)
    if n is None:
        raise HTTPException(404, "no such notice in the current feed")
    return templates.TemplateResponse(request, "notice.html", {"n": n})
