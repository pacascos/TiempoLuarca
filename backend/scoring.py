"""
Sistema de puntuación náutica 1-10 para Beneteau Antares 6.5.

10 = Condiciones perfectas (mar llana, sin viento, buen tiempo)
1  = Muy peligroso, no salir

Factores principales:
- Viento (peso 35%): el factor más crítico para un barco de 6.5m
- Oleaje (peso 30%): altura de ola y periodo
- Lluvia (peso 15%): probabilidad e intensidad
- Visibilidad (peso 10%): fundamental para navegación costera
- Racha máxima (peso 10%): las rachas son peligrosas en barcos pequeños
"""

from dataclasses import dataclass


@dataclass
class ScoringInput:
    viento_nudos: float | None = None
    racha_nudos: float | None = None
    ola_altura: float | None = None       # ola total combinada
    ola_periodo: float | None = None
    swell_altura: float | None = None     # mar de fondo
    swell_periodo: float | None = None
    viento_ola_altura: float | None = None  # mar de viento (chop)
    viento_ola_periodo: float | None = None
    prob_precipitacion: float | None = None
    precipitacion_mm: float | None = None
    visibilidad_m: float | None = None
    nubosidad: float | None = None       # % cobertura nubes (0=despejado, 100=cubierto)
    presion_hpa: float | None = None
    presion_trend_6h: float | None = None  # cambio en hPa últimas 6h (negativo=bajando)
    temperatura: float | None = None


@dataclass
class ScoringResult:
    score: int  # 1-10 (10=perfecto, 1=peligroso)
    score_viento: int
    score_oleaje: int
    score_lluvia: int
    score_visibilidad: int
    score_nubosidad: int
    score_presion: int
    score_racha: int
    score_temperatura: int
    label: str
    color: str
    recomendacion: str
    detalle: dict
    # Reglas que bajaron el score (caps de seguridad) — para que la explicación
    # venga de la fuente de la verdad, no se duplique en otros sitios.
    reglas_aplicadas: list = None
    score_ponderado: float = 0.0  # la suma ponderada antes de aplicar caps


# ─── Escalas individuales (10=óptimo, 1=peligroso) ───────────────────────────

def _score_viento(nudos: float | None) -> int:
    """Viento sostenido en nudos → score 10(calma)-1(temporal)."""
    if nudos is None:
        return 5
    if nudos <= 5:
        return 10
    if nudos <= 8:
        return 9
    if nudos <= 10:
        return 8
    if nudos <= 12:
        return 7
    if nudos <= 15:
        return 6
    if nudos <= 18:
        return 5
    if nudos <= 20:
        return 4
    if nudos <= 25:
        return 3
    if nudos <= 30:
        return 2
    return 1


def _score_racha(nudos: float | None) -> int:
    """Racha máxima en nudos → score 10(calma)-1(temporal)."""
    if nudos is None:
        return 5
    if nudos <= 10:
        return 10
    if nudos <= 14:
        return 9
    if nudos <= 18:
        return 8
    if nudos <= 22:
        return 7
    if nudos <= 25:
        return 6
    if nudos <= 28:
        return 5
    if nudos <= 32:
        return 4
    if nudos <= 36:
        return 3
    if nudos <= 40:
        return 2
    return 1


def _score_oleaje(inp) -> int:
    """Score de oleaje 10(llana)-1(temporal).
    Usa swell + mar de viento por separado si están disponibles.
    Para un Antares 6.5: 2m+ de swell ya es serio, chop > 0.5m ya es incómodo.
    """
    swell_h = inp.swell_altura
    swell_p = inp.swell_periodo
    chop_h = inp.viento_ola_altura
    chop_p = inp.viento_ola_periodo
    total_h = inp.ola_altura
    total_p = inp.ola_periodo

    if swell_h is not None and chop_h is not None:
        score_swell = _score_swell(swell_h, swell_p)
        score_chop = _score_chop(chop_h, chop_p)
        # El peor componente domina: chop bajo no compensa swell peligroso
        worst = min(score_swell, score_chop)
        best = max(score_swell, score_chop)
        if worst <= 2:
            # Oleaje peligroso: el componente bueno apenas influye
            return worst
        combined = worst * 0.75 + best * 0.25
        return max(1, min(10, round(combined)))

    if total_h is None:
        return 5
    return _score_ola_total(total_h, total_p)


def _score_swell(altura_m: float, periodo_s: float | None) -> int:
    """Mar de fondo (swell) para Antares 6.5.
    En el Cantábrico 0.5-0.8m es lo habitual en buen día.
    1m+ ya se nota, 1.5m+ incómodo, 2m+ no salir."""
    if altura_m <= 0.3:
        base = 10
    elif altura_m <= 0.5:
        base = 9
    elif altura_m <= 0.7:
        base = 8
    elif altura_m <= 0.9:
        base = 7
    elif altura_m <= 1.1:
        base = 6
    elif altura_m <= 1.3:
        base = 5
    elif altura_m <= 1.5:
        base = 4
    elif altura_m <= 1.8:
        base = 3
    elif altura_m <= 2.2:
        base = 2
    else:
        base = 1
    # Periodo largo solo mejora si el swell es moderado (< 2m)
    # Con 2m+ el periodo no compensa la altura para un barco de 6.5m
    if periodo_s is not None:
        if periodo_s > 12 and altura_m < 2.0:
            base = min(10, base + 1)
        elif periodo_s < 7:
            base = max(1, base - 1)
    return base


def _score_chop(altura_m: float, periodo_s: float | None) -> int:
    """Mar de viento (chop). Muy incómodo en barco pequeño.
    0.3m ya se nota, 0.7m+ peligroso."""
    if altura_m <= 0.1:
        base = 10
    elif altura_m <= 0.15:
        base = 9
    elif altura_m <= 0.25:
        base = 8
    elif altura_m <= 0.4:
        base = 7
    elif altura_m <= 0.5:
        base = 5
    elif altura_m <= 0.7:
        base = 4
    elif altura_m <= 1.0:
        base = 3
    elif altura_m <= 1.3:
        base = 2
    else:
        base = 1
    # Periodo muy corto empeora — pantocazos
    if periodo_s is not None:
        if periodo_s < 3:
            base = max(1, base - 2)
        elif periodo_s < 4:
            base = max(1, base - 1)
    return base


def _score_ola_total(altura_m: float, periodo_s: float | None) -> int:
    """Fallback cuando no hay desglose swell/chop."""
    if altura_m <= 0.2:
        base = 10
    elif altura_m <= 0.4:
        base = 9
    elif altura_m <= 0.6:
        base = 8
    elif altura_m <= 0.8:
        base = 7
    elif altura_m <= 1.0:
        base = 6
    elif altura_m <= 1.3:
        base = 5
    elif altura_m <= 1.6:
        base = 4
    elif altura_m <= 2.0:
        base = 3
    elif altura_m <= 2.5:
        base = 2
    else:
        base = 1
    if periodo_s is not None:
        if periodo_s < 5:
            base = max(1, base - 2)
        elif periodo_s < 7:
            base = max(1, base - 1)
        elif periodo_s > 11:
            base = min(10, base + 1)
    return base


def _score_temperatura(temp_c: float | None) -> int:
    """Temperatura → score de confort. En barco abierto el frío afecta.
    10=ideal, 1=hipotermia."""
    if temp_c is None:
        return 7
    if temp_c >= 22:
        return 10
    if temp_c >= 20:
        return 9
    if temp_c >= 18:
        return 8
    if temp_c >= 16:
        return 7
    if temp_c >= 14:
        return 6
    if temp_c >= 12:
        return 5
    if temp_c >= 10:
        return 4
    if temp_c >= 8:
        return 3
    if temp_c >= 5:
        return 2
    return 1


def _score_presion(trend_6h: float | None) -> int:
    """Tendencia de presion en 6h → score 10(estable/subiendo)-1(cayendo en picado).
    Lo que importa es la CAIDA rapida = borrasca acercandose."""
    if trend_6h is None:
        return 7
    if trend_6h >= 3:
        return 9   # subiendo rapido, mejorando
    if trend_6h >= 1:
        return 10  # subiendo, buen tiempo
    if trend_6h >= -1:
        return 9   # estable
    if trend_6h >= -2:
        return 7   # bajando lento
    if trend_6h >= -3:
        return 5   # bajando
    if trend_6h >= -5:
        return 3   # bajando rapido, atencion
    return 1       # desplome, borrasca inminente


def _score_nubosidad(pct: float | None) -> int:
    """Cobertura de nubes % → score 10(despejado)-1(cubierto).
    Afecta al confort y a la seguridad (visibilidad en costa)."""
    if pct is None:
        return 7
    if pct <= 10:
        return 10
    if pct <= 20:
        return 9
    if pct <= 30:
        return 8
    if pct <= 45:
        return 7
    if pct <= 55:
        return 6
    if pct <= 65:
        return 5
    if pct <= 75:
        return 4
    if pct <= 85:
        return 3
    if pct <= 95:
        return 2
    return 1


def _score_lluvia(prob: float | None, mm: float | None = None) -> int:
    """Combina probabilidad de precipitacion + intensidad en mm/h.
    Probabilidad alta + poca cantidad = llovizna (score medio).
    Probabilidad alta + mucha cantidad = lluvia fuerte (score bajo)."""
    if prob is None:
        return 8

    # Score base por probabilidad
    if prob <= 5:
        base_prob = 10
    elif prob <= 15:
        base_prob = 9
    elif prob <= 30:
        base_prob = 8
    elif prob <= 45:
        base_prob = 7
    elif prob <= 60:
        base_prob = 6
    elif prob <= 75:
        base_prob = 5
    elif prob <= 85:
        base_prob = 4
    elif prob <= 95:
        base_prob = 3
    else:
        base_prob = 2

    # Si tenemos intensidad en mm/h, ajustar
    if mm is not None and mm > 0 and prob > 30:
        if mm >= 5:
            score_mm = 1   # lluvia fuerte
        elif mm >= 2:
            score_mm = 3   # lluvia moderada
        elif mm >= 0.5:
            score_mm = 5   # lluvia ligera
        elif mm >= 0.1:
            score_mm = 7   # llovizna
        else:
            score_mm = 8   # casi nada
        # Combinar: el peor de los dos pesa mas
        return max(1, round(min(base_prob, score_mm) * 0.6 + max(base_prob, score_mm) * 0.4))

    return base_prob


def _score_visibilidad(vis_m: float | None) -> int:
    """Visibilidad en metros → score 10(clara)-1(niebla)."""
    if vis_m is None:
        return 8
    if vis_m >= 20000:
        return 10
    if vis_m >= 15000:
        return 9
    if vis_m >= 10000:
        return 8
    if vis_m >= 7000:
        return 7
    if vis_m >= 5000:
        return 6
    if vis_m >= 3000:
        return 5
    if vis_m >= 2000:
        return 4
    if vis_m >= 1000:
        return 3
    if vis_m >= 500:
        return 2
    return 1


# ─── Labels y colores (10=perfecto, 1=peligroso) ─────────────────────────────

LABELS = {
    10: ("Perfecto", "#00C853", "Condiciones ideales para navegar. A disfrutar!"),
    9:  ("Excelente", "#64DD17", "Condiciones excelentes. Mar en calma."),
    8:  ("Muy bueno", "#AEEA00", "Muy buenas condiciones. Navegacion comoda."),
    7:  ("Bueno", "#FFD600", "Buenas condiciones. Alguna ola pequena."),
    6:  ("Aceptable", "#FFAB00", "Condiciones aceptables. Navega con atencion."),
    5:  ("Regular", "#FF6D00", "Condiciones regulares. Solo si tienes experiencia."),
    4:  ("Malo", "#FF3D00", "Condiciones desfavorables. Mejor quedarse en puerto."),
    3:  ("Muy malo", "#E53935", "Condiciones muy malas. No se recomienda salir."),
    2:  ("Peligroso", "#F44336", "Condiciones peligrosas. No salir."),
    1:  ("Muy peligroso", "#EF5350", "Condiciones extremas. Prohibido navegar."),
}


# ─── Cálculo principal ───────────────────────────────────────────────────────

WEIGHTS = {
    "viento": 0.23,
    "oleaje": 0.23,
    "racha": 0.09,
    "lluvia": 0.09,
    "visibilidad": 0.07,
    "nubosidad": 0.05,
    "presion": 0.06,   # tendencia barométrica
    "temperatura": 0.06,
    "confort": 0.06,
    "estabilidad": 0.06,  # combinación presión + visibilidad (seguridad)
}


def calculate_score(inp: ScoringInput) -> ScoringResult:
    """Calcula el score compuesto 1-10 (10=perfecto, 1=peligroso)."""
    sv = _score_viento(inp.viento_nudos)
    sr = _score_racha(inp.racha_nudos)
    so = _score_oleaje(inp)
    sl = _score_lluvia(inp.prob_precipitacion, inp.precipitacion_mm)
    svis = _score_visibilidad(inp.visibilidad_m)
    snub = _score_nubosidad(inp.nubosidad)
    spres = _score_presion(inp.presion_trend_6h)
    stemp = _score_temperatura(inp.temperatura)

    confort = round((sl + snub + stemp) / 3)
    estabilidad = round((spres + svis) / 2)

    weighted = (
        sv * WEIGHTS["viento"]
        + so * WEIGHTS["oleaje"]
        + sr * WEIGHTS["racha"]
        + sl * WEIGHTS["lluvia"]
        + svis * WEIGHTS["visibilidad"]
        + snub * WEIGHTS["nubosidad"]
        + spres * WEIGHTS["presion"]
        + stemp * WEIGHTS["temperatura"]
        + confort * WEIGHTS["confort"]
        + estabilidad * WEIGHTS["estabilidad"]
    )

    score_ponderado = weighted
    score = max(1, min(10, round(weighted)))
    reglas: list[str] = []

    def cap(new_max: int, regla: str):
        nonlocal score
        if new_max < score:
            score = new_max
            reglas.append(regla)

    # Reglas de seguridad: factores críticos (viento, oleaje, rachas)
    critical = [sv, so, sr]
    count_critical_1 = sum(1 for s in critical if s <= 1)
    worst_critical = min(critical)

    # Dos o más factores críticos en 1 = temporal, score 1 sin discusión
    if count_critical_1 >= 2:
        cap(1, "2+ factores críticos (viento/oleaje/racha) en nota 1 → temporal: score 1")
    elif worst_critical <= 1:
        second_worst = sorted(critical)[1]
        if second_worst <= 3:
            cap(1, f"Un crítico en 1 y otro ≤3 → temporal claro: score 1")
        else:
            cap(2, "Un factor crítico (viento/oleaje/racha) en 1 → score limitado a 2")
    elif worst_critical <= 2:
        cap(3, "Peor crítico ≤2 → score limitado a 3")
    elif worst_critical <= 3:
        cap(4, "Peor crítico ≤3 → score limitado a 4")

    # Oleaje es especialmente importante para un barco de 6.5m
    if so <= 1:
        cap(2, "Oleaje en 1 → score limitado a 2 (mar peligroso para barco de 6.5m)")
    elif so <= 2:
        cap(3, "Oleaje ≤2 → score limitado a 3")
    elif so <= 3:
        cap(4, "Oleaje ≤3 → score limitado a 4")
    elif so <= 4:
        cap(5, "Oleaje ≤4 → score limitado a 5")
    elif so <= 5:
        cap(6, "Oleaje ≤5 → score limitado a 6")
    elif so <= 6:
        cap(7, "Oleaje ≤6 → score limitado a 7")

    # Viento y rachas
    if sv <= 1:
        cap(2, "Viento en 1 → score limitado a 2")
    elif sv <= 2:
        cap(3, "Viento ≤2 → score limitado a 3")
    if sr <= 1:
        cap(2, "Racha en 1 → score limitado a 2")
    elif sr <= 2:
        cap(3, "Racha ≤2 → score limitado a 3")
    elif sr <= 3:
        cap(4, "Racha ≤3 → score limitado a 4")

    # Visibilidad y presión
    if svis <= 2:
        cap(4, "Visibilidad ≤2 (niebla) → score limitado a 4")
    if spres <= 2:
        cap(4, "Presión en caída rápida → score limitado a 4 (borrasca)")
    elif spres <= 3:
        cap(5, "Presión bajando → score limitado a 5")

    # Lluvia muy alta limita el score (no es seguridad pero arruina la salida)
    if sl <= 2:
        cap(5, "Lluvia intensa → score limitado a 5")

    # Regla combinada: si varios factores de seguridad son malos a la vez
    # (no cuenta temperatura ni nubosidad que son confort)
    bad_count = sum(1 for s in [sv, so, sl, svis, sr] if s <= 4)
    if bad_count >= 4:
        cap(2, f"{bad_count} factores simultáneamente ≤4 → score limitado a 2")
    elif bad_count >= 3:
        cap(3, f"{bad_count} factores simultáneamente ≤4 → score limitado a 3")

    label, color, recomendacion = LABELS[score]

    return ScoringResult(
        score=score,
        score_viento=sv,
        score_oleaje=so,
        score_lluvia=sl,
        score_visibilidad=svis,
        score_nubosidad=snub,
        score_presion=spres,
        score_racha=sr,
        score_temperatura=stemp,
        label=label,
        color=color,
        recomendacion=recomendacion,
        reglas_aplicadas=reglas,
        score_ponderado=round(score_ponderado, 2),
        detalle={
            "viento_nudos": inp.viento_nudos,
            "racha_nudos": inp.racha_nudos,
            "ola_altura_m": inp.ola_altura,
            "ola_periodo_s": inp.ola_periodo,
            "swell_m": inp.swell_altura,
            "chop_m": inp.viento_ola_altura,
            "prob_precipitacion": inp.prob_precipitacion,
            "visibilidad_m": inp.visibilidad_m,
            "temperatura": inp.temperatura,
        },
    )


def score_forecast_hour(forecast_entry: dict, marine_entry: dict | None = None, presion_trend: float | None = None) -> dict:
    """Calcula el score para una hora de pronóstico combinando datos meteorológicos y marinos."""
    inp = ScoringInput(
        viento_nudos=forecast_entry.get("viento_nudos"),
        racha_nudos=forecast_entry.get("viento_racha_nudos"),
        prob_precipitacion=forecast_entry.get("prob_precipitacion"),
        precipitacion_mm=forecast_entry.get("precipitacion"),
        visibilidad_m=forecast_entry.get("visibilidad"),
        presion_hpa=forecast_entry.get("presion"),
        temperatura=forecast_entry.get("temperatura"),
        nubosidad=forecast_entry.get("nubosidad"),
        presion_trend_6h=presion_trend,
    )
    if marine_entry:
        inp.ola_altura = marine_entry.get("ola_altura")
        inp.ola_periodo = marine_entry.get("ola_periodo")
        inp.swell_altura = marine_entry.get("swell_altura")
        inp.swell_periodo = marine_entry.get("swell_periodo")
        inp.viento_ola_altura = marine_entry.get("viento_ola_altura")
        inp.viento_ola_periodo = marine_entry.get("viento_ola_periodo")

    result = calculate_score(inp)
    return {
        "score": result.score,
        "label": result.label,
        "color": result.color,
        "recomendacion": result.recomendacion,
        "scores": {
            "viento": result.score_viento,
            "oleaje": result.score_oleaje,
            "lluvia": result.score_lluvia,
            "visibilidad": result.score_visibilidad,
            "racha": result.score_racha,
            "nubosidad": result.score_nubosidad,
            "presion": result.score_presion,
            "temperatura": result.score_temperatura,
        },
        "reglas_aplicadas": result.reglas_aplicadas or [],
        "score_ponderado": result.score_ponderado,
        "detalle": result.detalle,
    }
