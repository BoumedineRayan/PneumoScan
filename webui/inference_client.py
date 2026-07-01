"""
Client vers le service d'inférence MedGemma (qui tourne sur le PC avec GPU).
L'URL du service est configurable via la variable d'environnement INFERENCE_URL
(ce sera l'URL du tunnel ngrok/cloudflare le jour de la démo).
"""
import os
import httpx

# En local sans tunnel : http://localhost:8000
# Avec tunnel : l'URL publique fournie par ngrok/cloudflare
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://localhost:8000")


async def call_inference(image_bytes: bytes, filename: str, variant: str) -> dict:
    """Envoie l'image au service d'inférence et renvoie le résultat JSON."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        files = {"file": (filename, image_bytes, "image/png")}
        data = {"variant": variant}
        resp = await client.post(f"{INFERENCE_URL}/predict", files=files, data=data)
        resp.raise_for_status()
        return resp.json()
