"""
Usage :
put it on the app folder then enter the following command in the terminal:
python -m app.reset_data --yes

if you delete the --yes argument, it will ask you for confirmation before deleting everything twin.
"""
import sqlite3
import sys
from pathlib import Path

from app import database as db
from app import storage
from app.reports_store import REPORTS_DIR


def reset() -> None:
    # 1) Tables applicatives (agnostique SQLite/PostgreSQL)
    db.init_db()
    with db.get_db() as con:
        cur = con.cursor()
        for table in ("reports", "analyses", "users"):
            try:
                cur.execute(f"DELETE FROM {table}")
                print(f"  vidé : {table}")
            except Exception as e:
                print(f"  ignoré {table} ({e})")

    # 2) Logs (predictions SQLite + CSV) — toujours locaux
    try:
        if storage.DB_PATH.exists():
            storage.DB_PATH.unlink()
            print(f"  supprimé : {storage.DB_PATH}")
        if storage.CSV_PATH.exists():
            storage.CSV_PATH.unlink()
            print(f"  supprimé : {storage.CSV_PATH}")
    except OSError as e:
        print(f"  logs ignorés ({e})")

    # 3) Fichiers de rapports sur disque
    n = 0
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    print(f"  fichiers de rapports supprimés : {n}")

    print("\nRéinitialisation terminée.")


if __name__ == "__main__":
    if "--yes" not in sys.argv:
        rep = input("Tout effacer (comptes, historique, rapports, logs) ? "
                    "Action IRRÉVERSIBLE. [oui/non] ").strip().lower()
        if rep not in ("oui", "o", "yes", "y"):
            print("Annulé.")
            sys.exit(0)
    reset()
