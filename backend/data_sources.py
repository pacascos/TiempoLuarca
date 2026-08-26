"""
Clientes para las fuentes de datos meteorológicos y marítimos.
- AEMET OpenData: observaciones Cabo Busto, predicción Valdés, costera
- IHM: mareas Navia y Cudillero
- Open-Meteo: oleaje y predicción meteorológica
"""

import io
import json
import logging
import tarfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from backend.config import (
    AEMET_API_KEY, AEMET_BASE_URL, AEMET_STATION_BUSTO,
    AEMET_MUNICIPIO_VALDES, AEMET_COSTA_CAN1, AEMET_PLAYA_LUARCA,
    IHM_BASE_URL, IHM_STATION_NAVIA, IHM_STATION_CUDILLERO,
    OPEN_METEO_MARINE_URL, OPEN_METEO_FORECAST_URL,
    LUARCA_LAT, LUARCA_LON, MAR_LAT, MAR_LON,
)

logger = logging.getLogger(__name__)


TZ_MADRID = ZoneInfo("Europe/Madrid")


def _utc_to_local(hora_str: str, fecha_str: str) -> tuple[str, str]:
    """Convierte hora UTC (HH:MM) + fecha (YYYY-MM-DD) a hora local de España.
    Devuelve (hora_local, fecha_local) porque al sumar puede cambiar de día."""
    try:
        dt_utc = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(TZ_MADRID)
        return dt_local.strftime("%H:%M"), dt_local.strftime("%Y-%m-%d")
    except Exception:
        return hora_str, fecha_str

AEMET_HEADERS = {"api_key": AEMET_API_KEY}
TIMEOUT = 15.0


async def _aemet_get(path: str) -> dict | list | None:
    """AEMET usa un sistema de dos pasos: primero da una URL con los datos."""
    if not AEMET_API_KEY:
        logger.warning("AEMET_API_KEY no configurada, omitiendo %s", path)
        return None
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
                return json.loads(r2.content.decode("latin-1"))
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
        "viento_vel_nudos": round(obs["vv"] * 1.94384, 1) if obs.get("vv") is not None else None,
        "viento_dir": obs.get("dv"),          # grados
        "viento_racha": obs.get("vmax"),      # m/s
        "viento_racha_nudos": round(obs["vmax"] * 1.94384, 1) if obs.get("vmax") is not None else None,
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
    def _safe_get(obj, key):
        """Extrae valor de un dict AEMET, tolerando campos que vengan como int."""
        v = obj.get(key)
        return v if isinstance(v, dict) else {}

    def _fecha_iso(v) -> str:
        """AEMET playa devuelve la fecha como int YYYYMMDD; otras como ISO."""
        s = str(v or "")
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s[:10]

    result = []
    for entry in data:
        pred = entry.get("prediccion", {})
        dia_data = pred.get("dia", [])
        for dia in dia_data:
            result.append({
                "fecha": _fecha_iso(dia.get("fecha")),
                "estado_cielo": _safe_get(dia, "estadoCielo").get("descripcion1", ""),
                "viento": _safe_get(dia, "viento").get("descripcion1", ""),
                "oleaje": _safe_get(dia, "oleaje").get("descripcion1", ""),
                "t_max": _safe_get(dia, "tMaxima").get("valor1"),
                "uv": _safe_get(dia, "uvMax").get("valor1"),
                "t_agua": _safe_get(dia, "tAgua").get("valor1"),
                "fuente": "AEMET Playa Luarca",
            })
    return result


# ─── IHM: Mareas ─────────────────────────────────────────────────────────────

async def get_ihm_mareas(days: int = 3) -> dict | None:
    """Mareas para Navia y Cudillero (que enmarcan Luarca).
    IHM API: sin fecha da hoy, con fecha dd-mm-yyyy.
    Respuesta: {"mareas": {"datos": {"marea": [{"hora","altura","tipo"},...]}}}
    """
    today = datetime.now(TZ_MADRID)
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
                        # IHM devuelve horas en UTC, convertir a Europe/Madrid
                        hora_utc = marea.get("hora", "")
                        hora_local, fecha_local = _utc_to_local(hora_utc, fecha_str)
                        tides.append({
                            "fecha": fecha_local,
                            "hora": hora_local,
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


# ─── AEMET: Alertas/Avisos costeros ───────────────────────────────────────────

async def get_aemet_alertas_costeras() -> list | None:
    """Obtiene avisos meteorológicos para Asturias (area 63), filtra costeros.
    AEMET devuelve CAP XML en tar.gz. Parseamos los avisos relevantes.
    Zonas costeras Asturias: 633301C (occidental), 633302C (oriental).
    """
    if not AEMET_API_KEY:
        logger.warning("AEMET_API_KEY no configurada, omitiendo alertas")
        return []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Paso 1: obtener URL de datos
            r = await client.get(
                f"{AEMET_BASE_URL}/avisos_cap/ultimoelaborado/area/63",
                headers=AEMET_HEADERS,
            )
            r.raise_for_status()
            body = r.json()
            if "datos" not in body:
                logger.warning("AEMET alertas sin 'datos': %s", body)
                return []

            # Paso 2: descargar tar.gz
            r2 = await client.get(body["datos"])
            r2.raise_for_status()

        # Parsear tar (puede ser tar o tar.gz)
        alertas = []
        for mode in ("r:gz", "r"):
            try:
                tar = tarfile.open(fileobj=io.BytesIO(r2.content), mode=mode)
                for member in tar.getmembers():
                    if member.name.endswith(".xml"):
                        f = tar.extractfile(member)
                        if f:
                            alertas.extend(_parse_cap_xml(f.read()))
                tar.close()
                break
            except Exception:
                continue
        else:
            # Ni tar.gz ni tar, intentar como XML directo
            try:
                alertas = _parse_cap_xml(r2.content)
            except Exception:
                logger.warning("AEMET alertas: formato no reconocido")
                return []

        # Filtrar costeras, descartando avisos verdes y los ya caducados (fin < ahora)
        now = datetime.now(timezone.utc)

        def vigente(a: dict) -> bool:
            fin = a.get("fin")
            if not fin:
                return True
            try:
                return datetime.fromisoformat(fin) >= now
            except Exception:
                return True

        costeras = [
            a for a in alertas
            if a.get("es_costera") and a.get("nivel") != "verde" and vigente(a)
        ]
        logger.info("AEMET alertas costeras vigentes: %d", len(costeras))
        return costeras

    except Exception as e:
        logger.error("Error AEMET alertas: %s", e)
        return []


def _parse_cap_xml(xml_bytes: bytes) -> list:
    """Parsea un XML CAP de AEMET y extrae alertas."""
    ns = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
    alertas = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []

    # Puede ser un <alert> directo o un contenedor
    alerts = root.findall(".//cap:alert", ns) if root.tag != "{urn:oasis:names:tc:emergency:cap:1.2}alert" else [root]
    if not alerts and root.tag.endswith("alert"):
        alerts = [root]

    for alert in alerts:
        for info in alert.findall("cap:info", ns):
            # Evitar duplicados: AEMET incluye cada aviso en es-ES y en-GB.
            # Nos quedamos solo con la versión en español.
            lang = info.findtext("cap:language", "", ns)
            if lang and not lang.lower().startswith("es"):
                continue

            nivel = "verde"
            fenomeno = ""
            es_costera = False
            zona = ""
            descripcion = info.findtext("cap:description", "", ns)
            headline = info.findtext("cap:headline", "", ns)
            severity = info.findtext("cap:severity", "", ns)
            onset = info.findtext("cap:onset", "", ns)  # inicio
            expires = info.findtext("cap:expires", "", ns)  # fin

            # Leer parámetros
            for param in info.findall("cap:parameter", ns):
                name = param.findtext("cap:valueName", "", ns)
                val = param.findtext("cap:value", "", ns)
                if "nivel" in name.lower():
                    nivel = val.lower()  # amarillo, naranja, rojo, verde
                if "fenomeno" in name.lower() or "parametro" in name.lower():
                    fenomeno = val

            # Zona costera marítima: geocódigo de Asturias terminado en "C"
            # (633301C = Costa litoral occidental, 633302C = oriental). El resto
            # (633303/04/05 = interior, 633301/02 = franja litoral terrestre) se descarta.
            for area in info.findall("cap:area", ns):
                area_desc = area.findtext("cap:areaDesc", "", ns)
                for gc in area.findall("cap:geocode", ns):
                    val = gc.findtext("cap:value", "", ns)
                    if val and val.startswith("6333") and val.endswith("C"):
                        es_costera = True
                        zona = area_desc

            if es_costera:
                alertas.append({
                    "nivel": nivel,
                    "severity": severity,
                    "headline": headline,
                    "descripcion": descripcion[:300] if descripcion else "",
                    "fenomeno": fenomeno,
                    "zona": zona or "Costa asturiana",
                    "inicio": onset,
                    "fin": expires,
                    "es_costera": True,
                })

    return alertas


# ─── Open-Meteo: Oleaje ──────────────────────────────────────────────────────

async def get_open_meteo_marine() -> list | None:
    """Previsión de oleaje desde Open-Meteo Marine API."""
    params = {
        "latitude": LUARCA_LAT,
        "longitude": LUARCA_LON,
        "hourly": "wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_period,swell_wave_direction,wind_wave_height,wind_wave_period,wind_wave_direction,sea_surface_temperature",
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
                "temp_agua": hourly.get("sea_surface_temperature", [None])[i],
                "fuente": "Open-Meteo Marine",
            })
        return result
    except Exception as e:
        logger.error("Error Open-Meteo Marine: %s", e)
        return None


# ─── Open-Meteo: Pronóstico meteorológico ────────────────────────────────────

async def _get_arome_wind(client: httpx.AsyncClient) -> dict:
    """Viento del modelo AROME HD de Météo-France (1.5km, cubre Luarca, ~48h).
    Mucho mejor que el blend global (~10km) para viento costero con cabos.
    Devuelve {timestamp: {viento_nudos, viento_dir, viento_racha_nudos}}."""
    arome_by_hour = {}
    try:
        r = await client.get(OPEN_METEO_FORECAST_URL, params={
            "latitude": LUARCA_LAT,
            "longitude": LUARCA_LON,
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "timezone": "Europe/Madrid",
            "forecast_days": 3,
            "wind_speed_unit": "kn",
            "models": "meteofrance_arome_france_hd",
        })
        r.raise_for_status()
        hourly = r.json().get("hourly", {})
        for i, t in enumerate(hourly.get("time", [])):
            v = hourly.get("wind_speed_10m", [None])[i]
            if v is None:
                continue  # más allá del horizonte AROME
            arome_by_hour[t] = {
                "viento_nudos": v,
                "viento_dir": hourly.get("wind_direction_10m", [None])[i],
                "viento_racha_nudos": hourly.get("wind_gusts_10m", [None])[i],
            }
    except Exception as e:
        logger.warning("AROME no disponible, usando solo best_match: %s", e)
    if arome_by_hour:
        logger.info("AROME 1.5km: viento de alta resolución para %d horas", len(arome_by_hour))
    else:
        logger.warning("AROME devolvió 0 horas, viento solo de best_match")
    return arome_by_hour


async def _get_viento_mar(client: httpx.AsyncClient) -> dict:
    """Viento en el punto de mar abierto (~10 nm), donde se calcula el oleaje.
    Con NE la costa queda abrigada y el viento de tierra engaña: aquí puede
    soplar 4x más. Solo informativo, no entra en el score (salidas costeras).
    Devuelve {timestamp: {viento_mar_nudos, viento_mar_racha_nudos}}."""
    by_hour = {}
    try:
        r = await client.get(OPEN_METEO_FORECAST_URL, params={
            "latitude": MAR_LAT,
            "longitude": MAR_LON,
            "hourly": "wind_speed_10m,wind_gusts_10m",
            "timezone": "Europe/Madrid",
            "forecast_days": 7,
            "wind_speed_unit": "kn",
        })
        r.raise_for_status()
        hourly = r.json().get("hourly", {})
        for i, t in enumerate(hourly.get("time", [])):
            v = hourly.get("wind_speed_10m", [None])[i]
            if v is None:
                continue
            by_hour[t] = {
                "viento_mar_nudos": v,
                "viento_mar_racha_nudos": hourly.get("wind_gusts_10m", [None])[i],
            }
    except Exception as e:
        logger.warning("Viento de mar abierto no disponible: %s", e)
    return by_hour


async def get_open_meteo_forecast() -> list | None:
    """Pronóstico meteorológico horario desde Open-Meteo.
    El viento de las primeras ~48h se sustituye por AROME HD (1.5km) si responde."""
    params = {
        "latitude": LUARCA_LAT,
        "longitude": LUARCA_LON,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility,pressure_msl,cloud_cover",
        "timezone": "Europe/Madrid",
        "forecast_days": 7,
        # Ayer incluido para poder calcular la tendencia de presión 6h
        # también en las primeras horas de hoy (la API filtra el pasado).
        "past_days": 1,
        "wind_speed_unit": "kn",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(OPEN_METEO_FORECAST_URL, params=params)
            r.raise_for_status()
            data = r.json()
            arome_by_hour = await _get_arome_wind(client)
            mar_by_hour = await _get_viento_mar(client)

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        result = []
        for i, t in enumerate(times):
            entry = {
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
            }
            ar = arome_by_hour.get(t)
            if ar:
                entry["viento_nudos"] = ar["viento_nudos"]
                if ar["viento_dir"] is not None:
                    entry["viento_dir"] = ar["viento_dir"]
                if ar["viento_racha_nudos"] is not None:
                    entry["viento_racha_nudos"] = ar["viento_racha_nudos"]
                entry["fuente_viento"] = "AROME 1.5km"
            mar = mar_by_hour.get(t)
            if mar:
                entry.update(mar)
            result.append(entry)
        return result
    except Exception as e:
        logger.error("Error Open-Meteo Forecast: %s", e)
        return None


# ─── Open-Meteo: Previsión extendida 16 días (diaria) ─────────────────────────

async def get_open_meteo_extended() -> list | None:
    """Previsión diaria a 16 días: meteo + oleaje combinados."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Meteo diario
            r1 = await client.get(OPEN_METEO_FORECAST_URL, params={
                "latitude": LUARCA_LAT, "longitude": LUARCA_LON,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,cloud_cover_mean",
                "timezone": "Europe/Madrid",
                "forecast_days": 16,
                "wind_speed_unit": "kn",
            })
            r1.raise_for_status()
            meteo = r1.json().get("daily", {})

            # Marine diario
            r2 = await client.get(OPEN_METEO_MARINE_URL, params={
                "latitude": LUARCA_LAT, "longitude": LUARCA_LON,
                "daily": "wave_height_max,swell_wave_height_max,wind_wave_height_max,wave_period_max,sea_surface_temperature_max",
                "timezone": "Europe/Madrid",
                "forecast_days": 16,
            })
            r2.raise_for_status()
            marine = r2.json().get("daily", {})

        times = meteo.get("time", [])
        result = []
        for i, date in enumerate(times):
            result.append({
                "fecha": date,
                "temp_max": meteo.get("temperature_2m_max", [None])[i],
                "temp_min": meteo.get("temperature_2m_min", [None])[i],
                "prob_precipitacion": meteo.get("precipitation_probability_max", [None])[i],
                "precipitacion_mm": meteo.get("precipitation_sum", [None])[i],
                "viento_max_kn": meteo.get("wind_speed_10m_max", [None])[i],
                "racha_max_kn": meteo.get("wind_gusts_10m_max", [None])[i],
                "viento_dir": meteo.get("wind_direction_10m_dominant", [None])[i],
                "nubosidad": meteo.get("cloud_cover_mean", [None])[i],
                "ola_max": marine.get("wave_height_max", [None])[i] if i < len(marine.get("wave_height_max", [])) else None,
                "swell_max": marine.get("swell_wave_height_max", [None])[i] if i < len(marine.get("swell_wave_height_max", [])) else None,
                "chop_max": marine.get("wind_wave_height_max", [None])[i] if i < len(marine.get("wind_wave_height_max", [])) else None,
                "periodo_max": marine.get("wave_period_max", [None])[i] if i < len(marine.get("wave_period_max", [])) else None,
                "temp_agua": marine.get("sea_surface_temperature_max", [None])[i] if i < len(marine.get("sea_surface_temperature_max", [])) else None,
            })
        return result
    except Exception as e:
        logger.error("Error Open-Meteo Extended: %s", e)
        return None
