"""
Sessions utilisateur via cookie signé (itsdangerous).
Le cookie contient l'id utilisateur, signé avec une clé secrète : il ne peut
pas être falsifié côté client. Pas de session serveur à stocker.
"""
import os
from itsdangerous import URLSafeSerializer, BadSignature
from fastapi import Request

# Clé secrète : en production, la mettre dans une variable d'environnement.
# En local, une valeur par défaut suffit (mais change-la pour un vrai déploiement).
SECRET_KEY = os.environ.get("APP_SECRET_KEY", "dev-secret-change-me-in-production")
COOKIE_NAME = "session"

_serializer = URLSafeSerializer(SECRET_KEY, salt="user-session")


def make_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def read_session_cookie(request: Request) -> int | None:
    """Retourne l'id utilisateur du cookie, ou None si absent/invalide."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = _serializer.loads(token)
        return data.get("user_id")
    except BadSignature:
        return None
