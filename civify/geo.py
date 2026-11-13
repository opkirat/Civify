"""'Is this near me?' without storing where anyone lives.

A resident's address is sent to the City of Toronto's own open-data API
(Address Points dataset), which answers with the ward and a coordinate. We use
the answer for one request and keep nothing: no database write, no log line.
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


def parse_address(text: str) -> tuple[str, str] | None:
    """'191-199 College Street' -> ('191', 'College'). Ranges use the first number."""
    m = re.match(r"\s*(\d+)[A-Za-z]?(?:\s*-\s*\d+)?\s+(.+)", text)
    if not m:
        return None
    words = [w for w in re.split(r"[\s,]+", m.group(2)) if w]
    name = [w for w in words if w.lower().rstrip(".") not in _TYPES]
    return (m.group(1), " ".join(name).title()) if name else None


def lookup(address: str, fetch=None) -> dict | None:
    """Return {'address', 'ward', 'ward_name', 'lat', 'lon'} or None. Nothing is stored."""
    parsed = parse_address(address)
    if not parsed:
        return None
    number, name = parsed
    params = urllib.parse.urlencode({
        "resource_id": ADDRESS_POINTS, "limit": 1,
        "filters": json.dumps({"ADDRESS_NUMBER": number, "LINEAR_NAME": name}),
    })
    fetch = fetch or _http_get
    try:
        records = json.loads(fetch(f"{API}?{params}"))["result"]["records"]
    except Exception:
        return None
    if not records:
        return None
    r = records[0]
    lon, lat = json.loads(r["geometry"])["coordinates"]
    return {"address": r["ADDRESS_FULL"], "ward": r["WARD"].lstrip("0"), "ward_name": r["WARD_NAME"], "lat": lat, "lon": lon}


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
