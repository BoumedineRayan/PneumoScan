# Assistant radiologue virtuel — Portail web (comptes + historique)

Portail web avec authentification et historique par utilisateur, pour le
prototype pédagogique d'analyse de radiographies thoraciques.

**Architecture (Option A) :** ce portail gère les comptes, l'interface et la
base de données. Il NE fait PAS tourner MedGemma. L'inférence est déléguée à un
service séparé (ton PC avec GPU), appelé via HTTP.

```
[Navigateur] -> [Ce portail sur Railway] --HTTP--> [MedGemma sur ton PC via ngrok]
```

## Base de données

Le code s'adapte automatiquement :
- **En local** : SQLite (fichier `webui_data/app.db`, rien à installer).
- **Sur Railway** : PostgreSQL (permanent), détecté via la variable `DATABASE_URL`.

---

## A. Tester en local (avant de déployer)

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate    |    Mac/Linux : source .venv/bin/activate
pip install -r requirements.txt
uvicorn webui.server:app --port 9000
```
Ouvre http://localhost:9000 . Crée un compte, connecte-toi.
(Les analyses nécessitent que ton service MedGemma tourne sur le port 8000.)

---

## B. Pousser sur GitHub

```bash
git init
git add .
git commit -m "Portail assistant radiologue avec comptes"
git branch -M main
git remote add origin https://github.com/TON_PSEUDO/TON_REPO.git
git push -u origin main
```

---

## C. Déployer sur Railway (étape par étape)

1. Va sur railway.app, connecte-toi avec GitHub.
2. **New Project** -> **Deploy from GitHub repo** -> choisis ton dépôt.
3. Railway détecte Python et lance le build automatiquement.
4. **Ajoute la base PostgreSQL** : dans ton projet Railway, clique **New** ->
   **Database** -> **Add PostgreSQL**. Railway crée la base ET définit
   automatiquement la variable `DATABASE_URL` pour ton app. Rien à copier.
5. **Ajoute les variables d'environnement** (onglet Variables de ton service) :
   - `APP_SECRET_KEY` = une longue chaîne aléatoire secrète (ex: colle 40
     caractères au hasard). Sert à signer les cookies de session.
   - `INFERENCE_URL` = l'URL publique de ton service MedGemma (voir section D).
6. Railway redéploie. Clique sur l'URL publique générée (onglet Settings ->
   Domains -> Generate Domain) pour ouvrir ton app en ligne.

---

## D. Connecter ton PC (le modèle) au portail en ligne

Le portail sur Railway doit pouvoir appeler MedGemma sur ton PC.

1. Sur ton PC, lance le service d'inférence :
   ```bash
   uvicorn app.server:app --port 8000
   ```
2. Installe ngrok (ngrok.com), puis expose le port 8000 :
   ```bash
   ngrok http 8000
   ```
   ngrok affiche une URL du type `https://xxxx-xxxx.ngrok-free.app`.
3. Copie cette URL dans la variable `INFERENCE_URL` sur Railway (section C.5).
4. Tant que ton PC + ngrok tournent, le portail en ligne peut analyser des radios.

> Note : sur le forfait gratuit ngrok, l'URL change à chaque redémarrage.
> Pense à mettre à jour INFERENCE_URL sur Railway si tu relances ngrok.

---

## Variables d'environnement (récapitulatif)

| Variable | Où | Rôle |
|----------|----|----|
| `DATABASE_URL` | auto (Railway Postgres) | connexion base permanente |
| `APP_SECRET_KEY` | à définir sur Railway | signature des sessions |
| `INFERENCE_URL` | à définir sur Railway | URL du service MedGemma (ngrok) |

## Sécurité

- Mots de passe hachés (bcrypt), jamais en clair.
- Sessions par cookie signé (itsdangerous), non falsifiable.
- Dashboard protégé : redirection vers /login si non connecté.

## Structure

```
├── webui/
│   ├── server.py            routes (login, register, dashboard, analyze)
│   ├── database.py          DB dual PostgreSQL/SQLite + bcrypt
│   ├── auth.py              sessions par cookie signé
│   ├── inference_client.py  appel HTTP vers MedGemma
│   └── templates/           login.html, register.html, dashboard.html
├── requirements.txt
├── Procfile                 commande de lancement Railway
├── railway.json             config Railway
├── runtime.txt              version Python
└── .gitignore
```
