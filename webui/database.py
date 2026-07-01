"""
Base de données de l'application (comptes + historique).

Fonctionne avec DEUX moteurs, choisis automatiquement :
  - PostgreSQL si la variable d'environnement DATABASE_URL existe (Railway, prod)
  - SQLite sinon (développement local, aucun serveur à installer)

Sécurité : mots de passe hachés avec bcrypt, jamais stockés en clair.
"""
import os
import json
import time
from pathlib import Path
from contextlib import contextmanager

import bcrypt

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    import sqlite3
    SQLITE_PATH = Path("webui_data") / "app.db"
    SQLITE_PATH.parent.mkdir(exist_ok=True)

PH = "%s" if USE_POSTGRES else "?"


@contextmanager
def get_db():
    if USE_POSTGRES:
        con = psycopg2.connect(DATABASE_URL)
        try:
            yield con
            con.commit()
        finally:
            con.close()
    else:
        con = sqlite3.connect(SQLITE_PATH)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def _dict_cursor(con):
    if USE_POSTGRES:
        return con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return con.cursor()


def _hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, hashed: str) -> bool:
    pw = password.encode("utf-8")[:72]
    return bcrypt.checkpw(pw, hashed.encode("utf-8"))


def init_db():
    pk = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with get_db() as con:
        cur = con.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {pk},
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL
            )""")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS analyses (
                id {pk},
                user_id INTEGER NOT NULL,
                ts DOUBLE PRECISION NOT NULL,
                filename TEXT,
                prompt_variant TEXT,
                predicted_class TEXT,
                confidence DOUBLE PRECISION,
                latency_s DOUBLE PRECISION,
                result_json TEXT
            )""")


def create_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if len(username) < 3:
        return False, "Le nom d'utilisateur doit faire au moins 3 caractères."
    if len(password) < 6:
        return False, "Le mot de passe doit faire au moins 6 caractères."
    with get_db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT id FROM users WHERE username = {PH}", (username,))
        if cur.fetchone():
            return False, "Ce nom d'utilisateur est déjà pris."
        cur.execute(
            f"INSERT INTO users (username, password_hash, created_at) VALUES ({PH},{PH},{PH})",
            (username, _hash_password(password), time.time()))
    return True, "Compte créé."


def verify_user(username: str, password: str) -> int | None:
    with get_db() as con:
        cur = _dict_cursor(con)
        cur.execute(f"SELECT id, password_hash FROM users WHERE username = {PH}",
                    (username.strip(),))
        row = cur.fetchone()
    if row and _check_password(password, row["password_hash"]):
        return row["id"]
    return None


def get_username(user_id: int) -> str | None:
    with get_db() as con:
        cur = _dict_cursor(con)
        cur.execute(f"SELECT username FROM users WHERE id = {PH}", (user_id,))
        row = cur.fetchone()
    return row["username"] if row else None


def save_analysis(user_id: int, filename: str, variant: str, result: dict, latency: float):
    with get_db() as con:
        cur = con.cursor()
        cur.execute(
            f"INSERT INTO analyses (user_id, ts, filename, prompt_variant, "
            f"predicted_class, confidence, latency_s, result_json) "
            f"VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
            (user_id, time.time(), filename, variant,
             result.get("predicted_class"), result.get("confidence"),
             latency, json.dumps(result, ensure_ascii=False)))


def get_user_analyses(user_id: int, limit: int = 50) -> list[dict]:
    with get_db() as con:
        cur = _dict_cursor(con)
        cur.execute(
            f"SELECT * FROM analyses WHERE user_id = {PH} ORDER BY ts DESC LIMIT {PH}",
            (user_id, limit))
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d["result_json"]) if d.get("result_json") else {}
        out.append(d)
    return out
