from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import os

from webapp.routes import kook_routes
  # Подключаем роуты

# ✅ Сначала создаём FastAPI-приложение
app = FastAPI()

# 📁 Создаём папку для загрузок, если не существует
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# 🧩 Настраиваем шаблоны и статику
templates = Jinja2Templates(directory="webapp/templates")
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")

# ✅ Подключаем роут Cook-o-Meter
app.include_router(kook_routes.router)

# 📥 Главная страница
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "result": ""})

# 📤 Обработка загрузки
@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):
    contents = await file.read()
    filename = file.filename
    with open(f"downloads/{filename}", "wb") as f:
        f.write(contents)
    return templates.TemplateResponse(
        "index.html", {"request": request, "result": f"✅ Файл {filename} загружен!"}
    )

