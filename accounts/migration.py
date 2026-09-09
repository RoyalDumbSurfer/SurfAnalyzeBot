"""Explicit, all-or-nothing legacy JSON import; source files are never modified."""
import hashlib
import json
import re
from pathlib import Path

from jobs.job_model import Job
from storage.database import Database


def import_legacy(database_path, source, owner_username, *, apply=False):
    raw = Path(source).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    records = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(records, list):
        raise ValueError("Legacy data must be a JSON list. Nothing was imported.")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not isinstance(record.get("file_path"), str) or not record["file_path"]:
            raise ValueError("Invalid legacy job record. Nothing was imported.")
        job = Job.from_dict(record)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", job.id) or job.id in seen:
            raise ValueError("Invalid or duplicate legacy job ID. Nothing was imported.")
        seen.add(job.id)
    database = Database(database_path, initialize=False)
    with database.connect(write=True) as db:
        owner = db.execute("SELECT id FROM users WHERE username=? AND role='admin' AND is_active=1",
                           (owner_username.strip().lower(),)).fetchone()
        if not owner:
            raise ValueError("An active admin must exist before importing legacy jobs.")
        previous = db.execute("SELECT value FROM metadata WHERE key='legacy_import'").fetchone()
        if previous:
            if previous["value"] != digest:
                raise ValueError("A different legacy snapshot was already imported. Manual review is required.")
            return {"jobs": len(records), "already_imported": True, "applied": False}
        for record in records:
            if db.execute("SELECT 1 FROM jobs WHERE id=?", (record["id"],)).fetchone():
                raise ValueError("A legacy job ID already exists. Nothing was imported.")
        if apply:
            for record in records:
                payload = dict(record, owner_user_id=owner["id"])
                job = Job.from_dict(payload)
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?)",
                           (job.id, owner["id"], job.status.value, job.created_at.isoformat(), json.dumps(payload)))
            db.execute("INSERT INTO metadata VALUES ('legacy_import', ?)", (digest,))
        return {"jobs": len(records), "already_imported": False, "applied": apply}
