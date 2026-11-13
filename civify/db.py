"""The only state the app keeps: staff decisions about each draft claim.

Everything else (stages, votes, claims, sources) is read from record.json,
which the pipeline produced and which can be regenerated at any time. The
decisions live in SQLite so they survive restarts and give an audit trail of
who-approved-what-when (the "who" is a free-text reviewer name for now).
"""

from __future__ import annotations

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
    PRIMARY KEY (item_id, claim_index)
);
"""


def connect(path: str = "civify.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def list_items() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(DATA.glob("*/record.json"))]


def load_record(item_id: str) -> dict | None:
    p = DATA / item_id / "record.json"
    return json.loads(p.read_text()) if p.exists() else None


def reviews_for(con: sqlite3.Connection, item_id: str) -> dict[int, sqlite3.Row]:
    rows = con.execute("SELECT * FROM reviews WHERE item_id = ?", (item_id,)).fetchall()
    return {r["claim_index"]: r for r in rows}


def save_review(con: sqlite3.Connection, item_id: str, idx: int, status: str, sentence: str, reviewer: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, idx, status, sentence, reviewer, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    con.commit()


def approved_claims(con: sqlite3.Connection, record: dict) -> list[dict]:
    """What residents may see: approved claims only, with any staff edit applied."""
    out = []
    for i, claim in enumerate(record["claims"]):
        r = reviews_for(con, record["item_id"]).get(i)
        if r and r["status"] == "approved":
            out.append({**claim, "sentence": r["sentence"]})
    return out
