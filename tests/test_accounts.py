import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from accounts.migration import import_legacy
from accounts.security import verify_password
from accounts.store import AccountStore
from jobs.job_manager import JobManager
from jobs.job_model import JobStatus
from webapp import main
from tests.conftest import PASSWORD, csrf, sign_in


INVITE = "test-only-invitation-code-123456789"


def register(client, code=INVITE, username="charlie", **extra):
    return client.post("/register", data={"username": username, "password": PASSWORD,
                       "invite_code": code, "csrf": csrf(client, "/register"), **extra})


def test_registration_invite_and_password_storage(guest, app_state):
    store = app_state[0]
    store.create_invite(INVITE)
    response = register(guest, role="admin")
    assert response.status_code == 303
    identity = guest.get("/api/me").json()
    assert identity["username"] == "charlie" and identity["role"] == "user"
    with store.database.connect() as db:
        row = db.execute("SELECT * FROM users WHERE username='charlie'").fetchone()
        assert row["password_hash"] != PASSWORD
        assert verify_password(PASSWORD, row["password_hash"])
        invite = db.execute("SELECT * FROM invites").fetchone()
        assert invite["used_count"] == 1
        assert invite["code_hash"] != INVITE
    html = guest.get("/").text
    assert PASSWORD not in html and INVITE not in html and row["password_hash"] not in html


@pytest.mark.parametrize("kind", ["invalid", "disabled", "exhausted"])
def test_unusable_invites_rejected(guest, app_state, kind):
    store = app_state[0]
    invite_id = store.create_invite(INVITE)
    with store.database.connect(write=True) as db:
        if kind == "disabled":
            db.execute("UPDATE invites SET is_active=0 WHERE id=?", (invite_id,))
        if kind == "exhausted":
            db.execute("UPDATE invites SET used_count=1 WHERE id=?", (invite_id,))
    response = register(guest, "wrong" if kind == "invalid" else INVITE)
    assert response.status_code == 303 and response.headers['location'] == '/register'
    assert {'invalid': 'not valid', 'disabled': 'disabled', 'exhausted': 'already been used'}[kind] in guest.get('/register').text
    assert guest.get("/api/me").status_code == 401


def test_duplicate_username_does_not_consume_invite(guest, app_state):
    store = app_state[0]
    store.create_invite(INVITE)
    assert register(guest, username="ALICE").headers['location'] == '/register'
    with store.database.connect() as db:
        assert db.execute("SELECT used_count FROM invites").fetchone()[0] == 0


def test_login_failure_success_cookie_and_logout_replay(guest):
    response = guest.post("/login", data={"username": "alice", "password": "wrong", "csrf": csrf(guest)})
    assert response.status_code == 401
    assert guest.get("/api/me").status_code == 401
    initial_cookie = guest.cookies.get("surfanalyze_account")
    response = sign_in(guest)
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header and "secure" in cookie_header and "samesite=lax" in cookie_header
    signed_cookie = guest.cookies.get("surfanalyze_account")
    assert signed_cookie != initial_cookie
    assert guest.get("/api/me").json()["username"] == "alice"
    assert guest.get("/dashboard").status_code == 200
    assert guest.post("/logout").status_code == 303
    assert guest.get("/api/me").status_code == 401
    guest.cookies.set("surfanalyze_account", signed_cookie, domain="testserver.local", path="/")
    assert guest.get("/api/me").status_code == 401


def test_inactive_user_and_expired_session_denied(client, app_state):
    store = app_state[0]
    with store.database.connect(write=True) as db:
        db.execute("UPDATE users SET is_active=0 WHERE username='alice'")
    assert client.get("/api/me").status_code == 401
    with store.database.connect(write=True) as db:
        db.execute("UPDATE users SET is_active=1 WHERE username='alice'")
        db.execute("UPDATE sessions SET expires_at=0")
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("path", ["/", "/upload", "/dashboard", "/dashboard-data", "/processing/known", "/result/known",
                                     "/frames/known/frame_01.jpg", "/uploads/known.mp4", "/download/known", "/docs", "/openapi.json"])
def test_guest_cannot_bypass_accounts(guest, path):
    response = guest.post(path) if path == "/upload" else guest.get(path)
    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert guest.get("/api/jobs/known").status_code == 401


def test_legacy_beta_and_telegram_do_not_authenticate(guest, monkeypatch):
    monkeypatch.setattr(main.settings, "PRIVATE_BETA_ACCESS_CODE", "legacy-code")
    assert guest.post("/beta", data={"access_code": "legacy-code"}).status_code == 405
    assert guest.get("/api/me").status_code == 401
    guest.post("/telegram-auth", json={"telegram_id": 1})
    assert guest.get("/api/me").status_code == 401


@pytest.mark.parametrize("path", ["/login", "/register", "/logout", "/upload"])
def test_csrf_required(client, path):
    del client.headers["X-CSRF-Token"]
    response = client.post(path)
    assert response.status_code == (303 if path == '/register' else 403)
    if path == '/register':
        assert response.headers['location'] == '/register'


def test_cross_origin_post_denied_even_with_token(client):
    assert client.post("/logout", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.get("/api/me").status_code == 200


def test_persistent_auth_rate_limits(guest, app_state):
    store = app_state[0]
    for _ in range(10):
        assert store.allow_attempt("testclient", "alice")
    # A fresh store/process sees the same bucket.
    assert not AccountStore(store.database.path).allow_attempt("other-ip", "alice")
    response = guest.post("/login", data={"username": "alice", "password": PASSWORD, "csrf": csrf(guest)})
    assert response.status_code == 429
    response = register(guest, username="alice")
    assert response.status_code == 303 and response.headers['location'] == '/register'
    assert 'Too many attempts' in guest.get('/register').text


def test_user_ownership_every_resource(client, monkeypatch, app_state):
    monkeypatch.setattr(main, "readable_thumbnail", lambda path: True)
    response = client.post("/upload", files={"file": ("alice-ride.mp4", b"video", "video/mp4")})
    assert response.status_code == 303
    job = main.job_manager.list_jobs()[0]
    assert job.owner_user_id == 1
    assert client.get(f"/processing/{job.id}").status_code == 200
    frame_dir = main.EXTRACTED_FRAMES_DIR / job.id
    frame_dir.mkdir()
    (frame_dir / "frame_01.jpg").write_bytes(b"frame")
    download = app_state[1] / "result.mp4"
    download.write_bytes(b"result")
    frames = [f"/frames/{job.id}/frame_01.jpg"]
    main.job_manager.update_job(job.id, status=JobStatus.DONE, result_path=str(download),
                               extracted_frame_paths=frames, analysis_result={"level": "Intermediate"})
    paths = [f"/result/{job.id}", f"/processing/{job.id}", f"/api/jobs/{job.id}", frames[0],
             f"/uploads/{Path(job.file_path).name}", f"/download/{job.id}"]
    for path in paths:
        owner_response = client.get(path)
        assert owner_response.status_code == 200
        assert owner_response.headers["cache-control"] == "no-store"
    assert "alice-ride.mp4" in client.get("/dashboard").text
    assert 'data-frame-index="0"' in client.get(f"/result/{job.id}").text
    client.post("/logout")
    client.headers.pop("X-CSRF-Token")
    sign_in(client, "bob")
    for path in paths:
        denied = client.get(path)
        assert denied.status_code == 404, path
        assert denied.json() == {"detail": "Not found"}
    for path in ("/dashboard", "/dashboard-data"):
        assert "alice-ride.mp4" not in client.get(path).text
        assert "Upload Your First Video" in client.get(path).text
    assert client.get("/api/jobs/nonexistent").json() == {"detail": "Not found"}


def test_unowned_telegram_id_collision_cannot_grant_access(client):
    job = main.job_manager.create_job(user_id=1, file_path="legacy.mp4", chat_id=1)
    assert job.owner_user_id is None
    assert client.get(f"/result/{job.id}").status_code == 404
    assert "legacy.mp4" not in client.get("/dashboard").text


def test_traversal_and_unlisted_frames_denied(client, tmp_path):
    job = main.job_manager.create_job(user_id=1, owner_user_id=1, file_path=str(tmp_path / "secret.txt"))
    outside = tmp_path / "secret.txt"
    outside.write_text("PRIVATE")
    main.job_manager.update_job(job.id, status=JobStatus.DONE, result_path=str(outside))
    assert client.get(f"/download/{job.id}").status_code == 404
    assert client.get("/uploads/secret.txt").status_code == 404
    assert client.get(f"/frames/{job.id}/unlisted.jpg").status_code == 404
    for path in ("/uploads/%2e%2e%2fsecret.txt", f"/frames/{job.id}/%2e%2e%2fsecret.txt"):
        assert client.get(path).status_code == 404


def test_migration_preserves_jobs_and_source_and_is_idempotent(tmp_path):
    path = tmp_path / "new.sqlite3"
    store = AccountStore(path)
    admin = store.create_admin("owner", PASSWORD)
    legacy_manager = JobManager(tmp_path / "fixture.sqlite3")
    job = legacy_manager.create_job(user_id=0, file_path="data/uploads/legacy.mp4", original_filename="legacy.mp4")
    legacy_manager.update_job(job.id, status=JobStatus.DONE, analysis_result={"level": "Intermediate"},
                              extracted_frame_paths=[f"/frames/{job.id}/frame_01.jpg"])
    original = legacy_manager.get_job(job.id).to_dict()
    source = tmp_path / "jobs_db.json"
    source.write_text(json.dumps([original]))
    before = source.read_bytes()
    assert import_legacy(path, source, "owner")["applied"] is False
    assert not JobManager(path).list_jobs()
    assert import_legacy(path, source, "owner", apply=True)["jobs"] == 1
    migrated = JobManager(path).get_job(job.id)
    assert migrated.to_dict() == dict(original, owner_user_id=admin.id)
    assert source.read_bytes() == before
    assert import_legacy(path, source, "owner", apply=True)["already_imported"]
    assert len(JobManager(path).list_jobs()) == 1


def test_migration_errors_are_atomic(tmp_path):
    path = tmp_path / "new.sqlite3"
    store = AccountStore(path)
    store.create_admin("owner", PASSWORD)
    job = JobManager(tmp_path / "old.sqlite3").create_job(user_id=0, file_path="ride.mp4")
    source = tmp_path / "jobs.json"
    source.write_text(json.dumps([job.to_dict(), job.to_dict()]))
    with pytest.raises(ValueError):
        import_legacy(path, source, "owner", apply=True)
    assert not JobManager(path).list_jobs()
    source.write_text(json.dumps([job.to_dict()]))
    with pytest.raises(ValueError):
        import_legacy(path, source, "missing-owner", apply=True)
    assert not JobManager(path).list_jobs()


def test_invite_cannot_be_double_spent(app_state):
    store = app_state[0]
    store.create_invite(INVITE, max_uses=1)
    def attempt(username):
        try:
            return store.register(username, PASSWORD, INVITE)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["charlie", "diana"]))
    assert sum(user is not None for user in outcomes) == 1


def test_parallel_job_writes_preserve_both_jobs(app_state):
    manager = main.job_manager
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda i: manager.create_job(user_id=1, owner_user_id=1, file_path=f"{i}.mp4"), range(2)))
    manager.update_job(jobs[0].id, status=JobStatus.DONE)
    assert len(manager.list_jobs()) == 2
    assert manager.get_job(jobs[1].id).status == JobStatus.QUEUED


@pytest.mark.parametrize("secret", ["", "short"])
def test_startup_refuses_missing_signing_secret(tmp_path, secret):
    import os
    import subprocess
    import sys
    env = os.environ.copy()
    env.update(SESSION_SECRET=secret, API_TOKEN="test-only-api-token",
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-c", "import webapp.main"], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Accounts require SESSION_SECRET" in result.stderr


def test_startup_requires_legacy_import(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "new.sqlite3"
    monkeypatch.setattr(main.settings, "DATABASE_PATH", str(path))
    source = tmp_path / "jobs_db.json"
    source.write_text("[]")
    store = AccountStore(path)
    with pytest.raises(RuntimeError, match="explicit import"):
        JobManager()
    store.create_admin("owner", PASSWORD)
    import_legacy(path, source, "owner", apply=True)
    assert JobManager().list_jobs() == []


def test_bootstrap_refuses_second_admin(tmp_path):
    store = AccountStore(tmp_path / "new.sqlite3")
    assert store.create_admin("owner", PASSWORD).role == "admin"
    with pytest.raises(ValueError, match="admin already exists"):
        store.create_admin("second-owner", PASSWORD)


def test_cli_does_not_echo_secrets(app_state, monkeypatch, capsys):
    from accounts import cli
    monkeypatch.setattr("sys.argv", ["accounts.cli", "create-invite", "--max-uses", "2", "--label", "family"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: INVITE)
    cli.main()
    output = capsys.readouterr()
    assert "Invite created: ID" in output.out
    assert INVITE not in output.out + output.err


def test_auth_errors_never_echo_sensitive_fields(guest):
    secret = "do-not-reflect-this-password-or-invite"
    response = guest.post("/register", data={"username": "x" * 41, "password": secret,
                          "invite_code": secret, "csrf": csrf(guest)})
    assert response.status_code == 303 and response.headers['location'] == '/register'
    assert secret not in response.text + guest.get('/register').text


def test_session_fixation_and_tampering(guest):
    sign_in(guest)
    old = guest.cookies.get("surfanalyze_account")
    sign_in(guest)
    guest.cookies.set("surfanalyze_account", old, domain="testserver.local", path="/")
    assert guest.get("/api/me").status_code == 401
    guest.cookies.set("surfanalyze_account", "forged", domain="testserver.local", path="/")
    assert guest.get("/api/me").status_code == 401


def test_symlink_file_denied(client, tmp_path):
    from webapp.routes.download import private_file
    from fastapi import HTTPException
    target = tmp_path / "private.txt"
    target.write_text("private")
    link = main.UPLOAD_DIR / "alias.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this Windows host")
    with pytest.raises(HTTPException) as exc:
        private_file(link, main.UPLOAD_DIR)
    assert exc.value.status_code == 404


def test_oversized_auth_form_is_bounded(guest):
    response = guest.post("/login", content=b"password=" + b"x" * 20000,
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code in (400, 413)
    assert "x" * 100 not in response.text


def test_cli_refuses_echoing_password_fallback(monkeypatch):
    import warnings
    from accounts import cli
    def fallback(prompt):
        warnings.warn("No terminal", cli.getpass.GetPassWarning)
        raise AssertionError("Must never read an echoed secret")
    monkeypatch.setattr(cli.getpass, "getpass", fallback)
    with pytest.raises(cli.getpass.GetPassWarning):
        cli.read_secret("Secret: ")
