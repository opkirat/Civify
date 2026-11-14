"""Consent-gated ward alerts. No automatic sends from the publication pipeline."""

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
        send(phone, f"Civify code: {code}. Enter it on the signup page within 10 minutes. If you did not request this, ignore it.")
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
    title = rec["title"].split(" - ", 2)[-1]
    title = title[:55].rstrip() + ("..." if len(title) > 55 else "")
    return f"Civify Ward {int(rec['ward'])}: {title}. City record: {rec['official_url']} Check current details there. Reply STOP to opt out."


def send_item(con: sqlite3.Connection, rec: dict, publication: dict, reviewer: str) -> dict:
    """A signed-in staff action; one campaign per item, only to confirmed ward subscribers."""
    if not publication or not publication["claims"] or not rec.get("ward") or not rec.get("official_url", "").startswith("https://"):
        raise ValueError("This item needs a published explanation, ward, and official HTTPS link.")
    body = alert_body(rec)
    con.execute("INSERT OR IGNORE INTO sms_campaigns (item_id, publication_version, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (rec["item_id"], publication["version"], body, reviewer, db.now()))
    con.commit()
    campaign = con.execute("SELECT * FROM sms_campaigns WHERE item_id=?", (rec["item_id"],)).fetchone()
    subscribers = con.execute("SELECT phone FROM sms_subscriptions WHERE status='active' AND ward=? AND "
                              "(last_alert_at IS NULL OR last_alert_at < ?) ORDER BY phone",
                              (str(rec["ward"]).zfill(2), (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat())).fetchall()
    sent = 0
    for sub in subscribers:
        phone = sub["phone"]
        if con.execute("SELECT 1 FROM sms_deliveries WHERE campaign_id=? AND phone=?", (campaign["id"], phone)).fetchone():
            continue
        # Reserve before calling the provider. A timeout stays 'unknown' rather than risking a duplicate text.
        con.execute("INSERT INTO sms_deliveries VALUES (?, ?, 'unknown', NULL, ?)", (campaign["id"], phone, db.now()))
        con.commit()
        try:
            provider_id = send(phone, body)
        except Exception:
            continue
        con.execute("UPDATE sms_deliveries SET status=?, provider_id=?, at=? WHERE campaign_id=? AND phone=?",
                    ("demo" if mode() == "demo" else "accepted", provider_id, db.now(), campaign["id"], phone))
        con.execute("UPDATE sms_subscriptions SET last_alert_at=? WHERE phone=?", (db.now(), phone))
        con.commit()
        sent += 1
    return {"sent": sent, "mode": mode()}
