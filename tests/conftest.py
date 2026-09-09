import os
import re
from datetime import datetime, timezone

import pytest

# Test-only signing key; no .env file or production setting is modified.
os.environ.setdefault("SESSION_SECRET", "test-only-signing-key-with-at-least-32-characters")

from fastapi.testclient import TestClient
from accounts.security import hash_password
from accounts.store import AccountStore
from jobs.job_manager import JobManager
from webapp import main


PASSWORD = "a unique test passphrase"


def csrf(client, path="/login"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def sign_in(client, username="alice"):
    response = client.post("/login", data={"username": username, "password": PASSWORD, "csrf": csrf(client)})
    assert response.status_code == 303
    client.headers["X-CSRF-Token"] = csrf(client, "/")
    return response


@pytest.fixture(scope="session")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def app_state(monkeypatch, tmp_path, password_hash):
    path = tmp_path / "accounts.sqlite3"
    store = AccountStore(path)
    with store.database.connect(write=True) as db:
        for name in ("alice", "bob"):
            db.execute("INSERT INTO users(username,password_hash,created_at) VALUES (?,?,?)",
                       (name, password_hash, datetime.now(timezone.utc).isoformat()))
    monkeypatch.setattr(main, "account_store", store)
    monkeypatch.setattr(main, "job_manager", JobManager(path))
    monkeypatch.setattr(main.settings, "MAX_FILE_SIZE", 50 * 1024 * 1024)
    monkeypatch.setattr(main.settings, "DATABASE_PATH", str(path))
    for attribute, folder in (("UPLOAD_DIR", "uploads"), ("EXTRACTED_FRAMES_DIR", "frames")):
        directory = tmp_path / folder
        directory.mkdir()
        monkeypatch.setattr(main, attribute, directory)
    results = tmp_path / "results"
    results.mkdir()
    return store, results


@pytest.fixture
def guest(app_state):
    with TestClient(main.app, base_url="https://testserver", follow_redirects=False) as client:
        main.app.state.results_dir = app_state[1]
        yield client


@pytest.fixture
def client(guest):
    sign_in(guest)
    return guest
