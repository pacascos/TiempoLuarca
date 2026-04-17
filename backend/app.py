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
    get_aemet_alertas_costeras,
    get_ihm_mareas, get_open_meteo_marine, get_open_meteo_forecast,
    get_open_meteo_extended,
)
from backend.scoring import ScoringInput, calculate_score, score_forecast_hour
from backend.database import init_db, save_snapshot, save_hourly_batch, save_feedback, get_feedback_list, get_history, save_page_view, get_usage_stats

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
    "alertas_costeras":   SourceCache("AEMET Alertas",   get_aemet_alertas_costeras, ttl_minutes=30),
    "extended":           SourceCache("Extended 16d",    get_open_meteo_extended, ttl_minutes=180),
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

    # Guardar histórico horario: las horas ya pasadas del forecast + marine combinadas
    try:
        forecast_data = _cache.get("forecast") or []
        marine_data = _cache.get("oleaje") or []
        marine_by_h = {m.get("timestamp", "")[:13]: m for m in marine_data}
        now_str = datetime.now().strftime("%Y-%m-%dT%H")

        # Solo guardar horas pasadas o la actual (no futuras, esas son predicción)
        entries_to_save = []
        for f in forecast_data:
            ts = f.get("timestamp", "")
            if ts[:13] > now_str:
                break
            m = marine_by_h.get(ts[:13], {})
            scored = score_forecast_hour(f, m if m else None)
            entries_to_save.append({
                "timestamp": ts,
                "viento_nudos": f.get("viento_nudos"),
                "racha_nudos": f.get("viento_racha_nudos"),
                "viento_dir": f.get("viento_dir"),
                "ola_altura": m.get("ola_altura"),
                "ola_periodo": m.get("ola_periodo"),
                "swell_altura": m.get("swell_altura"),
                "swell_periodo": m.get("swell_periodo"),
                "viento_ola_altura": m.get("viento_ola_altura"),
                "viento_ola_periodo": m.get("viento_ola_periodo"),
                "temp_agua": m.get("temp_agua"),
                "temperatura": f.get("temperatura"),
                "humedad": f.get("humedad"),
                "presion": f.get("presion"),
                "prob_precipitacion": f.get("prob_precipitacion"),
                "precipitacion": f.get("precipitacion"),
                "visibilidad": f.get("visibilidad"),
                "nubosidad": f.get("nubosidad"),
                "score": scored.get("score"),
                "score_viento": scored.get("scores", {}).get("viento"),
                "score_oleaje": scored.get("scores", {}).get("oleaje"),
                "score_lluvia": scored.get("scores", {}).get("lluvia"),
                "score_visibilidad": scored.get("scores", {}).get("visibilidad"),
                "score_nubosidad": scored.get("scores", {}).get("nubosidad"),
                "score_presion": scored.get("scores", {}).get("presion"),
                "score_temperatura": scored.get("scores", {}).get("temperatura"),
            })
        if entries_to_save:
            save_hourly_batch(entries_to_save)
            logger.info("Historico: %d registros horarios guardados", len(entries_to_save))
    except Exception as e:
        logger.error("Error guardando historico: %s", e)


def _compute_day_score_from_hourly(
    date_str: str,
    forecast: list,
    marine_by_hour: dict,
    aemet_by_hour: dict,
) -> tuple[int | None, list[int]]:
    """Score diario 1-10 a partir del forecast horario.
    Toma horas de luz (8-20), promedia scores y penaliza con la peor ventana 3h.
    Devuelve (score_dia, scores_horarios). None si no hay datos.
    """
    day_hours = [f for f in forecast if f.get("timestamp", "").startswith(date_str)]
    daylight = [f for f in day_hours if 8 <= int(f.get("timestamp", "T00")[11:13]) <= 20]
    if not daylight:
        daylight = day_hours
    if not daylight:
        return None, []

    scores = []
    for f in daylight:
        ts = f.get("timestamp", "")[:13]
        m = marine_by_hour.get(ts)
        aemet_h = aemet_by_hour.get(ts)
        f_scoring = f
        if aemet_h and aemet_h.get("prob_precipitacion") is not None:
            f_scoring = {**f, "prob_precipitacion": aemet_h["prob_precipitacion"]}
        scored = score_forecast_hour(f_scoring, m)
        scores.append(scored["score"])

    avg_raw = sum(scores) / len(scores)
    worst_window_avg = None
    if len(scores) >= 3:
        worst_window_avg = min(
            sum(scores[i:i+3]) / 3 for i in range(len(scores) - 2)
        )
    day_score_float = min(avg_raw, worst_window_avg) if worst_window_avg is not None else avg_raw
    return round(day_score_float), scores


def _explain_componente(comp: str, horas: list) -> str:
    """Texto que describe por qué un componente tiene nota baja."""
    if comp == "oleaje":
        chops = [h.get("chop_m") for h in horas if h.get("chop_m") is not None]
        swells = [h.get("swell_m") for h in horas if h.get("swell_m") is not None]
        chop_max = max(chops) if chops else 0
        swell_max = max(swells) if swells else 0
        if chop_max >= 0.7 and chop_max >= swell_max * 0.7:
            return (f"Mar de viento (chop) llega a {chop_max:.2f}m. "
                    f"Escala: chop >0.7m → score 4, >1.0m → 3, >1.3m → 2. "
                    f"Con periodo corto (<4s) baja 1-2 puntos más por pantocazos.")
        if swell_max >= 1.3:
            return (f"Swell máximo {swell_max:.2f}m. "
                    f"Escala: swell 1.3m → 5, 1.5m → 4, 1.8m → 3, 2.2m → 2. "
                    f"Por encima de 2m no se recomienda salir con un Antares 6.5.")
        return f"Oleaje combinado máximo {max(chop_max, swell_max):.2f}m."
    if comp == "viento":
        vs = [h.get("viento_kn") for h in horas if h.get("viento_kn") is not None]
        if not vs: return ""
        vmax = max(vs)
        return (f"Viento máximo {vmax:.1f}kn. "
                f"Escala: >15kn → 6, >18kn → 5, >20kn → 4, >25kn → 3, >30kn → 2.")
    if comp == "racha":
        rs = [h.get("racha_kn") for h in horas if h.get("racha_kn") is not None]
        if not rs: return ""
        rmax = max(rs)
        return (f"Racha máxima {rmax:.1f}kn. "
                f"Escala: >22kn → 7, >25kn → 6, >28kn → 5, >32kn → 4, >36kn → 3.")
    if comp == "lluvia":
        ps = [h.get("prob_precip") for h in horas if h.get("prob_precip") is not None]
        if not ps: return ""
        pmax = max(ps)
        return f"Probabilidad de lluvia máxima {pmax}%. Se combina con intensidad (mm/h)."
    if comp == "visibilidad":
        vs = [h.get("visibilidad_m") for h in horas if h.get("visibilidad_m") is not None]
        if not vs: return ""
        vmin = min(vs)
        return (f"Visibilidad mínima {vmin/1000:.1f}km. "
                f"Escala: <3km → 5, <2km → 4, <1km → 3, <500m → 2.")
    if comp == "nubosidad":
        ns = [h.get("nubosidad") for h in horas if h.get("nubosidad") is not None]
        if not ns: return ""
        nmax = max(ns)
        return f"Nubosidad máxima {nmax}%. Afecta al confort y visibilidad costera."
    if comp == "presion":
        return "Tendencia barométrica bajando (borrasca acercándose)."
    if comp == "temperatura":
        ts = [h.get("temperatura") for h in horas if h.get("temperatura") is not None]
        if not ts: return ""
        tmin = min(ts)
        return f"Temperatura mínima {tmin:.1f}°C. En barco abierto el frío reduce confort."
    return ""


COMP_LABEL = {
    "viento": "Viento",
    "oleaje": "Oleaje",
    "racha": "Rachas",
    "lluvia": "Lluvia",
    "visibilidad": "Visibilidad",
    "nubosidad": "Nubosidad",
    "presion": "Presión",
    "temperatura": "Temperatura",
}


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
async def index(request: Request):
    ip = request.client.host if request.client else "unknown"
    save_page_view(ip)
    return FileResponse("frontend/index.html")


@app.get("/uso", response_class=HTMLResponse)
async def usage_page():
    return FileResponse("frontend/usage.html")


@app.get("/porque", response_class=HTMLResponse)
async def porque_page():
    return FileResponse("frontend/porque.html")


@app.get("/api/usage")
async def api_usage():
    return get_usage_stats()


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

    # Lluvia: priorizar AEMET Valdés sobre Open-Meteo
    aemet_valdes = _cache.get("prediccion_valdes") or []
    aemet_by_hour_cur = {}
    for av in aemet_valdes:
        if av.get("fecha") and av.get("hora") is not None:
            key = f"{av['fecha']}T{int(av['hora']):02d}"
            aemet_by_hour_cur[key] = av

    now_key = now.strftime("%Y-%m-%dT%H")
    aemet_now = aemet_by_hour_cur.get(now_key)
    if aemet_now and current_forecast and aemet_now.get("prob_precipitacion") is not None:
        current_forecast = {**current_forecast, "prob_precipitacion": aemet_now["prob_precipitacion"]}

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
            # Inyectar lluvia AEMET si hay
            aemet_h = aemet_by_hour_cur.get(h_str)
            if aemet_h and aemet_h.get("prob_precipitacion") is not None:
                fc_h = {**fc_h, "prob_precipitacion": aemet_h["prob_precipitacion"]}
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
                "presion": result_now.score_presion,
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

    # Tendencia de presión: comparar ahora con hace 6h y con +6h
    presion_trend = None
    if current_forecast and forecast:
        presion_ahora = current_forecast.get("presion")
        # Buscar presión hace 6h
        h_6ago = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H")
        h_6fut = (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H")
        presion_6h_ago = None
        presion_6h_fut = None
        for f in forecast:
            ts = f.get("timestamp", "")[:13]
            if ts == h_6ago:
                presion_6h_ago = f.get("presion")
            if ts == h_6fut:
                presion_6h_fut = f.get("presion")
        if presion_ahora and presion_6h_ago:
            diff = round(presion_ahora - presion_6h_ago, 1)
            if diff <= -4:
                trend_label = "Bajando rapido"
            elif diff <= -2:
                trend_label = "Bajando"
            elif diff >= 4:
                trend_label = "Subiendo rapido"
            elif diff >= 2:
                trend_label = "Subiendo"
            else:
                trend_label = "Estable"
            presion_trend = {
                "diff_6h": diff,
                "label": trend_label,
                "presion_6h_ago": presion_6h_ago,
                "presion_6h_fut": presion_6h_fut,
            }

    return {
        "observacion": obs_response,
        "marine": current_marine,
        "forecast_now": {
            "nubosidad": current_forecast.get("nubosidad") if current_forecast else None,
            "visibilidad": current_forecast.get("visibilidad") if current_forecast else None,
            "prob_precipitacion": current_forecast.get("prob_precipitacion") if current_forecast else None,
            "cielo": aemet_now.get("cielo") if aemet_now else None,
            "fuente_lluvia": "AEMET" if (aemet_now and aemet_now.get("prob_precipitacion") is not None) else "Open-Meteo",
        } if current_forecast else None,
        "presion_trend": presion_trend,
        "alertas": _cache.get("alertas_costeras") or [],
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

    # Indexar AEMET Valdés por fecha+hora para lluvia (más fiable que Open-Meteo)
    aemet_by_hour = {}
    aemet_valdes = _cache.get("prediccion_valdes") or []
    for av in aemet_valdes:
        if av.get("fecha") and av.get("hora") is not None:
            key = f"{av['fecha']}T{int(av['hora']):02d}"
            aemet_by_hour[key] = av

    # Indexar datos marinos por hora
    marine_by_hour = {}
    for m in marine:
        ts = m.get("timestamp", "")[:13]
        marine_by_hour[ts] = m

    # Indexar presion por hora para calcular tendencia 6h
    presion_by_hour = {}
    for f in forecast:
        ts = f.get("timestamp", "")[:13]
        if f.get("presion") is not None:
            presion_by_hour[ts] = f["presion"]

    result = []
    for f in forecast:
        ts = f.get("timestamp", "")[:13]
        m = marine_by_hour.get(ts)
        # Tendencia presion: valor actual - valor 6h antes
        p_trend = None
        if f.get("presion") is not None:
            try:
                h_dt = datetime.fromisoformat(f["timestamp"])
                h_6ago = (h_dt - timedelta(hours=6)).strftime("%Y-%m-%dT%H")
                if h_6ago in presion_by_hour:
                    p_trend = round(f["presion"] - presion_by_hour[h_6ago], 1)
            except Exception:
                pass
        # Lluvia: priorizar AEMET Valdés (más fiable localmente)
        aemet_h = aemet_by_hour.get(ts)
        prob_precip = f.get("prob_precipitacion")
        cielo_aemet = None
        if aemet_h and aemet_h.get("prob_precipitacion") is not None:
            prob_precip = aemet_h["prob_precipitacion"]
            cielo_aemet = aemet_h.get("cielo")

        # Inyectar en el forecast para que el scoring use AEMET
        f_scoring = {**f, "prob_precipitacion": prob_precip}

        scored = score_forecast_hour(f_scoring, m, presion_trend=p_trend)
        result.append({
            "timestamp": f.get("timestamp"),
            "temperatura": f.get("temperatura"),
            "humedad": f.get("humedad"),
            "viento_nudos": f.get("viento_nudos"),
            "viento_dir": f.get("viento_dir"),
            "viento_racha_nudos": f.get("viento_racha_nudos"),
            "prob_precipitacion": prob_precip,
            "precipitacion": f.get("precipitacion"),
            "cielo": cielo_aemet,
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

    # Indexar AEMET Valdés por fecha+hora para lluvia (más fiable localmente)
    aemet_by_hour = {}
    for av in _cache.get("prediccion_valdes") or []:
        if av.get("fecha") and av.get("hora") is not None:
            aemet_by_hour[f"{av['fecha']}T{int(av['hora']):02d}"] = av

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

    import math
    def _circular_mean(angles_deg):
        """Media circular de ángulos en grados (para dirección de viento)."""
        sin_sum = sum(math.sin(math.radians(a)) for a in angles_deg)
        cos_sum = sum(math.cos(math.radians(a)) for a in angles_deg)
        mean = math.degrees(math.atan2(sin_sum, cos_sum))
        return round(mean % 360)

    def summarize_day(date_str: str) -> dict:
        day_hours = [f for f in forecast if f.get("timestamp", "").startswith(date_str)]
        daylight = [f for f in day_hours if 8 <= int(f.get("timestamp", "T00")[11:13]) <= 20]
        if not daylight:
            daylight = day_hours

        if not daylight:
            return {"fecha": date_str, "disponible": False}

        avg_score, scores = _compute_day_score_from_hourly(
            date_str, forecast, marine_by_hour, aemet_by_hour
        )

        # Partes del día: mañana 8-13, tarde 14-20
        morning_h = [f for f in daylight if 8 <= int(f.get("timestamp", "T00")[11:13]) <= 13]
        afternoon_h = [f for f in daylight if 14 <= int(f.get("timestamp", "T00")[11:13]) <= 20]

        def _parte_meteo(hours):
            if not hours:
                return None
            nubs = [h.get("nubosidad") for h in hours if h.get("nubosidad") is not None]
            probs = []
            for h in hours:
                ts = h.get("timestamp", "")[:13]
                ae = aemet_by_hour.get(ts)
                p = ae.get("prob_precipitacion") if ae and ae.get("prob_precipitacion") is not None else h.get("prob_precipitacion")
                if p is not None:
                    probs.append(p)
            return {
                "nubosidad_media": round(sum(nubs) / len(nubs)) if nubs else None,
                "prob_lluvia_max": max(probs) if probs else None,
            }

        vientos = [f.get("viento_nudos") for f in daylight if f.get("viento_nudos") is not None]
        viento_dirs = [f.get("viento_dir") for f in daylight if f.get("viento_dir") is not None]
        rachas = [f.get("viento_racha_nudos") for f in daylight if f.get("viento_racha_nudos") is not None]
        olas = [marine_by_hour.get(f.get("timestamp", "")[:13], {}).get("ola_altura") for f in daylight]
        olas = [o for o in olas if o is not None]
        swells = [marine_by_hour.get(f.get("timestamp", "")[:13], {}).get("swell_altura") for f in daylight]
        swells = [s for s in swells if s is not None]
        chops = [marine_by_hour.get(f.get("timestamp", "")[:13], {}).get("viento_ola_altura") for f in daylight]
        chops = [c for c in chops if c is not None]
        precip = [f.get("prob_precipitacion") for f in daylight if f.get("prob_precipitacion") is not None]
        temps = [f.get("temperatura") for f in daylight if f.get("temperatura") is not None]

        best_score = max(scores) if scores else None
        worst_score = min(scores) if scores else None

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
            "viento_dir_predominante": _circular_mean(viento_dirs) if viento_dirs else None,
            "racha_max": round(max(rachas), 1) if rachas else None,
            "ola_media": round(sum(olas) / len(olas), 2) if olas else None,
            "ola_max": round(max(olas), 2) if olas else None,
            "swell_max": round(max(swells), 2) if swells else None,
            "chop_max": round(max(chops), 2) if chops else None,
            "precip_max": max(precip) if precip else None,
            "temp_min": round(min(temps), 1) if temps else None,
            "temp_max": round(max(temps), 1) if temps else None,
            "mejor_ventana": best_window,
            "manana": _parte_meteo(morning_h),
            "tarde": _parte_meteo(afternoon_h),
        }

    result = {"updated": _cache.get("timestamp"), "days": []}
    for d in days:
        summary = summarize_day(d["date"])
        summary["label"] = d["label"]
        result["days"].append(summary)
    return result


@app.get("/api/summary-explain")
async def api_summary_explain():
    """Explicación detallada del score de los 4 días del resumen,
    basada en las reglas reales de scoring.py (reglas_aplicadas vienen
    directamente de calculate_score, no se duplican aquí)."""
    if not _cache:
        raise HTTPException(503, "Datos no disponibles todavía")

    forecast = _cache.get("forecast") or []
    marine = _cache.get("oleaje") or []
    marine_by_hour = {m.get("timestamp", "")[:13]: m for m in marine}
    aemet_by_hour = {}
    for av in _cache.get("prediccion_valdes") or []:
        if av.get("fecha") and av.get("hora") is not None:
            aemet_by_hour[f"{av['fecha']}T{int(av['hora']):02d}"] = av

    now = datetime.now()
    DAY_NAMES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]

    from backend.scoring import LABELS, WEIGHTS

    def explain_day(date_str: str, day_label: str) -> dict:
        day_hours = [f for f in forecast if f.get("timestamp", "").startswith(date_str)]
        daylight = [f for f in day_hours if 8 <= int(f.get("timestamp", "T00")[11:13]) <= 20]
        if not daylight:
            daylight = day_hours
        if not daylight:
            return {"fecha": date_str, "label": day_label, "disponible": False}

        horas = []
        for f in daylight:
            ts = f.get("timestamp", "")[:13]
            m = marine_by_hour.get(ts)
            aemet_h = aemet_by_hour.get(ts)
            f_scoring = f
            if aemet_h and aemet_h.get("prob_precipitacion") is not None:
                f_scoring = {**f, "prob_precipitacion": aemet_h["prob_precipitacion"]}
            scored = score_forecast_hour(f_scoring, m)
            horas.append({
                "hora": f["timestamp"][11:16],
                "score": scored["score"],
                "score_ponderado": scored.get("score_ponderado"),
                "componentes": scored["scores"],
                "reglas_aplicadas": scored.get("reglas_aplicadas", []),
                "viento_kn": f.get("viento_nudos"),
                "racha_kn": f.get("viento_racha_nudos"),
                "viento_dir": f.get("viento_dir"),
                "ola_total_m": (m or {}).get("ola_altura"),
                "swell_m": (m or {}).get("swell_altura"),
                "swell_periodo": (m or {}).get("swell_periodo"),
                "chop_m": (m or {}).get("viento_ola_altura"),
                "chop_periodo": (m or {}).get("viento_ola_periodo"),
                "prob_precip": f_scoring.get("prob_precipitacion"),
                "visibilidad_m": f.get("visibilidad"),
                "nubosidad": f.get("nubosidad"),
                "temperatura": f.get("temperatura"),
            })

        # Score del día: promedio + peor ventana 3h
        scores_h = [h["score"] for h in horas]
        promedio = sum(scores_h) / len(scores_h)
        peor_ventana = None
        peor_ventana_rango = None
        if len(scores_h) >= 3:
            min_avg = 999
            for i in range(len(scores_h) - 2):
                w = sum(scores_h[i:i+3]) / 3
                if w < min_avg:
                    min_avg = w
                    peor_ventana_rango = {
                        "inicio": horas[i]["hora"],
                        "fin": horas[min(i+3, len(horas)-1)]["hora"],
                    }
            peor_ventana = min_avg
        day_score_float = min(promedio, peor_ventana) if peor_ventana is not None else promedio
        day_score = round(day_score_float)

        # Componente más limitante (peor media)
        comp_names = ["viento", "oleaje", "racha", "lluvia", "visibilidad", "nubosidad", "presion", "temperatura"]
        avg_per_comp = {}
        for c in comp_names:
            vals = [h["componentes"].get(c) for h in horas if h["componentes"].get(c) is not None]
            if vals:
                avg_per_comp[c] = round(sum(vals) / len(vals), 1)

        # Factores críticos: componentes con score medio ≤5, ordenados de peor a mejor
        factores = []
        for comp, avg in sorted(avg_per_comp.items(), key=lambda x: x[1]):
            if avg <= 5:
                factores.append({
                    "factor": comp,
                    "factor_label": COMP_LABEL.get(comp, comp),
                    "score_medio": avg,
                    "explicacion": _explain_componente(comp, horas),
                })

        # Reglas únicas aplicadas durante el día (de scoring.py, fuente de verdad)
        reglas_set = []
        for h in horas:
            for r in h.get("reglas_aplicadas", []):
                if r not in reglas_set:
                    reglas_set.append(r)

        # Regla decisiva para el score diario
        regla_diaria = None
        if peor_ventana is not None:
            if abs(peor_ventana - promedio) < 0.01:
                regla_diaria = f"Promedio de horas de luz = peor ventana 3h ({promedio:.1f})"
            elif peor_ventana < promedio:
                regla_diaria = (
                    f"Peor ventana 3h = {peor_ventana:.1f} (menor que promedio {promedio:.1f}) "
                    f"→ se toma la peor ventana como score del día"
                )
            else:
                regla_diaria = (
                    f"Promedio {promedio:.1f} (menor que peor ventana {peor_ventana:.1f}) → promedio gana"
                )
        else:
            regla_diaria = f"Pocas horas para ventana 3h → promedio {promedio:.1f}"

        label, color, recomendacion = LABELS[day_score]

        return {
            "fecha": date_str,
            "label": day_label,
            "disponible": True,
            "score_dia": day_score,
            "label_score": label,
            "color": color,
            "recomendacion": recomendacion,
            "promedio_horas_luz": round(promedio, 1),
            "peor_ventana_3h": round(peor_ventana, 1) if peor_ventana is not None else None,
            "peor_ventana_rango": peor_ventana_rango,
            "regla_diaria": regla_diaria,
            "score_medio_componentes": avg_per_comp,
            "factores_criticos": factores,
            "reglas_aplicadas_dia": reglas_set,
            "horas": horas,
        }

    result = []
    for i in range(4):
        d = now + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        if i == 0:
            label = "Hoy"
        elif i == 1:
            label = "Manana"
        else:
            label = DAY_NAMES[d.weekday()]
        result.append(explain_day(date_str, label))

    return {
        "updated": _cache.get("timestamp"),
        "pesos_componentes": WEIGHTS,
        "days": result,
    }


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


@app.get("/api/extended")
async def api_extended():
    """Previsión extendida 16 días con score diario orientativo."""
    if not _cache:
        raise HTTPException(503, "Datos no disponibles todavía")

    extended = _cache.get("extended") or []
    if not extended:
        return {"days": [], "updated": _cache.get("timestamp")}

    # Indexar forecast horario + marine + AEMET Valdés para reusar en días con datos finos
    forecast = _cache.get("forecast") or []
    marine = _cache.get("oleaje") or []
    marine_by_hour = {m.get("timestamp", "")[:13]: m for m in marine}
    aemet_by_hour = {}
    for av in _cache.get("prediccion_valdes") or []:
        if av.get("fecha") and av.get("hora") is not None:
            aemet_by_hour[f"{av['fecha']}T{int(av['hora']):02d}"] = av

    forecast_dates = {f.get("timestamp", "")[:10] for f in forecast}

    from backend.scoring import LABELS

    DAY_NAMES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

    result = []
    for i, d in enumerate(extended):
        fecha = d.get("fecha", "")

        # Si tenemos forecast horario para esa fecha, usar scoring fino (mismo que summary)
        day_score_hourly = None
        if fecha in forecast_dates:
            day_score_hourly, _ = _compute_day_score_from_hourly(
                fecha, forecast, marine_by_hour, aemet_by_hour
            )

        if day_score_hourly is not None:
            score_val = day_score_hourly
            label_v, color_v, _rec = LABELS[score_val]
        else:
            # Fallback: score orientativo desde valores diarios máximos
            inp = ScoringInput(
                viento_nudos=d.get("viento_max_kn"),
                racha_nudos=d.get("racha_max_kn"),
                swell_altura=d.get("swell_max"),
                viento_ola_altura=d.get("chop_max"),
                ola_altura=d.get("ola_max"),
                ola_periodo=d.get("periodo_max"),
                prob_precipitacion=d.get("prob_precipitacion"),
                precipitacion_mm=d.get("precipitacion_mm"),
                nubosidad=d.get("nubosidad"),
                temperatura=(d.get("temp_max", 15) + d.get("temp_min", 10)) / 2 if d.get("temp_max") else None,
            )
            scored = calculate_score(inp)
            score_val = scored.score
            label_v = scored.label
            color_v = scored.color
        try:
            from datetime import datetime as dt
            day_dt = dt.strptime(fecha, "%Y-%m-%d")
            day_name = DAY_NAMES[day_dt.weekday()]
        except Exception:
            day_name = ""

        result.append({
            "fecha": fecha,
            "dia": day_name,
            "fiable": i < 7,  # primeros 7 dias = fiable
            "score": score_val,
            "label": label_v,
            "color": color_v,
            "viento_max_kn": d.get("viento_max_kn"),
            "racha_max_kn": d.get("racha_max_kn"),
            "ola_max": d.get("ola_max"),
            "swell_max": d.get("swell_max"),
            "prob_precipitacion": d.get("prob_precipitacion"),
            "precipitacion_mm": d.get("precipitacion_mm"),
            "nubosidad": d.get("nubosidad"),
            "temp_max": d.get("temp_max"),
            "temp_min": d.get("temp_min"),
            "temp_agua": d.get("temp_agua"),
            "viento_dir": d.get("viento_dir"),
        })

    return {"days": result, "updated": _cache.get("timestamp")}


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
