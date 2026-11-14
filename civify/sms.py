"""Consent-gated ward alerts, sent automatically.

- A resident opts in for one ward and confirms a 6-digit code.
- Right after confirming, they get what is already live in their ward (catch_up).
- When an item first has a live explanation, its ward's subscribers get a text (alert_new_item);
  city-wide items go to every subscriber. No person approves the text: it only names the
  place and links the official record, and never claims a comment period is open.
- Once per phone per item; at most one new-item alert per phone per 24 hours; STOP opts out.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from civify import db, geo


def load_sms_env(path: str = ".env") -> None:
    """Read local SMS settings without overriding process-provided values."""
    file = Path(path)
    if not file.is_file():
        return
    allowed = {"SMS_MODE", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "SMS_WEBHOOK_URL"}
    for line in file.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in allowed:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def mode() -> str:
    load_sms_env()
    return "twilio" if os.getenv("SMS_MODE") == "twilio" else "demo"


def phone_number(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01" or digits[3] in "01":
        raise ValueError("Enter a 10-digit Canadian phone number.")
    return "+1" + digits


def _code_hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def send(to: str, body: str) -> str:
    if mode() != "twilio":
        return "demo"
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_FROM_NUMBER")
    if not all((sid, token, sender)):
        raise RuntimeError("Twilio SMS settings are incomplete")
    payload = urlencode({"To": to, "From": sender, "Body": body}).encode()
    credentials = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=payload,
                  headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=12) as response:
        return json.load(response)["sid"]


def begin(con: sqlite3.Connection, raw_phone: str, ward: str) -> tuple[str, str | None]:
    phone = phone_number(raw_phone)
    ward = ward.zfill(2)
    if ward not in geo.WARDS:
        raise ValueError("Choose a Toronto ward.")
    old = con.execute("SELECT * FROM sms_subscriptions WHERE phone = ?", (phone,)).fetchone()
    now = datetime.now(timezone.utc)
    if old and old["status"] == "active":
        raise ValueError("This number is already subscribed. Text STOP to leave, or contact the pilot team to change wards.")
    if old and old["status"] == "stopped":
        raise ValueError("This number opted out. Contact the pilot team before signing up again.")
    if old and datetime.fromisoformat(old["requested_at"]) > now - timedelta(minutes=2):
        raise ValueError("Please wait two minutes before requesting another code.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    con.execute("INSERT INTO sms_subscriptions (phone, ward, status, code_hash, code_expires, requested_at) VALUES (?, ?, 'pending', ?, ?, ?) "
                "ON CONFLICT(phone) DO UPDATE SET ward=excluded.ward, status='pending', code_hash=excluded.code_hash, "
                "code_expires=excluded.code_expires, code_attempts=0, requested_at=excluded.requested_at",
                (phone, ward, _code_hash(phone, code), (now + timedelta(minutes=10)).isoformat(), now.isoformat()))
    con.commit()
    try:
        send(phone, code_body(code))
    except Exception:
        con.execute("DELETE FROM sms_subscriptions WHERE phone=? AND status='pending'", (phone,))
        con.commit()
        raise
    return phone, code if mode() == "demo" else None


def confirm(con: sqlite3.Connection, raw_phone: str, code: str) -> bool:
    phone = phone_number(raw_phone)
    row = con.execute("SELECT * FROM sms_subscriptions WHERE phone=?", (phone,)).fetchone()
    if not row or row["status"] != "pending" or not row["code_expires"] or row["code_attempts"] >= 5:
        return False
    if datetime.fromisoformat(row["code_expires"]) < datetime.now(timezone.utc):
        return False
    if not hmac.compare_digest(row["code_hash"], _code_hash(phone, code.strip())):
        con.execute("UPDATE sms_subscriptions SET code_attempts=code_attempts+1 WHERE phone=?", (phone,))
        con.commit()
        return False
    con.execute("UPDATE sms_subscriptions SET status='active', code_hash=NULL, code_expires=NULL, confirmed_at=? WHERE phone=?",
                (db.now(), phone))
    con.commit()
    return True


def stop(con: sqlite3.Connection, raw_phone: str) -> None:
    phone = phone_number(raw_phone)
    con.execute("UPDATE sms_subscriptions SET status='stopped', code_hash=NULL, code_expires=NULL WHERE phone=?", (phone,))
    con.commit()


def valid_twilio_signature(url: str, params: dict[str, str], signature: str) -> bool:
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not token or not signature:
        return False
    signed = url + "".join(k + v for k, v in sorted(params.items()))
    digest = hmac.new(token.encode(), signed.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def alert_body(rec: dict) -> str:
    """Short and plain: which ward, which place, and the official link. Never claims a comment period is open."""
    parts = (rec.get("title") or "").split(" - ")
    place = parts[1] if len(parts) > 1 else parts[0]
    place = place[:60].rstrip() + ("..." if len(place) > 60 else "")
    where = "city-wide" if rec.get("citywide") else f"Ward {int(rec['ward'])}"
    return f"Civify {where}: new plain-language explanation for {place}. City record: {rec['official_url']} Reply STOP to opt out."


def code_body(code: str) -> str:
    return f"Civify code: {code}. Enter it on the signup page within 10 minutes. If you did not request this, ignore it."


def inbox(con: sqlite3.Connection, raw_phone: str) -> list[dict]:
    """Demo only: the simulated alerts one number has received, oldest first."""
    phone = phone_number(raw_phone)
    rows = con.execute("SELECT c.body, d.at FROM sms_deliveries d JOIN sms_campaigns c ON c.id = d.campaign_id "
                       "WHERE d.phone = ? ORDER BY d.at", (phone,)).fetchall()
    return [{"text": r["body"], "at": r["at"]} for r in rows]


AUTO_SENDER = "auto"   # alerts go out on their own; not a person


def sendable(rec: dict) -> bool:
    """An alert needs somewhere to go (a ward, or the whole city) and an official HTTPS link."""
    return bool((rec.get("ward") or rec.get("citywide")) and rec.get("official_url", "").startswith("https://"))


def _campaign(con: sqlite3.Connection, rec: dict, publication: dict, by: str) -> sqlite3.Row:
    """One campaign (one alert text) per item, created the first time it is needed."""
    con.execute("INSERT OR IGNORE INTO sms_campaigns (item_id, publication_version, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (rec["item_id"], publication["version"], alert_body(rec), by, db.now()))
    con.commit()
    return con.execute("SELECT * FROM sms_campaigns WHERE item_id=?", (rec["item_id"],)).fetchone()


def _deliver(con: sqlite3.Connection, campaign: sqlite3.Row, phone: str, count_toward_limit: bool = True) -> bool:
    """Text one phone, at most once per campaign. True if the provider accepted it (or it was simulated)."""
    if con.execute("SELECT 1 FROM sms_deliveries WHERE campaign_id=? AND phone=?", (campaign["id"], phone)).fetchone():
        return False
    # Reserve before calling the provider. A timeout stays 'unknown' rather than risking a duplicate text.
    con.execute("INSERT INTO sms_deliveries VALUES (?, ?, 'unknown', NULL, ?)", (campaign["id"], phone, db.now()))
    con.commit()
    try:
        provider_id = send(phone, campaign["body"])
    except Exception:
        return False
    con.execute("UPDATE sms_deliveries SET status=?, provider_id=?, at=? WHERE campaign_id=? AND phone=?",
                ("demo" if mode() == "demo" else "accepted", provider_id, db.now(), campaign["id"], phone))
    if count_toward_limit:
        con.execute("UPDATE sms_subscriptions SET last_alert_at=? WHERE phone=?", (db.now(), phone))
    con.commit()
    return True


def send_item(con: sqlite3.Connection, rec: dict, publication: dict, sender: str) -> dict:
    """Text an item's ward (every ward for a city-wide item): only confirmed subscribers, once per
    phone per item, and at most one new-item alert per phone per 24 hours."""
    if not publication or not publication["claims"] or not sendable(rec):
        raise ValueError("This item needs a published explanation, a ward (or city-wide), and an official HTTPS link.")
    campaign = _campaign(con, rec, publication, sender)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    where, args = ("", (since,)) if rec.get("citywide") else ("ward=? AND ", (str(rec["ward"]).zfill(2), since))
    subscribers = con.execute(f"SELECT phone FROM sms_subscriptions WHERE status='active' AND {where}"
                              "(last_alert_at IS NULL OR last_alert_at < ?) ORDER BY phone", args).fetchall()
    sent = sum(_deliver(con, campaign, sub["phone"]) for sub in subscribers)
    return {"sent": sent, "mode": mode()}


def alert_new_item(con: sqlite3.Connection, rec: dict) -> dict | None:
    """Automatic: once an item has a live explanation, text its ward's subscribers. No person
    approves the text; it only names the place and links the official record (alert_body).
    Never raises, so a text failure can't stop publishing."""
    pub = db.latest_publication(con, rec["item_id"])
    if not pub or not pub["claims"] or not sendable(rec):
        return None
    try:
        return send_item(con, rec, pub, AUTO_SENDER)
    except Exception:
        return None


def alert_item(db_path: str, item_id: str) -> None:
    """Background task after a staff decision publishes a new version."""
    rec = db.load_record(item_id)
    if rec:
        alert_new_item(db.connect(db_path), rec)


CATCH_UP = 3   # texts right after sign-up, newest first


def catch_up(con: sqlite3.Connection, raw_phone: str) -> int:
    """Right after a resident confirms: text them what is already live in their ward (and
    city-wide), newest first, at most CATCH_UP. Doesn't count toward the 24-hour limit, so
    the next new item still reaches them. Returns how many were sent."""
    phone = phone_number(raw_phone)
    sub = con.execute("SELECT ward FROM sms_subscriptions WHERE phone=? AND status='active'", (phone,)).fetchone()
    if not sub:
        return 0
    live = []
    for rec in db.list_items():
        if not sendable(rec) or not (rec.get("citywide") or str(rec.get("ward") or "").zfill(2) == sub["ward"]):
            continue
        pub = db.latest_publication(con, rec["item_id"])
        if pub and pub["claims"]:
            live.append((pub["published_at"], rec, pub))
    live.sort(key=lambda x: x[0], reverse=True)
    sent = 0
    for _, rec, pub in reversed(live[:CATCH_UP]):   # oldest first, like a text thread
        sent += _deliver(con, _campaign(con, rec, pub, AUTO_SENDER), phone, count_toward_limit=False)
    return sent
