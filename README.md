# TiempoLuarca

Aplicacion web de meteorologia maritima para Luarca (Asturias), orientada a la navegacion con un Beneteau Antares 6.5 en un radio de 12 millas nauticas.

## Que hace

- **Score 1-10** de condiciones de navegacion (10=perfecto, 1=peligroso), basado en las proximas 5 horas con indicador de tendencia (mejorando/estable/empeorando)
- **Barba de viento meteorologica** + emoji del cielo en el indicador principal
- Datos en tiempo real de **viento, oleaje (swell + mar de viento), lluvia, temperatura, visibilidad, nubosidad, presion atmosferica (con tendencia barometrica), temperatura del agua**
- **Alertas costeras** de AEMET (avisos amarillo/naranja/rojo) con banner visual
- Pronostico **hora a hora** con colores por variable (horas nocturnas agrupadas)
- **Resumen** de hoy y proximos 3 dias con mejor ventana horaria y colores
- **Prevision extendida 16 dias** en formato calendario (Lun-Dom) con score orientativo
- **Graficas expandibles** de viento, oleaje (con periodos), lluvia, visibilidad, nubosidad, temperatura y presion (48h) con eje secundario
- **Grafica de mareas** con curva sinusoidal, marcador de hora actual y extrapolacion
- **Fase lunar** con disco, iluminacion y proximas fases
- **Mapas interactivos** de Windy (viento, olas, lluvia, nubes, satelite, radar) y Puertos del Estado (oleaje, viento, temp agua, corrientes, nivel del mar) — colapsables con lazy-load
- **Webcam de Luarca** en directo (colapsable)
- **Sistema de feedback** para registrar tu experiencia real y afinar el scoring
- **Historicos horarios** con 26 campos guardados en SQLite
- **Boton de ayuda** (?) que explica como se calcula el score
- Cambio de unidades **nudos/km/h** con persistencia en localStorage
- Cache inteligente por fuente con TTL independiente
- Fallback automatico de AEMET a Open-Meteo
- Lluvia prioriza AEMET Valdes (mas fiable localmente) sobre Open-Meteo
- Soporte de deploy bajo subpath (ej: /tiempo/)

## Fuentes de datos

| Fuente | Datos | TTL cache |
|--------|-------|-----------|
| AEMET Cabo Busto (1283U) | Observacion actual: viento, temp, presion, humedad, visibilidad | 30 min |
| AEMET Valdes (33074) | Prediccion municipal horaria 48h (lluvia prioritaria) | 2h |
| AEMET Costera/Playa | Prediccion costera y playa | 3h |
| AEMET Alertas (area 63) | Avisos costeros CAP XML (amarillo/naranja/rojo) | 30 min |
| Open-Meteo Forecast | Pronostico meteo 7-16 dias: viento, lluvia, temp, visibilidad, nubosidad, presion | 1h |
| Open-Meteo Marine | Oleaje 7-16 dias: ola total, swell, chop, periodos, temp agua (SST) | 1h |
| IHM Mareas | Pleamares/bajamares Navia y Aviles (horas UTC convertidas a local) | 12h |
| Windy (embed) | Mapas interactivos: viento, olas, lluvia, nubes, satelite, radar | - |
| Puertos del Estado (embed) | Mapas: oleaje, viento, temp agua, corrientes, nivel del mar | - |
| rtsp.me (embed) | Webcam Luarca en directo | - |

## Scoring

Score 1-10 para las **proximas 5 horas** (min entre score actual y media 5h). Combina:

| Factor | Peso | Descripcion |
|--------|------|-------------|
| Viento | 23% | Velocidad sostenida en nudos |
| Oleaje | 23% | Combina swell (40%) + chop (60%), el chop penaliza mas |
| Racha | 9% | Rachas maximas |
| Lluvia | 9% | Probabilidad AEMET + intensidad mm/h Open-Meteo |
| Visibilidad | 7% | Metros de visibilidad |
| Presion | 6% | Tendencia barometrica 6h (caida rapida = borrasca) |
| Nubosidad | 5% | Cobertura de nubes % |
| Temperatura | 6% | Temp aire (confort, no seguridad) |
| Confort | 6% | Media de lluvia + nubes + temp |
| Estabilidad | 6% | Media de presion + visibilidad |

Reglas de seguridad:
- Oleaje o viento <= 2 → max 4
- Oleaje o viento <= 3 → max 5
- Oleaje <= 4 o <= 5 → max 5 o 6
- Visibilidad <= 2 → max 4
- Presion cayendo rapido → max 5
- Lluvia score <= 2 → max 5
- 3+ factores de seguridad malos → max 4
- 4+ factores → max 3

## Requisitos

- Python 3.11+
- Conexion a internet (para las APIs)
- Servidor en timezone Europe/Madrid (para conversion de horas IHM)

## Instalacion

```bash
# 1. Clonar
git clone https://github.com/pacascos/TiempoLuarca.git
cd TiempoLuarca

# 2. Entorno virtual
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configurar API key de AEMET
cat > .env << 'EOF'
AEMET_API_KEY=tu_api_key_aqui
DATABASE_PATH=data/tiempoluarca.db
HOST=0.0.0.0
PORT=8000
ROOT_PATH=
EOF

# API key gratuita en: https://opendata.aemet.es/centrodedescargas/obtencionAPIKey

# 4. Arrancar
python run.py
```

Disponible en **http://localhost:8000**

Para deploy bajo subpath (ej: `/tiempo/`), poner `ROOT_PATH=/tiempo` en `.env`.

## Estructura

```
TiempoLuarca/
├── .env                    # API keys (NO incluido, crear manualmente)
├── requirements.txt        # Dependencias Python
├── run.py                  # Punto de entrada
├── backend/
│   ├── app.py              # API REST (FastAPI) + cache + scoring endpoints
│   ├── config.py           # Configuracion y constantes
│   ├── data_sources.py     # Clientes: AEMET, IHM, Open-Meteo, alertas CAP
│   ├── database.py         # SQLite: historicos horarios, snapshots, feedback
│   └── scoring.py          # Algoritmo de puntuacion 1-10 con reglas de seguridad
├── frontend/
│   ├── index.html          # Interfaz web (glassmorphism, responsive)
│   ├── styles.css          # Estilos con CSS variables, animaciones
│   └── app.js              # Logica: graficas canvas, mareas, luna, mapas, scoring visual
└── data/
    └── tiempoluarca.db     # Base de datos SQLite (se crea automaticamente)
```

## API endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/` | Interfaz web |
| GET | `/api/current` | Datos actuales + score 5h + tendencia + alertas |
| GET | `/api/forecast` | Pronostico horario 7 dias con scores (lluvia AEMET priorizada) |
| GET | `/api/summary` | Resumen proximos 4 dias con mejor ventana |
| GET | `/api/extended` | Prevision extendida 16 dias con score diario |
| GET | `/api/tides` | Mareas Navia + Aviles (horas locales) |
| GET | `/api/feedback` | Listar feedback historico |
| POST | `/api/feedback` | Guardar feedback |
| POST | `/api/refresh` | Forzar recarga de todas las fuentes |
| GET | `/api/cache-status` | Estado del cache por fuente |
