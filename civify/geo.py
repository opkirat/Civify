"""'Is this near me?' without storing where anyone lives.

A resident's address is sent to the City of Toronto's own open-data API
(Address Points dataset), which answers with the ward and a coordinate. We use
the answer for one request and keep nothing: no application database write. Search URLs may still appear in browser history or server access logs.
The City already holds every address; we are only asking it which ward one is in.

Items are located the same way at build time, from the address in their title.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path

ADDRESS_POINTS = "0b3756af-9caf-4f0f-ac28-9c6617adede4"   # Toronto Open Data resource id
API = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/datastore_search"
WARDS = json.loads((Path(__file__).parent.parent / "data" / "wards.json").read_text())

# Street-type words the City stores separately from the street name.
_TYPES = {"st", "street", "ave", "avenue", "rd", "road", "blvd", "boulevard", "dr", "drive", "cres",
          "crescent", "ct", "court", "pl", "place", "way", "lane", "ln", "terr", "terrace", "pkwy", "parkway",
          "sq", "square", "cir", "circle", "trl", "trail", "gdns", "gardens", "hwy", "highway", "e", "w", "n", "s",
          "east", "west", "north", "south"}


_ALIASES = dict(zip(
    "street avenue road boulevard drive crescent court place lane terrace parkway square circle trail gardens highway east west north south".split(),
    "st ave rd blvd dr cres ct pl ln terr pkwy sq cir trl gdns hwy e w n s".split()))


def address_parts(text: str) -> tuple[str, str, str, str] | None:
    """Normalize street suffixes, preserving directions and names like St Clair."""
    text = text.strip().lower().replace(".", "")
    text = re.sub(r"^(?:unit|apt|apartment|suite)\s*[\w-]+\s*[,/]?\s*", "", text)
    text = re.split(r",|\b(?:toronto|ontario|canada|etobicoke|scarborough|north york)\b", text)[0]
    text = re.sub(r"\s+(?:unit|apt|apartment|suite|#)\s*.*$", "", text)
    text = re.sub(r"\s+[a-z]\d[a-z]\s*\d[a-z]\d.*$", "", text)
    m = re.fullmatch(r"(\d+[a-z]?)(?:-\d+[a-z]?)?\s+(.+)", text.strip())
    if not m:
        return None
    words = [_ALIASES.get(w, w) for w in m[2].split()]
    direction = words.pop() if words[-1] in {"e", "w", "n", "s"} else ""
    kind = words.pop() if words and words[-1] in _TYPES else ""
    return (m[1], " ".join(words), kind, direction) if words else None


def parse_address(text: str) -> tuple[str, str] | None:
    parts = address_parts(text)
    return (parts[0], parts[1].title()) if parts else None


def search_address(address: str, fetch=None) -> dict:
    """Return a match, selectable alternatives, or a specific failure; never guess."""
    from difflib import SequenceMatcher
    parts = address_parts(address)
    empty = {"match": None, "candidates": []}
    if not parts or len(address) > 250:
        return {**empty, "status": "invalid"}
    number, name, kind, direction = parts
    fetch = fetch or _http_get
    records = []
    try:
        # Match the number on the server, then normalize street names locally.
        # This avoids brittle case-sensitive street filters and retains E/W.
        for offset in range(0, 6000, 2000):
            params = urllib.parse.urlencode({"resource_id": ADDRESS_POINTS, "limit": 2000,
                "offset": offset, "filters": json.dumps({"ADDRESS_NUMBER": number.upper()})})
            result = json.loads(fetch(f"{API}?{params}"))["result"]
            records.extend(result["records"])
            if len(records) >= result.get("total", len(records)):
                break
        else:
            return {**empty, "status": "unavailable"}
    except (OSError, ValueError, KeyError, TypeError):
        return {**empty, "status": "unavailable"}
    candidates = {}
    matches = {}
    for r in records:
        try:
            full = r["ADDRESS_FULL"]
            actual = address_parts(full)
            if not actual or actual[0] != number:
                continue
            lon, lat = json.loads(r["geometry"])["coordinates"]
            ward = str(r["WARD"]).lstrip("0")
            if ward.zfill(2) not in WARDS or not (-80 < lon < -78 and 43 < lat < 45):
                continue
            point = {"address": full, "ward": ward, "ward_name": r["WARD_NAME"], "lat": lat, "lon": lon}
            key = (actual, ward)
            if actual[1] == name and (not kind or kind == actual[2]) and (not direction or direction == actual[3]):
                matches[key] = point
            if SequenceMatcher(None, name, actual[1]).ratio() >= .7:
                candidates[key] = point
        except (KeyError, ValueError, TypeError):
            continue
    if len(matches) == 1:
        return {"status": "matched", "match": next(iter(matches.values())), "candidates": []}
    choices = list(matches.values()) if matches else list(candidates.values())
    return {**empty, "status": "ambiguous" if len(matches) > 1 else "not_found",
            "candidates": sorted(choices, key=lambda p: p["address"])[:8]}


def lookup(address: str, fetch=None) -> dict | None:
    """Compatibility wrapper for record building; ambiguity is not a match."""
    return search_address(address, fetch)["match"]


def _http_get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode()


def distance_km(a: dict, b: dict) -> float:
    """Great-circle distance between two {'lat','lon'} points."""
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def ward_number(text: str | None) -> str | None:
    """'11 - University-Rosedale' -> '11'."""
    m = re.match(r"\s*0*(\d+)", text or "")
    return m.group(1) if m else None
