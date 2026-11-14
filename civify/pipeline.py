"""Run the whole pipeline for one item as a tracked job, step by step.

The same code the command-line tools use, run in the background after a worker
starts processing. Each step records its status, timing, a short detail and a
preliminary output, so the Processing page can show real progress and a Retry
button can resume from the step that failed.

Steps: save files → fetch linked records → classify → draft + source check (AI)
       → two AI checks (meaning, then in context) → build record, approve and publish what passed

AI output is reused automatically when nothing it depends on has changed
(same staff report for drafting; same sentences for the meaning check), so
retrying or re-running doesn't call the model again for no reason.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import date
from pathlib import Path
from typing import Callable

from civify import db, fetch, intake, record, sms, summary, triage
from civify.classify import DocType, classify
from civify.draft import draft, load_env
from civify.extract import extract
from civify.ingest import ingest

STEPS = [
    ("save", "Save files to the item"),
    ("fetch", "Fetch linked records"),
    ("classify", "Classify documents"),
    ("draft", "Draft summary and check sources (AI + code)"),
    ("meaning", "Two AI checks: meaning, then in context"),
    ("record", "Build the record, publish what passed, write the AI summary"),
]

# Swappable in tests; None means "call the real model".
DRAFT_CALL: Callable[[str], str] | None = None
MEANING_CALL: Callable[[str], str] | None = None
CONFIRM_CALL: Callable[[str], str] | None = None
FETCH_HTTP: Callable[[str], bytes] | None = None


class Blocked(Exception):
    """A step can't run until a person does something (shown as 'blocked', not 'failed')."""


def create_job(con, upload_id: str, item_id: str, who: str) -> int:
    cur = con.execute("INSERT INTO jobs (item_id, upload_id, status, started_by, created_at) VALUES (?, ?, 'queued', ?, ?)",
                      (item_id, upload_id, who, db.now()))
    job_id = cur.lastrowid
    for pos, (key, label) in enumerate(STEPS):
        con.execute("INSERT INTO job_steps (job_id, position, step, label, status) VALUES (?, ?, ?, ?, 'queued')", (job_id, pos, key, label))
    con.commit()
    return job_id


def job(con, job_id: int) -> dict | None:
    j = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if j is None:
        return None
    steps = [dict(s) | {"output": json.loads(s["output_json"]) if s["output_json"] else None}
             for s in con.execute("SELECT * FROM job_steps WHERE job_id = ? ORDER BY position", (job_id,))]
    return dict(j) | {"steps": steps}


def recent_jobs(con, limit: int = 20) -> list[dict]:
    return [job(con, r["id"]) for r in con.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def _set(con, job_id, pos, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    con.execute(f"UPDATE job_steps SET {cols} WHERE job_id = ? AND position = ?", (*fields.values(), job_id, pos))
    con.commit()


def run(db_path: str, job_id: int) -> None:
    """Run (or resume) a job. Steps already done are skipped, so Retry resumes."""
    con = db.connect(db_path)
    j = job(con, job_id) | {"db_path": db_path}
    con.execute("UPDATE jobs SET status = 'running', finished_at = NULL WHERE id = ?", (job_id,)); con.commit()
    folder = db.DATA / j["item_id"]
    final = "done"
    for s in j["steps"]:
        if s["status"] in ("done", "skipped"):
            continue
        _set(con, job_id, s["position"], status="running", started_at=db.now(), finished_at=None, detail=None, output_json=None)
        try:
            detail, output, status = STEP_FUNCS[s["step"]](j, folder)
            _set(con, job_id, s["position"], status=status, finished_at=db.now(), detail=detail, output_json=json.dumps(output) if output is not None else None)
        except Blocked as b:
            _set(con, job_id, s["position"], status="blocked", finished_at=db.now(), detail=str(b))
            final = "blocked"; break
        except Exception as e:
            _set(con, job_id, s["position"], status="failed", finished_at=db.now(),
                 detail=f"{type(e).__name__}: {e}", output_json=json.dumps({"trace": traceback.format_exc()[-1500:]}))
            final = "failed"; break
    con.execute("UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?", (final, db.now(), job_id)); con.commit()


def retry(con, job_id: int) -> None:
    """Reset the failed/blocked step and everything after it to queued."""
    con.execute("UPDATE job_steps SET status = 'queued', started_at = NULL, finished_at = NULL, detail = NULL, output_json = NULL "
                "WHERE job_id = ? AND status NOT IN ('done', 'skipped')", (job_id,))
    con.execute("UPDATE jobs SET status = 'queued' WHERE id = ?", (job_id,)); con.commit()


# --- the steps: each returns (detail, preliminary output, status) ---------------------

def step_save(j, folder):
    moved = intake.move_to_item(j["upload_id"], j["item_id"])
    return f"{len(moved)} new file(s) saved to the item", {"files": moved}, "done"


def step_fetch(j, folder):
    pages = [p for p in folder.glob("*.pdf") if classify(extract(p)).doc_type is DocType.ITEM_PAGE]
    if not pages:
        return "no saved item page, so there are no links to follow", None, "skipped"
    got = fetch.fetch_folder(folder, FETCH_HTTP)
    return f"downloaded {len(got)} linked record(s)", {"files": got}, "done"


def step_classify(j, folder):
    item = ingest(folder, date.today().isoformat())
    (folder / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False))
    counts = {}
    for d in item["documents"]:
        counts[d["doc_type"]] = counts.get(d["doc_type"], 0) + 1
    if not counts.get("staff_report"):
        raise Blocked("No staff report among the documents. Upload the staff report, or the item page that links to it.")
    return ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in sorted(counts.items())), \
        {"documents": [{"file": d["filename"], "type": d["doc_type"], "pages": d["pages"], "author": d["author"]} for d in item["documents"]]}, "done"


def _latest_report(folder: Path):
    reports = [(classify(d), d) for d in map(extract, sorted(folder.glob("*.pdf")))]
    reports = [(c, d) for c, d in reports if c.doc_type is DocType.STAFF_REPORT]
    return max(reports, key=lambda cd: (record._sortable(cd[0].fields.get("Date")), cd[1].filename))[1]


def step_draft(j, folder):
    report = _latest_report(folder)
    drafts_path, saved = folder / "drafts.json", folder / "draft_response.json"
    reuse = drafts_path.exists() and saved.exists() and all(c.get("source_sha256") == report.sha256 for c in json.loads(drafts_path.read_text()))
    if reuse:
        call, note = (lambda _p: saved.read_text()), "reused the saved AI draft (same staff report)"
    else:
        call = DRAFT_CALL or _live_call("draft")
        note = f"drafted from {report.filename}"
    raw, checked = draft(report, call)
    saved.write_text(raw)
    drafts_path.write_text(json.dumps(checked, indent=2, ensure_ascii=False))
    ok = sum(c["verified"] for c in checked)
    return f"{note}: {len(checked)} sentences, {ok} passed the source check", \
        {"sentences": [{"sentence": c["sentence"], "verified": c["verified"], "reason": c["reason"], "page": c["page"]} for c in checked]}, "done"


def step_meaning(j, folder):
    claims = json.loads((folder / "drafts.json").read_text())
    saved, saved_c, tri = folder / "meaning_response.json", folder / "confirm_response.json", folder / "triage.json"
    same = tri.exists() and [t["sentence"] for t in json.loads(tri.read_text())] == [c["sentence"] for c in claims]
    reuse_m, reuse_c = same and saved.exists(), same and saved_c.exists()
    raw, meaning = triage.check_meaning(claims, (lambda _p: saved.read_text()) if reuse_m else (MEANING_CALL or _live_call("meaning")))
    saved.write_text(raw)
    contexts = triage.contexts_for(claims, folder)
    raw, confirm = triage.check_confirm(claims, contexts, meaning,
                                        (lambda _p: saved_c.read_text()) if reuse_c else (CONFIRM_CALL or _live_call("confirm")))
    saved_c.write_text(raw)
    result = triage.triage(claims, meaning, confirm)
    tri.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    auto = sum(t["auto"] for t in result)
    lanes = {l: sum(t["lane"] == l for t in result) for l in ("ready", "review", "blocked")}
    return (("reused the saved AI checks: " if reuse_m and reuse_c else "") +
            f"{auto} can be approved automatically, {lanes['review']} need a person, {lanes['blocked']} blocked"), \
        {"lanes": lanes | {"auto": auto}}, "done"


def step_record(j, folder):
    rec = record.build(folder)
    (folder / "record.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    con = db.connect(j["db_path"])
    n = db.auto_approve(con, rec)
    version = db.sync_publication(con, rec, db.AUTO_REVIEWER)
    live = f" · version {version} live for residents" if version else ""
    pub = db.latest_publication(con, rec["item_id"])
    s = summary.refresh(rec["item_id"], [c["sentence"] for c in pub["claims"]]) if pub else None
    texted = sms.alert_new_item(con, rec)
    if texted and texted["sent"]:
        live += f" · texted {texted['sent']} subscriber(s)"
    live += " · AI summary " + ({"ok": "ready", "held": "held back by its checks"}[s["status"]] if s else "not made")
    return f"{rec['item_id']} · stage: {rec['current_stage'].replace('_', ' ')} · {'city-wide' if rec.get('citywide') else 'ward ' + str(rec.get('ward') or '?')} · {n} sentence(s) approved automatically{live}", \
        {"title": rec["title"], "stage": rec["current_stage"], "auto_approved": n, "version": version}, "done"


def _live_call(kind: str):
    load_env()
    if "GEMINI_API_KEY" not in os.environ:
        raise Blocked("No AI key configured (GEMINI_API_KEY). Ask an administrator to add it, then retry.")
    return {"draft": __import__("civify.draft", fromlist=["call_gemini"]).call_gemini,
            "meaning": triage.call_gemini, "confirm": triage.call_gemini_confirm}[kind]


STEP_FUNCS = {"save": step_save, "fetch": step_fetch, "classify": step_classify,
              "draft": step_draft, "meaning": step_meaning, "record": step_record}


def main() -> int:
    """Approve and publish what passed every check, for an item processed from the command line:
    python -m civify.pipeline data/2027.PB1.6"""
    import sys
    folder = Path(sys.argv[1])
    rec = db.load_record(folder.name)
    con = db.connect("civify.db")
    n = db.auto_approve(con, rec)
    version = db.sync_publication(con, rec, db.AUTO_REVIEWER)
    print(f"{rec['item_id']}: {n} sentence(s) approved automatically" + (f"; version {version} is live for residents." if version else "; nothing new to publish."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
