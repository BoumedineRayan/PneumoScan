"""
Application unifiée : comptes + analyse MedGemma + PDF, dans UN seul serveur.

  GET  /            -> redirige vers login ou dashboard
  GET  /login       -> connexion       | POST /login
  GET  /register    -> inscription      | POST /register
  GET  /logout      -> déconnexion
  GET  /dashboard   -> interface d'analyse + historique (protégé)
  POST /analyze     -> analyse l'image DIRECTEMENT (modèle dans cette app)
  POST /report      -> génère le PDF de rapport

Lancer :  uvicorn app.server:app --port 8000
Le modèle MedGemma se charge une seule fois au démarrage.
"""
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, Response)
from fastapi.templating import Jinja2Templates
from PIL import Image

from . import database as db
from .auth import make_session_cookie, read_session_cookie, COOKIE_NAME
from .model import load_model, run_inference
from .prompts import PROMPTS, extract_json, apply_safeguards, WARNING
from .storage import log_result
from .report import build_report

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    load_model()          # chargement unique de MedGemma au démarrage
    yield


app = FastAPI(title="Assistant radiologue virtuel", lifespan=lifespan)
try:
    db.init_db()
except Exception as e:
    print(f"[init_db] report au lifespan ({e})")


def current_user(request: Request):
    return read_session_cookie(request)


# ---------------- Accueil ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


# ---------------- Inscription ----------------

@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": None})


@app.post("/register", response_class=HTMLResponse)
def register(request: Request, username: str = Form(...), password: str = Form(...)):
    ok, msg = db.create_user(username, password)
    if not ok:
        return templates.TemplateResponse(request, "register.html", {"error": msg})
    user_id = db.verify_user(username, password)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(user_id), httponly=True, samesite="lax")
    return resp


# ---------------- Connexion ----------------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user_id = db.verify_user(username, password)
    if not user_id:
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Identifiants incorrects."})
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(user_id), httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------------- Dashboard ----------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)
    username = db.get_username(user_id)
    analyses = db.get_user_analyses(user_id)
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"username": username, "analyses": analyses})


# ---------------- Analyse (modèle appelé DIRECTEMENT) ----------------

@app.post("/analyze")
async def analyze(request: Request, file: UploadFile = File(...),
                  variant: str = Form("baseline")):
    user_id = current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Non connecté."})
    if variant not in PROMPTS:
        variant = "baseline"
    try:
        image = Image.open(BytesIO(await file.read())).convert("RGB")
        raw, latency = run_inference(image, PROMPTS[variant])
        result = apply_safeguards(extract_json(raw), variant)
        log_result(file.filename, variant, result, latency)
        db.save_analysis(user_id, file.filename, variant, result, latency)
        result["latency_s"] = round(latency, 1)
        result["filename"] = file.filename
        result["variant"] = variant
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": str(e), "warning": WARNING})


# ---------------- Rapport PDF ----------------

@app.post("/report")
async def report(request: Request, payload: str = Form(...)):
    user_id = current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Non connecté."})
    data = json.loads(payload)
    pdf = build_report(
        data,
        filename=data.get("filename", "radiographie"),
        variant=data.get("variant", "baseline"),
        latency=float(data.get("latency_s", 0.0)))
    fname = f"rapport_{data.get('filename', 'radio')}.pdf".replace(" ", "_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
