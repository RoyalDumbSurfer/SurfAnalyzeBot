from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from webapp.storage.jobs import get_job

router = APIRouter()
templates = Jinja2Templates(directory="webapp/templates")


@router.get("/processing/{job_id}", response_class=HTMLResponse)
async def processing_page(request: Request, job_id: str):
    job = get_job(job_id)

    if not job:
        return HTMLResponse("Job not found", status_code=404)

    return templates.TemplateResponse(
        "processing.html",
        {
            "request": request,
            "job_id": job_id,
            "status": job["status"]
        }
    )
