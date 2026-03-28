# TiempoLuarca

Aplicacion web de meteorologia maritima para Luarca (Asturias), orientada a la navegacion con un Beneteau Antares 6.5 en un radio de 12 millas nauticas.

## Que hace

- **Score 1-10** de condiciones de navegacion (10=perfecto, 1=peligroso)
- Datos en tiempo real de **viento, oleaje (swell + mar de viento), lluvia, temperatura, mareas**
- Pronostico **hora a hora** con colores por variable
- **Resumen** de hoy y proximos 3 dias con mejor ventana horaria
- **Graficas expandibles** de viento, oleaje, lluvia, temperatura (48h)
- **Grafica de mareas** con curva sinusoidal y marcador de hora actual
- **Mapas interactivos** de Windy (viento, olas, lluvia, nubes, satelite, radar)
- **Sistema de feedback** para registrar tu experiencia real y afinar el scoring
- **Historicos** guardados en SQLite
- Cache inteligente por fuente con TTL independiente

## Fuentes de datos

| Fuente | Datos | TTL cache |
|--------|-------|-----------|
| AEMET OpenData (Cabo Busto) | Observacion actual: viento, temp, presion, visibilidad | 30 min |
| AEMET OpenData (Valdes) | Prediccion municipal horaria 48h | 2h |
| Open-Meteo Forecast | Pronostico meteo 7 dias: viento, lluvia, temp, visibilidad | 1h |
| Open-Meteo Marine | Oleaje 7 dias: ola total, swell, mar de viento | 1h |
| IHM Mareas | Pleamares/bajamares Navia y Aviles | 12h |

## Requisitos

- Python 3.11+
- Conexion a internet (para las APIs)

## Instalacion

```bash
# 1. Clonar o copiar el proyecto
cd /ruta/donde/quieras
# (copiar la carpeta TiempoLuarca aqui)

# 2. Crear entorno virtual e instalar dependencias
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configurar la API key de AEMET
# Crear archivo .env en la raiz del proyecto:
cat > .env << 'EOF'
AEMET_API_KEY=tu_api_key_de_aemet_aqui
DATABASE_PATH=data/tiempoluarca.db
HOST=0.0.0.0
PORT=8000
EOF

# Si no tienes API key de AEMET, registrate gratis en:
# https://opendata.aemet.es/centrodedescargas/obtencionAPIKey

# 4. Arrancar
python run.py
```

La aplicacion estara disponible en **http://localhost:8000**

## Estructura

```
TiempoLuarca/
├── .env                    # API keys (NO incluido, crear manualmente)
├── requirements.txt        # Dependencias Python
├── run.py                  # Punto de entrada
├── backend/
│   ├── app.py              # API REST (FastAPI)
│   ├── config.py           # Configuracion y constantes
│   ├── data_sources.py     # Clientes para AEMET, IHM, Open-Meteo
│   ├── database.py         # SQLite: historicos y feedback
│   └── scoring.py          # Algoritmo de puntuacion 1-10
├── frontend/
│   ├── index.html          # Interfaz web
│   ├── styles.css          # Estilos (glassmorphism, responsive)
│   └── app.js              # Logica del frontend (graficas canvas, etc)
└── data/
    └── tiempoluarca.db     # Base de datos SQLite (se crea automaticamente)
```

## API endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/` | Interfaz web |
| GET | `/api/current` | Datos actuales + score |
| GET | `/api/forecast` | Pronostico horario 7 dias con scores |
| GET | `/api/summary` | Resumen de proximos 4 dias |
| GET | `/api/tides` | Mareas Navia + Aviles |
| GET | `/api/feedback` | Listar feedback historico |
| POST | `/api/feedback` | Guardar feedback |
| POST | `/api/refresh` | Forzar recarga de todas las fuentes |
| GET | `/api/cache-status` | Estado del cache por fuente |

## Notas

- El scoring distingue **mar de fondo (swell)** de **mar de viento (chop)** — el chop es mucho mas incomodo en barco pequeno
- La temperatura afecta al score (10C en barco abierto es frio)
- Las reglas de seguridad limitan el score maximo cuando oleaje o viento son malos
- Los datos se refrescan automaticamente con TTL por fuente (no todas a la vez)
- Si AEMET falla, usa Open-Meteo como fallback
