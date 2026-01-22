from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobs.job_manager import JobManager
from jobs.job_model import JobStatus
from webapp.routes.download import router as download_router

app = FastAPI(title="SurfAnalyze WebApp")

# подключаем /download/{job_id}
app.include_router(download_router)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

job_manager = JobManager()

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/upload")


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/processing/{job_id}", response_class=HTMLResponse)
def processing_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        "processing.html",
        {
            "request": request,
            "job_id": job_id,
        },
    )


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    safe_name = Path(file.filename or "upload.bin").name
    out_path = DOWNLOADS_DIR / safe_name

    content = await file.read()
    out_path.write_bytes(content)

    # создаём job ОДИН раз
    job = job_manager.create_job(user_id=0, file_path=str(out_path))

    return RedirectResponse(
        url=f"/processing/{job.id}",
        status_code=303,
    )


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        return JSONResponse({"ok": False, "error": "job_not_found"}, status_code=404)

    return {
        "ok": True,
        "job": {
            "id": job.id,
            "user_id": job.user_id,
            "file_path": job.file_path,
            "status": job.status.value
            if isinstance(job.status, JobStatus)
            else str(job.status),
            "result_path": job.result_path,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        },
    }


@app.get("/kookometer", response_class=HTMLResponse)
def kookometer_page():
    return HTMLResponse("<h1>Kook-o-Meter (demo)</h1>")
