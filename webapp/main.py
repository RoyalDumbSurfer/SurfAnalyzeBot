from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import uuid
import cv2
import logging
import secrets
import hashlib
import hmac
import asyncio

from config import settings
from utils.video_formats import VIDEO_MIME_TYPES, GENERIC_MIME_TYPES
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

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


class UploadBodyLimit:
    """Bound multipart parsing, including requests without Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/upload":
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            # Allow multipart headers; the endpoint enforces the exact file limit.
            if received > settings.MAX_FILE_SIZE + 1024 * 1024:
                # Starlette closes temporary multipart files on this exception.
                raise MultiPartException("Video is too large.")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(UploadBodyLimit)

# Signed, HttpOnly sessions; no access code is placed in the cookie.
if settings.PRIVATE_BETA_ACCESS_CODE and (
    not settings.SESSION_SECRET or len(settings.SESSION_SECRET) < 32
):
    raise RuntimeError("Private beta requires SESSION_SECRET with at least 32 characters.")
session_secret = settings.SESSION_SECRET or secrets.token_urlsafe(32)


def beta_token():
    return hmac.new(
        session_secret.encode(),
        (settings.PRIVATE_BETA_ACCESS_CODE or "").encode(),
        hashlib.sha256,
    ).hexdigest()


@app.middleware("http")
async def private_beta_gate(request: Request, call_next):
    if settings.PRIVATE_BETA_ACCESS_CODE and request.url.path != "/beta":
        token = request.session.get("private_beta", "")
        if not isinstance(token, str) or not hmac.compare_digest(token, beta_token()):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"ok": False, "error": "Private beta access required"}, status_code=401)
            return RedirectResponse("/beta", status_code=303)
    response = await call_next(request)
    if settings.PRIVATE_BETA_ACCESS_CODE:
        response.headers["Cache-Control"] = "no-store"
    return response


# Added last so sessions are available to the gate, including static mounts.
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="surfanalyze_session",
    max_age=7 * 24 * 60 * 60,
    same_site="lax",
    https_only=settings.SESSION_COOKIE_SECURE,
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

@app.get("/beta", response_class=HTMLResponse)
async def beta_page(request: Request):
    if not settings.PRIVATE_BETA_ACCESS_CODE:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("beta.html", {"request": request})


@app.post("/beta", response_class=HTMLResponse)
async def beta_login(request: Request, access_code: str = Form(default="", max_length=1024)):
    if not settings.PRIVATE_BETA_ACCESS_CODE:
        return RedirectResponse("/", status_code=303)
    if not hmac.compare_digest(access_code.encode(), settings.PRIVATE_BETA_ACCESS_CODE.encode()):
        await asyncio.sleep(0.5)
        return templates.TemplateResponse(
            "beta.html", {"request": request, "error": "That access code is not valid."}, status_code=401
        )
    request.session.clear()
    request.session["private_beta"] = beta_token()
    return RedirectResponse("/", status_code=303)


def upload_page(request: Request, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse("index.html", {
        "request": request, "error": error,
        "video_types": VIDEO_MIME_TYPES, "generic_types": GENERIC_MIME_TYPES,
        "max_file_size": settings.MAX_FILE_SIZE,
        "max_size_label": f"{settings.MAX_FILE_SIZE / (1024 * 1024):g} MiB",
    }, status_code=status_code)


@app.exception_handler(HTTPException)
async def expected_http_error(request: Request, exc: HTTPException):
    if request.url.path == "/upload":
        too_large = exc.detail == "Video is too large."
        return upload_page(request, "Video is too large. Please choose a smaller video." if too_large
                           else "Video could not be read. Please choose another video.",
                           413 if too_large else exc.status_code)
    return await http_exception_handler(request, exc)


@app.exception_handler(MultiPartException)
async def oversized_body(request: Request, exc: MultiPartException):
    return upload_page(request, "Video is too large. Please choose a smaller video.", 413)


@app.exception_handler(RequestValidationError)
async def invalid_form(request: Request, exc: RequestValidationError):
    if request.url.path == "/upload":
        return upload_page(request, "Please choose a valid video to upload.", 400)
    if request.url.path == "/beta":
        return templates.TemplateResponse("beta.html", {
            "request": request, "error": "That access code is not valid."
        }, status_code=401)
    return await request_validation_exception_handler(request, exc)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return upload_page(request)


def readable_thumbnail(filepath: Path):
    video = cv2.VideoCapture(str(filepath))
    try:
        success, frame = video.read()
        if not video.isOpened() or not success or frame is None:
            return False
        # Thumbnail failure must not reject an otherwise readable video.
        try:
            cv2.imwrite(str(filepath.with_suffix(".jpg")), frame)
        except cv2.error:
            pass
        return True
    finally:
        video.release()


@app.post("/upload")
async def upload_video(request: Request, file: UploadFile | None = File(default=None)):
    if file is None or not file.filename:
        return upload_page(request, "Please choose a video to upload.", 400)
    safe_name = Path(file.filename.replace("\\", "/")).name
    extension = Path(safe_name).suffix.lower()
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    filepath = None
    accepted = False
    try:
        if "\x00" in safe_name or extension not in VIDEO_MIME_TYPES or mime_type not in (
            *VIDEO_MIME_TYPES.get(extension, ()), *GENERIC_MIME_TYPES
        ):
            return upload_page(request, "Unsupported video format. Please choose another video.", 400)
        if file.size is not None and file.size > settings.MAX_FILE_SIZE:
            return upload_page(request, "Video is too large. Please choose a smaller video.", 413)
        filepath = UPLOAD_DIR / f"{uuid.uuid4()}{extension}"
        size = 0
        with filepath.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.MAX_FILE_SIZE:
                    return upload_page(request, "Video is too large. Please choose a smaller video.", 413)
                destination.write(chunk)
        if not size:
            return upload_page(request, "This video is empty. Please choose another video.", 400)
        try:
            readable = await run_in_threadpool(readable_thumbnail, filepath)
        except cv2.error:
            readable = False
        if not readable:
            return upload_page(request, "Video could not be read. Please choose another video.", 400)
        job = job_manager.create_job(
            user_id=get_user_id(request), file_path=str(filepath), original_filename=safe_name,
        )
        accepted = True
        return RedirectResponse(url=f"/processing/{job.id}", status_code=303)
    except OSError:
        logger.warning("Upload storage unavailable")
        return upload_page(request, "We could not save your video. Please try again shortly.", 503)
    finally:
        await file.close()
        if not accepted and filepath is not None:
            try:
                filepath.unlink(missing_ok=True)
                filepath.with_suffix(".jpg").unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not clean up rejected upload")


@app.get("/processing/{job_id}", response_class=HTMLResponse)
def processing_page(request: Request, job_id: str):
    job = job_manager.get_job(job_id)

    if not job:
        return upload_page(request, "This analysis is no longer available. Please choose another video.", 404)

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
            "result_path": f"/download/{job.id}" if job.result_path else None,
            "thumbnail": getattr(job, "thumbnail", None),
        },
    }


@app.get("/result/{job_id}", response_class=HTMLResponse)
def result_page(request: Request, job_id: str):
    job = job_manager.get_job(job_id)

    if not job:
        return upload_page(request, "This analysis is no longer available. Please choose another video.", 404)

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
