"""A short AI summary for residents, written only from sentences that are already live.

Residents see the summary first, labelled as AI-written, and can expand it to read
each verified sentence with its exact source quote. No person approves the summary;
instead it has to pass the same kind of checks a sentence does:

1. WRITE (AI call 1). The model gets only the live sentences, numbered, and writes
   two or three plain sentences (about 60 words). Each summary sentence must list which numbered
   sentences it relies on.
2. CODE CHECK. Every summary sentence must cite at least one live sentence, and
   every number in it must appear in the sentences it cites.
3. GUARDRAIL (AI call 2). A second call reads each summary sentence beside the
   sentences it cites, told to hold when in doubt: nothing added, nothing stated
   more strongly, no condition or decision status lost.

4. REPAIR. If the code check or the guardrail holds it, the writer gets the reasons
   and one more try; the rewrite goes through the same checks.

If it still fails, there is no summary and residents see the verified sentences
directly. A summary is shown only while every sentence it cites is still live, so
rejecting a sentence withdraws any summary built on it.

Run:  python -m civify.summary data/2027.PB1.6     (needs GEMINI_API_KEY)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from civify import db
from civify.draft import DEFAULT_MODEL, load_env
from civify.verify import numbers

WRITE_PROMPT = """You are writing a short summary of a City of Toronto council item for residents.

Use ONLY the numbered sentences below. They have already been checked against the official
records. Do not add any fact, number, name, date or opinion that is not in them.

Write 2 or 3 short sentences, 60 words or fewer in total, in plain language (grade 8 reading
level). Pick only the most important facts: what is proposed or decided, where, and what happens
next if the sentences say so. Leave detail out; residents can expand the full list of sentences.
Keep who does what exactly as stated (staff recommend, Council decided, the owner must).
Keep any condition or uncertainty that changes the meaning. Stay neutral: no praise, criticism
or prediction. Keep every number exactly as it is written in the sentences.

For each summary sentence, list the numbers of the sentences it relies on in "uses".

SENTENCES:
{sentences}
"""

CHECK_PROMPT = """You are the last check before an AI-written summary is shown to residents of Toronto
WITHOUT any person reading it first. When in doubt, hold.

For each numbered SUMMARY sentence you get the SOURCE sentences it relies on. Those source
sentences were already checked against the official records.

Approve only if ALL are true:
- every fact in the summary sentence is in its source sentences;
- nothing is stated more strongly or more certainly, and who does what is unchanged
  (a staff recommendation must not read as a Council decision);
- no condition, exception or uncertainty that changes the meaning is lost;
- the wording is neutral.

For every summary sentence return: verdict "approve" or "hold", and issue (one short sentence, or "").

ITEMS:
{items}
"""


class SummarySentence(BaseModel):
    text: str
    uses: list[int] = Field(min_length=1)


class Written(BaseModel):
    sentences: list[SummarySentence] = Field(min_length=1, max_length=4)


class Verdict(BaseModel):
    index: int
    verdict: Literal["approve", "hold"]
    issue: str


class Checked(BaseModel):
    results: list[Verdict]


# Swappable in tests; None means "call the real model".
WRITE_CALL: Callable[[str], str] | None = None
CHECK_CALL: Callable[[str], str] | None = None


def _gemini(schema):
    def call(prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0),
        ).text
    return call


def path_for(item_id: str) -> Path:
    return db.DATA / item_id / "summary.json"


REPAIR = """
A previous summary was held back by the checks. Fix every problem below and write it again.
PREVIOUS SUMMARY: {previous}
PROBLEMS:
{problems}
"""

ATTEMPTS = 2   # first try, plus one repair using the checks' reasons


def make(live: list[str], write: Callable[[str], str], check: Callable[[str], str]) -> dict:
    """Write and check a summary of the live sentences, with one repair attempt.
    Never raises for a bad summary: returns {"status": "ok" | "held", ...} so the reason is kept."""
    out = None
    for attempt in range(1, ATTEMPTS + 1):
        feedback = "" if out is None else REPAIR.format(
            previous=" ".join(x["text"] for x in out["sentences"]), problems="\n".join(f"- {i}" for i in out["issues"]))
        out = _attempt(live, write, check, feedback)
        out["attempts"] = attempt
        if out["status"] == "ok":
            break
    return out


def _attempt(live: list[str], write: Callable[[str], str], check: Callable[[str], str], feedback: str) -> dict:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(live, 1))
    written = Written.model_validate_json(write(WRITE_PROMPT.format(sentences=numbered) + feedback))
    out = {"status": "ok", "based_on": live, "sentences": [], "issues": [],
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "model": os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)}
    for k, s in enumerate(written.sentences, 1):
        uses = [live[u - 1] for u in dict.fromkeys(s.uses) if 1 <= u <= len(live)]
        if not uses:
            out["issues"].append(f"summary sentence {k} cites no live sentence")
        extra = numbers(s.text) - set().union(*(numbers(u) for u in uses)) if uses else set()
        if extra:
            out["issues"].append(f"summary sentence {k} has number(s) not in its sources: {', '.join(sorted(extra))}")
        out["sentences"].append({"text": s.text.strip(), "uses": uses})
    if out["issues"]:
        out["status"] = "held"
        return out
    items = "\n".join(f"{k}. SUMMARY: {s['text']}\n   SOURCES: " + " | ".join(s["uses"]) for k, s in enumerate(out["sentences"], 1))
    verdicts = {v.index: v for v in Checked.model_validate_json(check(CHECK_PROMPT.format(items=items))).results}
    for k in range(1, len(out["sentences"]) + 1):
        v = verdicts.get(k)
        if v is None or v.verdict != "approve":
            out["issues"].append(f"summary sentence {k}: guardrail held" + (f" ({v.issue})" if v and v.issue else " (no verdict)"))
    if out["issues"]:
        out["status"] = "held"
    return out


def refresh(item_id: str, live: list[str]) -> dict | None:
    """Make sure data/<item>/summary.json matches the live sentences. Does nothing if it
    already does (no AI cost). Returns the summary, or None if it couldn't be made
    (no live sentences, no AI key, or the model call failed): residents then see the
    verified sentences without a summary."""
    p = path_for(item_id)
    if not live:
        return None
    if p.exists():
        old = json.loads(p.read_text())
        if old.get("based_on") == live:
            return old
    write, check = WRITE_CALL, CHECK_CALL
    if write is None or check is None:
        load_env()
        if "GEMINI_API_KEY" not in os.environ:
            return None
        write, check = write or _gemini(Written), check or _gemini(Checked)
    try:
        result = make(live, write, check)
    except Exception:
        return None
    p.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result


def for_residents(item_id: str, live: list[str]) -> dict | None:
    """The summary to show, or None. Shown only if it passed and every sentence it cites is still live."""
    p = path_for(item_id)
    if not p.exists():
        return None
    s = json.loads(p.read_text())
    if s.get("status") != "ok":
        return None
    current = set(live)
    return s if all(u in current for x in s["sentences"] for u in x["uses"]) else None


def refresh_item(db_path: str, item_id: str) -> None:
    """Background task after a staff decision: rebuild the summary for what is now live."""
    pub = db.latest_publication(db.connect(db_path), item_id)
    if pub and pub["claims"]:
        refresh(item_id, [c["sentence"] for c in pub["claims"]])


def main() -> int:
    folder = Path(sys.argv[1])
    pub = db.latest_publication(db.connect("civify.db"), folder.name)
    live = [c["sentence"] for c in pub["claims"]] if pub else []
    s = refresh(folder.name, live)
    if s is None:
        print("No summary: nothing live yet, no GEMINI_API_KEY, or the model call failed.")
        return 1
    print(f"{s['status'].upper()}: " + " ".join(x["text"] for x in s["sentences"]))
    for i in s["issues"]:
        print("  ↳", i)
    return 0


if __name__ == "__main__":
    sys.exit(main())
