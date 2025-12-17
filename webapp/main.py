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


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    # защита от хитрых имен (path traversal)
    safe_name = Path(file.filename or "upload.bin").name
    out_path = DOWNLOADS_DIR / safe_name

    content = await file.read()
    out_path.write_bytes(content)

    # user_id=0 для web (пока без авторизации)
    job = job_manager.create_job(user_id=0, file_path=str(out_path))

    # Страница со слежением за статусом + кнопка скачивания
    html = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SurfAnalyze — processing</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
      background: #f6f7f9;
      margin: 0;
      padding: 40px 16px;
      color: #0b0f19;
    }}
    .card {{
      max-width: 760px;
      margin: 0 auto;
      background: #fff;
      border: 1px solid #e6e8ec;
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 8px 30px rgba(16, 24, 40, 0.08);
    }}
    .title {{
      font-size: 22px;
      font-weight: 800;
      margin-bottom: 12px;
    }}
    .status {{
      font-size: 16px;
      margin-top: 10px;
    }}
    .muted {{
      color: #667085;
      font-size: 14px;
    }}
    code {{
      background: #f6f7f9;
      border: 1px solid #e6e8ec;
      padding: 2px 6px;
      border-radius: 8px;
    }}
    .done {{
      color: #16a34a;
      font-weight: 700;
    }}
    .btn {{
      appearance: none;
      border: 1px solid #e6e8ec;
      background: #0b0f19;
      color: #fff;
      padding: 10px 14px;
      border-radius: 12px;
      font-weight: 650;
      font-size: 14px;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
    }}
    .btn.secondary {{
      background: #f6f7f9;
      color: #0b0f19;
    }}
    .row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="title">📤 Файл принят</div>

    <div class="muted">Файл: <code>{safe_name}</code></div>
    <div class="muted">Job ID: <code id="job-id">{job.id}</code></div>

    <div class="status">
      Статус: <span id="status">queued</span>
    </div>

    <div id="result" class="status" style="display:none;"></div>

    <div class="row">
      <a class="btn secondary" href="/upload">← Назад к загрузке</a>
    </div>
  </div>

<script>
const jobId = "{job.id}";
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");

async function poll() {{
  try {{
    const res = await fetch(`/api/jobs/${{jobId}}`);
    if (!res.ok) return;

    const data = await res.json();
    if (!data.ok) return;

    const job = data.job;
    statusEl.textContent = job.status;

    if (job.status === "done") {{
      statusEl.classList.add("done");
      resultEl.style.display = "block";

      const downloadUrl = `/download/${{jobId}}`;

      resultEl.innerHTML = `
        ✅ Готово!<br>
        Результат: <code>${{job.result_path}}</code><br>
        <a class="btn" href="${{downloadUrl}}">⬇️ Скачать результат</a>
      `;

      clearInterval(timer);
    }}

    if (job.status === "failed") {{
      statusEl.textContent = "failed";
      resultEl.style.display = "block";
      resultEl.innerHTML = `❌ Ошибка: <code>${{job.error_message}}</code>`;
      clearInterval(timer);
    }}

  }} catch (e) {{
    console.error(e);
  }}
}}

const timer = setInterval(poll, 2000);
poll();
</script>

</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/kookometer", response_class=HTMLResponse)
def kookometer_page(request: Request):
    return HTMLResponse("<h1>Kook-o-Meter (demo)</h1>")


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
            "chat_id": job.chat_id,
            "file_path": job.file_path,
            "status": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
            "result_path": job.result_path,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        },
    }
