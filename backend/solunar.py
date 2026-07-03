"""
Actividad solunar (peces) calculada en local con efemérides lunares (ephem).

Teoría solunar: los peces están más activos en los periodos en que la luna
cruza el meridiano del lugar (tránsito superior e inferior → periodos MAYORES,
~2h) y en el orto/ocaso lunar (periodos MENORES, ~1h). La fase lunar modula la
intensidad: luna nueva y llena = máxima actividad, cuartos = mínima.

Sin dependencia de APIs externas: todo se calcula con ephem para las
coordenadas de Luarca. Es una teoría tradicional sin evidencia científica
sólida — se presenta como orientativa.
"""

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import ephem

TZ_MADRID = ZoneInfo("Europe/Madrid")

# Duración de los periodos (minutos a cada lado del evento lunar)
MAYOR_HALF_MIN = 60   # tránsito ± 1h → periodo de 2h
MENOR_HALF_MIN = 30   # orto/ocaso ± 30min → periodo de 1h

# Curva de actividad: amplitud de las campanas segun tipo de periodo
SIGMA_MAYOR = 55.0   # anchura (min) de la campana de un periodo mayor
SIGMA_MENOR = 35.0
BASELINE = 12        # actividad de fondo (0-100)
SOL_BOOST = 1.15     # bonus si el periodo coincide con salida/puesta de sol
SOL_OVERLAP_MIN = 45


def _to_local(edate: ephem.Date) -> datetime:
    """ephem.Date (UTC) → datetime con zona Europe/Madrid."""
    return edate.datetime().replace(tzinfo=timezone.utc).astimezone(TZ_MADRID)


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _collect_events(observer: ephem.Observer, body, method: str,
                    start_utc: datetime, end_utc: datetime) -> list[datetime]:
    """Todos los eventos (tránsitos, ortos...) de `body` entre start y end, en local."""
    events = []
    cursor = ephem.Date(start_utc)
    end = ephem.Date(end_utc)
    fn = getattr(observer, method)
    for _ in range(6):  # nunca hay más de ~4 eventos lunares en 30h
        try:
            ev = fn(body, start=cursor)
        except (ephem.AlwaysUpError, ephem.NeverUpError):
            break
        if ev > end:
            break
        events.append(_to_local(ev))
        cursor = ephem.Date(ev + ephem.minute * 5)
    return events


def _rating_dia(day_noon_utc: datetime) -> tuple[int, str]:
    """Actividad base del día (0-100) según distancia a luna nueva/llena."""
    d = ephem.Date(day_noon_utc)
    dist_new = min(abs(d - ephem.previous_new_moon(d)), abs(ephem.next_new_moon(d) - d))
    dist_full = min(abs(d - ephem.previous_full_moon(d)), abs(ephem.next_full_moon(d) - d))

    if dist_new <= 1.5:
        rating = 95    # luna nueva: máxima actividad
    elif dist_full <= 1.5:
        rating = 85    # luna llena
    elif min(dist_new, dist_full) <= 3:
        rating = 70
    elif min(dist_new, dist_full) <= 5:
        rating = 55
    else:
        rating = 40    # cerca de los cuartos: mínima

    if rating >= 85:
        label = "Muy alta"
    elif rating >= 65:
        label = "Alta"
    elif rating >= 50:
        label = "Media"
    else:
        label = "Baja"
    return rating, label


def _fase_lunar(day_noon_utc: datetime) -> dict:
    d = ephem.Date(day_noon_utc)
    moon = ephem.Moon()
    moon.compute(d)
    lunation = (d - ephem.previous_new_moon(d)) / 29.53058867
    fases = [
        (0.0625, "Luna nueva", "\U0001F311"),
        (0.1875, "Creciente", "\U0001F312"),
        (0.3125, "Cuarto creciente", "\U0001F313"),
        (0.4375, "Gibosa creciente", "\U0001F314"),
        (0.5625, "Luna llena", "\U0001F315"),
        (0.6875, "Gibosa menguante", "\U0001F316"),
        (0.8125, "Cuarto menguante", "\U0001F317"),
        (0.9375, "Menguante", "\U0001F318"),
        (1.01, "Luna nueva", "\U0001F311"),
    ]
    nombre, emoji = next((n, e) for lim, n, e in fases if lunation < lim)
    return {"nombre": nombre, "emoji": emoji, "iluminacion": round(moon.phase, 1)}


def compute_solunar(now_local: datetime, lat: float, lon: float) -> dict:
    """Actividad solunar de las próximas 24h para (lat, lon).

    La ventana empieza en la hora actual (redondeada a la hora en punto) y
    cubre 24h hacia delante. Devuelve periodos mayores/menores, rating,
    fase lunar y una curva de actividad 0-100 muestreada cada 10 min.
    Los minutos de la curva y los periodos son relativos a las 00:00 locales
    del día de `fecha` (pueden superar 1440 si caen mañana).
    """
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    ini_min = now_local.hour * 60  # ventana desde la hora en punto actual
    fin_min = ini_min + 1440
    ventana_ini = day_start + timedelta(minutes=ini_min)
    ventana_fin = day_start + timedelta(minutes=fin_min)
    # Margen de 3h a cada lado: un tránsito justo antes de la ventana sigue
    # aportando actividad al inicio de esta
    win_start = (ventana_ini - timedelta(hours=3)).astimezone(timezone.utc)
    win_end = (ventana_fin + timedelta(hours=3)).astimezone(timezone.utc)

    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.pressure = 0  # sin refracción para orto/ocaso estándar
    obs.horizon = "-0:34"

    moon = ephem.Moon()
    sun = ephem.Sun()

    transits = _collect_events(obs, moon, "next_transit", win_start, win_end)
    antitransits = _collect_events(obs, moon, "next_antitransit", win_start, win_end)
    moonrises = _collect_events(obs, moon, "next_rising", win_start, win_end)
    moonsets = _collect_events(obs, moon, "next_setting", win_start, win_end)

    sunrises = _collect_events(obs, sun, "next_rising",
                               ventana_ini.astimezone(timezone.utc),
                               ventana_fin.astimezone(timezone.utc))
    sunsets = _collect_events(obs, sun, "next_setting",
                              ventana_ini.astimezone(timezone.utc),
                              ventana_fin.astimezone(timezone.utc))
    sol_events = sunrises + sunsets

    centro_ventana_utc = (ventana_ini + timedelta(hours=12)).astimezone(timezone.utc)
    rating, rating_label = _rating_dia(centro_ventana_utc)
    fase = _fase_lunar(centro_ventana_utc)

    def _mins(dt: datetime) -> float:
        """Minutos desde las 00:00 locales de hoy (puede ser <0 o >1440)."""
        return (dt - day_start).total_seconds() / 60.0

    def _solapa_sol(dt: datetime) -> bool:
        return any(abs(_mins(dt) - _mins(s)) <= SOL_OVERLAP_MIN for s in sol_events)

    def _periodos(events: list[datetime], half_min: int, tipo: str) -> list[dict]:
        out = []
        for ev in events:
            centro = _mins(ev)
            # Solo listar periodos que tocan la ventana de 24h
            if centro + half_min < ini_min or centro - half_min > fin_min:
                continue
            out.append({
                "tipo": tipo,
                "centro_min": round(centro),
                "inicio": _hhmm(ev - timedelta(minutes=half_min)),
                "fin": _hhmm(ev + timedelta(minutes=half_min)),
                "pico": _hhmm(ev),
                "coincide_sol": _solapa_sol(ev),
            })
        return out

    mayores = _periodos(transits + antitransits, MAYOR_HALF_MIN, "mayor")
    menores = _periodos(moonrises + moonsets, MENOR_HALF_MIN, "menor")
    mayores.sort(key=lambda p: p["centro_min"])
    menores.sort(key=lambda p: p["centro_min"])

    # ─── Curva de actividad 0-100, cada 10 min ────────────────────────────────
    bumps = []
    for ev in transits + antitransits:
        amp = rating * 0.9 * (SOL_BOOST if _solapa_sol(ev) else 1.0)
        bumps.append((_mins(ev), amp, SIGMA_MAYOR))
    for ev in moonrises + moonsets:
        amp = rating * 0.55 * (SOL_BOOST if _solapa_sol(ev) else 1.0)
        bumps.append((_mins(ev), amp, SIGMA_MENOR))

    curva = []
    for m in range(ini_min, fin_min + 1, 10):
        v = BASELINE * (rating / 70.0)
        for centro, amp, sigma in bumps:
            v += amp * math.exp(-((m - centro) ** 2) / (2 * sigma ** 2))
        curva.append({"m": m, "v": round(max(0.0, min(100.0, v)))})

    sol_eventos = sorted(
        [{"tipo": "salida", "m": round(_mins(ev)), "hora": _hhmm(ev)} for ev in sunrises]
        + [{"tipo": "puesta", "m": round(_mins(ev)), "hora": _hhmm(ev)} for ev in sunsets],
        key=lambda e: e["m"],
    )

    return {
        "fecha": day_start.strftime("%Y-%m-%d"),
        "ventana": {"inicio_min": ini_min, "fin_min": fin_min},
        "rating": rating,
        "rating_label": rating_label,
        "fase": fase,
        "sol_eventos": sol_eventos,
        "mayores": mayores,
        "menores": menores,
        "curva": curva,
    }
