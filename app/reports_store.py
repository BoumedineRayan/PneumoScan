"""
Stockage sur disque et cycle de vie des rapports détaillés.

- Fichiers PDF + heatmap enregistrés dans  data_outputs/reports/  (à la racine projet).
- Durée d'accès (TTL) comptée À PARTIR DE LA CRÉATION : expiry = created_at + ttl.
  Toggler un vieux rapport sur "1 min" peut donc l'expirer immédiatement.
- Suppression PARESSEUSE : purge_expired() est appelée au chargement du dashboard
  et à chaque accès ; elle supprime les fichiers et marque le rapport "expired".
  Un compte à rebours côté navigateur gère l'affichage en temps réel.
"""
import time
import uuid
from pathlib import Path

from . import database as db

# data_outputs/reports à la racine du projet (app/ -> racine)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "data_outputs" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Durées d'accès proposées
TTL_SECONDS = {"1min": 60, "1j": 86_400, "1sem": 604_800}
TTL_LABELS_FR = {"1min": "1 min", "1j": "1 jour", "1sem": "1 semaine"}
DEFAULT_TTL = "1j"


def _safe_ttl(ttl_label: str) -> str:
    return ttl_label if ttl_label in TTL_SECONDS else DEFAULT_TTL


def _delete_files(*paths):
    for p in paths:
        if not p:
            continue
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


def create_report(user_id, filename, variant, result, pdf_bytes,
                  heatmap_bytes, detail_latency, ttl_label=DEFAULT_TTL,
                  analysis_id=None) -> dict:
    """Écrit les fichiers, calcule l'expiration, insère en base et renvoie l'état."""
    ttl_label = _safe_ttl(ttl_label)
    now = time.time()
    stem = f"{int(now)}_{uuid.uuid4().hex[:8]}"

    pdf_path = REPORTS_DIR / f"rapport_{stem}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    heatmap_path = None
    if heatmap_bytes:
        heatmap_path = REPORTS_DIR / f"heatmap_{stem}.png"
        heatmap_path.write_bytes(heatmap_bytes)

    expiry_ts = now + TTL_SECONDS[ttl_label]
    report_id = db.insert_report(
        user_id=user_id, filename=filename, variant=variant,
        predicted_class=result.get("predicted_class"),
        confidence=result.get("confidence"),
        detail_latency=detail_latency, ttl_label=ttl_label,
        created_at=now, expiry_ts=expiry_ts, status="active",
        pdf_path=str(pdf_path),
        heatmap_path=str(heatmap_path) if heatmap_path else None,
        analysis_id=analysis_id)

    return {
        "id": report_id,
        "analysis_id": analysis_id,
        "filename": filename,
        "predicted_class": result.get("predicted_class"),
        "confidence": result.get("confidence"),
        "created_at": now,
        "ttl_label": ttl_label,
        "expiry_ts": expiry_ts,
        "status": "active",
        "remaining": max(0, int(expiry_ts - now)),
    }


def purge_expired(user_id: int | None = None) -> int:
    """Supprime les fichiers des rapports expirés et les marque 'expired'. Idempotent."""
    now = time.time()
    rows = db.get_reports_for_user(user_id) if user_id is not None else []
    n = 0
    for r in rows:
        if r.get("status") == "active" and r.get("expiry_ts", 0) <= now:
            _delete_files(r.get("pdf_path"), r.get("heatmap_path"))
            db.mark_report_expired(r["id"])
            n += 1
    return n


def set_ttl(report_id: int, ttl_label: str) -> dict | None:
    """Change la durée d'accès. Recalcule depuis la création (durée totale)."""
    ttl_label = _safe_ttl(ttl_label)
    r = db.get_report(report_id)
    if not r:
        return None
    if r.get("status") != "active":
        return _state(r)  # déjà expiré : inchangé

    now = time.time()
    expiry_ts = r["created_at"] + TTL_SECONDS[ttl_label]
    if expiry_ts <= now:
        # La nouvelle durée est déjà dépassée -> expiration immédiate
        _delete_files(r.get("pdf_path"), r.get("heatmap_path"))
        db.mark_report_expired(report_id)
        r = db.get_report(report_id)
        r["ttl_label"] = ttl_label
        db.update_report_ttl(report_id, ttl_label, expiry_ts, "expired")
    else:
        db.update_report_ttl(report_id, ttl_label, expiry_ts, "active")
        r = db.get_report(report_id)
    return _state(r)


def _state(r: dict) -> dict:
    now = time.time()
    status = r.get("status", "expired")
    remaining = max(0, int(r.get("expiry_ts", 0) - now))
    if status == "active" and remaining <= 0:
        status = "expired"
    return {
        "id": r["id"],
        "analysis_id": r.get("analysis_id"),
        "filename": r.get("filename"),
        "predicted_class": r.get("predicted_class"),
        "confidence": r.get("confidence"),
        "created_at": r.get("created_at"),
        "ttl_label": r.get("ttl_label"),
        "expiry_ts": r.get("expiry_ts"),
        "status": status,
        "remaining": remaining,
    }


def get_visible_reports(user_id: int) -> list[dict]:
    """Purge d'abord, puis renvoie l'état de tous les rapports de l'utilisateur."""
    purge_expired(user_id)
    return [_state(r) for r in db.get_reports_for_user(user_id)]


def get_reports_map(user_id: int) -> dict:
    """
    Purge puis renvoie {analysis_id: état} — le rapport le plus récent par analyse.
    Sert à placer l'icône de téléchargement directement dans l'historique.
    """
    purge_expired(user_id)
    out = {}
    for r in db.get_reports_for_user(user_id):   # déjà trié du + récent au + ancien
        aid = r.get("analysis_id")
        if aid is None or aid in out:
            continue
        out[aid] = _state(r)
    return out


def get_active_report_for_download(report_id: int, user_id: int):
    """Renvoie (chemin_pdf, nom) si le rapport est accessible, sinon None."""
    purge_expired(user_id)
    r = db.get_report(report_id)
    if not r or r.get("user_id") != user_id:
        return None
    if r.get("status") != "active" or not r.get("pdf_path"):
        return None
    p = Path(r["pdf_path"])
    if not p.exists():
        return None
    fname = f"rapport_{(r.get('filename') or 'radio')}.pdf".replace(" ", "_")
    return p, fname
