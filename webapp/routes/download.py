from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from jobs.job_manager import JobManager
from jobs.job_model import JobStatus

router = APIRouter()
job_manager = JobManager()


@router.get("/download/{job_id}")
def download_result(job_id: str):
    job = job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=400, detail="Job not finished yet")

    if not job.result_path:
        raise HTTPException(status_code=404, detail="Result not available")

    path = Path(job.result_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )
