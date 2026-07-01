"""
API de l'application.
  GET  /            -> page web (upload + choix du prompt)
  POST /predict     -> reçoit image + variante, renvoie le JSON, journalise
  POST /report      -> renvoie un PDF de rapport à partir d'un résultat JSON

Lancer :  uvicorn app.server:app --reload --port 8000
Le modèle se charge une seule fois au démarrage (lifespan).
"""
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .model import load_model, run_inference
from .prompts import PROMPTS, extract_json, apply_safeguards, WARNING
from .storage import log_result
from .report import build_report

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()          # chargement unique (~25s) au démarrage du serveur
    yield


app = FastAPI(title="Assistant radiologue virtuel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE / "templates" / "index.html").read_text(encoding="utf-8")


@app.post("/predict")
async def predict(file: UploadFile = File(...), variant: str = Form("improved")):
    if variant not in PROMPTS:
        variant = "improved"
    import time
    t_start = time.time()
    try:
        image = Image.open(BytesIO(await file.read())).convert("RGB")
        raw, inference_s = run_inference(image, PROMPTS[variant])
        result = apply_safeguards(extract_json(raw), variant)
        log_result(file.filename, variant, result, inference_s)
        total_s = time.time() - t_start
        result["inference_s"] = round(inference_s, 1)      # génération du modèle
        result["processing_s"] = round(total_s - inference_s, 2)  # parsing + garde-fous + logs
        result["latency_s"] = round(total_s, 1)            # total bout-en-bout
        result["filename"] = file.filename
        result["variant"] = variant
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": str(e), "warning": WARNING})


@app.post("/report")
async def report(payload: str = Form(...)):
    """payload = le JSON du résultat (string) renvoyé par /predict."""
    data = json.loads(payload)
    pdf = build_report(
        data,
        filename=data.get("filename", "radiographie"),
        variant=data.get("variant", "improved"),
        latency=float(data.get("latency_s", 0.0)),
    )
    fname = f"rapport_{data.get('filename', 'radio')}.pdf".replace(" ", "_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
