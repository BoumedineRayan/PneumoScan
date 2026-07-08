"""Prompts, extraction JSON robuste et garde-fous (règle d'incertitude + warning).

Version compacte : les prompts demandent une sortie courte (1 observation,
1 phrase de justification, 1 limite) pour que le modèle génère ~90-110 tokens
et tienne sous max_new_tokens=128 sans troncature.
"""
import json
import re

WARNING = ("Prototype pédagogique uniquement. Ne pas utiliser pour un diagnostic. "
           "L'image doit être vérifiée par un clinicien qualifié.")

VALID_CLASSES = {"normal", "suspected_opacity", "uncertain"}
VALID_QUALITY = {"good", "limited", "poor"}
UNCERTAINTY_THRESHOLD = 0.60

# Tolérance : si le modèle renvoie les valeurs énumérées en français,
# on les remappe vers les valeurs anglaises attendues par le contrat de sortie.
CLASS_ALIASES = {
    "incertain": "uncertain",
    "normale": "normal",
    "normal": "normal",
    "opacite_suspectee": "suspected_opacity",
    "opacité_suspectée": "suspected_opacity",
    "opacite suspectee": "suspected_opacity",
    "opacité suspectée": "suspected_opacity",
    "suspicion_opacite": "suspected_opacity",
    "suspicion d'opacite": "suspected_opacity",
    "suspicion d'opacité": "suspected_opacity",
}
QUALITY_ALIASES = {
    "bonne": "good",
    "correcte": "good",
    "limitee": "limited",
    "limitée": "limited",
    "mauvaise": "poor",
    "faible": "poor",
}

BASELINE_PROMPT = """Tu es un assistant pédagogique en radiologie. Tu n'es pas un clinicien et tu ne dois pas poser de diagnostic.
Analyse cette radiographie thoracique de face : normale vs opacité pulmonaire suspectée vs incertain.
Retourne UNIQUEMENT un JSON compact et valide, sans texte supplémentaire, avec exactement ces clés :
{"image_quality":"good|limited|poor","predicted_class":"normal|suspected_opacity|uncertain","confidence":0.0,"visual_evidence":"une courte observation","justification":"une courte phrase","limitations":"une courte limite"}
Règles : n'invente pas de constatations ; utilise "uncertain" si les indices sont faibles ; garde chaque champ très court.
Langue : rédige visual_evidence, justification et limitations en FRANÇAIS. Les valeurs de image_quality et predicted_class restent exactement parmi les mots anglais listés ci-dessus."""

IMPROVED_PROMPT = """Tu es un assistant pédagogique en radiologie. Tu n'es pas un clinicien et tu ne dois pas poser de diagnostic.
Analyse cette radiographie thoracique de face selon des règles strictes de gestion de l'incertitude. Si la constatation peut être due à la projection, à une rotation ou à une mauvaise exposition, baisse la confiance et privilégie "uncertain".
Retourne UNIQUEMENT un JSON compact et valide, sans texte supplémentaire, avec exactement ces clés :
{"image_quality":"good|limited|poor","predicted_class":"normal|suspected_opacity|uncertain","confidence":0.0,"visual_evidence":"une courte observation","justification":"une courte phrase","limitations":"une courte limite"}
Règles : aucune constatation inventée ; si confidence < 0.60, predicted_class doit être "uncertain" ; garde chaque champ très court.
Langue : rédige visual_evidence, justification et limitations en FRANÇAIS. Les valeurs de image_quality et predicted_class restent exactement parmi les mots anglais listés ci-dessus."""

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
    # Tolérance aux valeurs énumérées renvoyées en français
    pc = str(result.get("predicted_class", "")).strip().lower()
    result["predicted_class"] = CLASS_ALIASES.get(pc, pc)
    iq = str(result.get("image_quality", "")).strip().lower()
    result["image_quality"] = QUALITY_ALIASES.get(iq, iq)

    if result["predicted_class"] not in VALID_CLASSES:
        result["predicted_class"] = "uncertain"
    if result["image_quality"] not in VALID_QUALITY:
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


# ---------------- Rapport détaillé compact (2e inférence) ----------------

# Objectif : rapport COURT (1 page) et RAPIDE à générer, avec la radiographie.
# Peu de champs = moins de tokens = génération plus rapide.
# Contenu libre en FRANÇAIS ; valeurs énumérées en anglais.
DETAILED_REPORT_PROMPT = """Tu es un assistant pédagogique en radiologie. Tu n'es pas un clinicien et tu ne dois pas poser de diagnostic définitif.
Rédige un compte rendu COURT de cette radiographie thoracique de face, destiné à un médecin : il doit repérer d'un coup d'œil s'il y a une anomalie et où.
Reste factuel et prudent ; n'invente rien.

CONSIGNE DE LANGUE STRICTE : tout le texte libre (signe_principal, localisation, observations, justification, limitations) doit être écrit EN FRANÇAIS uniquement. N'écris JAMAIS un mot en anglais dans ces champs. Seules les valeurs de image_quality et predicted_class restent en anglais parmi les mots imposés.

Retourne UNIQUEMENT un JSON compact et valide, sans texte autour, exactement dans ce format (mêmes clés) :
{"image_quality":"good|limited|poor","predicted_class":"normal|suspected_opacity|uncertain","confidence":0.0,"signe_principal":"","localisation":"","observations":["",""],"justification":"","limitations":""}

Exemple du style et de la langue attendus (à imiter, pas à recopier) :
{"image_quality":"good","predicted_class":"suspected_opacity","confidence":0.68,"signe_principal":"Opacité alvéolaire mal limitée de la base droite.","localisation":"base pulmonaire droite","observations":["Opacité de la base droite","Silhouette cardiaque de taille normale","Pas de pneumothorax visible"],"justification":"Opacité focale compatible avec un foyer, sans certitude.","limitations":"Cliché unique de face, pas de comparatif."}

Règles : si confidence < 0.60, predicted_class doit être "uncertain" ; "localisation" décrit précisément la zone concernée (ex. "base pulmonaire droite") ou "aucune" ; 2 à 3 observations courtes maximum ; chaque champ très bref et EN FRANÇAIS."""


def apply_detailed_safeguards(result: dict) -> dict:
    """Normalise et sécurise la sortie du rapport compact."""
    pc = str(result.get("predicted_class", "")).strip().lower()
    result["predicted_class"] = CLASS_ALIASES.get(pc, pc)
    iq = str(result.get("image_quality", "")).strip().lower()
    result["image_quality"] = QUALITY_ALIASES.get(iq, iq)
    if result["predicted_class"] not in VALID_CLASSES:
        result["predicted_class"] = "uncertain"
    if result["image_quality"] not in VALID_QUALITY:
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

    for champ in ("signe_principal", "localisation", "justification"):
        result[champ] = str(result.get(champ, "") or "")
    result["observations"] = _as_list(result.get("observations"))[:3]
    lim = result.get("limitations")
    result["limitations"] = " ".join(_as_list(lim)) if isinstance(lim, list) else str(lim or "")
    result["warning"] = WARNING
    return result
