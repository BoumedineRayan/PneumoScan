"""Journalisation des résultats : SQLite (logs structurés) + CSV (export)."""
import csv
import json
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path("data_outputs")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "logs.db"
CSV_PATH = DATA_DIR / "results.csv"


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            filename TEXT,
            prompt_variant TEXT,
            predicted_class TEXT,
            confidence REAL,
            image_quality TEXT,
            justification TEXT,
            visual_evidence TEXT,
            limitations TEXT,
            latency_s REAL,
            raw_json TEXT
        )""")
    con.commit()
    con.close()


def log_result(filename, variant, result, latency):
    init_db()
    ve = " | ".join(result.get("visual_evidence", []))
    lim = " | ".join(result.get("limitations", []))
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO predictions (ts, filename, prompt_variant, predicted_class, "
        "confidence, image_quality, justification, visual_evidence, limitations, "
        "latency_s, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), filename, variant, result["predicted_class"],
         result["confidence"], result["image_quality"], result.get("justification", ""),
         ve, lim, latency, json.dumps(result, ensure_ascii=False)))
    con.commit()
    con.close()

    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["ts", "filename", "prompt_variant", "predicted_class",
                        "confidence", "image_quality", "justification",
                        "visual_evidence", "limitations", "latency_s"])
        w.writerow([round(time.time(), 1), filename, variant, result["predicted_class"],
                    result["confidence"], result["image_quality"],
                    result.get("justification", ""), ve, lim, round(latency, 1)])
