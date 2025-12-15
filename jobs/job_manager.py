from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .job_model import Job, JobStatus

# База задач в простом JSON-файле.
JOBS_DB_PATH = Path("jobs_db.json")


class JobManager:
    """
    Простейший менеджер задач: хранит их в JSON-файле.
    Для MVP этого достаточно. Потом можно заменить на БД.
    """

    def __init__(self, db_path: Path = JOBS_DB_PATH) -> None:
        self.db_path = db_path
        if not self.db_path.exists():
            self._write([])

    # --- Внутренние методы работы с файлом ---

    def _read(self) -> List[Job]:
        try:
            raw = self.db_path.read_text(encoding="utf-8")
            if not raw.strip():
                return []
            data = json.loads(raw)
            return [Job.from_dict(item) for item in data]
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            # если файл побился – просто начинаем с пустого списка
            return []

    def _write(self, jobs: List[Job]) -> None:
        data = [job.to_dict() for job in jobs]
        self.db_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- Публичные методы ---

    def create_job(self, user_id: int, file_path: str, chat_id: int | None = None) -> Job:
        jobs = self._read()
        job_id = str(uuid.uuid4())

        job = Job(
            id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            file_path=file_path,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        jobs.append(job)
        self._write(jobs)
        return job

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[Job]:
        jobs = self._read()
        if status is None:
            return jobs
        return [j for j in jobs if j.status == status]

    def get_job(self, job_id: str) -> Optional[Job]:
        jobs = self._read()
        for job in jobs:
            if job.id == job_id:
                return job
        return None

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[JobStatus] = None,
        result_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Job]:
        jobs = self._read()
        updated_job: Optional[Job] = None

        for idx, job in enumerate(jobs):
            if job.id == job_id:
                if status is not None:
                    job.status = status
                if result_path is not None:
                    job.result_path = result_path
                if error_message is not None:
                    job.error_message = error_message
                job.updated_at = datetime.utcnow()
                jobs[idx] = job
                updated_job = job
                break

        if updated_job is not None:
            self._write(jobs)

        return updated_job
