from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings
from storage.database import Database
from .job_model import Job, JobStatus


class JobManager:
    """Transactional SQLite storage with the existing worker-facing interface."""

    def __init__(self, db_path=None):
        self.database = Database(db_path or settings.DATABASE_PATH, initialize=db_path is not None)
        self.db_path = self.database.path
        if db_path is None and Path("jobs_db.json").exists():
            with self.database.connect() as db:
                migrated = db.execute("SELECT value FROM metadata WHERE key='legacy_import'").fetchone()
            if not migrated:
                raise RuntimeError("Legacy jobs require an explicit import. See docs/accounts-v1.md.")
            if migrated["value"] != hashlib.sha256(Path("jobs_db.json").read_bytes()).hexdigest():
                raise RuntimeError("Legacy jobs changed after import. Stop old writers and review the migration.")

    @staticmethod
    def _job(row):
        if row is None:
            return None
        data = json.loads(row["payload"])
        data["owner_user_id"] = row["owner_user_id"]
        return Job.from_dict(data)

    def create_job(self, user_id: int, file_path: str, chat_id=None, original_filename=None,
                   *, owner_user_id=None, analysis_language=None) -> Job:
        job = Job(id=str(uuid.uuid4()), user_id=user_id, file_path=file_path,
                  status=JobStatus.QUEUED, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                  chat_id=chat_id, original_filename=original_filename, owner_user_id=owner_user_id,
                  analysis_language=analysis_language)
        with self.database.connect(write=True) as db:
            db.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
                       (job.id, owner_user_id, job.status.value, job.created_at.isoformat(), json.dumps(job.to_dict())))
        return job

    def list_jobs(self, status: Optional[JobStatus] = None, *, owner_user_id=None) -> list[Job]:
        clauses, values = [], []
        if status is not None:
            clauses.append("status=?")
            values.append(status.value)
        if owner_user_id is not None:
            clauses.append("owner_user_id=?")
            values.append(owner_user_id)
        query = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        with self.database.connect() as db:
            return [self._job(row) for row in db.execute(query, values)]

    def get_job(self, job_id: str, *, owner_user_id=None) -> Optional[Job]:
        query, values = "SELECT * FROM jobs WHERE id=?", [job_id]
        if owner_user_id is not None:
            query += " AND owner_user_id=?"
            values.append(owner_user_id)
        with self.database.connect() as db:
            return self._job(db.execute(query, values).fetchone())

    def update_job(self, job_id: str, *, status=None, result_path=None, error_message=None,
                   analysis_result=None, extracted_frame_paths=None) -> Optional[Job]:
        with self.database.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            job = self._job(row)
            if job is None:
                return None
            payload = json.loads(row["payload"])
            for name, value in (("status", status), ("result_path", result_path),
                                ("error_message", error_message), ("analysis_result", analysis_result),
                                ("extracted_frame_paths", extracted_frame_paths)):
                if value is not None:
                    setattr(job, name, value)
                    payload[name] = value.value if isinstance(value, JobStatus) else value
            job.updated_at = datetime.utcnow()
            payload["updated_at"] = job.updated_at.isoformat()
            db.execute("UPDATE jobs SET status=?, payload=? WHERE id=?",
                       (job.status.value, json.dumps(payload), job_id))
            return job
