from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import uuid
import os
import cv2

from jobs.job_manager import JobManager
from jobs.job_model import JobStatus
from webapp.routes.download import router as download_router

app = FastAPI()
app.include_router(download_router)

app.add_middleware(
    SessionMiddleware,
    secret_key="super-secret-key-change-later"
)

templates = Jinja2Templates(directory="webapp/templates")

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory="data/uploads"), name="uploads")

job_manager = JobManager()


def get_user_id(request: Request) -> int:
    if "user_id" not in request.session:
        request.session["user_id"] = str(uuid.uuid4())
    return 0


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_video(request: Request, file: UploadFile = File(...)):
    user_id = get_user_id(request)

    safe_name = Path(file.filename).name
    filepath = UPLOAD_DIR / f"{uuid.uuid4()}_{safe_name}"

    with open(filepath, "wb") as f:
        f.write(await file.read())

    # -------- Thumbnail generation --------
    thumbnail_path = None
    try:
        video = cv2.VideoCapture(str(filepath))
        success, frame = video.read()
        if success:
            thumb_name = filepath.stem + "_thumb.jpg"
            thumb_path = UPLOAD_DIR / thumb_name
            cv2.imwrite(str(thumb_path), frame)
            thumbnail_path = f"/uploads/{thumb_name}"
    except:
        pass
    # --------------------------------------

    job = job_manager.create_job(
        user_id=user_id,
        file_path=str(filepath),
    )

    # временно динамически добавляем thumbnail
    job.thumbnail = thumbnail_path

    return RedirectResponse(
        url=f"/processing/{job.id}",
        status_code=303,
    )


@app.get("/processing/{job_id}", response_class=HTMLResponse)
def processing_page(request: Request, job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)

    return templates.TemplateResponse(
        "processing.html",
        {"request": request, "job_id": job_id},
    )


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return JSONResponse({"ok": False}, status_code=404)

    return {
        "ok": True,
        "job": {
            "id": job.id,
            "status": job.status.value,
            "result_path": job.result_path,
        },
    }

@app.get("/result/{job_id}", response_class=HTMLResponse)
def result_page(request: Request, job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)

    if job.status != JobStatus.DONE:
        return RedirectResponse(url=f"/processing/{job_id}")

    result_data = {
        "level": "Intermediate",
        "focus": "Stance & timing",
        "summary": "Хороший контроль, но можно улучшить устойчивость в повороте."
    }

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "job": job,
            "result": result_data,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    jobs = job_manager.list_jobs()
    jobs_sorted = sorted(jobs, key=lambda j: j.created_at, reverse=True)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "jobs": jobs_sorted,
        },
    )


@app.get("/dashboard-data", response_class=HTMLResponse)
def dashboard_data(request: Request):
    jobs = job_manager.list_jobs()
    jobs_sorted = sorted(jobs, key=lambda j: j.created_at, reverse=True)

    return templates.TemplateResponse(
        "dashboard_partial.html",
        {
            "request": request,
            "jobs": jobs_sorted,
        },
    )
