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
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import database as db
from . import reports_store
from .auth import make_session_cookie, read_session_cookie, COOKIE_NAME
from .model import load_model, run_inference, run_detailed_inference
from .prompts import (PROMPTS, extract_json, apply_safeguards, WARNING,
                      DETAILED_REPORT_PROMPT, apply_detailed_safeguards)
from .storage import log_result
from .report import build_detailed_report

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    load_model()          # chargement unique de MedGemma au démarrage
    yield


app = FastAPI(title="Assistant radiologue virtuel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
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
    reports_map = reports_store.get_reports_map(user_id)  # {analysis_id: état} + purge
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"username": username, "analyses": analyses,
                                       "reports_map": reports_map})


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
        analysis_id = db.save_analysis(user_id, file.filename, variant, result, latency)
        result["analysis_id"] = analysis_id
        result["latency_s"] = round(latency, 1)
        result["filename"] = file.filename
        result["variant"] = variant
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": str(e), "warning": WARNING})


# ---------------- Rapport détaillé (2e inférence) ----------------

@app.post("/report")
async def report(request: Request,
                 file: UploadFile = File(...),
                 payload: str = Form(...),
                 ttl_label: str = Form("1j")):
    """
    Lance une 2e inférence détaillée (rapport médecin), embarque la radiographie,
    construit le PDF, l'enregistre dans data_outputs/reports et renvoie son état.
    """
    user_id = current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Non connecté."})
    try:
        data = json.loads(payload)
        filename = data.get("filename", "radiographie")
        variant = data.get("variant", "baseline")
        base_latency = float(data.get("latency_s", 0.0))
        analysis_id = data.get("analysis_id")

        image = Image.open(BytesIO(await file.read())).convert("RGB")
        raw, detail_latency = run_detailed_inference(image, DETAILED_REPORT_PROMPT)
        detailed = apply_detailed_safeguards(extract_json(raw))

        # On embarque la radiographie elle-même dans le rapport (PNG)
        radio_buf = BytesIO()
        image.save(radio_buf, format="PNG")
        radio_png = radio_buf.getvalue()

        pdf = build_detailed_report(detailed, filename, variant,
                                    base_latency, detail_latency, radio_png)

        state = reports_store.create_report(
            user_id=user_id, filename=filename, variant=variant,
            result=detailed, pdf_bytes=pdf, heatmap_bytes=radio_png,
            detail_latency=detail_latency, ttl_label=ttl_label,
            analysis_id=analysis_id)
        state["detail_latency_s"] = round(detail_latency, 1)
        return JSONResponse(state)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "warning": WARNING})


@app.get("/report/{report_id}/download")
def report_download(request: Request, report_id: int):
    user_id = current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Non connecté."})
    found = reports_store.get_active_report_for_download(report_id, user_id)
    if not found:
        return JSONResponse(status_code=410, content={"error": "Rapport expiré ou introuvable."})
    path, fname = found
    return Response(content=path.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/report/{report_id}/ttl")
def report_set_ttl(request: Request, report_id: int, ttl_label: str = Form(...)):
    user_id = current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Non connecté."})
    r = db.get_report(report_id)
    if not r or r.get("user_id") != user_id:
        return JSONResponse(status_code=404, content={"error": "Rapport introuvable."})
    state = reports_store.set_ttl(report_id, ttl_label)
    return JSONResponse(state)
