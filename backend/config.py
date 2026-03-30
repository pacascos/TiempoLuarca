import os
from dotenv import load_dotenv

load_dotenv()

AEMET_API_KEY = os.getenv("AEMET_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/tiempoluarca.db")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
ROOT_PATH = os.getenv("ROOT_PATH", "")  # ej: "/tiempo" si se sirve bajo subpath

# Coordenadas de Luarca
LUARCA_LAT = 43.5414
LUARCA_LON = -6.5361

# AEMET
AEMET_BASE_URL = "https://opendata.aemet.es/opendata/api"
AEMET_STATION_BUSTO = "1283U"
AEMET_MUNICIPIO_VALDES = "33074"  # Valdés
AEMET_COSTA_CAN1 = "42"  # Costa asturiana occidental
AEMET_PLAYA_LUARCA = "3303407"

# IHM Mareas
IHM_BASE_URL = "https://ideihm.covam.es/api-ihm/getmarea"
IHM_STATION_NAVIA = 9
IHM_STATION_CUDILLERO = 8

# Open-Meteo Marine
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
