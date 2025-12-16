from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from jobs.job_manager import JobManager


app = FastAPI(title="SurfAnalyze WebApp")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# если папки static нет — не падаем
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

job_manager = JobManager()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/upload")


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    # Рендерим твой index.html как есть
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    """
    1) сохраняем файл в папку downloads/
    2) создаём job в jobs_db.json (status = queued)
    """
    # 1) Папка downloads
    downloads_dir = Path(settings.DOWNLOAD_FOLDER)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # 2) Сохраняем файл
    safe_name = Path(file.filename).name  # защита от путей
    save_path = downloads_dir / safe_name

    contents = await file.read()
    save_path.write_bytes(contents)

    # 3) Создаём задачу в JobManager (важно: это то, чего не хватало)
    job = job_manager.create_job(
        user_id=0,                # web-загрузка (не из Telegram)
        file_path=str(save_path),
        chat_id=None
    )

    # 4) Возвращаем простой ответ (без правок шаблона)
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="ru">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>SurfAnalyze — Uploaded</title>
          <style>
            body {{
              font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
              background: #fff;
              color: #0b0f19;
              padding: 28px;
            }}
            .card {{
              max-width: 720px;
              margin: 0 auto;
              border: 1px solid #e6e8ec;
              border-radius: 16px;
              padding: 18px 18px;
              box-shadow: 0 8px 30px rgba(16,24,40,.08);
            }}
            .muted {{ color:#667085; }}
            code {{
              background:#f6f7f9;
              border:1px solid #e6e8ec;
              padding:2px 6px;
              border-radius:8px;
            }}
            a {{
              display:inline-block;
              margin-top: 12px;
              text-decoration:none;
              border:1px solid #e6e8ec;
              border-radius:12px;
              padding:10px 12px;
              color:#0b0f19;
              background:#f6f7f9;
              font-weight:600;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h2>✅ Файл загружен и поставлен в очередь</h2>
            <p class="muted">Файл: <code>{safe_name}</code></p>
            <p class="muted">Job ID: <code>{job.id}</code></p>
            <p class="muted">Статус: <code>queued</code> (воркер должен подхватить)</p>
            <a href="/upload">← Назад к загрузке</a>
          </div>
        </body>
        </html>
        """
    )


@app.get("/kookometer", response_class=HTMLResponse)
def kookometer_demo():
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="ru">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Kook-o-Meter</title>
          <style>
            body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 28px; }
          </style>
        </head>
        <body>
          <h2>📈 Kook-o-Meter (demo)</h2>
          <p>Пока просто демо-страница.</p>
          <a href="/upload">← Назад</a>
        </body>
        </html>
        """
    )
