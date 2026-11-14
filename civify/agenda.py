"""Turn a saved TMMIS meeting agenda into a list of upcoming items by ward.

A person saves the agenda page (Print to PDF or Save as HTML); this reads the
meeting details and every item on it: id, title, ward, and any posted notes
("A revised report was posted", "A communication was posted"). That is enough
to tell a resident *what is coming up near them and when*, before any staff
report has been summarised. The general rules for taking part are quoted from
the City's "Participate in Council and Committee Meetings" page.

Run:  python -m civify.agenda data/agendas/2026-11-16-PB1.pdf
      python -m civify.agenda --rules      # refresh data/official/participate.json from toronto.ca
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

from civify.extract import extract

PARTICIPATE_URL = "https://www.toronto.ca/city-government/council/council-committee-meetings/participate/"
RULES_FILE = Path("data/official/participate.json")
AGENDAS = Path("data/agendas")

_PRINT_NOISE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M .* - TMMIS|https://secure\.toronto\.ca/council/\S+ \d+/\d+)$")
_ITEM_ID = re.compile(r"^([A-Z]{2,4}\d+\.\d+)$")
_WARD = re.compile(r"\(Ward (\d{1,2})\)")
_NOTE = re.compile(r"^([A-Z][a-z]+ \d{1,2}, \d{4}) - (.+)")
_MEETING = re.compile(r"^([A-Z][a-z]+ \d{1,2}, \d{4}) - (\d{1,2}:\d{2} [AP]M) - (.+)$")
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                       "August", "September", "October", "November", "December"], 1)}


def _iso(text: str) -> str | None:
    m = re.match(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", text)
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}" if m and m.group(1) in _MONTHS else None


def parse(path: Path, retrieved: str) -> dict:
    raw = extract(path).text if path.suffix.lower() == ".pdf" else path.read_text(errors="ignore")
    text = raw if path.suffix.lower() == ".pdf" else _html_to_text(raw)
    lines = [l.strip() for l in text.splitlines() if l.strip() and not _PRINT_NOISE.match(l.strip())]

    body = re.sub(r"\s*\(\d{4}-\d{4}\)$", "", lines[0]) if lines else None
    meeting = next((m for l in lines if (m := _MEETING.match(l))), None)
    loc_idx = next((i for i, l in enumerate(lines) if _MEETING.match(l)), None)
    location = lines[loc_idx + 1] if loc_idx is not None and loc_idx + 1 < len(lines) else None
    status = next((l for l in lines if l in ("Agenda Published", "Agenda Not Yet Published", "Meeting Cancelled")), None)
    # The meeting year is not necessarily the item year (November 2026 PB1
    # items have 2027 IDs). Keep short IDs unless a saved source confirms one.
    ids = re.findall(r"agenda-item\.do\?item=(\d{4}\.[A-Z]{2,4}\d+\.\d+)", raw.replace("\n", ""))

    items, cur = [], None
    for l in lines:
        if (m := _ITEM_ID.match(l)):
            short_id = m.group(1)
            matches = {i for i in ids if i.split(".", 1)[1] == short_id}
            item_id = next(iter(matches)) if len(matches) == 1 else short_id
            cur = {"id": item_id, "short_id": short_id, "title": "", "ward": None, "notes": [],
                   "official_url": f"https://secure.toronto.ca/council/agenda-item.do?item={item_id}" if len(matches) == 1 else None}
            items.append(cur)
        elif cur is None:
            continue
        elif cur["ward"] is None:
            w = _WARD.search(l)
            cur["title"] = (cur["title"] + " " + _WARD.sub("", l)).strip()
            if w:
                cur["ward"] = w.group(1).lstrip("0")
        elif (n := _NOTE.match(l)):
            cur["notes"].append({"date": _iso(n.group(1)), "note": n.group(2)})
        elif l.startswith("This list demonstrates"):
            break
        elif cur["notes"] and not l[0].isupper():
            cur["notes"][-1]["note"] += " " + l     # a note that wrapped onto the next line
    return {
        "body": body,
        "meeting_date": _iso(meeting.group(1)) if meeting else None,
        "meeting_time": meeting.group(2) if meeting else None,
        "meeting_status": meeting.group(3) if meeting else None,
        "location": location,
        "agenda_status": status,
        "items": items,
        "source": {"file": path.name, "retrieved": retrieved},
    }


def _html_to_text(h: str) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "\n", h))


# --- the City's general participation rules, quoted ---------------------------

_RULE_PATTERNS = [
    r"You should register by .*? at the latest\.",   # contains "12:00 p.m.", so don't stop at the first period
    r"You can submit comments in writing or speak[^.]*\.",
    r"If we receive your comments after a matter has been decided[^.]*\.",
    r"Any written comments submitted[^.]*public record[^.]*\.",
]


def fetch_rules(fetch=None) -> dict:
    raw = (fetch or _http_get)(PARTICIPATE_URL)
    flat = re.sub(r"\s+", " ", _html_to_text(raw))
    quotes = [m.group(0).strip() for p in _RULE_PATTERNS if (m := re.search(p, flat))]
    return {"source": PARTICIPATE_URL, "retrieved": dt.date.today().isoformat(), "quotes": quotes}


def _http_get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def load_rules() -> dict:
    return json.loads(RULES_FILE.read_text()) if RULES_FILE.exists() else {"source": PARTICIPATE_URL, "retrieved": None, "quotes": []}


def resolve_items(meeting: dict, records: list[dict]) -> dict:
    """Join only when the short ID, body, meeting date and ward all agree."""
    for item in meeting["items"]:
        short_id = item.get("short_id") or re.sub(r"^\d{4}\.", "", item["id"])
        matches = []
        for rec in records:
            nxt = rec.get("participation", {}).get("next_meeting") or {}
            if (rec["item_id"].split(".", 1)[1] == short_id
                    and nxt.get("body") == meeting["body"]
                    and _iso(nxt.get("date", "")) == meeting["meeting_date"]
                    and rec.get("ward") == item.get("ward")):
                matches.append(rec)
        if len(matches) == 1:
            item.update(id=matches[0]["item_id"], official_url=matches[0]["official_url"],
                        local_url=f"/items/{matches[0]['item_id']}")
    return meeting


def load_meetings(records: list[dict] | None = None) -> list[dict]:
    return sorted((resolve_items(json.loads(p.read_text()), records or []) for p in AGENDAS.glob("*.json")),
                  key=lambda m: m["meeting_date"] or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agenda", nargs="?", type=Path)
    ap.add_argument("--retrieved", default=dt.date.today().isoformat())
    ap.add_argument("--rules", action="store_true", help="refresh the quoted participation rules from toronto.ca")
    args = ap.parse_args()
    if args.rules:
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        rules = fetch_rules()
        RULES_FILE.write_text(json.dumps(rules, indent=1, ensure_ascii=False))
        print(f"{len(rules['quotes'])} rule(s) quoted from {PARTICIPATE_URL}")
        for q in rules["quotes"]:
            print("  ›", q)
    if args.agenda:
        m = parse(args.agenda, args.retrieved)
        out = args.agenda.with_suffix(".json")
        out.write_text(json.dumps(m, indent=1, ensure_ascii=False))
        print(f"{m['body']} · {m['meeting_date']} {m['meeting_time']} · {m['agenda_status']} · {len(m['items'])} items")
        for it in m["items"]:
            print(f"  {it['id']:14} ward {it['ward'] or '?':>2}  {it['title'][:80]}{'  (+notes)' if it['notes'] else ''}")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
