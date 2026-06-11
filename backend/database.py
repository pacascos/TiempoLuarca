"""
Base de datos SQLite para históricos y feedback.
"""

import sqlite3
import os
import hashlib
from contextlib import contextmanager
from backend.config import DATABASE_PATH

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), DATABASE_PATH)


@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS hourly_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                viento_nudos REAL,
                racha_nudos REAL,
                viento_dir REAL,
                ola_altura REAL,
                ola_periodo REAL,
                swell_altura REAL,
                swell_periodo REAL,
                viento_ola_altura REAL,
                viento_ola_periodo REAL,
                temp_agua REAL,
                temperatura REAL,
                humedad REAL,
                presion REAL,
                prob_precipitacion REAL,
                precipitacion REAL,
                visibilidad REAL,
                nubosidad REAL,
                score INTEGER,
                score_viento INTEGER,
                score_oleaje INTEGER,
                score_lluvia INTEGER,
                score_visibilidad INTEGER,
                score_nubosidad INTEGER,
                score_presion INTEGER,
                score_temperatura INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(timestamp)
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

            CREATE INDEX IF NOT EXISTS idx_hourly_timestamp ON hourly_history(timestamp);
            CREATE INDEX IF NOT EXISTS idx_feedback_date ON feedback(date);

            CREATE TABLE IF NOT EXISTS page_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_hash TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pv_user ON page_views(user_hash);
            CREATE INDEX IF NOT EXISTS idx_pv_ts ON page_views(timestamp);
        """)


_HOURLY_COLUMNS = (
    "timestamp", "viento_nudos", "racha_nudos", "viento_dir",
    "ola_altura", "ola_periodo", "swell_altura", "swell_periodo",
    "viento_ola_altura", "viento_ola_periodo", "temp_agua",
    "temperatura", "humedad", "presion", "prob_precipitacion", "precipitacion",
    "visibilidad", "nubosidad", "score",
    "score_viento", "score_oleaje", "score_lluvia", "score_visibilidad",
    "score_nubosidad", "score_presion", "score_temperatura",
)

_HOURLY_INSERT = (
    f"INSERT OR REPLACE INTO hourly_history ({', '.join(_HOURLY_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_HOURLY_COLUMNS))})"
)


def save_hourly_batch(entries: list):
    """Guarda múltiples registros horarios de una vez (REPLACE evita duplicados)."""
    if not entries:
        return
    rows = [tuple(e.get(c) for c in _HOURLY_COLUMNS) for e in entries]
    with get_db() as conn:
        conn.executemany(_HOURLY_INSERT, rows)


def save_feedback(fb: dict):
    with get_db() as conn:
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


def get_feedback_list(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_page_view(ip: str):
    """Registra una visita usando hash de IP (anónimo)."""
    user_hash = hashlib.sha256(ip.encode()).hexdigest()[:12]
    with get_db() as conn:
        conn.execute("INSERT INTO page_views (user_hash) VALUES (?)", (user_hash,))


def get_usage_stats() -> dict:
    """Devuelve estadísticas de uso."""
    with get_db() as conn:
        # Total de usuarios únicos y visitas
        totals = conn.execute(
            "SELECT COUNT(DISTINCT user_hash) as users, COUNT(*) as views FROM page_views"
        ).fetchone()
        # Visitas por día (últimos 30 días)
        daily = conn.execute(
            """SELECT DATE(timestamp) as dia, COUNT(DISTINCT user_hash) as usuarios, COUNT(*) as visitas
               FROM page_views WHERE timestamp >= datetime('now', '-30 days')
               GROUP BY dia ORDER BY dia"""
        ).fetchall()
        # Top usuarios por frecuencia
        top_users = conn.execute(
            """SELECT user_hash, COUNT(*) as visitas,
                      MIN(timestamp) as primera, MAX(timestamp) as ultima
               FROM page_views GROUP BY user_hash ORDER BY visitas DESC LIMIT 20"""
        ).fetchall()
    return {
        "total_usuarios": totals["users"],
        "total_visitas": totals["views"],
        "diario": [dict(r) for r in daily],
        "usuarios": [dict(r) for r in top_users],
    }
