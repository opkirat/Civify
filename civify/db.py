"""The only state the app keeps: staff accounts and their decisions.

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
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username),
    created_at TEXT NOT NULL
);
"""


def connect(path: str = "civify.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # Databases created before approvals were bound to content lack the column.
    if "claim_hash" not in {r["name"] for r in con.execute("PRAGMA table_info(reviews)")}:
        con.execute("ALTER TABLE reviews ADD COLUMN claim_hash TEXT")
    return con


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


def save_review(con: sqlite3.Connection, item_id: str, idx: int, claim: dict, status: str, sentence: str, reviewer: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    h = claim_hash(claim)
    con.execute("INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)", (item_id, idx, status, sentence, reviewer, now, h))
    con.execute("INSERT INTO audit (item_id, claim_index, claim_hash, action, sentence, reviewer, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item_id, idx, h, status, sentence, reviewer, now))
    con.commit()


def approved_claims(con: sqlite3.Connection, record: dict) -> list[dict]:
    """What residents may see: current approvals only, with any staff edit applied."""
    reviews = reviews_for(con, record["item_id"])
    out = []
    for i, claim in enumerate(record["claims"]):
        r = current_review(reviews.get(i), claim)
        if r and r["status"] == "approved":
            out.append({**claim, "sentence": r["sentence"]})
    return out
