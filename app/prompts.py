"""Prompts, extraction JSON robuste et garde-fous (règle d'incertitude + warning).

Version compacte : les prompts demandent une sortie courte (1 observation,
1 phrase de justification, 1 limite) pour que le modèle génère ~90-110 tokens
et tienne sous max_new_tokens=128 sans troncature.
"""
import json
import re

WARNING = ("Educational prototype only. Not for diagnosis. "
           "A qualified clinician must verify the image.")

VALID_CLASSES = {"normal", "suspected_opacity", "uncertain"}
VALID_QUALITY = {"good", "limited", "poor"}
UNCERTAINTY_THRESHOLD = 0.60

BASELINE_PROMPT = """You are an educational radiology assistant. You are not a clinician and must not give a diagnosis.
Analyze this frontal chest X-ray: normal vs suspected lung opacity vs uncertain.
Return ONLY compact valid JSON, no extra text, with exactly these keys:
{"image_quality":"good|limited|poor","predicted_class":"normal|suspected_opacity|uncertain","confidence":0.0,"visual_evidence":"one short observation","justification":"one short sentence","limitations":"one short limitation"}
Rules: do not invent findings; use "uncertain" if evidence is weak; keep every field very short."""

IMPROVED_PROMPT = """You are an educational radiology assistant. You are not a clinician and must not give a diagnosis.
Analyze this frontal chest X-ray under strict uncertainty rules. If the finding could be due to projection, rotation or poor exposure, lower confidence and prefer "uncertain".
Return ONLY compact valid JSON, no extra text, with exactly these keys:
{"image_quality":"good|limited|poor","predicted_class":"normal|suspected_opacity|uncertain","confidence":0.0,"visual_evidence":"one short observation","justification":"one short sentence","limitations":"one short limitation"}
Rules: no invented findings; if confidence < 0.60, predicted_class must be "uncertain"; keep every field very short."""

PROMPTS = {"baseline": BASELINE_PROMPT, "improved": IMPROVED_PROMPT}


def extract_json(text: str) -> dict:
    """Extrait le premier objet JSON, même entouré de balises markdown ```json```."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("Aucun JSON exploitable dans la réponse du modèle.")
    return json.loads(match.group(0))


def _as_list(v):
    """Accepte une chaine OU une liste et renvoie toujours une liste (pour l'affichage/PDF)."""
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if v in (None, ""):
        return []
    return [str(v)]


def apply_safeguards(result: dict, variant: str) -> dict:
    """Normalise les champs, applique la règle d'incertitude, force le warning."""
    if result.get("predicted_class") not in VALID_CLASSES:
        result["predicted_class"] = "uncertain"
    if result.get("image_quality") not in VALID_QUALITY:
        result["image_quality"] = "limited"
    try:
        conf = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    result["confidence"] = conf

    if result["image_quality"] == "poor" and result["predicted_class"] == "normal":
        result["predicted_class"] = "uncertain"
    if conf < UNCERTAINTY_THRESHOLD and result["predicted_class"] != "uncertain":
        result["predicted_class"] = "uncertain"

    result["visual_evidence"] = _as_list(result.get("visual_evidence"))
    result["limitations"] = _as_list(result.get("limitations"))
    result.setdefault("justification", "")
    result["warning"] = WARNING
    return result