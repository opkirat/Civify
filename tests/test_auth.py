"""Account and session tests (offline, temporary database)."""

import sqlite3

import pytest

from civify import auth, db


@pytest.fixture
def con(tmp_path):
    return db.connect(str(tmp_path / "a.db"))


def test_password_is_hashed_and_checked(con):
    auth.add_user(con, "JSmith", "Jordan Smith", "a long passphrase")
    row = con.execute("SELECT * FROM users").fetchone()
    assert row["username"] == "jsmith" and "a long passphrase" not in row["password_hash"]
    assert auth.check_password("a long passphrase", row["password_hash"])
    assert not auth.check_password("wrong", row["password_hash"])


def test_sign_in_sign_out(con):
    auth.add_user(con, "jsmith", "Jordan Smith", "a long passphrase")
    assert auth.sign_in(con, "jsmith", "nope nope nope") is None
    assert auth.sign_in(con, "nobody", "a long passphrase") is None
    token = auth.sign_in(con, "JSMITH", "a long passphrase")
    assert auth.user_for(con, token)["name"] == "Jordan Smith"
    auth.sign_out(con, token)
    assert auth.user_for(con, token) is None


def test_removing_a_user_ends_their_sessions(con):
    auth.add_user(con, "jsmith", "Jordan Smith", "a long passphrase")
    token = auth.sign_in(con, "jsmith", "a long passphrase")
    auth.remove_user(con, "jsmith")
    assert auth.user_for(con, token) is None


def test_expired_session_is_refused(con):
    auth.add_user(con, "jsmith", "Jordan Smith", "a long passphrase")
    token = auth.sign_in(con, "jsmith", "a long passphrase")
    con.execute("UPDATE sessions SET created_at = '2000-01-01T00:00:00+00:00'"); con.commit()
    assert auth.user_for(con, token) is None


def test_weak_passwords_and_bad_usernames_rejected(con):
    with pytest.raises(ValueError):
        auth.add_user(con, "jsmith", "J", "short")
    with pytest.raises(ValueError):
        auth.add_user(con, "j smith", "J", "a long passphrase")
    auth.add_user(con, "jsmith", "J", "a long passphrase")
    with pytest.raises(sqlite3.IntegrityError):
        auth.add_user(con, "jsmith", "J", "a long passphrase")


def test_old_database_gets_claim_hash_column(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE reviews (item_id TEXT, claim_index INTEGER, status TEXT, sentence TEXT, reviewer TEXT, reviewed_at TEXT, PRIMARY KEY (item_id, claim_index))")
    old.execute("INSERT INTO reviews VALUES ('x', 0, 'approved', 's', 'r', 't')"); old.commit(); old.close()
    con = db.connect(path)
    row = con.execute("SELECT * FROM reviews").fetchone()
    assert row["claim_hash"] is None
    assert db.current_review(row, {"sentence": "s", "quote": "q"}) is None   # old approvals don't count
