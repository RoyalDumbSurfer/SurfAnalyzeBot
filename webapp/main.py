from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import uuid
import cv2
import logging

from pydantic import BaseModel

from jobs.job_manager import JobManager
from jobs.job_model import JobStatus
from webapp.routes.download import router as download_router


# =========================
# APP INITIALIZATION
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(download_router)

app.add_middleware(
    SessionMiddleware,
    secret_key="super-secret-key-change-later",
    same_site="lax",
    https_only=False,
)

templates = Jinja2Templates(directory="webapp/templates")

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTED_FRAMES_DIR = Path("data/extracted_frames")
EXTRACTED_FRAMES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/frames", StaticFiles(directory=str(EXTRACTED_FRAMES_DIR)), name="frames")

job_manager = JobManager()


# =========================
# TELEGRAM AUTH
# =========================

class TelegramUser(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@app.post("/telegram-auth")
async def telegram_auth(request: Request, user: TelegramUser):
    request.session["telegram_id"] = user.telegram_id
    request.session["telegram_username"] = user.username
    request.session["telegram_first_name"] = user.first_name
    request.session["telegram_last_name"] = user.last_name

    return {"ok": True}


def get_user_id(request: Request):
    """
    Если пользователь пришёл из Telegram Mini App — берём telegram_id.
    Если открыт обычный браузер — ставим 0.

    Важно:
    НЕ использовать строку 'anonymous',
    потому что job_model пытается привести user_id к int.
    """
    return request.session.get("telegram_id", 0)


# =========================
# ROUTES
# =========================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
    )


@app.post("/upload")
async def upload_video(request: Request, file: UploadFile = File(...)):
    user_id = get_user_id(request)

    if not file.filename:
        return HTMLResponse("No file uploaded", status_code=400)

    safe_name = Path(file.filename).name
    unique_name = f"{uuid.uuid4()}_{safe_name}"
    filepath = UPLOAD_DIR / unique_name

    file_content = await file.read()

    if not file_content:
        return HTMLResponse("Uploaded file is empty", status_code=400)

    with open(filepath, "wb") as f:
        f.write(file_content)

    # =========================
    # THUMBNAIL GENERATION
    # =========================

    thumbnail_path = None
    video = None

    try:
        video = cv2.VideoCapture(str(filepath))
        success, frame = video.read()

        if success and frame is not None:
            thumb_name = f"{filepath.stem}_thumb.jpg"
            thumb_path = UPLOAD_DIR / thumb_name
            cv2.imwrite(str(thumb_path), frame)
            thumbnail_path = f"/uploads/{thumb_name}"

    except Exception as e:
        logger.warning(f"Thumbnail generation failed: {e}")

    finally:
        if video is not None:
            video.release()

    # =========================
    # CREATE JOB
    # =========================

    job = job_manager.create_job(
        user_id=user_id,
        file_path=str(filepath),
        original_filename=safe_name,
    )

    if hasattr(job, "thumbnail"):
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
        {
            "request": request,
            "job": job,
            "job_id": job_id,
        },
    )


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str):
    job = job_manager.get_job(job_id)

    if not job:
        return JSONResponse(
            {"ok": False, "error": "Job not found"},
            status_code=404,
        )

    return {
        "ok": True,
        "job": {
            "id": job.id,
            "status": job.status.value,
            "result_path": job.result_path,
            "thumbnail": getattr(job, "thumbnail", None),
        },
    }


@app.get("/result/{job_id}", response_class=HTMLResponse)
def result_page(request: Request, job_id: str):
    job = job_manager.get_job(job_id)

    if not job:
        return HTMLResponse("Job not found", status_code=404)

    if job.status != JobStatus.DONE:
        return RedirectResponse(
            url=f"/processing/{job_id}",
            status_code=303,
        )

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "job": job,
            "analysis_result": job.analysis_result,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = get_user_id(request)

    jobs = job_manager.list_jobs()
    user_jobs = [j for j in jobs if str(j.user_id) == str(user_id)]
    jobs_sorted = sorted(user_jobs, key=lambda j: j.created_at, reverse=True)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "jobs": jobs_sorted,
        },
    )


@app.get("/dashboard-data", response_class=HTMLResponse)
def dashboard_data(request: Request):
    user_id = get_user_id(request)

    jobs = job_manager.list_jobs()
    user_jobs = [j for j in jobs if str(j.user_id) == str(user_id)]
    jobs_sorted = sorted(user_jobs, key=lambda j: j.created_at, reverse=True)

    return templates.TemplateResponse(
        "dashboard_partial.html",
        {
            "request": request,
            "jobs": jobs_sorted,
        },
    )
