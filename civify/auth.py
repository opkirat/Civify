"""Staff accounts and sign-in.

Each reviewer has their own account, so the audit trail records who really
approved what. Passwords are hashed with scrypt from Python's standard library
(salted, never stored in plain text). Sessions are random tokens kept in the
database and sent as an HttpOnly cookie, so signing out or deleting an account
ends the session immediately. A pilot would replace this with the City's single
sign-on; nothing else in the app would change.

Manage accounts:
  python -m civify.auth add jsmith --name "Jordan Smith"    # prompts for a password
  python -m civify.auth list
  python -m civify.auth remove jsmith
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

SESSION_HOURS = 12
MIN_PASSWORD = 10
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add_user(con: sqlite3.Connection, username: str, name: str, password: str) -> None:
    username = username.strip().lower()
    if not username.isidentifier():
        raise ValueError("username: letters, digits and underscores only")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    con.execute("INSERT INTO users (username, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (username, name.strip() or username, hash_password(password), _now().isoformat(timespec="seconds")))
    con.commit()


def remove_user(con: sqlite3.Connection, username: str) -> None:
    con.execute("DELETE FROM sessions WHERE username = ?", (username,))
    con.execute("DELETE FROM users WHERE username = ?", (username,))
    con.commit()


def sign_in(con: sqlite3.Connection, username: str, password: str) -> str | None:
    """Return a new session token, or None. Same answer for unknown user and wrong password."""
    row = con.execute("SELECT password_hash FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
    if row is None or not check_password(password, row["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions (token, username, created_at) VALUES (?, ?, ?)",
                (token, username.strip().lower(), _now().isoformat(timespec="seconds")))
    con.commit()
    return token


def user_for(con: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    row = con.execute("""SELECT u.username, u.name, s.created_at FROM sessions s
                         JOIN users u ON u.username = s.username WHERE s.token = ?""", (token,)).fetchone()
    if row is None:
        return None
    if _now() - datetime.fromisoformat(row["created_at"]) > timedelta(hours=SESSION_HOURS):
        sign_out(con, token)
        return None
    return row


def sign_out(con: sqlite3.Connection, token: str | None) -> None:
    if token:
        con.execute("DELETE FROM sessions WHERE token = ?", (token,))
        con.commit()


def main() -> int:
    from civify import db

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("username"); a.add_argument("--name", default="")
    sub.add_parser("list")
    r = sub.add_parser("remove"); r.add_argument("username")
    ap.add_argument("--db", default="civify.db")
    args = ap.parse_args()
    con = db.connect(args.db)
    if args.cmd == "add":
        pw = getpass.getpass(f"Password for {args.username} (min {MIN_PASSWORD} characters): ")
        if pw != getpass.getpass("Repeat password: "):
            print("passwords do not match"); return 1
        try:
            add_user(con, args.username, args.name, pw)
        except (ValueError, sqlite3.IntegrityError) as e:
            print(f"not added: {e}"); return 1
        print(f"added {args.username}")
    elif args.cmd == "list":
        for row in con.execute("SELECT username, name, created_at FROM users ORDER BY username"):
            print(f"{row['username']:16} {row['name']:28} since {row['created_at']}")
    elif args.cmd == "remove":
        remove_user(con, args.username); print(f"removed {args.username}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
