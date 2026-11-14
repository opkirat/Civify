"""The only state the app keeps: staff accounts, their decisions, published
versions, escalations, and processing runs.

Everything else (stages, votes, claims, sources) is read from record.json,
which the pipeline produced and which can be regenerated at any time.

Each decision is bound to the exact content it approved: a hash of the
sentence, its quote and the source file's checksum. If the pipeline is re-run
and a sentence or its evidence changes, the old approval no longer counts and
the sentence goes back to review. Every decision is also appended to an audit
log that is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA = Path("data")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    item_id      TEXT NOT NULL,
    claim_index  INTEGER NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('approved', 'rejected')),
    sentence     TEXT NOT NULL,   -- the sentence as approved (may be a staff edit)
    reviewer     TEXT NOT NULL,
    reviewed_at  TEXT NOT NULL,
    claim_hash   TEXT,            -- what was reviewed; a mismatch means the draft changed since
    PRIMARY KEY (item_id, claim_index)
);
CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL,
    claim_index  INTEGER NOT NULL,
    claim_hash   TEXT NOT NULL,
    action       TEXT NOT NULL,
    sentence     TEXT NOT NULL,
    reviewer     TEXT NOT NULL,
    at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
    item_id      TEXT NOT NULL,
    version      INTEGER NOT NULL,
    published_at TEXT NOT NULL,
    published_by TEXT NOT NULL,
    claims_json  TEXT NOT NULL,   -- the exact approved sentences residents see, frozen
    PRIMARY KEY (item_id, version)
);
CREATE TABLE IF NOT EXISTS escalations (
    item_id      TEXT NOT NULL,
    claim_index  INTEGER NOT NULL,
    claim_hash   TEXT NOT NULL,
    note         TEXT NOT NULL,   -- internal; never shown to residents
    raised_by    TEXT NOT NULL,
    raised_at    TEXT NOT NULL,
    resolved_by  TEXT,
    resolved_at  TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT,
    upload_id   TEXT NOT NULL,
    status      TEXT NOT NULL,    -- queued, running, done, failed, blocked
    started_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS job_steps (
    job_id      INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    step        TEXT NOT NULL,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL,    -- queued, running, done, failed, blocked, skipped
    started_at  TEXT,
    finished_at TEXT,
    detail      TEXT,
    output_json TEXT,
    PRIMARY KEY (job_id, position)
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sms_subscriptions (
    phone TEXT PRIMARY KEY,
    ward TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'stopped')),
    code_hash TEXT,
    code_expires TEXT,
    code_attempts INTEGER NOT NULL DEFAULT 0,
    requested_at TEXT NOT NULL,
    confirmed_at TEXT,
    last_alert_at TEXT
);
CREATE TABLE IF NOT EXISTS sms_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL UNIQUE,
    publication_version INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sms_deliveries (
    campaign_id INTEGER NOT NULL REFERENCES sms_campaigns(id),
    phone TEXT NOT NULL REFERENCES sms_subscriptions(phone),
    status TEXT NOT NULL,
    provider_id TEXT,
    at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, phone)
);
"""


def connect(path: str = "civify.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # Databases created before approvals were bound to content lack the column.
    if "claim_hash" not in {r["name"] for r in con.execute("PRAGMA table_info(reviews)")}:
        con.execute("ALTER TABLE reviews ADD COLUMN claim_hash TEXT")
    if "note" not in {r["name"] for r in con.execute("PRAGMA table_info(audit)")}:
        con.execute("ALTER TABLE audit ADD COLUMN note TEXT")
    if "code_attempts" not in {r["name"] for r in con.execute("PRAGMA table_info(sms_subscriptions)")}:
        con.execute("ALTER TABLE sms_subscriptions ADD COLUMN code_attempts INTEGER NOT NULL DEFAULT 0")
    return con


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def claim_hash(claim: dict) -> str:
    parts = [claim["sentence"], claim["quote"], claim.get("source_sha256", "")]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def list_items() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(DATA.glob("*/record.json"))]


def load_record(item_id: str) -> dict | None:
    p = DATA / item_id / "record.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_item(item_id: str) -> dict | None:
    p = DATA / item_id / "item.json"
    return json.loads(p.read_text()) if p.exists() else None


def reviews_for(con: sqlite3.Connection, item_id: str) -> dict[int, sqlite3.Row]:
    rows = con.execute("SELECT * FROM reviews WHERE item_id = ?", (item_id,)).fetchall()
    return {r["claim_index"]: r for r in rows}


def current_review(review: sqlite3.Row | None, claim: dict) -> sqlite3.Row | None:
    """A review counts only if it was made on exactly this sentence and evidence."""
    return review if review is not None and review["claim_hash"] == claim_hash(claim) else None


def log(con: sqlite3.Connection, item_id: str, idx: int, h: str, action: str, sentence: str, who: str, note: str | None = None) -> None:
    con.execute("INSERT INTO audit (item_id, claim_index, claim_hash, action, sentence, reviewer, at, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, idx, h, action, sentence, who, now(), note))


def save_review(con: sqlite3.Connection, item_id: str, idx: int, claim: dict, status: str, sentence: str, reviewer: str, note: str | None = None) -> None:
    h = claim_hash(claim)
    con.execute("INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)", (item_id, idx, status, sentence, reviewer, now(), h))
    log(con, item_id, idx, h, status, sentence, reviewer, note)
    # A decision resolves any open escalation on this sentence.
    con.execute("UPDATE escalations SET resolved_by = ?, resolved_at = ? WHERE item_id = ? AND claim_index = ? AND resolved_at IS NULL",
                (reviewer, now(), item_id, idx))
    con.commit()


AUTO_REVIEWER = "auto-check"   # not a valid username, so no person can sign in as it
AUTO_NOTE = ("Approved automatically: the quote is in the source, every number matches, and two separate "
             "AI checks (against the quote, then against the whole page) found the sentence fully supported and neutral.")


def auto_approve(con: sqlite3.Connection, record: dict) -> int:
    """Approve every sentence the triage marked "auto", unless a person already decided
    this exact sentence or it is escalated. Logged like any decision; a person can
    reject or edit it later. Callers publish afterwards with sync_publication."""
    if os.environ.get("CIVIFY_AUTO_APPROVE", "1") == "0":   # a person approves every sentence; checks still guide them
        return 0
    iid = record["item_id"]
    reviews = reviews_for(con, iid)
    escalated = {e["claim_index"] for e in open_escalations(con, iid)}
    n = 0
    for i, c in enumerate(record.get("claims", [])):
        if c.get("auto") and c.get("verified") and i not in escalated and current_review(reviews.get(i), c) is None:
            save_review(con, iid, i, c, "approved", c["sentence"], AUTO_REVIEWER, AUTO_NOTE)
            n += 1
    return n


# --- escalations: "a senior reviewer should decide this", with an internal note --------

def escalate(con: sqlite3.Connection, item_id: str, idx: int, claim: dict, note: str, who: str) -> None:
    h = claim_hash(claim)
    con.execute("INSERT INTO escalations (item_id, claim_index, claim_hash, note, raised_by, raised_at) VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, idx, h, note, who, now()))
    log(con, item_id, idx, h, "escalated", claim["sentence"], who, note)
    con.commit()


def open_escalations(con: sqlite3.Connection, item_id: str | None = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM escalations WHERE resolved_at IS NULL" + (" AND item_id = ?" if item_id else "") + " ORDER BY raised_at"
    return con.execute(q, (item_id,) if item_id else ()).fetchall()


# --- publications: what residents see is a frozen, numbered version -----------------

def publish(con: sqlite3.Connection, record: dict, who: str, allow_empty: bool = False) -> int:
    claims = approved_claims(con, record)
    if not claims and not allow_empty:
        raise ValueError("nothing approved to publish")
    keep = ("sentence", "quote", "page", "source_file", "source_sha256")
    frozen = [{k: c.get(k) for k in keep} for c in claims]   # no lanes, reasons, notes or reviewer names
    version = (con.execute("SELECT MAX(version) FROM publications WHERE item_id = ?", (record["item_id"],)).fetchone()[0] or 0) + 1
    con.execute("INSERT INTO publications VALUES (?, ?, ?, ?, ?)", (record["item_id"], version, now(), who, json.dumps(frozen)))
    log(con, record["item_id"], -1, "", "published", f"version {version} ({len(frozen)} sentences)", who)
    con.commit()
    return version


def sync_publication(con: sqlite3.Connection, record: dict, who: str) -> int | None:
    """Make what residents see match the current approvals: approving a sentence puts it
    live, rejecting or editing one updates the page. Each change is a new frozen
    version, so the history of what residents saw is kept. Returns the new version,
    or None if nothing changed (or nothing has ever been approved)."""
    ch = unpublished_changes(con, record)
    if not (ch["added"] or ch["removed"]):
        return None
    return publish(con, record, who, allow_empty=True)


def latest_publication(con: sqlite3.Connection, item_id: str) -> dict | None:
    row = con.execute("SELECT * FROM publications WHERE item_id = ? ORDER BY version DESC LIMIT 1", (item_id,)).fetchone()
    if row is None:
        return None
    return {"version": row["version"], "published_at": row["published_at"], "published_by": row["published_by"],
            "claims": json.loads(row["claims_json"])}


def unpublished_changes(con: sqlite3.Connection, record: dict) -> dict:
    """How the current approvals differ from what residents see now."""
    current = {c["sentence"] for c in approved_claims(con, record)}
    pub = latest_publication(con, record["item_id"])
    live = {c["sentence"] for c in pub["claims"]} if pub else set()
    return {"added": len(current - live), "removed": len(live - current), "live": len(live), "approved": len(current)}


def approved_claims(con: sqlite3.Connection, record: dict) -> list[dict]:
    """What residents may see: current approvals only, with any staff edit applied."""
    reviews = reviews_for(con, record["item_id"])
    out = []
    for i, claim in enumerate(record["claims"]):
        r = current_review(reviews.get(i), claim)
        if r and r["status"] == "approved":
            out.append({**claim, "sentence": r["sentence"]})
    return out
