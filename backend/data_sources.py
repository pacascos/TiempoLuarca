"""
Clientes para las fuentes de datos meteorológicos y marítimos.
- AEMET OpenData: observaciones Cabo Busto, predicción Valdés, costera
- IHM: mareas Navia y Cudillero
- Open-Meteo: oleaje y predicción meteorológica
"""

import httpx
import logging
from datetime import datetime, timedelta
from backend.config import (
    AEMET_API_KEY, AEMET_BASE_URL, AEMET_STATION_BUSTO,
    AEMET_MUNICIPIO_VALDES, AEMET_COSTA_CAN1, AEMET_PLAYA_LUARCA,
    IHM_BASE_URL, IHM_STATION_NAVIA, IHM_STATION_CUDILLERO,
    OPEN_METEO_MARINE_URL, OPEN_METEO_FORECAST_URL,
    LUARCA_LAT, LUARCA_LON,
)

logger = logging.getLogger(__name__)

AEMET_HEADERS = {"api_key": AEMET_API_KEY}
TIMEOUT = 15.0


async def _aemet_get(path: str) -> dict | list | None:
    """AEMET usa un sistema de dos pasos: primero da una URL con los datos."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{AEMET_BASE_URL}{path}", headers=AEMET_HEADERS)
            r.raise_for_status()
            body = r.json()
            if "datos" not in body:
                logger.warning("AEMET sin campo 'datos': %s", body)
                return None
            r2 = await client.get(body["datos"])
            r2.raise_for_status()
            # AEMET a veces devuelve latin-1 en vez de utf-8
            try:
                return r2.json()
            except Exception:
                text = r2.content.decode("latin-1")
                import json
                return json.loads(text)
    except Exception as e:
        logger.error("Error AEMET %s: %s", path, e)
        return None


# ─── AEMET: Observación Cabo Busto ───────────────────────────────────────────

async def get_aemet_observacion_busto() -> dict | None:
    """Últimas observaciones de la estación de Cabo Busto (1283U)."""
    data = await _aemet_get(
        f"/observacion/convencional/datos/estacion/{AEMET_STATION_BUSTO}"
    )
    if not data:
        return None
    # Tomar la observación más reciente
    latest = max(data, key=lambda x: x.get("fint", ""))
    return _parse_observacion(latest)


def _parse_observacion(obs: dict) -> dict:
    return {
        "timestamp": obs.get("fint"),
        "temperatura": obs.get("ta"),         # °C
        "humedad": obs.get("hr"),             # %
        "presion": obs.get("pres"),           # hPa
        "viento_vel": obs.get("vv"),          # m/s
        "viento_vel_nudos": round(obs.get("vv", 0) * 1.94384, 1) if obs.get("vv") else None,
        "viento_dir": obs.get("dv"),          # grados
        "viento_racha": obs.get("vmax"),      # m/s
        "viento_racha_nudos": round(obs.get("vmax", 0) * 1.94384, 1) if obs.get("vmax") else None,
        "precipitacion": obs.get("prec"),     # mm
        "visibilidad": obs.get("vis"),        # km
        "fuente": "AEMET Cabo Busto",
    }


# ─── AEMET: Predicción municipal Valdés ──────────────────────────────────────

async def get_aemet_prediccion_valdes() -> list | None:
    """Predicción horaria para Valdés (próximas 48h)."""
    data = await _aemet_get(
        f"/prediccion/especifica/municipio/horaria/{AEMET_MUNICIPIO_VALDES}"
    )
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    pred = data[0].get("prediccion", {})
    dias = pred.get("dia", [])
    result = []
    for dia in dias:
        fecha = dia.get("fecha", "")[:10]
        # Extraer horas de cada variable
        temps = {int(h["periodo"]): h["value"] for h in dia.get("temperatura", []) if "periodo" in h and "value" in h}
        humeds = {int(h["periodo"]): h["value"] for h in dia.get("humedadRelativa", []) if "periodo" in h and "value" in h}

        # probPrecipitacion usa periodos como "1319" (rango 13:00-19:00)
        probs_precip_raw = {}
        for h in dia.get("probPrecipitacion", []):
            if "periodo" in h and h.get("value", "") != "":
                probs_precip_raw[h["periodo"]] = int(h["value"])

        # vientoAndRachaMax alterna: viento (con direccion/velocidad) y racha (con value)
        vientos = {}
        rachas = {}
        for v in dia.get("vientoAndRachaMax", []):
            if "periodo" not in v:
                continue
            hora = int(v["periodo"])
            if "direccion" in v:
                vel_list = v.get("velocidad", [])
                dir_list = v.get("direccion", [])
                vientos[hora] = {
                    "velocidad": int(vel_list[0]) if vel_list else 0,
                    "direccion": dir_list[0] if dir_list else "",
                }
            elif "value" in v and v["value"] != "":
                rachas[hora] = int(v["value"])

        cielo = {}
        for c in dia.get("estadoCielo", []):
            if "periodo" in c:
                cielo[int(c["periodo"])] = c.get("descripcion", "")

        # Buscar prob_precipitacion por hora: mapear rangos a horas individuales
        def get_precip_for_hour(hora):
            for periodo, val in probs_precip_raw.items():
                p = str(periodo)
                if len(p) == 4:
                    start, end = int(p[:2]), int(p[2:])
                    if start <= hora < end:
                        return val
                elif len(p) <= 2:
                    if int(p) == hora:
                        return val
            return None

        for hora in sorted(set(list(temps.keys()) + list(vientos.keys()))):
            entry = {
                "fecha": fecha,
                "hora": hora,
                "temperatura": temps.get(hora),
                "humedad": humeds.get(hora),
                "prob_precipitacion": get_precip_for_hour(hora),
                "viento_vel_kmh": vientos.get(hora, {}).get("velocidad"),
                "viento_dir": vientos.get(hora, {}).get("direccion"),
                "racha_max_kmh": rachas.get(hora),
                "cielo": cielo.get(hora, ""),
                "fuente": "AEMET Valdés",
            }
            # Convertir viento a nudos
            if entry["viento_vel_kmh"] is not None:
                entry["viento_vel_nudos"] = round(entry["viento_vel_kmh"] / 1.852, 1)
            if entry["racha_max_kmh"] is not None:
                entry["racha_max_nudos"] = round(entry["racha_max_kmh"] / 1.852, 1)
            result.append(entry)
    return result


# ─── AEMET: Predicción costera ───────────────────────────────────────────────

async def get_aemet_prediccion_costera() -> dict | None:
    """Predicción marítima costera para la costa asturiana."""
    data = await _aemet_get(
        f"/prediccion/maritima/costera/costa/{AEMET_COSTA_CAN1}"
    )
    if not data:
        return None
    # La costera viene como texto, parseamos lo que podemos
    if isinstance(data, list) and len(data) > 0:
        return {"texto": data[0] if isinstance(data[0], str) else str(data[0]), "fuente": "AEMET Costera"}
    return {"texto": str(data), "fuente": "AEMET Costera"}


# ─── AEMET: Predicción playa ─────────────────────────────────────────────────

async def get_aemet_prediccion_playa() -> list | None:
    """Predicción de playa para Luarca."""
    data = await _aemet_get(
        f"/prediccion/especifica/playa/{AEMET_PLAYA_LUARCA}"
    )
    if not data or not isinstance(data, list):
        return None
    result = []
    for entry in data:
        pred = entry.get("prediccion", {})
        dia_data = pred.get("dia", [])
        for dia in dia_data:
            result.append({
                "fecha": dia.get("fecha", "")[:10],
                "estado_cielo": dia.get("estadoCielo", {}).get("descripcion1", ""),
                "viento": dia.get("viento", {}).get("descripcion1", ""),
                "oleaje": dia.get("oleaje", {}).get("descripcion1", ""),
                "t_max": dia.get("tMaxima", {}).get("valor1"),
                "uv": dia.get("uvMax", {}).get("valor1"),
                "t_agua": dia.get("tAgua", {}).get("valor1"),
                "fuente": "AEMET Playa Luarca",
            })
    return result


# ─── IHM: Mareas ─────────────────────────────────────────────────────────────

async def get_ihm_mareas(days: int = 3) -> dict | None:
    """Mareas para Navia y Cudillero (que enmarcan Luarca).
    IHM API: sin fecha da hoy, con fecha dd-mm-yyyy.
    Respuesta: {"mareas": {"datos": {"marea": [{"hora","altura","tipo"},...]}}}
    """
    today = datetime.now()
    results = {}

    # IHM: Navia=9, Cudillero no está. Avilés=7 es la más cercana al este.
    stations = [("navia", IHM_STATION_NAVIA), ("aviles", 7)]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for name, station_id in stations:
            try:
                tides = []
                for d in range(days):
                    date = today + timedelta(days=d)
                    date_str = date.strftime("%d-%m-%Y")
                    url = (
                        f"{IHM_BASE_URL}?request=gettide&id={station_id}"
                        f"&date={date_str}&format=json"
                    )
                    r = await client.get(url)
                    r.raise_for_status()

                    # IHM devuelve latin-1
                    import json
                    text = r.content.decode("latin-1")
                    if "No existen datos" in text:
                        # Sin fecha específica, prueba sin ella (solo funciona para hoy)
                        if d == 0:
                            url_today = f"{IHM_BASE_URL}?request=gettide&id={station_id}&format=json"
                            r2 = await client.get(url_today)
                            text = r2.content.decode("latin-1")
                            if "No existen datos" in text:
                                continue
                        else:
                            continue
                    data = json.loads(text)

                    # Formato: {"mareas": {"datos": {"marea": [...]}}}
                    mareas_obj = data.get("mareas", {})
                    datos = mareas_obj.get("datos", {})
                    marea_list = datos.get("marea", [])
                    fecha_str = mareas_obj.get("fecha", date.strftime("%Y-%m-%d"))

                    for marea in marea_list:
                        tides.append({
                            "fecha": fecha_str,
                            "hora": marea.get("hora", ""),
                            "altura": float(marea.get("altura", 0)),
                            "tipo": marea.get("tipo", ""),
                        })
                results[name] = tides
            except Exception as e:
                logger.error("Error IHM %s: %s", name, e)
                results[name] = []

    return {
        "navia": results.get("navia", []),
        "aviles": results.get("aviles", []),
        "fuente": "IHM Mareas",
    }


# ─── Open-Meteo: Oleaje ──────────────────────────────────────────────────────

async def get_open_meteo_marine() -> list | None:
    """Previsión de oleaje desde Open-Meteo Marine API."""
    params = {
        "latitude": LUARCA_LAT,
        "longitude": LUARCA_LON,
        "hourly": "wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_period,swell_wave_direction,wind_wave_height,wind_wave_period,wind_wave_direction",
        "timezone": "Europe/Madrid",
        "forecast_days": 7,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(OPEN_METEO_MARINE_URL, params=params)
            r.raise_for_status()
            data = r.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        result = []
        for i, t in enumerate(times):
            result.append({
                "timestamp": t,
                "ola_altura": hourly.get("wave_height", [None])[i],
                "ola_direccion": hourly.get("wave_direction", [None])[i],
                "ola_periodo": hourly.get("wave_period", [None])[i],
                "swell_altura": hourly.get("swell_wave_height", [None])[i],
                "swell_periodo": hourly.get("swell_wave_period", [None])[i],
                "swell_direccion": hourly.get("swell_wave_direction", [None])[i],
                "viento_ola_altura": hourly.get("wind_wave_height", [None])[i],
                "viento_ola_periodo": hourly.get("wind_wave_period", [None])[i],
                "viento_ola_direccion": hourly.get("wind_wave_direction", [None])[i],
                "fuente": "Open-Meteo Marine",
            })
        return result
    except Exception as e:
        logger.error("Error Open-Meteo Marine: %s", e)
        return None


# ─── Open-Meteo: Pronóstico meteorológico ────────────────────────────────────

async def get_open_meteo_forecast() -> list | None:
    """Pronóstico meteorológico horario desde Open-Meteo."""
    params = {
        "latitude": LUARCA_LAT,
        "longitude": LUARCA_LON,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility,pressure_msl,cloud_cover",
        "timezone": "Europe/Madrid",
        "forecast_days": 7,
        "wind_speed_unit": "kn",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(OPEN_METEO_FORECAST_URL, params=params)
            r.raise_for_status()
            data = r.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        result = []
        for i, t in enumerate(times):
            result.append({
                "timestamp": t,
                "temperatura": hourly.get("temperature_2m", [None])[i],
                "humedad": hourly.get("relative_humidity_2m", [None])[i],
                "prob_precipitacion": hourly.get("precipitation_probability", [None])[i],
                "precipitacion": hourly.get("precipitation", [None])[i],
                "viento_nudos": hourly.get("wind_speed_10m", [None])[i],
                "viento_dir": hourly.get("wind_direction_10m", [None])[i],
                "viento_racha_nudos": hourly.get("wind_gusts_10m", [None])[i],
                "visibilidad": hourly.get("visibility", [None])[i],
                "presion": hourly.get("pressure_msl", [None])[i],
                "nubosidad": hourly.get("cloud_cover", [None])[i],
                "fuente": "Open-Meteo",
            })
        return result
    except Exception as e:
        logger.error("Error Open-Meteo Forecast: %s", e)
        return None


# ─── Agregador principal ─────────────────────────────────────────────────────

async def fetch_all_data() -> dict:
    """Obtiene datos de todas las fuentes en paralelo."""
    import asyncio

    results = await asyncio.gather(
        get_aemet_observacion_busto(),
        get_aemet_prediccion_valdes(),
        get_aemet_prediccion_costera(),
        get_aemet_prediccion_playa(),
        get_ihm_mareas(days=8),
        get_open_meteo_marine(),
        get_open_meteo_forecast(),
        return_exceptions=True,
    )

    def safe(r):
        if isinstance(r, Exception):
            logger.error("Error en fetch: %s", r)
            return None
        return r

    return {
        "observacion_busto": safe(results[0]),
        "prediccion_valdes": safe(results[1]),
        "prediccion_costera": safe(results[2]),
        "prediccion_playa": safe(results[3]),
        "mareas": safe(results[4]),
        "oleaje": safe(results[5]),
        "forecast": safe(results[6]),
        "timestamp": datetime.now().isoformat(),
    }
