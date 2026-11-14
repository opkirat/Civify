"""Build one `record.json` per agenda item: the thing the web app reads.

It combines, with a source for every part:
  - the three STAGES the brief says to keep distinct: staff recommendation,
    committee decision, council decision, each read from the record that made it;
  - the council VOTES and any declared interests, from the saved item page;
  - the PARTICIPATION rules, quoted verbatim from the Clerk's notice;
  - the checked CLAIMS from drafts.json (if the drafter has run).

Nothing here is inferred by a model. Where a value is read from a document,
`source` names the file and the passage it came from, so staff can check it.

Run:  python -m civify.record data/2026.TE34.21
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from civify.classify import DocType, classify
from civify.extract import Document, extract
from civify.geo import lookup, parse_address, ward_number

# Lines Chrome adds when a web page is printed to PDF; they are not part of the record.
_PRINT_NOISE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M Agenda Item History.*|https://secure\.toronto\.ca/council/\S+ \d+/\d+)$")


def page_text(doc: Document) -> str:
    return "\n".join(l for l in doc.text.splitlines() if not _PRINT_NOISE.match(l.strip()))


def section(text: str, heading: str, *until: str) -> str | None:
    """Text from `heading` up to the first of the `until` headings (or 2000 chars)."""
    start = text.find(heading)
    if start < 0:
        return None
    body = text[start + len(heading):]
    end = min([body.find(u) for u in until if body.find(u) >= 0] + [2000])
    return body[:end].strip()


def parse_vote(block: str) -> dict:
    """'Yes: 23 names...  No: 0  Absent: 3 names...' -> counts and names."""
    out = {}
    for key in ("Yes", "No", "Absent"):
        m = re.search(rf"{key}:\s*(\d+)\s*(.*?)(?=\n(?:Yes|No|Absent):|\nMotion|\nDeclared|\Z)", block, re.S)
        if m:
            out[key.lower()] = {"count": int(m.group(1)), "members": re.sub(r"\s+", " ", m.group(2)).strip(" ,")}
    result = re.search(r"Result:\s*\n?(.+)", block)
    if result:
        out["result"] = result.group(1).strip()
    return out


def council_stage(text: str, src: dict) -> dict:
    decision = section(text, "City Council Decision", "Background Information", "Motions (City Council)")
    date = re.search(r"City Council on (.+?), adopted", decision or "")
    votes = []
    for m in re.finditer(r"Vote \((.+?)\)\n(.*?)(?=\nVote \(|\nDeclared Interests|\nMotion to|\Z)", text, re.S):
        votes.append({"on": m.group(1), **parse_vote(m.group(2))})
    # Each motion: "1 - Motion to Amend Item moved by Councillor X (Carried)" then its text up to the vote.
    motions = [
        {"motion": m.group(1), "moved_by": m.group(2), "result": m.group(3),
         "text": re.sub(r"[ \t]+", " ", m.group(4)).strip()}
        for m in re.finditer(r"^\d+ - (Motion to .+?) moved by (.+?) \((Carried|Lost|Withdrawn)\)\n(.*?)(?=\nVote \(|\n\d+ - Motion to|\nMotion to Adopt|\Z)", text, re.M | re.S)
    ]
    interests = section(text, "The following member(s) declared an interest:", "Written Declaration")
    return {
        "stage": "council_decision",
        "body": "City Council",
        "date": date.group(1) if date else None,
        "outcome": next((line.strip() for line in (section(text, "Tracking Status", "This item was considered", "This item will be considered", "consideration on") or "").splitlines()
                         if line.strip().startswith("City Council ")), None),
        "decision_text": decision,
        "motions": motions,
        "votes": votes,
        "declared_interests": interests,
        "source": src,
    }


_CONSIDERATION = re.compile(r"^(.+?) consideration on ([A-Z][a-z]+ \d{1,2}(?: and \d{1,2})?, \d{4})$", re.M)


def committee_stage(text: str, src: dict) -> dict:
    """The committee or board stage. Works for any body: the heading is
    '<Body> consideration on <date>'. Before the meeting there is no decision yet."""
    m = next((m for m in _CONSIDERATION.finditer(text) if "City Council" not in m.group(1)), None)
    body, date = (m.group(1).strip(), m.group(2)) if m else (None, None)
    block = text[m.end():] if m else ""
    following = _CONSIDERATION.search(block)
    if following:
        block = block[:following.start()]
    status = re.search(r"^Status:[ \t]*(.+)", block, re.M)
    recs = None
    if status:
        for heading in (f"{body} Recommendations", "Community Council Recommendations", "Committee Recommendations", "Board Recommendations"):
            recs = section(block, heading, "Decision Advice", "Origin")
            if recs:
                break
    return {
        "stage": "committee_decision",
        "body": body,
        "date": date,
        "status": status.group(1).strip() if status else ("pending" if date else None),
        "recommendations": recs,
        "public_meeting": section(block, "Decision Advice and Other Information", "Origin"),
        "source": src,
    }


def latest_report(reports: list[dict]) -> dict:
    """Staff sometimes post revised reports; the newest dated one is the current recommendation."""
    return max(reports, key=lambda r: (_sortable(r["fields"].get("Date")), r["filename"]))


def _sortable(date_text: str | None) -> str:
    m = re.match(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", date_text or "")
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{m.group(3)}-{months.index(m.group(1)) + 1:02d}-{int(m.group(2)):02d}" if m and m.group(1) in months else ""


def staff_stage(reports: list[dict], recommendation: str | None, text: str) -> dict:
    report = latest_report(reports)
    f = report["fields"]
    ward = f.get("Ward") or (re.search(r"^Ward:\s*(.+)$", text, re.M) or [None, None])[1]
    staff_recs = section(text, "Recommendations\n", "Summary", "Financial Impact")
    return {
        "stage": "staff_recommendation",
        "body": f.get("From"),
        "date": f.get("Date"),
        "ward": ward,
        "application_number": f.get("Planning Application Number"),
        "summary": recommendation,
        "recommendations": staff_recs,
        "versions": [{"file": r["filename"], "date": r["fields"].get("Date")} for r in sorted(reports, key=lambda r: _sortable(r["fields"].get("Date")))],
        "source": {"file": report["filename"], "sha256": report["sha256"], "page": 1},
    }


def enacted_stage(bylaws: list[dict]) -> dict | None:
    """Fourth stage, from the enacted by-laws: when they passed and whether the Mayor
    gave written approval under Strong Mayor powers. Absent if none were downloaded."""
    if not bylaws:
        return None
    f0 = bylaws[0]["fields"]
    return {
        "stage": "enacted",
        "body": "City Clerk (by-laws passed)",
        "date": f0.get("council_vote_date"),
        "bylaws": [{"number": b["fields"].get("bylaw_number"), "title": b["fields"].get("title"), "file": b["filename"]} for b in bylaws],
        "mayoral_decision": f0.get("mayoral_decision"),
        "mayoral_decision_date": f0.get("mayoral_decision_date"),
        "source": {"file": bylaws[0]["filename"], "sha256": bylaws[0]["sha256"], "page": 1},
    }


def participation(notice: dict | None, council: dict, text: str) -> dict:
    """Quote the Clerk's rules; never compute a deadline. Derived fields are read from the
    Tracking Status line only: whether Council has decided, and which meeting is next."""
    f = notice["fields"] if notice else {}
    decided = bool(council.get("outcome") and "adopted" in council["outcome"].lower())
    nxt = re.search(r"This item will be considered by (.+?) on ([A-Z][a-z]+ \d{1,2}(?: and \d{1,2})?, \d{4})", text)
    return {
        "written_comments_rule": f.get("written_comments"),
        "speaker_registration_rule": f.get("speaker_registration"),
        "public_meeting": {k: f.get(k) for k in ("Date", "Time", "Place") if f.get(k)},
        "council_has_decided": decided,
        "next_meeting": {"body": nxt.group(1), "date": nxt.group(2)} if nxt else None,
        "basis": council.get("outcome") or (nxt.group(0) + "." if nxt else None),
        "source": {"file": notice["filename"], "sha256": notice["sha256"]} if notice else None,
        "note": "Staff must confirm current participation status on the official item page before publishing.",
    }


def with_triage(claims: list[dict], path: Path) -> list[dict]:
    """Attach lane, reasons and meaning-check result from triage.json, matched by index and sentence."""
    if not path.exists():
        return claims
    by_index = {t["index"]: t for t in json.loads(path.read_text())}
    out = []
    for i, c in enumerate(claims):
        t = by_index.get(i)
        out.append({**c, "lane": t["lane"], "reasons": t["reasons"], "meaning": t["meaning"]} if t and t["sentence"] == c["sentence"] else c)
    return out


def build(folder: Path) -> dict:
    item = json.loads((folder / "item.json").read_text())
    by_type = {d["doc_type"]: d for d in item["documents"]}
    page_doc = extract(folder / by_type[DocType.ITEM_PAGE.value]["filename"])
    text = page_text(page_doc)
    page_src = {"file": page_doc.filename, "sha256": page_doc.sha256}

    # The title is the line(s) immediately before "Decision Type:", e.g.
    # "TE34.21 - 191-199 College Street ... - Decision Report - Approval".
    short_id = item["item_id"].split(".", 1)[1]
    title = re.search(rf"^({re.escape(short_id)} - .+?)\n(?:Decision|Consideration) Type", text, re.M | re.S)
    council = council_stage(text, page_src)
    reports = [d for d in item["documents"] if d["doc_type"] == DocType.STAFF_REPORT.value]
    stages = [
        staff_stage(reports, section(text, "Summary", "Background Information"), text),
        committee_stage(text, page_src),
        council,
    ]
    enacted = enacted_stage([d for d in item["documents"] if d["doc_type"] == DocType.ENACTED_BYLAW.value])
    if enacted:
        stages.append(enacted)
    drafts_path = folder / "drafts.json"
    title_text = re.sub(r"\s+", " ", title.group(1).replace("-\n", "-")) if title else None
    staff = stages[0]
    # Location: the first street address in the title, looked up in the City's address list.
    # Best effort; None if offline or not found. The ward comes from the staff report regardless.
    addr = re.search(r"\d+(?:-\d+)? [A-Z][A-Za-z' ]+? (?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Crescent|Cres)\b(?: [EWNS]\b| East| West)?", title_text or "")
    location = lookup(addr.group(0)) if addr and parse_address(addr.group(0)) else None
    return {
        "item_id": item["item_id"],
        "title": title_text,
        "ward": ward_number(staff.get("ward")),
        "location": location,
        "retrieved": item["retrieved"],
        "official_url": f"https://secure.toronto.ca/council/agenda-item.do?item={item['item_id']}",
        "current_stage": ("enacted" if enacted else "council_decision" if council.get("date")
                          else "committee_decision" if stages[1]["status"] not in (None, "pending") else "staff_recommendation"),
        "stages": stages,
        "participation": participation(by_type.get(DocType.PUBLIC_NOTICE.value), council, text),
        "public_letters": sum(d["doc_type"] == DocType.PUBLIC_LETTER.value for d in item["documents"]),
        "claims": with_triage(json.loads(drafts_path.read_text()) if drafts_path.exists() else [], folder / "triage.json"),
    }


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/2026.TE34.21")
    rec = build(folder)
    (folder / "record.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(f"{rec['item_id']}: {rec['title']}")
    for s in rec["stages"]:
        print(f"  {s['stage']:22} {s.get('date') or '-':28} {s.get('status') or s.get('outcome') or ''}"[:120])
    c = rec["stages"][2]
    for v in c["votes"]:
        print(f"  vote on '{v['on']}': {v.get('result')}")
    print(f"  participation: council_has_decided={rec['participation']['council_has_decided']}")
    print(f"  claims: {sum(x['verified'] for x in rec['claims'])}/{len(rec['claims'])} verified")
    print(f"wrote {folder / 'record.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
