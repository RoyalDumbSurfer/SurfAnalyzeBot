from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from jobs.job_model import JobStatus
from accounts.web import owned_job

router = APIRouter()


def private_file(path: Path, root: Path):
    """Contain resolved paths, including symlinks, within the intended media root."""
    try:
        relative = path.absolute().relative_to(root.absolute())
        if ".." in relative.parts:
            raise ValueError
        candidate = root
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ValueError
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        if not resolved.is_file():
            raise ValueError
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Not found") from None
    return resolved


@router.get("/download/{job_id}")
def download_result(request: Request, job_id: str):
    job = owned_job(request, job_id)

    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=404, detail="Not found")

    if not job.result_path:
        raise HTTPException(status_code=404, detail="Not found")

    path = private_file(Path(job.result_path), request.app.state.results_dir)

    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )
