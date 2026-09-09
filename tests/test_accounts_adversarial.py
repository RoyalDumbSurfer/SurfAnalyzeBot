"""Adversarial checks use only temporary stores and synthetic legacy copies."""
import hashlib
import json
import multiprocessing
import shutil
import sqlite3
from pathlib import Path

import pytest

from accounts.migration import import_legacy
from accounts.store import AccountStore
from jobs.job_manager import JobManager
from jobs.job_model import JobStatus
from storage.database import Database
from tests.conftest import PASSWORD, csrf, sign_in
from webapp import main


def fingerprints(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


@pytest.fixture
def legacy_copy(tmp_path):
    original = tmp_path / "legacy-original"
    original.mkdir()
    records = []
    for index, status in enumerate(("done", "processing", "queued", "failed")):
        job_id = f"legacy-{status}"
        video = f"data/uploads/{job_id}.mp4"
        result = f"videos_processed/{job_id}.mp4"
        thumbnail = f"data/uploads/{job_id}_thumb.jpg"
        frames = [f"/frames/{job_id}/frame_{i:02d}.jpg" for i in range(1, 16)]
        for relative in [video, result, thumbnail] + ["data/extracted_frames/" + f.split("/frames/")[1] for f in frames]:
            path = original / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"representative legacy media bytes")
        records.append({
            "id": job_id, "user_id": [0, "anonymous", None, 12345][index], "chat_id": None,
            "file_path": video, "original_filename": f"Ride {index}.mp4", "status": status,
            "created_at": "2026-08-01T10:20:30", "updated_at": "2026-08-01T10:25:30",
            "result_path": result, "thumbnail": "/uploads/" + Path(thumbnail).name,
            "analysis_result": {"level": "Intermediate", "main_issue": "Timing", "why_it_matters": "Balance",
                                "how_to_fix": "Look ahead", "drill": "Practice turns", "coach_note": "Keep practicing"},
            "extracted_frame_paths": frames, "error_message": "legacy failure" if status == "failed" else None,
            "legacy_extra_metadata": {"camera": "family", "tags": ["sunset", 1, None]},
        })
    (original / "jobs_db.json").write_text(json.dumps(records), encoding="utf-8")
    rehearsal = tmp_path / "rehearsal"
    shutil.copytree(original, rehearsal)
    return original, rehearsal, records


def test_copy_rehearsal_preserves_every_field_and_file(legacy_copy, tmp_path):
    original, copy, records = legacy_copy
    before = fingerprints(original)
    assert fingerprints(copy) == before
    path = tmp_path / "rehearsal.sqlite3"
    store = AccountStore(path)
    admin = store.create_admin("owner", PASSWORD)
    with store.database.connect() as db:
        before_dump = list(db.iterdump())
    preview = import_legacy(path, copy / "jobs_db.json", "owner")
    assert preview == {"jobs": 4, "already_imported": False, "applied": False}
    with store.database.connect() as db:
        assert list(db.iterdump()) == before_dump
    assert import_legacy(path, copy / "jobs_db.json", "owner", apply=True)["applied"]
    with store.database.connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        for record in records:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (record["id"],)).fetchone()
            assert row["owner_user_id"] == admin.id
            assert row["status"] == record["status"]
            assert json.loads(row["payload"]) == dict(record, owner_user_id=admin.id)
    manager = JobManager(path)
    manager.update_job("legacy-queued", status=JobStatus.PROCESSING)
    with store.database.connect() as db:
        changed = json.loads(db.execute("SELECT payload FROM jobs WHERE id='legacy-queued'").fetchone()[0])
    for key, value in records[2].items():
        if key not in {"status", "updated_at"}:
            assert changed[key] == value  # Includes unknown fields and legacy ID types.
    extra = manager.create_job(user_id=admin.id, owner_user_id=admin.id, file_path="new.mp4")
    assert import_legacy(path, copy / "jobs_db.json", "owner", apply=True)["already_imported"]
    assert len(manager.list_jobs()) == 5 and manager.get_job(extra.id)
    assert manager.get_job("legacy-queued").status == JobStatus.PROCESSING
    assert fingerprints(original) == before
    assert fingerprints(copy) == before


def test_import_rolls_back_when_second_insert_fails(legacy_copy, tmp_path):
    original, copy, _ = legacy_copy
    before = fingerprints(original)
    path = tmp_path / "rehearsal.sqlite3"
    store = AccountStore(path)
    store.create_admin("owner", PASSWORD)
    with store.database.connect(write=True) as db:
        db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON jobs WHEN NEW.id='legacy-processing' "
                   "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        import_legacy(path, copy / "jobs_db.json", "owner", apply=True)
    with store.database.connect() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert not db.execute("SELECT 1 FROM metadata WHERE key='legacy_import'").fetchone()
        db.execute("DROP TRIGGER fail_import")
    assert import_legacy(path, copy / "jobs_db.json", "owner", apply=True)["jobs"] == 4
    assert fingerprints(original) == fingerprints(copy) == before


def test_production_cli_import_sequence_on_copy(legacy_copy, tmp_path):
    import os
    import subprocess
    import sys
    original, copy, _ = legacy_copy
    before = fingerprints(original)
    path = tmp_path / "cli-rehearsal.sqlite3"
    AccountStore(path).create_admin("owner", PASSWORD)
    env = os.environ.copy()
    env.update(DATABASE_PATH=str(path), API_TOKEN="test-only-api-token",
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    command = [sys.executable, "-m", "accounts.cli", "import-legacy", "--source", "jobs_db.json", "--owner", "owner"]
    for flags, expected_count, expected_output in [([], 0, "applied: False"),
                                                 (["--apply"], 4, "applied: True"),
                                                 (["--apply"], 4, "already imported: True")]:
        result = subprocess.run(command + flags, cwd=copy, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert expected_output in result.stdout
        assert len(JobManager(path).list_jobs()) == expected_count
    assert fingerprints(original) == fingerprints(copy) == before


@pytest.mark.parametrize("legacy_exists", [True, False])
def test_runtime_missing_database_never_creates_empty_store(tmp_path, monkeypatch, legacy_exists):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "missing" / "production.sqlite3"
    monkeypatch.setattr(main.settings, "DATABASE_PATH", str(path))
    if legacy_exists:
        (tmp_path / "jobs_db.json").write_text("[]")
    with pytest.raises(RuntimeError, match="Database is missing"):
        JobManager()
    with pytest.raises(RuntimeError, match="Database is missing"):
        AccountStore(path, initialize=False)
    assert not path.exists() and not path.parent.exists()


def test_dry_run_missing_database_does_not_initialize_one(legacy_copy, tmp_path):
    _, copy, _ = legacy_copy
    path = tmp_path / "not-bootstrapped.sqlite3"
    with pytest.raises(RuntimeError, match="Database is missing"):
        import_legacy(path, copy / "jobs_db.json", "owner")
    assert not path.exists()


def test_runtime_rejects_changed_legacy_snapshot(legacy_copy, tmp_path, monkeypatch):
    _, copy, _ = legacy_copy
    path = tmp_path / "rehearsal.sqlite3"
    AccountStore(path).create_admin("owner", PASSWORD)
    import_legacy(path, copy / "jobs_db.json", "owner", apply=True)
    monkeypatch.chdir(copy)
    monkeypatch.setattr(main.settings, "DATABASE_PATH", str(path))
    assert len(JobManager().list_jobs()) == 4
    # Simulate a stale JSON writer changing only the rehearsal copy after cutover.
    with (copy / "jobs_db.json").open("a") as stream:
        stream.write("\n")
    with pytest.raises(RuntimeError, match="changed after import"):
        JobManager()
    with pytest.raises(ValueError, match="different legacy snapshot"):
        import_legacy(path, copy / "jobs_db.json", "owner", apply=True)
    assert len(JobManager(path).list_jobs()) == 4


def _concurrent_writer(path, ready, start, kind, job_id):
    manager = JobManager(path)
    ready.put(kind)
    if not start.wait(15):
        raise RuntimeError("Test synchronization failed")
    for index in range(20):
        if kind == "web":
            manager.create_job(user_id=1, owner_user_id=1, file_path=f"upload-{index}.mp4")
        else:
            manager.update_job(job_id, analysis_result={"level": f"stage-{index}"})


def _waiting_writer(path, ready, job_id):
    database = Database(path, initialize=False)
    ready.put("waiting")
    with database.connect(write=True) as db:
        db.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))


def test_separate_web_and_worker_processes_do_not_lose_writes(app_state):
    manager = main.job_manager
    job = manager.create_job(user_id=1, owner_user_id=1, file_path="worker.mp4")
    ctx = multiprocessing.get_context("spawn")
    ready, start = ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_concurrent_writer, args=(str(manager.db_path), ready, start, kind, job.id))
                 for kind in ("web", "worker")]
    try:
        for process in processes:
            process.start()
        assert {ready.get(timeout=20), ready.get(timeout=20)} == {"web", "worker"}
        start.set()
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert len(manager.list_jobs()) == 21
        assert manager.get_job(job.id).analysis_result == {"level": "stage-19"}
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()


def test_wal_readers_and_busy_timeout_during_other_process_write(app_state):
    manager = main.job_manager
    job = manager.create_job(user_id=1, owner_user_id=1, file_path="ride.mp4")
    database = manager.database
    with database.connect() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 15000
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    child = ctx.Process(target=_waiting_writer, args=(str(database.path), ready, job.id))
    try:
        with database.connect(write=True) as db:
            db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job.id,))
            child.start()
            assert ready.get(timeout=20) == "waiting"
            with database.connect() as reader:
                assert reader.execute("SELECT status FROM jobs WHERE id=?", (job.id,)).fetchone()[0] == "queued"
            child.join(timeout=0.3)
            assert child.is_alive()  # The writer waits; readers still see committed data.
        child.join(timeout=20)
        assert child.exitcode == 0
        with database.connect() as db:
            assert db.execute("SELECT status FROM jobs WHERE id=?", (job.id,)).fetchone()[0] == "done"
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        if child.is_alive():
            child.terminate()
            child.join()


def test_exact_resource_ids_cannot_be_probed_by_b_or_guest(client, app_state):
    job = main.job_manager.create_job(user_id=1, owner_user_id=1, file_path=str(main.UPLOAD_DIR / "a.mp4"), original_filename="private-a.mp4")
    Path(job.file_path).write_bytes(b"original")
    frame = main.EXTRACTED_FRAMES_DIR / job.id / "frame_01.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"frame")
    thumbnail = main.UPLOAD_DIR / "a_thumb.jpg"
    thumbnail.write_bytes(b"thumbnail")
    output = app_state[1] / "a.mp4"
    output.write_bytes(b"result")
    main.job_manager.update_job(job.id, status=JobStatus.DONE, result_path=str(output),
                               extracted_frame_paths=[f"/frames/{job.id}/frame_01.jpg"])
    with main.job_manager.database.connect(write=True) as db:
        payload = json.loads(db.execute("SELECT payload FROM jobs WHERE id=?", (job.id,)).fetchone()[0])
        payload["thumbnail"] = "/uploads/a_thumb.jpg"
        db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(payload), job.id))
    routes = [(f"/result/{job.id}", "/result/missing"), (f"/processing/{job.id}", "/processing/missing"),
              (f"/api/jobs/{job.id}", "/api/jobs/missing"), (f"/frames/{job.id}/frame_01.jpg", "/frames/missing/frame_01.jpg"),
              ("/uploads/a.mp4", "/uploads/missing.mp4"), ("/uploads/a_thumb.jpg", "/uploads/missing.jpg"),
              (f"/download/{job.id}", "/download/missing")]
    for existing, _ in routes:
        assert client.get(existing).status_code == 200
    client.post("/logout")
    client.headers.pop("X-CSRF-Token")
    for existing, missing in routes + [("/dashboard", "/dashboard"), ("/dashboard-data", "/dashboard-data")]:
        actual, absent = client.get(existing), client.get(missing)
        assert actual.status_code == absent.status_code == (401 if existing.startswith("/api/") else 303)
        assert actual.content == absent.content
        assert actual.headers.get("location") == absent.headers.get("location")
    sign_in(client, "bob")
    for existing, missing in routes:
        actual, absent = client.get(existing), client.get(missing)
        assert actual.status_code == absent.status_code == 404
        assert actual.content == absent.content == b'{"detail":"Not found"}'
    assert "private-a.mp4" not in client.get("/dashboard?user_id=1&owner_user_id=1").text
    assert "private-a.mp4" not in client.get("/dashboard-data?user_id=1").text


def test_origin_redirect_and_normalization_attacks(guest):
    token = csrf(guest)
    data = {"username": " ALICE ", "password": PASSWORD, "csrf": token, "next": "https://attacker.invalid"}
    for origin in ("null", "http://testserver", "https://testserver.attacker.invalid"):
        assert guest.post("/login", data=data, headers={"Origin": origin}).status_code == 403
    response = guest.post("/login?next=//attacker.invalid", data=data, headers={"Origin": "https://testserver"})
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"
    assert guest.get("/api/me").json()["username"] == "alice"
    guest.headers["X-CSRF-Token"] = csrf(guest, "/")
    assert guest.post("/logout?next=https://attacker.invalid").headers["location"] == "/login"


def test_ip_limit_cannot_be_bypassed_by_username_or_forwarded_header(guest, app_state):
    store = app_state[0]
    for index in range(30):
        assert store.allow_attempt("testclient", f"user-{index}")
    response = guest.post("/login", data={"username": "fresh-user", "password": PASSWORD, "csrf": csrf(guest)},
                          headers={"X-Forwarded-For": "192.0.2.123"})
    assert response.status_code == 429
