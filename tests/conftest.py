"""Shared test helpers: a fresh database per test and a signed-in staff client."""

import pytest
from fastapi.testclient import TestClient

from civify import app as appmod
from civify import auth, db


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
