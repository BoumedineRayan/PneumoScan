# Assistant radiologue virtuel — application unifiée

Prototype pédagogique d'analyse de radiographies thoraciques frontales.
Une seule application qui gère : comptes utilisateurs, analyse par MedGemma 4B,
sortie JSON structurée, garde-fous, historique et rapport PDF.

> Prototype pédagogique. Aucune valeur clinique. Ne pas utiliser pour un diagnostic.

## Fonctionnalités

- Comptes utilisateurs (inscription, connexion, sessions sécurisées bcrypt).
- Upload d'une radiographie + choix du prompt (baseline / amélioré).
- Analyse par MedGemma 4B en 4-bit sur GPU (~6 s sur RTX 4060).
- Sortie JSON : classe, confiance, observations, justification, limites, warning.
- Garde-fous : seuil d'incertitude, warning systématique.
- Historique des analyses par utilisateur.
- Génération d'un rapport PDF épuré.
- Journalisation SQLite + CSV.

## Prérequis

- Python 3.11
- GPU NVIDIA (le modèle tourne en 4-bit, ~3.4 Go de VRAM)
- Un compte Hugging Face avec accès à `google/medgemma-4b-it` accepté

## Installation

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate                 # Windows
# source .venv/bin/activate            # Mac/Linux

# 1) torch GPU d'abord
pip install torch --index-url https://download.pytorch.org/whl/cu121
# 2) le reste
pip install -r requirements.txt
# 3) authentification Hugging Face (une fois)
hf auth login
```

## Lancement

```bash
uvicorn app.server:app --port 8000
```

Au démarrage, MedGemma se charge une fois (~25 s). Attends « Modèle prêt »,
puis ouvre http://localhost:8000 . Crée un compte, connecte-toi, analyse.

**Un seul terminal, un seul port, une seule interface.**


## Structure

```
app/
├── server.py       routes (auth + analyze + report) + chargement modèle
├── model.py        chargement MedGemma 4-bit + inférence
├── prompts.py      prompts baseline/amélioré + garde-fous + extraction JSON
├── report.py       génération PDF (reportlab)
├── storage.py      logs SQLite + CSV
├── auth.py         sessions par cookie signé
├── database.py     comptes + historique (SQLite/PostgreSQL)
└── templates/      login.html, register.html, dashboard.html
```

## Sécurité & éthique

- Mots de passe hachés (bcrypt), jamais en clair.
- Sessions par cookie signé (itsdangerous).
- Modèle `google/medgemma-4b-it` sous licence Health AI Developer Foundations,
  non validé cliniquement. Warning affiché sur chaque analyse.
