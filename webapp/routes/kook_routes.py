from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import random

router = APIRouter()
templates = Jinja2Templates(directory="webapp/templates")

@router.get("/kookometer", response_class=HTMLResponse)
async def kookometer(request: Request):
    return templates.TemplateResponse("kookometer.html", {"request": request})
