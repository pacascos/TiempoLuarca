"""
Base de datos SQLite para históricos y feedback.
"""

import sqlite3
import json
import os
from datetime import datetime
from backend.config import DATABASE_PATH

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), DATABASE_PATH)


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS weather_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            data_json TEXT NOT NULL,
            score INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS forecast_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_date TEXT NOT NULL,
            target_hour INTEGER,
            viento_nudos REAL,
            racha_nudos REAL,
            ola_altura REAL,
            ola_periodo REAL,
            prob_precipitacion REAL,
            temperatura REAL,
            visibilidad REAL,
            score INTEGER,
            source TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            salida INTEGER NOT NULL DEFAULT 0,  -- 0=no salió, 1=salió
            score_app INTEGER,                  -- score que daba la app ese día
            score_real INTEGER,                 -- score que el usuario le da (1-10)
            viento_real TEXT,                    -- percepción: calma, suave, moderado, fuerte, muy fuerte
            oleaje_real TEXT,                    -- percepción: llana, rizada, marejadilla, marejada, fuerte
            lluvia_real TEXT,                    -- percepción: nada, llovizna, moderada, fuerte
            comentario TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather_snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_forecast_date ON forecast_history(target_date);
        CREATE INDEX IF NOT EXISTS idx_feedback_date ON feedback(date);
    """)
    conn.commit()
    conn.close()


def save_snapshot(data: dict, score: int | None = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO weather_snapshots (timestamp, data_json, score) VALUES (?, ?, ?)",
        (datetime.now().isoformat(), json.dumps(data, ensure_ascii=False), score),
    )
    conn.commit()
    conn.close()


def save_forecast_entry(entry: dict):
    conn = get_db()
    conn.execute(
        """INSERT INTO forecast_history
           (target_date, target_hour, viento_nudos, racha_nudos, ola_altura,
            ola_periodo, prob_precipitacion, temperatura, visibilidad, score, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.get("fecha"), entry.get("hora"),
            entry.get("viento_nudos"), entry.get("racha_nudos"),
            entry.get("ola_altura"), entry.get("ola_periodo"),
            entry.get("prob_precipitacion"), entry.get("temperatura"),
            entry.get("visibilidad"), entry.get("score"),
            entry.get("fuente", "combined"),
        ),
    )
    conn.commit()
    conn.close()


def save_feedback(fb: dict):
    conn = get_db()
    conn.execute(
        """INSERT INTO feedback
           (date, salida, score_app, score_real, viento_real, oleaje_real, lluvia_real, comentario)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fb["date"], fb.get("salida", 0), fb.get("score_app"),
            fb.get("score_real"), fb.get("viento_real"),
            fb.get("oleaje_real"), fb.get("lluvia_real"),
            fb.get("comentario"),
        ),
    )
    conn.commit()
    conn.close()


def get_feedback_list(limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM feedback ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_history(days: int = 30) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, score, data_json FROM weather_snapshots
           ORDER BY timestamp DESC LIMIT ?""",
        (days * 24,),  # aprox 1 snapshot por hora
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
