"""Shared test helpers: a fresh database per test and a signed-in staff client."""

import pytest
from fastapi.testclient import TestClient

from civify import app as appmod
from civify import auth, db, summary


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "test.db"))  # fresh database per test
    return TestClient(appmod.app)


@pytest.fixture
def staff(client):
    """The same client, signed in as reviewer 'Clerk A'."""
    auth.add_user(db.connect(appmod.DB_PATH), "clerka", "Clerk A", "correct horse battery")
    r = client.post("/login", data={"username": "clerka", "password": "correct horse battery"}, follow_redirects=False)
    assert r.status_code == 303
    return client


@pytest.fixture(autouse=True)
def no_live_summaries(monkeypatch):
    """Tests never call the model for summaries, and never write summary.json into data/."""
    def offline(_prompt):
        raise RuntimeError("no model in tests")
    monkeypatch.setattr(summary, "WRITE_CALL", offline)
    monkeypatch.setattr(summary, "CHECK_CALL", offline)


@pytest.fixture(autouse=True)
def no_real_texts(monkeypatch):
    """Whatever the local .env says, tests only ever simulate texts."""
    monkeypatch.setenv("SMS_MODE", "demo")
