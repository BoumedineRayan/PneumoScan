"""
Application web avec comptes.
  GET  /              -> page d'accueil (redirige vers login ou dashboard)
  GET  /register      -> formulaire d'inscription
  POST /register      -> crée le compte
  GET  /login         -> formulaire de connexion
  POST /login         -> connecte, pose le cookie de session
  GET  /logout        -> déconnecte
  GET  /dashboard     -> interface d'analyse + historique (protégé)
  POST /analyze       -> appelle le service d'inférence, sauve lié au compte (protégé)

Lancer :  uvicorn webui.server:app --reload --port 9000
Le service d'inférence MedGemma doit tourner séparément (INFERENCE_URL).
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import database as db
from .auth import make_session_cookie, read_session_cookie, COOKIE_NAME
from .inference_client import call_inference

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Assistant radiologue - portail", lifespan=lifespan)

# Garantir que les tables existent même hors lifespan (ex: tests).
# Tolérant aux erreurs : si la DB n'est pas encore joignable au chargement
# du module (cas possible sur certains hébergeurs), le lifespan réessaiera.
try:
    db.init_db()
except Exception as e:
    print(f"[init_db] report au lifespan ({e})")


def current_user(request: Request) -> int | None:
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
    # Connexion automatique après inscription
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
        return templates.TemplateResponse(request, "login.html", {"error": "Identifiants incorrects."})
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(user_id), httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------------- Dashboard (protégé) ----------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)
    username = db.get_username(user_id)
    analyses = db.get_user_analyses(user_id)
    return templates.TemplateResponse(request, "dashboard.html", {"username": username, "analyses": analyses})


@app.post("/analyze")
async def analyze(request: Request, file: UploadFile = File(...), variant: str = Form("baseline")):
    user_id = current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Non connecté."})
    try:
        image_bytes = await file.read()
        result = await call_inference(image_bytes, file.filename, variant)
        if "error" in result:
            return JSONResponse(status_code=502, content={
                "error": "Service d'inférence: " + str(result["error"])})
        latency = result.get("latency_s", 0.0)
        db.save_analysis(user_id, file.filename, variant, result, latency)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=502, content={
            "error": f"Service d'inférence injoignable : {e}"})
