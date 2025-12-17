# webapp/routes/download.py

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from jobs.job_manager import JobManager
from jobs.job_model import JobStatus

router = APIRouter()

jm = JobManager()


def _safe_resolve(path_str: str) -> Path:
    """
    Безопасно резолвим путь к файлу, чтобы избежать path traversal.
    Разрешаем только файлы внутри папки проекта.
    """
    p = Path(path_str)

    # Если у тебя в job.result_path хранится относительный путь — это ок.
    # Если вдруг абсолютный — тоже обработаем.
    resolved = p.resolve()

    project_root = Path.cwd().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path")

    return resolved


@router.get("/download/{job_id}")
def download_result(job_id: str):
    job = jm.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=409, detail=f"Job not ready. Status: {job.status}")

    if not job.result_path:
        raise HTTPException(status_code=404, detail="Result not found")

    file_path = _safe_resolve(job.result_path)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Result file missing on disk")

    # В браузере будет скачиваться как исходное имя файла
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )
