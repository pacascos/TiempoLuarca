"""
API REST principal de TiempoLuarca.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.data_sources import (
    get_aemet_observacion_busto, get_aemet_prediccion_valdes,
    get_aemet_prediccion_costera, get_aemet_prediccion_playa,
    get_ihm_mareas, get_open_meteo_marine, get_open_meteo_forecast,
)
from backend.scoring import ScoringInput, calculate_score, score_forecast_hour
from backend.database import init_db, save_snapshot, save_feedback, get_feedback_list, get_history

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── Cache por fuente con TTL independiente ───────────────────────────────────

class SourceCache:
    """Cache individual por fuente de datos."""
    def __init__(self, name: str, fetcher, ttl_minutes: int):
        self.name = name
        self.fetcher = fetcher
        self.ttl = timedelta(minutes=ttl_minutes)
        self.data = None
        self.last_fetch: datetime | None = None
        self.ttl_minutes = ttl_minutes

    def is_stale(self) -> bool:
        if self.last_fetch is None:
            return True
        return datetime.now() - self.last_fetch > self.ttl

    async def get(self, force: bool = False) -> any:
        if not force and not self.is_stale() and self.data is not None:
            return self.data
        try:
            logger.info("Fetching %s (TTL %dm)...", self.name, self.ttl_minutes)
            result = await self.fetcher()
            if result is not None:
                self.data = result
                self.last_fetch = datetime.now()
            else:
                logger.warning("%s devolvió None, manteniendo cache anterior", self.name)
            return self.data
        except Exception as e:
            logger.error("Error fetching %s: %s", self.name, e)
            return self.data  # Devolver datos anteriores si falla


# Definir caches con TTL apropiado
_sources = {
    "observacion_busto":  SourceCache("AEMET Busto",     get_aemet_observacion_busto, ttl_minutes=30),
    "prediccion_valdes":  SourceCache("AEMET Valdés",    get_aemet_prediccion_valdes, ttl_minutes=120),
    "prediccion_costera": SourceCache("AEMET Costera",   get_aemet_prediccion_costera, ttl_minutes=180),
    "prediccion_playa":   SourceCache("AEMET Playa",     get_aemet_prediccion_playa, ttl_minutes=180),
    "mareas":             SourceCache("IHM Mareas",      lambda: get_ihm_mareas(days=8), ttl_minutes=720),
    "oleaje":             SourceCache("Open-Meteo Marine", get_open_meteo_marine, ttl_minutes=60),
    "forecast":           SourceCache("Open-Meteo Forecast", get_open_meteo_forecast, ttl_minutes=60),
}

# Cache combinado
_cache: dict = {}
_cache_time: datetime | None = None


async def _refresh_cache(force: bool = False):
    """Refresca solo las fuentes cuyo TTL ha expirado (o todas si force=True)."""
    global _cache, _cache_time

    # Fetch en paralelo solo las fuentes que lo necesitan
    stale = {k: v for k, v in _sources.items() if force or v.is_stale()}
    if not stale and _cache:
        return  # Nada que refrescar

    if stale:
        names = ", ".join(stale.keys())
        logger.info("Refrescando: %s", names)
        results = await asyncio.gather(
            *[s.get(force=force) for s in stale.values()],
            return_exceptions=True,
        )
        for key, result in zip(stale.keys(), results):
            if isinstance(result, Exception):
                logger.error("Error en %s: %s", key, result)

    # Construir cache combinado con los datos más recientes de cada fuente
    _cache = {key: src.data for key, src in _sources.items()}
    _cache["timestamp"] = datetime.now().isoformat()
    _cache_time = datetime.now()

    # Guardar snapshot cada hora (no cada refresh)
    obs_cache = _sources["observacion_busto"]
    if obs_cache.last_fetch and (datetime.now() - obs_cache.last_fetch).seconds < 120:
        current_score = _compute_current_score(_cache)
        save_snapshot(_cache, current_score)


def _compute_current_score(data: dict) -> int | None:
    obs = data.get("observacion_busto")
    forecast = data.get("forecast") or []
    marine = data.get("oleaje") or []
    now_str = datetime.now().strftime("%Y-%m-%dT%H:")

    current_marine = None
    for m in marine:
        if m.get("timestamp", "").startswith(now_str):
            current_marine = m
            break

    current_fc = None
    for f in forecast:
        if f.get("timestamp", "").startswith(now_str):
            current_fc = f
            break

    # Usar AEMET si hay, sino Open-Meteo
    if obs:
        viento = obs.get("viento_vel_nudos")
        racha = obs.get("viento_racha_nudos")
        vis = (obs.get("visibilidad") or 0) * 1000 if obs.get("visibilidad") else None
    elif current_fc:
        viento = current_fc.get("viento_nudos")
        racha = current_fc.get("viento_racha_nudos")
        vis = current_fc.get("visibilidad")
    else:
        return None

    inp = ScoringInput(
        viento_nudos=viento,
        racha_nudos=racha,
        ola_altura=current_marine.get("ola_altura") if current_marine else None,
        ola_periodo=current_marine.get("ola_periodo") if current_marine else None,
        prob_precipitacion=current_fc.get("prob_precipitacion") if current_fc else None,
        visibilidad_m=vis,
    )
    result = calculate_score(inp)
    return result.score


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await _refresh_cache(force=True)
    # Chequear cada 5 min, pero solo refresca lo que haya expirado su TTL
    scheduler.add_job(_refresh_cache, "interval", minutes=5)
    scheduler.start()
    yield
    scheduler.shutdown()


from backend.config import ROOT_PATH

app = FastAPI(title="TiempoLuarca", version="1.0.0", lifespan=lifespan, root_path=ROOT_PATH)
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("frontend/index.html")


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/current")
async def api_current():
    """Datos actuales y score."""
    if not _cache:
        raise HTTPException(503, "Datos no disponibles todavía")

    obs = _cache.get("observacion_busto")
    marine = _cache.get("oleaje") or []
    forecast = _cache.get("forecast") or []

    # Encontrar datos marinos y forecast más cercanos a ahora
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%dT%H:")

    current_marine = None
    for m in marine:
        if m.get("timestamp", "").startswith(now_str):
            current_marine = m
            break

    current_forecast = None
    for f in forecast:
        if f.get("timestamp", "").startswith(now_str):
            current_forecast = f
            break

    # ─── Score principal: hora actual + próximas 4h (ventana de 5h) ──────────
    # Indexar forecast y marine por hora
    marine_by_hour = {}
    for m in marine:
        marine_by_hour[m.get("timestamp", "")[:13]] = m

    # Obtener scores de las próximas 5 horas
    hour_scores = []
    now_dt = datetime.now()
    for i in range(5):
        h_dt = now_dt + timedelta(hours=i)
        h_str = h_dt.strftime("%Y-%m-%dT%H")
        fc_h = None
        for f in forecast:
            if f.get("timestamp", "").startswith(h_str):
                fc_h = f
                break
        m_h = marine_by_hour.get(h_str)
        if fc_h:
            scored = score_forecast_hour(fc_h, m_h)
            hour_scores.append(scored["score"])

    # Para la hora actual, preferir datos de AEMET si hay
    score_data = None
    if (obs or current_forecast) and hour_scores:
        # Score actual con AEMET (más preciso)
        if obs:
            viento = obs.get("viento_vel_nudos")
            racha = obs.get("viento_racha_nudos")
            vis = (obs.get("visibilidad") or 0) * 1000 if obs.get("visibilidad") else None
        else:
            viento = current_forecast.get("viento_nudos") if current_forecast else None
            racha = current_forecast.get("viento_racha_nudos") if current_forecast else None
            vis = current_forecast.get("visibilidad") if current_forecast else None

        inp = ScoringInput(
            viento_nudos=viento,
            racha_nudos=racha,
            ola_altura=current_marine.get("ola_altura") if current_marine else None,
            ola_periodo=current_marine.get("ola_periodo") if current_marine else None,
            swell_altura=current_marine.get("swell_altura") if current_marine else None,
            swell_periodo=current_marine.get("swell_periodo") if current_marine else None,
            viento_ola_altura=current_marine.get("viento_ola_altura") if current_marine else None,
            viento_ola_periodo=current_marine.get("viento_ola_periodo") if current_marine else None,
            prob_precipitacion=current_forecast.get("prob_precipitacion") if current_forecast else None,
            visibilidad_m=vis,
            temperatura=obs.get("temperatura") if obs else (current_forecast.get("temperatura") if current_forecast else None),
            nubosidad=current_forecast.get("nubosidad") if current_forecast else None,
        )
        result_now = calculate_score(inp)

        # Score principal = peor de: (actual, media próximas 5h)
        # Si las próximas horas empeoran, el score baja
        avg_5h = round(sum(hour_scores) / len(hour_scores))
        worst_5h = min(hour_scores)
        # El score principal es el mínimo entre el actual y la media de 5h
        # Así si ahora es 9 pero en 2h será 4, el principal no da 9
        main_score = min(result_now.score, avg_5h)

        from backend.scoring import LABELS
        label, color, recomendacion = LABELS[main_score]

        # Tendencia: comparar primeras 2h con últimas 2h
        if len(hour_scores) >= 4:
            early = sum(hour_scores[:2]) / 2
            late = sum(hour_scores[-2:]) / 2
            diff = late - early
            if diff >= 1.5:
                tendencia = "mejorando"
            elif diff <= -1.5:
                tendencia = "empeorando"
            else:
                tendencia = "estable"
        else:
            tendencia = "estable"

        score_data = {
            "score": main_score,
            "score_ahora": result_now.score,
            "score_5h": avg_5h,
            "score_peor_5h": worst_5h,
            "tendencia": tendencia,
            "label": label,
            "color": color,
            "recomendacion": recomendacion,
            "scores": {
                "viento": result_now.score_viento,
                "oleaje": result_now.score_oleaje,
                "lluvia": result_now.score_lluvia,
                "visibilidad": result_now.score_visibilidad,
                "racha": result_now.score_racha,
                "nubosidad": result_now.score_nubosidad,
                "temperatura": result_now.score_temperatura,
            },
            "hora_scores": hour_scores,
        }

    # Construir observacion fallback con datos de Open-Meteo si AEMET no responde
    obs_response = obs
    if not obs and current_forecast:
        obs_response = {
            "timestamp": current_forecast.get("timestamp"),
            "temperatura": current_forecast.get("temperatura"),
            "humedad": current_forecast.get("humedad"),
            "presion": current_forecast.get("presion"),
            "viento_vel": None,
            "viento_vel_nudos": current_forecast.get("viento_nudos"),
            "viento_dir": current_forecast.get("viento_dir"),
            "viento_racha": None,
            "viento_racha_nudos": current_forecast.get("viento_racha_nudos"),
            "precipitacion": current_forecast.get("precipitacion"),
            "visibilidad": (current_forecast.get("visibilidad") or 0) / 1000 if current_forecast.get("visibilidad") else None,
            "fuente": "Open-Meteo (fallback)",
        }

    return {
        "observacion": obs_response,
        "marine": current_marine,
        "forecast_now": {
            "nubosidad": current_forecast.get("nubosidad") if current_forecast else None,
            "visibilidad": current_forecast.get("visibilidad") if current_forecast else None,
            "prob_precipitacion": current_forecast.get("prob_precipitacion") if current_forecast else None,
        } if current_forecast else None,
        "score": score_data,
        "playa": (_cache.get("prediccion_playa") or [None])[0] if _cache.get("prediccion_playa") else None,
        "costera": _cache.get("prediccion_costera"),
        "updated": _cache.get("timestamp"),
    }


@app.get("/api/forecast")
async def api_forecast():
    """Pronóstico horario con scores para los próximos 7 días."""
    if not _cache:
        raise HTTPException(503, "Datos no disponibles todavía")

    forecast = _cache.get("forecast") or []
    marine = _cache.get("oleaje") or []

    # Indexar datos marinos por hora
    marine_by_hour = {}
    for m in marine:
        ts = m.get("timestamp", "")[:13]  # "2024-01-01T12"
        marine_by_hour[ts] = m

    result = []
    for f in forecast:
        ts = f.get("timestamp", "")[:13]
        m = marine_by_hour.get(ts)
        scored = score_forecast_hour(f, m)
        result.append({
            "timestamp": f.get("timestamp"),
            "temperatura": f.get("temperatura"),
            "humedad": f.get("humedad"),
            "viento_nudos": f.get("viento_nudos"),
            "viento_dir": f.get("viento_dir"),
            "viento_racha_nudos": f.get("viento_racha_nudos"),
            "prob_precipitacion": f.get("prob_precipitacion"),
            "precipitacion": f.get("precipitacion"),
            "nubosidad": f.get("nubosidad"),
            "visibilidad": f.get("visibilidad"),
            "presion": f.get("presion"),
            "ola_altura": m.get("ola_altura") if m else None,
            "ola_periodo": m.get("ola_periodo") if m else None,
            "ola_direccion": m.get("ola_direccion") if m else None,
            "swell_altura": m.get("swell_altura") if m else None,
            "swell_periodo": m.get("swell_periodo") if m else None,
            "viento_ola_altura": m.get("viento_ola_altura") if m else None,
            "viento_ola_periodo": m.get("viento_ola_periodo") if m else None,
            "temp_agua": m.get("temp_agua") if m else None,
            **scored,
        })

    return {"forecast": result, "updated": _cache.get("timestamp")}


@app.get("/api/tides")
async def api_tides():
    """Mareas de Navia y Cudillero."""
    if not _cache:
        raise HTTPException(503, "Datos no disponibles todavía")
    return _cache.get("mareas") or {}


@app.get("/api/summary")
async def api_summary():
    """Resumen para hoy, mañana y próximo fin de semana."""
    if not _cache:
        raise HTTPException(503, "Datos no disponibles todavía")

    forecast = _cache.get("forecast") or []
    marine = _cache.get("oleaje") or []
    marine_by_hour = {}
    for m in marine:
        ts = m.get("timestamp", "")[:13]
        marine_by_hour[ts] = m

    now = datetime.now()
    DAY_NAMES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]

    # Generar los próximos 4 días (hoy + 3)
    days = []
    for i in range(4):
        d = now + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        if i == 0:
            label = "Hoy"
        elif i == 1:
            label = "Manana"
        else:
            label = DAY_NAMES[d.weekday()]
        days.append({"key": f"day{i}", "label": label, "date": date_str})

    def summarize_day(date_str: str) -> dict:
        day_hours = [f for f in forecast if f.get("timestamp", "").startswith(date_str)]
        # Solo horas de luz (7-21)
        daylight = [f for f in day_hours if 7 <= int(f.get("timestamp", "T00")[11:13]) <= 20]
        if not daylight:
            daylight = day_hours

        if not daylight:
            return {"fecha": date_str, "disponible": False}

        scores = []
        for f in daylight:
            ts = f.get("timestamp", "")[:13]
            m = marine_by_hour.get(ts)
            scored = score_forecast_hour(f, m)
            scores.append(scored["score"])

        vientos = [f.get("viento_nudos") for f in daylight if f.get("viento_nudos") is not None]
        rachas = [f.get("viento_racha_nudos") for f in daylight if f.get("viento_racha_nudos") is not None]
        olas = [marine_by_hour.get(f.get("timestamp", "")[:13], {}).get("ola_altura") for f in daylight]
        olas = [o for o in olas if o is not None]
        precip = [f.get("prob_precipitacion") for f in daylight if f.get("prob_precipitacion") is not None]
        temps = [f.get("temperatura") for f in daylight if f.get("temperatura") is not None]

        avg_score = round(sum(scores) / len(scores)) if scores else None
        best_score = max(scores) if scores else None   # 10=mejor
        worst_score = min(scores) if scores else None   # 1=peor

        from backend.scoring import LABELS
        label, color, recomendacion = LABELS.get(avg_score, ("?", "#999", ""))

        # Encontrar mejor ventana (3h consecutivas con mayor score promedio)
        best_window = None
        if len(scores) >= 3:
            max_avg = -1
            for i in range(len(scores) - 2):
                window_avg = sum(scores[i:i+3]) / 3
                if window_avg > max_avg:
                    max_avg = window_avg
                    best_window = {
                        "inicio": daylight[i].get("timestamp", "")[11:16],
                        "fin": daylight[min(i+3, len(daylight)-1)].get("timestamp", "")[11:16],
                        "score_medio": round(max_avg, 1),
                    }

        return {
            "fecha": date_str,
            "disponible": True,
            "score_medio": avg_score,
            "score_mejor": best_score,
            "score_peor": worst_score,
            "label_score": label,
            "color": color,
            "recomendacion": recomendacion,
            "viento_medio": round(sum(vientos) / len(vientos), 1) if vientos else None,
            "viento_max": round(max(vientos), 1) if vientos else None,
            "racha_max": round(max(rachas), 1) if rachas else None,
            "ola_media": round(sum(olas) / len(olas), 2) if olas else None,
            "ola_max": round(max(olas), 2) if olas else None,
            "precip_max": max(precip) if precip else None,
            "temp_min": round(min(temps), 1) if temps else None,
            "temp_max": round(max(temps), 1) if temps else None,
            "mejor_ventana": best_window,
        }

    result = {"updated": _cache.get("timestamp"), "days": []}
    for d in days:
        summary = summarize_day(d["date"])
        summary["label"] = d["label"]
        result["days"].append(summary)
    return result


# ─── Feedback ─────────────────────────────────────────────────────────────────

@app.post("/api/feedback")
async def api_feedback(request: Request):
    """Guardar feedback del usuario."""
    body = await request.json()
    required = ["date", "score_real"]
    for field in required:
        if field not in body:
            raise HTTPException(400, f"Campo requerido: {field}")
    save_feedback(body)
    return {"ok": True}


@app.get("/api/feedback")
async def api_feedback_list():
    """Listar feedback histórico."""
    return {"feedback": get_feedback_list()}


@app.get("/api/history")
async def api_history_list():
    return {"history": get_history()}


# ─── Refresh manual ──────────────────────────────────────────────────────────

@app.post("/api/refresh")
async def api_refresh():
    """Forzar actualización de todas las fuentes."""
    await _refresh_cache(force=True)
    return {"ok": True, "timestamp": _cache.get("timestamp")}


@app.get("/api/cache-status")
async def api_cache_status():
    """Estado del cache de cada fuente."""
    now = datetime.now()
    status = {}
    for key, src in _sources.items():
        age = (now - src.last_fetch).total_seconds() if src.last_fetch else None
        status[key] = {
            "ttl_min": src.ttl_minutes,
            "last_fetch": src.last_fetch.isoformat() if src.last_fetch else None,
            "age_sec": round(age) if age else None,
            "stale": src.is_stale(),
            "has_data": src.data is not None,
        }
    return status
