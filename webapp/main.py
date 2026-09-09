from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import uuid
import cv2
import logging
import sqlite3
import re

from config import settings
from utils.video_formats import VIDEO_MIME_TYPES, GENERIC_MIME_TYPES
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from contextlib import asynccontextmanager
from accounts.store import AccountStore
from accounts.web import current_user, csrf_token, check_csrf, owned_job
from webapp.i18n import language, translate, template_translate, SUPPORTED_LANGUAGES
from webapp.routes.download import private_file
from fastapi.responses import FileResponse

from jobs.job_manager import JobManager
from jobs.job_model import JobStatus
from webapp.routes.download import router as download_router


# =========================
# APP INITIALIZATION
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

job_manager = None
account_store = None


@asynccontextmanager
async def lifespan(app):
    global job_manager, account_store
    job_manager = job_manager or JobManager()
    account_store = account_store or AccountStore(settings.DATABASE_PATH, initialize=False)
    app.state.job_manager = job_manager
    app.state.results_dir = Path("videos_processed")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(download_router)


class UploadBodyLimit:
    """Bound multipart parsing, including requests without Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in {"/upload", "/login", "/register", "/logout", "/language"}:
            return await self.app(scope, receive, send)
        limit = settings.MAX_FILE_SIZE + 1024 * 1024 if scope["path"] == "/upload" else 16 * 1024
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            # Allow multipart headers; the endpoint enforces the exact file limit.
            if received > limit:
                # Starlette closes temporary multipart files on this exception.
                raise MultiPartException("Video is too large.")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(UploadBodyLimit)

@app.middleware("http")
async def account_gate(request: Request, call_next):
    request.state.user = await run_in_threadpool(account_store.session_user, request.session.get("sid"))
    public = request.url.path in {"/login", "/register", "/beta", "/language"}
    if not public and request.state.user is None:
        if request.url.path.startswith("/api/"):
            response = JSONResponse({"ok": False, "error": "Login required"}, status_code=401)
        else:
            response = RedirectResponse("/login", status_code=303)
    else:
        # Tokens protect form submissions; Origin also rejects cross-origin POSTs.
        origin = request.headers.get("origin")
        expected_origin = str(request.base_url).rstrip("/")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != expected_origin:
            response = HTMLResponse(translate(request, "Please reload the page and try again."), status_code=403)
        else:
            response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


if not settings.SESSION_SECRET or len(settings.SESSION_SECRET) < 32:
    raise RuntimeError("Accounts require SESSION_SECRET with at least 32 characters.")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    session_cookie="surfanalyze_account",
    max_age=7 * 86400,
    same_site="lax",
    https_only=settings.SESSION_COOKIE_SECURE,
)

templates = Jinja2Templates(directory="webapp/templates")
templates.env.globals["csrf_token"] = csrf_token
templates.env.globals.update(t=template_translate, language=language)


@app.post("/language")
async def select_language(request: Request, selected: str = Form(), csrf: str = Form(default=""),
                          return_to: str = Form(default="/", max_length=200)):
    check_csrf(request, csrf)
    if selected not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language")
    # Only known local pages; no user-provided absolute URLs or Referer redirects.
    if not re.fullmatch(r"/(?:login|register|dashboard|(?:result|processing)/[A-Za-z0-9_-]+)?", return_to):
        return_to = "/"
    response = RedirectResponse(return_to, status_code=303)
    response.set_cookie("surfanalyze_language", selected, max_age=365 * 86400,
                        httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite="lax")
    return response

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTED_FRAMES_DIR = Path("data/extracted_frames")
EXTRACTED_FRAMES_DIR.mkdir(parents=True, exist_ok=True)

def auth_page(request, mode, error=None, status_code=200):
    return templates.TemplateResponse("account.html", {
        "request": request, "mode": mode, "error": translate(request, error) if error else None, "csrf": csrf_token(request)
    }, status_code=status_code)


@app.get("/beta")
async def old_beta():
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return auth_page(request, "login")


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return auth_page(request, "register")


async def establish_session(request, user):
    await run_in_threadpool(account_store.revoke_session, request.session.get("sid"))
    request.session.clear()
    request.session["sid"] = await run_in_threadpool(account_store.new_session, user.id)
    csrf_token(request)
    return RedirectResponse("/dashboard", status_code=303)


async def allow_auth_attempt(request, username):
    address = request.client.host if request.client else "unknown"
    return await run_in_threadpool(account_store.allow_attempt, address, username)


@app.post("/login")
async def login(request: Request, username: str = Form(default="", max_length=40),
                password: str = Form(default="", max_length=128), csrf: str = Form(default="")):
    check_csrf(request, csrf)
    if not await allow_auth_attempt(request, username):
        return auth_page(request, "login", "Too many attempts. Please try again in 15 minutes.", 429)
    user = await run_in_threadpool(account_store.authenticate, username, password)
    if user is None:
        return auth_page(request, "login", "That username or password is not valid.", 401)
    return await establish_session(request, user)


@app.post("/register")
async def register(request: Request, username: str = Form(default="", max_length=40),
                   password: str = Form(default="", max_length=128),
                   invite_code: str = Form(default="", max_length=256), csrf: str = Form(default="")):
    check_csrf(request, csrf)
    if not await allow_auth_attempt(request, username):
        return auth_page(request, "register", "Too many attempts. Please try again in 15 minutes.", 429)
    try:
        user = await run_in_threadpool(account_store.register, username, password, invite_code)
    except ValueError:
        return auth_page(request, "register", "Unable to register. Check your invite, username, and password requirements.", 400)
    return await establish_session(request, user)


@app.post("/logout")
async def logout(request: Request, csrf: str = Form(default="")):
    check_csrf(request, csrf)
    await run_in_threadpool(account_store.revoke_session, request.session.get("sid"))
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/api/me")
def api_me(request: Request):
    user = current_user(request)
    return {"id": user.id, "username": user.username, "role": user.role}


@app.get("/frames/{job_id}/{filename}")
def frame_file(request: Request, job_id: str, filename: str):
    job = owned_job(request, job_id)
    url = f"/frames/{job_id}/{filename}"
    if url not in (job.extracted_frame_paths or []):
        raise HTTPException(status_code=404, detail="Not found")
    path = private_file(EXTRACTED_FRAMES_DIR / job_id / filename, EXTRACTED_FRAMES_DIR)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/uploads/{filename}")
def upload_file(request: Request, filename: str):
    user = current_user(request)
    # Preserve legacy URLs but only serve files explicitly belonging to this user.
    for job in job_manager.list_jobs(owner_user_id=user.id):
        if Path(job.file_path).name == filename:
            return FileResponse(private_file(Path(job.file_path), UPLOAD_DIR))
        if job.thumbnail == f"/uploads/{filename}":
            return FileResponse(private_file(UPLOAD_DIR / filename, UPLOAD_DIR), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Not found")


def upload_page(request: Request, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse("index.html", {
        "request": request, "error": translate(request, error) if error else None,
        "video_types": VIDEO_MIME_TYPES, "generic_types": GENERIC_MIME_TYPES,
        "max_file_size": settings.MAX_FILE_SIZE, "csrf": csrf_token(request),
        "max_size_label": f"{settings.MAX_FILE_SIZE / (1024 * 1024):g} MiB",
    }, status_code=status_code)


@app.exception_handler(HTTPException)
async def expected_http_error(request: Request, exc: HTTPException):
    if request.url.path in {"/logout", "/language"} and exc.status_code == 403:
        return HTMLResponse(translate(request, "Please reload the page and try again."), status_code=403)
    if request.url.path in {"/login", "/register"}:
        return auth_page(request, request.url.path[1:], "Please reload the page and check your details.", exc.status_code)
    if request.url.path == "/upload":
        if exc.status_code == 403:
            return upload_page(request, "Please reload the page and choose your video again.", 403)
        too_large = exc.detail == "Video is too large."
        return upload_page(request, "Video is too large. Please choose a smaller video." if too_large
                           else "Video could not be read. Please choose another video.",
                           413 if too_large else exc.status_code)
    return await http_exception_handler(request, exc)


@app.exception_handler(MultiPartException)
async def oversized_body(request: Request, exc: MultiPartException):
    if request.url.path in {"/login", "/register"}:
        return auth_page(request, request.url.path[1:], "Please check your details and try again.", 413)
    return upload_page(request, "Video is too large. Please choose a smaller video.", 413)


@app.exception_handler(RequestValidationError)
async def invalid_form(request: Request, exc: RequestValidationError):
    if request.url.path == "/upload":
        return upload_page(request, "Please choose a valid video to upload.", 400)
    if request.url.path in {"/login", "/register"}:
        return auth_page(request, request.url.path[1:], "Please check your details and try again.", 400)
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
async def upload_video(request: Request, file: UploadFile | None = File(default=None), csrf: str = Form(default="")):
    check_csrf(request, csrf)
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
            user_id=current_user(request).id, owner_user_id=current_user(request).id,
            file_path=str(filepath), original_filename=safe_name,
            analysis_language=language(request),
        )
        accepted = True
        return RedirectResponse(url=f"/processing/{job.id}", status_code=303)
    except (OSError, sqlite3.Error):
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
    job = owned_job(request, job_id)

    return templates.TemplateResponse(
        "processing.html",
        {
            "request": request,
            "job": job,
            "job_id": job_id,
        },
    )


@app.get("/api/jobs/{job_id}")
def api_job_status(request: Request, job_id: str):
    job = owned_job(request, job_id)

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
    job = owned_job(request, job_id)

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
    user_jobs = job_manager.list_jobs(owner_user_id=current_user(request).id)
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
    user_jobs = job_manager.list_jobs(owner_user_id=current_user(request).id)
    jobs_sorted = sorted(user_jobs, key=lambda j: j.created_at, reverse=True)

    return templates.TemplateResponse(
        "dashboard_partial.html",
        {
            "request": request,
            "jobs": jobs_sorted,
        },
    )
