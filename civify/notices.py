"""Public notices from the City Clerk, via Toronto Open Data.

The City publishes every statutory public notice (planning applications, public
meetings, heritage designations, fees, road renamings) as open data, refreshed
daily. Each notice carries the Clerk's full text, the addresses with coordinates,
the decision body and the agenda item it belongs to. The text is the official
record, so it is shown as is: no model, no paraphrase, nothing to verify.

What we add is structure: the ward, the sentences that say how to take part
(quoted verbatim, never interpreted), and a link to the agenda item.

Run:  python -m civify.notices            # refresh data/notices.json from the City API
      python -m civify.notices --days 90  # how far back to keep (default 60)
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

RESOURCE = "72a930b4-f82f-4ef6-bc44-013b5364d7d2"  # Public Notices, datastore resource id
API = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/datastore_search"
SOURCE_URL = "https://open.toronto.ca/dataset/public-notices/"
NOTICES_SITE = "https://secure.toronto.ca/nm/notices/current.do"
OUT = Path("data/notices.json")

# Sentences that say how or when a person can take part. Quoted, never computed.
_PARTICIPATION = re.compile(
    r"no later than|deadline|written (comments|submissions)|wish to (speak|address|comment|appeal)|"
    r"may (make|submit|file)|register by|submit .* until|before the (by-law|decision)", re.I)


def fetch_all(fetch=None) -> list[dict]:
    fetch = fetch or _http_json
    rows, offset = [], 0
    while True:
        page = fetch(f"{API}?resource_id={RESOURCE}&limit=1000&offset={offset}")["result"]["records"]
        rows += page
        if len(page) < 1000:
            return rows
        offset += 1000


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def _list(value) -> list:
    try:
        return json.loads(value) if isinstance(value, str) else (value or [])
    except json.JSONDecodeError:
        return []


def plain_text(h: str | None) -> str:
    t = re.sub(r"</p\s*>|<br\s*/?>", "\n", h or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def _coord(value) -> float | None:
    """The dataset sometimes stores '43.648,' with a stray comma; tolerate that, skip junk."""
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(value or "")))
    except ValueError:
        return None


def _date(ms) -> str | None:
    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).date().isoformat() if ms else None


def normalize(row: dict, retrieved: str) -> dict:
    text = plain_text(row.get("noticeDescription"))
    flat = re.sub(r"\s+", " ", text)
    ward = re.search(r"\bWard\s*(\d{1,2})\b", flat)
    # Split into sentences without breaking at "a.m."/"p.m." (the deadline date follows them).
    sentences = [s.strip() for s in re.split(r"(?<![ap]\.m\.)(?<=[.!?])\s+", flat) if _PARTICIPATION.search(s)]
    events = [{"date": _date(e.get("startDateTime")), "location": e.get("locationName"), "address": e.get("streetAddress")}
              for e in _list(row.get("eventList"))]
    return {
        "notice_id": row["noticeId"],
        "title": row.get("title"),
        "posted": _date(row.get("noticeDate")),
        "type": row.get("noticeHeadingType"),
        "topics": _list(row.get("topics")),
        "decision_body": row.get("decisionBody"),
        "ward": ward.group(1).lstrip("0") if ward else None,
        "addresses": [{"address": a.get("streetAddress"), "postal_code": a.get("postalCode"), "lat": lat, "lon": lon}
                      for a in _list(row.get("addressList"))
                      if (lat := _coord(a.get("latitudeCoordinate"))) is not None
                      and (lon := _coord(a.get("longitudeCoordinate"))) is not None],
        "events": events,
        "agenda_items": [{"id": m.group(1), "url": r.get("url"), "description": r.get("description")}
                         for r in _list(row.get("otherReferenceList"))
                         if (m := re.search(r"item=(\d{4}\.[A-Z]{2,4}\d+\.\d+)", r.get("url") or ""))],
        "application_numbers": _list(row.get("planningApplicationNumbers")),
        "participation": sentences,
        "text": text,
        "signed_by": row.get("signedBy"),
        "source": {"dataset": SOURCE_URL, "site": NOTICES_SITE, "retrieved": retrieved},
    }


def build(rows: list[dict], days: int, today: dt.date, retrieved: str) -> list[dict]:
    """Keep notices posted in the last `days` days or with an event still to come."""
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    out = []
    for row in rows:
        n = normalize(row, retrieved)
        upcoming = any(e["date"] and e["date"] >= today.isoformat() for e in n["events"])
        if (n["posted"] and n["posted"] >= cutoff) or upcoming:
            out.append(n)
    return sorted(out, key=lambda n: n["posted"] or "", reverse=True)


def load() -> list[dict]:
    return json.loads(OUT.read_text()) if OUT.exists() else []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()
    today = dt.date.today()
    rows = fetch_all()
    notices = build(rows, args.days, today, today.isoformat())
    OUT.write_text(json.dumps(notices, indent=1, ensure_ascii=False))
    print(f"{len(rows)} notices in the City dataset; kept {len(notices)} from the last {args.days} days")
    for n in notices:
        print(f"  {n['posted']}  ward {n['ward'] or '?':>2}  {n['title'][:80]}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
