"""Where each item is in the pipeline, and what needs a person.

Workers see six steps per item, each done, needing attention, or not started,
plus a plain list of the specific things to fix, each linked to where to fix it.
Everything here is computed from files the pipeline wrote and the review table;
nothing is stored.
"""

from __future__ import annotations

import sqlite3

from civify import db
from civify.triage import assign_lane

STEPS = [
    ("documents", "Documents saved"),
    ("drafted", "Plain-language draft"),
    ("checked", "Checked against source"),
    ("meaning", "Meaning check"),
    ("reviewed", "Unsure ones reviewed"),
    ("published", "Live for residents"),
]


def lanes(record: dict) -> list[dict]:
    """Each claim with its lane, reasons and index. Falls back safely if triage hasn't run."""
    out = []
    for i, c in enumerate(record.get("claims", [])):
        if "lane" in c:
            lane, reasons = c["lane"], c.get("reasons", [])
        else:
            lane, reasons = assign_lane(c, None)
        out.append({**c, "index": i, "lane": lane, "reasons": reasons})
    return out


def status(record: dict, item: dict | None, reviews: dict[int, sqlite3.Row],
           publication: dict | None = None, escalations: list | None = None, changes: dict | None = None) -> dict:
    iid = record["item_id"]
    claims = lanes(record)
    docs = (item or {}).get("documents", [])
    unknown = [d for d in docs if d["doc_type"] == "unknown"]
    has_report = any(d["doc_type"] == "staff_report" for d in docs)
    meaning_run = any(c.get("meaning") for c in claims)

    decided, stale, waiting = {}, [], []
    for c in claims:
        raw = reviews.get(c["index"])
        cur = db.current_review(raw, c)
        if cur:
            decided[c["index"]] = cur["status"]
        elif raw is not None:
            stale.append(c)
        else:
            waiting.append(c)
    approved = sum(s == "approved" for s in decided.values())
    blocked = [c for c in waiting + stale if c["lane"] == "blocked"]
    review = [c for c in waiting + stale if c["lane"] == "review"]
    ready = [c for c in waiting + stale if c["lane"] == "ready"]

    escalations = escalations or []
    escalated = {e["claim_index"] for e in escalations}
    attention = []
    for e in escalations:
        attention.append({"text": f"Sentence {e['claim_index'] + 1} was escalated by {e['raised_by']}: “{e['note']}”", "href": f"/staff/{iid}#claim-{e['claim_index']}"})
    for d in unknown:
        attention.append({"text": f"{d['filename']} was not recognised. Check what it is: {d['evidence'][:80]}", "href": None})
    if docs and not has_report:
        attention.append({"text": "No staff report found, so there is nothing to explain yet.", "href": None})
    for c in stale:
        attention.append({"text": f"Sentence {c['index'] + 1} changed since it was reviewed. Review it again.", "href": f"/staff/{iid}#claim-{c['index']}"})
    for c in blocked:
        attention.append({"text": f"Sentence {c['index'] + 1} failed the source check ({c.get('reason')}). Edit so it passes, or reject.", "href": f"/staff/{iid}#claim-{c['index']}"})
    for c in review:
        if c["index"] in escalated:
            continue
        attention.append({"text": f"Sentence {c['index'] + 1} needs a look: {'; '.join(c['reasons'])}.", "href": f"/staff/{iid}#claim-{c['index']}"})
    if ready:
        attention.append({"text": f"{len(ready)} sentence(s) passed every check. Review and approve them, then publish.", "href": f"/staff/{iid}#ready"})
    changes = changes or {"added": 0, "removed": 0}
    unpublished = changes["added"] + changes["removed"]
    if unpublished:
        nxt = (publication["version"] + 1) if publication else 1
        attention.append({"text": f"{unpublished} approved change(s) are not on the resident page yet. Open the item and update it (version {nxt}).", "href": f"/staff/{iid}#publish"})
    if claims and not meaning_run:
        attention.append({"text": "Meaning check has not run. Review each sentence against its source.", "href": f"/staff/{iid}#review"})
    p = record.get("participation", {})
    if not p.get("council_has_decided") and not (p.get("written_comments_rule") or p.get("speaker_registration_rule")):
        attention.append({"text": "No item-specific rule for taking part was found. Confirm on the official item page before telling residents.", "href": record.get("official_url")})

    n = len(claims)
    state = {
        "documents": ("attention" if unknown or (docs and not has_report) else "done" if docs else "todo", f"{len(docs)} files" + (f", {len(unknown)} unrecognised" if unknown else "")),
        "drafted": ("done" if n else "todo", f"{n} sentences" if n else "not drafted"),
        "checked": ("attention" if any(c["lane"] == "blocked" for c in claims) else "done" if n else "todo",
                    f"{sum(1 for c in claims if c.get('verified'))}/{n} quotes found" if n else "-"),
        "meaning": ("done" if meaning_run else "attention" if n else "todo",
                    f"{sum(c['lane'] == 'ready' for c in claims)} ready, {sum(c['lane'] == 'review' for c in claims)} to look at" if meaning_run else "not run"),
        "reviewed": ("done" if n and not (waiting or stale) else "attention" if n else "todo", f"{len(decided)}/{n} decided" if n else "-"),
        "published": ("attention" if unpublished else "done" if publication else "todo",
                      (f"version {publication['version']} live · {len(publication['claims'])} sentences" if publication else "nothing live yet")
                      + (f" · {unpublished} change(s) waiting" if unpublished else "")),
    }
    return {
        "steps": [{"key": k, "label": label, "state": state[k][0], "detail": state[k][1]} for k, label in STEPS],
        "attention": attention,
        "counts": {"ready": len(ready), "review": len(review), "blocked": len(blocked), "stale": len(stale),
                   "approved": approved, "decided": len(decided), "total": n, "escalated": len(escalations),
                   "unpublished": unpublished, "live_version": publication["version"] if publication else None},
    }
