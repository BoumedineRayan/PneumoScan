"""
Tests automatiques simples pour PneumoScan.

Verifient le contrat de sortie et les garde-fous, sans GPU ni modele :
- extraction JSON robuste (avec/sans balises markdown)
- normalisation des classes et de la confiance
- regle d'incertitude (seuil 0.60)
- regle qualite "poor" interdit "normal"
- warning toujours present

Lancer :  python -m pytest tests_pneumoscan.py -v
      ou :  python tests_pneumoscan.py   (mode autonome sans pytest)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.prompts import (
    extract_json, apply_safeguards, WARNING,
    VALID_CLASSES, UNCERTAINTY_THRESHOLD,
)


# ---------- extract_json ----------

def test_extract_json_simple():
    d = extract_json('{"predicted_class": "normal", "confidence": 0.9}')
    assert d["predicted_class"] == "normal"

def test_extract_json_avec_balises_markdown():
    # Le modele entoure souvent le JSON de ```json ... ```
    txt = '```json\n{"predicted_class": "uncertain", "confidence": 0.3}\n```'
    d = extract_json(txt)
    assert d["predicted_class"] == "uncertain"

def test_extract_json_invalide_leve_erreur():
    try:
        extract_json("pas de json ici")
        assert False, "aurait du lever une erreur"
    except ValueError:
        pass


# ---------- apply_safeguards : classes ----------

def test_classe_invalide_devient_uncertain():
    r = apply_safeguards({"predicted_class": "pneumonie", "confidence": 0.9}, "baseline")
    assert r["predicted_class"] == "uncertain"

def test_classe_valide_conservee():
    r = apply_safeguards({"predicted_class": "normal", "confidence": 0.95}, "baseline")
    assert r["predicted_class"] == "normal"


# ---------- apply_safeguards : regle d'incertitude ----------

def test_confiance_basse_force_uncertain():
    # Sous le seuil 0.60 -> doit basculer en uncertain
    r = apply_safeguards({"predicted_class": "normal", "confidence": 0.40}, "improved")
    assert r["predicted_class"] == "uncertain"

def test_confiance_haute_ne_bascule_pas():
    r = apply_safeguards({"predicted_class": "suspected_opacity", "confidence": 0.85}, "improved")
    assert r["predicted_class"] == "suspected_opacity"


# ---------- apply_safeguards : qualite poor ----------

def test_qualite_poor_interdit_normal():
    r = apply_safeguards(
        {"predicted_class": "normal", "confidence": 0.95, "image_quality": "poor"}, "baseline")
    assert r["predicted_class"] == "uncertain"


# ---------- apply_safeguards : confiance bornee ----------

def test_confiance_hors_bornes_ramenee():
    r = apply_safeguards({"predicted_class": "normal", "confidence": 1.5}, "baseline")
    assert 0.0 <= r["confidence"] <= 1.0

def test_confiance_non_numerique_geree():
    r = apply_safeguards({"predicted_class": "normal", "confidence": "abc"}, "baseline")
    assert r["confidence"] == 0.0


# ---------- apply_safeguards : warning ----------

def test_warning_toujours_present():
    r = apply_safeguards({"predicted_class": "normal", "confidence": 0.9}, "baseline")
    assert r["warning"] == WARNING
    assert len(r["warning"]) > 0


# ---------- contrat de sortie complet ----------

def test_contrat_sortie_complet():
    r = apply_safeguards({"predicted_class": "normal", "confidence": 0.9}, "baseline")
    for champ in ["predicted_class", "confidence", "visual_evidence",
                  "limitations", "justification", "warning"]:
        assert champ in r
    assert r["predicted_class"] in VALID_CLASSES
    assert isinstance(r["visual_evidence"], list)
    assert isinstance(r["limitations"], list)


# ---------- mode autonome (sans pytest) ----------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__} : {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__} : {e}")
    print(f"\n{ok}/{len(tests)} tests passes.")