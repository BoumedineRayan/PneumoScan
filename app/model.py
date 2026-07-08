"""
Chargement de MedGemma 4B en 4-bit (une seule fois) et fonction d'inférence.
Le modèle reste en mémoire GPU entre les requêtes : chaque requête ne paie
que l'inférence (~6s sur RTX 4060), pas le chargement (~25s, payé une fois).
"""
import time
import torch
from PIL import Image
from transformers import (
    AutoProcessor,
    AutoModelForImageTextToText,
    BitsAndBytesConfig,
)

MODEL_ID = "google/medgemma-4b-it"

_STATE = {"model": None, "processor": None}

SYSTEM_TEXT = ("Tu es un assistant pédagogique prudent en radiologie. "
               "Tu ne poses jamais de diagnostic définitif. "
               "Tu réponds toujours en français, sauf pour les valeurs énumérées imposées par le format JSON.")


def load_model():
    """Charge le modèle en 4-bit. Idempotent : ne charge qu'une fois."""
    if _STATE["model"] is not None:
        return
    print("Chargement de MedGemma 4B en 4-bit...")
    t0 = time.time()
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4",
    )
    _STATE["processor"] = AutoProcessor.from_pretrained(MODEL_ID)
    _STATE["model"] = AutoModelForImageTextToText.from_pretrained(
        MODEL_ID, quantization_config=bnb, device_map="auto"
    ).eval()
    print(f"Modèle prêt en {time.time() - t0:.1f}s "
          f"(VRAM {torch.cuda.memory_allocated()/1e9:.2f} Go)")


def run_inference(image: Image.Image, prompt: str, max_new_tokens: int = 128) -> tuple[str, float]:
    """Lance une inférence. Retourne (texte_brut, latence_secondes)."""
    if _STATE["model"] is None:
        load_model()
    proc, model = _STATE["processor"], _STATE["model"]
    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_TEXT}]},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "image": image}]},
    ]
    inputs = proc.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    ).to(model.device)
    input_len = inputs["input_ids"].shape[-1]
    t0 = time.time()
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    latency = time.time() - t0
    decoded = proc.decode(gen[0][input_len:], skip_special_tokens=True)
    return decoded, latency


def run_detailed_inference(image: Image.Image, prompt: str,
                           max_new_tokens: int = 200) -> tuple[str, float]:
    """
    2e inférence, compacte, pour le rapport médecin (1 page).
    Renvoie (texte_brut, latence_s). Sortie courte => génération plus rapide.
    """
    if _STATE["model"] is None:
        load_model()
    proc, model = _STATE["processor"], _STATE["model"]
    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_TEXT}]},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "image": image}]},
    ]
    inputs = proc.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    ).to(model.device)
    input_len = inputs["input_ids"].shape[-1]
    t0 = time.time()
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    decoded = proc.decode(gen[0][input_len:], skip_special_tokens=True)
    latency = time.time() - t0
    return decoded, latency
