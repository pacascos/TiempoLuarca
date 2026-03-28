# Weather & Maritime Data Sources for Luarca, Asturias
## Research for Small Recreational Boat Application (12nm range)

**Location:** Luarca (Valdés), Asturias, Spain
**Coordinates:** 43.5449 N, 6.5367 W
**Date of research:** 2026-03-28

---

## 1. AEMET OpenData API (Spanish National Weather Service)

### Overview
AEMET OpenData is the official REST API of Spain's national meteorological agency. It is **the single most important source** for this application because it provides local weather observations, municipality forecasts, coastal maritime forecasts, and beach forecasts - all directly relevant to Luarca.

### API Access
- **Base URL:** `https://opendata.aemet.es/opendata`
- **Swagger UI / Docs:** https://opendata.aemet.es/dist/index.html
- **API Key Registration:** https://opendata.aemet.es/centrodedescargas/obtencionAPIKey
  - Free registration with email
  - You receive a confirmation email, then a second email with the API key
  - Key is valid for 3 months (renewable)
- **Authentication:** API key passed as query parameter `?api_key=YOUR_KEY`
- **Rate limit:** 50 requests per minute
- **Cost:** Completely free
- **Data format:** JSON (two-step retrieval: first call returns a URL, second call fetches actual data)

### Key Endpoints for Luarca

#### a) Cabo Busto Weather Station (Real-Time Observations)
- **Station ID (idema):** `1283U`
- **Station name:** Cabo Busto
- **Location:** On the coast west of Luarca, within Valdés municipality
- **Endpoint:** `GET /api/observacion/convencional/datos/estacion/1283U`
- **Data available:** Hourly observations (last 12 hours):
  - Wind speed (`vv`) and direction (`dv`)
  - Wind gust (`vmax`)
  - Air temperature (`ta`), min/max
  - Relative humidity (`hr`)
  - Atmospheric pressure (`pres`)
  - Precipitation (`prec`)
  - Visibility
- **Update frequency:** Hourly
- **Web view:** https://www.aemet.es/en/eltiempo/observacion/ultimosdatos?k=ast&l=1283U
- **CRITICAL VALUE:** This is the closest automated weather station to Luarca. Located on Cabo Busto headland, it gives excellent coastal wind readings.

#### b) Municipality Forecast (Valdés/Luarca)
- **Municipality code:** `33034`
- **Daily forecast (7 days):** `GET /api/prediccion/especifica/municipio/diaria/33034`
- **Hourly forecast (48h):** `GET /api/prediccion/especifica/municipio/horaria/33034`
- **Data:** Temperature, wind, rain probability, sky state, humidity, UV index
- **Web view:** https://www.aemet.es/en/eltiempo/prediccion/municipios/valdes-luarca-id33034

#### c) Coastal Maritime Forecast (Cantabrian Coast)
- **Area code:** `can1` (Costa de Asturias, Cantabria y País Vasco)
- **Endpoint:** `GET /api/prediccion/maritima/costera/costa/can1`
- **Data:** Text-based forecast including:
  - Wind force and direction (Beaufort scale)
  - Sea state (Douglas scale)
  - Wave height
  - Visibility
  - Weather phenomena
- **Forecast range:** 24-hour text, 48-hour warnings, 5-day maps
- **Update:** Twice daily
- **Web view:** https://www.aemet.es/en/eltiempo/prediccion/maritima?opc1=0&opc3=0&area=can1

#### d) High Sea Maritime Forecast
- **Endpoint:** `GET /api/prediccion/maritima/altamar/area/{area}`
- **Relevant area:** Cantábrico (code to discover via API)
- **Data:** Open sea conditions for vessels going beyond coastal waters

#### e) Beach Forecasts
- **Luarca beaches:**
  - Primera y Segunda de Luarca: code `3303407`
  - Otur: code `3303402`
- **Endpoint:** `GET /api/prediccion/especifica/playa/3303407`
- **Data:** Sky state, temperature, wind, UV index, wave height, water temperature
- **Web view:** https://www.aemet.es/en/eltiempo/prediccion/playas/primera-y-segunda-de-luarca-3303407

### Pros
- Official Spanish government source - most authoritative
- FREE with no commercial restrictions
- Cabo Busto station (1283U) is extremely local to Luarca
- Covers weather, maritime, and beach forecasts
- Hourly observations + 48h hourly forecasts
- Good coverage of all basic weather parameters

### Cons
- Two-step data retrieval (adds latency and complexity)
- Maritime forecast is text-based (requires NLP parsing for structured data)
- Rate limited to 50 req/min
- API key expires every 3 months
- No direct wave model data (heights are in text forecasts)
- No sea surface temperature in observation data from Cabo Busto

---

## 2. Puertos del Estado (Spanish Port Authority)

### Overview
Puertos del Estado operates Spain's oceanographic monitoring and prediction infrastructure. They maintain buoy networks, tide gauges, HF radars, and run wave/circulation forecast models. This is **the primary source for wave, tide, and sea state data**.

### Monitoring Networks

#### a) REDEXT (Deep Water Buoy Network)
- **Nearest buoy:** Cabo Peñas
  - Depth: 615m
  - Location: Between Cudillero and Avilés (~40km east of Luarca)
  - **Data:** Significant wave height, peak period, mean direction, sea temperature, wind speed/direction, atmospheric pressure
  - Update: Hourly via satellite
- **Portus URL:** https://portus.puertos.es

#### b) REDCOS (Coastal Buoy Network)
- Located near ports at depths under 100m
- Stations near Asturias include Gijón area
- Provides coastal wave measurements

#### c) REDMAR (Tide Gauge Network)
- **Nearest stations with tide gauges:**
  - Avilés (San Juan de Nieva) - ~50km east
  - Gijón - ~95km east
- 42 stations across Spanish ports
- Radar sensors on docks
- Real-time sea level measurements + wave agitation
- 20-minute update interval

#### d) REDRAD (HF Radar Network)
- CODAR technology for surface currents and waves
- No station confirmed near Luarca area

### Prediction Models

#### a) Wave Forecasts via THREDDS/OpenDAP
- **Main catalog:** http://opendap.puertos.es/thredds/catalog.html
- **Cantabrian regional waves:** http://opendap.puertos.es/thredds/catalog/wave_regional_can/catalog.html
- **Asturias coastal waves:** `/thredds/catalog/wave_coast_s00/catalog.html`
- **Avilés coastal waves:** `/thredds/catalog/wave_coast_s07/catalog.html`
- **Gijón coastal waves:** `/thredds/catalog/wave_coast_s01/catalog.html`
- **Port-scale forecasts:** Avilés (`wave_local_a07`), Gijón (`wave_local_a01`)
- **Format:** NetCDF via OpenDAP, OGC WMS, HTTP
- **Forecast range:** 72 hours (3 days), updated daily

#### b) HARMONIE Atmospheric Model (1km resolution!)
- **Gijón domain:** `/thredds/catalog/harmonie1k_gijon/catalog.html`
- **Avilés domain:** `/thredds/catalog/harmonie1k_aviles/catalog.html`
- **Resolution:** 1km - extremely high resolution for wind forecasts
- This is a major asset for accurate local wind prediction

#### c) SAMOA Model
- High-resolution coastal forecasting system
- ROMS-based ocean model: ~350m coastal resolution, ~70m port resolution
- 72-hour forecasts of currents, temperature, salinity
- Updated daily with hourly resolution
- Covers Spanish port areas

#### d) NIVMAR (Sea Level Model)
- Storm surge predictions
- `/thredds/catalog/nivmar_large_nivmar/catalog.html`

### Data Access Methods
1. **Portus web portal:** https://portus.puertos.es - real-time data, predictions, historical
2. **Portuscopia:** https://portuscopia.puertos.es - bulk data downloads, scripted recurring downloads
3. **Environmental Dashboard:** https://cma.puertos.es
4. **THREDDS/OpenDAP:** http://opendap.puertos.es/thredds/catalog.html - programmatic NetCDF access
5. **Imar mobile app:** iOS and Android
6. **No formal REST API** - data access is through THREDDS/OpenDAP or web portals

### Pros
- The most comprehensive source for marine/oceanographic data in Spain
- Real buoy observations (Cabo Peñas) for validation
- HARMONIE 1km atmospheric model - exceptional wind resolution
- High-resolution wave predictions for Asturias coast
- SAMOA model for ports/coastal areas
- Real tide gauge data
- Free to use
- THREDDS/OpenDAP allows programmatic access

### Cons
- No simple REST API (must use THREDDS/OpenDAP or scrape Portus)
- Nearest deep-water buoy (Cabo Peñas) is ~40km from Luarca
- No tide gauge in Luarca itself (nearest: Avilés)
- Data license restricts redistribution to third parties
- NetCDF format requires specialized parsing libraries
- Documentation is fragmented across multiple portals

---

## 3. Open-Meteo (Free Weather API)

### Overview
Open-Meteo is a free, open-source weather API that aggregates data from multiple national weather services. It offers a dedicated **Marine Weather API** that provides wave and ocean data globally.

### Marine Weather API
- **Base URL:** `https://marine-api.open-meteo.com/v1/marine`
- **Example call:** `?latitude=43.54&longitude=-6.54&hourly=wave_height,wave_direction,wave_period,swell_wave_height,sea_surface_temperature`

### Available Marine Variables
| Variable | Description |
|----------|-------------|
| `wave_height` | Significant wave height (m) |
| `wave_direction` | Wave direction (degrees) |
| `wave_period` | Wave period (s) |
| `wave_peak_period` | Peak wave period (s) |
| `wind_wave_height` | Wind-driven wave height |
| `wind_wave_direction` | Wind wave direction |
| `wind_wave_period` | Wind wave period |
| `swell_wave_height` | Swell height |
| `swell_wave_direction` | Swell direction |
| `swell_wave_period` | Swell period |
| `ocean_current_velocity` | Current speed |
| `ocean_current_direction` | Current direction |
| `sea_surface_temperature` | SST |
| `sea_level_height_msl` | Sea level height |

### Wave Models Available
| Model | Resolution | Temporal | Update | Notes |
|-------|-----------|----------|--------|-------|
| **DWD EWAM** | 0.05° (~5km) | Hourly | Every 12h | **Best for Europe** |
| MeteoFrance MFWAM | 0.08° (~8km) | 3-hourly | Every 12h | Good backup |
| ECMWF WAM | 9km | Hourly | Every 6h | Global model |
| GFS Wave 0.25° | ~25km | Hourly | Every 6h | NOAA model |
| DWD GWAM | ~25km | Hourly | Every 12h | Global DWD |

### Standard Weather API (for non-marine variables)
- **Base URL:** `https://api.open-meteo.com/v1/forecast`
- Wind, temperature, precipitation, pressure, humidity, visibility, cloud cover
- Multiple models: ECMWF, GFS, ICON, ARPEGE, etc.
- Hourly data up to 16 days

### Pricing
- **Free for non-commercial use** (no API key required)
- **Commercial use:** Paid plans, requires API key
- No strict rate limits documented for free tier

### Pros
- Extremely easy to integrate - simple REST API, JSON response
- No API key needed for non-commercial use
- Comprehensive marine variables (wave, swell, SST, currents)
- Multiple models to choose from
- DWD EWAM provides 5km resolution for Europe
- Combines atmospheric + marine data
- Fast, reliable infrastructure
- Up to 16-day forecasts

### Cons
- **"Limited accuracy in coastal areas"** - their own documentation warns about this
- No real-time observations (forecast-only)
- 5km resolution is coarse for coastal navigation
- Tides/currents computed at 0.08° resolution with "limited accuracy"
- No Spanish-specific data (no AEMET integration)
- Not designed for coastal/port applications
- Attribution required

---

## 4. StormGlass API

### Overview
StormGlass is a commercial marine weather API that aggregates data from multiple global weather models and national services, providing a unified interface.

### API Details
- **Base URL:** `https://api.stormglass.io/v2`
- **Docs:** https://docs.stormglass.io
- **Authentication:** API key in header `Authorization: YOUR_KEY`
- **Response format:** JSON
- **Forecast range:** Up to 10 days

### Data Sources Aggregated
- ECMWF (European Centre)
- NOAA GFS
- DWD ICON
- UK Met Office
- Met.no (Norwegian)
- FMI (Finnish)
- Meteo France
- ECMWF AIFS (AI model)
- NOAA AIGFS (AI model)
- **"sg" source:** StormGlass AI auto-selection of best model

### Available Parameters
**Atmospheric:**
- Air temperature, pressure, humidity
- Wind speed, direction, gust
- Precipitation, cloud cover
- UV index, visibility, solar radiance

**Marine:**
- Wave height, direction, period
- Swell height, direction, period
- Secondary swell
- Wind wave height/direction/period
- Ocean current speed/direction
- Water temperature
- Ice cover/thickness

**Tides:**
- Tide extremes (high/low)
- Sea level

**Bio (for environmental apps):**
- Chlorophyll, salinity, pH, oxygen

### Pricing (as of 2025/2026)
| Plan | Cost | Requests/Day | Commercial |
|------|------|-------------|------------|
| Free | EUR 0 | 10 | No |
| Small | EUR 19/mo | 500 | No support |
| Medium | EUR 49/mo | 5,000 | Yes |
| Large | EUR 129/mo | 25,000 | Yes |
| Enterprise | Custom | Custom | Yes |

10% discount for annual billing.

### Pros
- Very comprehensive - aggregates many models into one API
- Clean REST API, easy to integrate
- Includes tide data
- AI-powered source selection
- Up to 10-day forecasts
- Historical data available (ERA5)
- Global coverage

### Cons
- **Free tier is nearly useless:** 10 requests/day, non-commercial only
- Paid plans needed for any real application (minimum EUR 19/mo)
- EUR 49/mo minimum for commercial use
- No hyper-local data (uses global/European models, not AEMET)
- Resolution depends on underlying models (~10-25km for most)
- Adds a middleman layer - data is not more accurate than going to sources directly
- No specific Cantabrian coast optimization

---

## 5. Windguru

### Overview
Windguru is a popular wind/wave forecast site used by surfers, sailors, and kitesurfers. It has spot-specific forecasts but **does NOT offer a public forecast API**.

### Luarca Spot
- **Spot ID:** 100034
- **URL:** https://www.windguru.cz/100034
- **Puerto de Luarca spot ID:** 160831

### Other nearby spots
- Navia: https://www.windguru.cz/48712
- Asturias general: https://www.windguru.cz/150379

### API Situation
- **Station JSON API** exists but is ONLY for uploading/reading data from physical weather stations you own
  - URL: `https://www.windguru.cz/int/wgsapi.php`
  - Requires station authentication (MAC/ID + password)
  - Provides: wind_avg, wind_max, wind_min, wind_direction, temperature, humidity
  - This is NOT a forecast API
- **Widget embedding** available for website integration
  - URL: https://www.windguru.cz/help.php?sec=distr
  - Embeds an iframe with forecast display
- **No official forecast data API** - forecast data is not exposed via API
- **Scraping** is technically possible (libraries exist on GitHub) but:
  - Violates terms of service
  - Data is obfuscated (encrypted JavaScript)
  - Unreliable long-term
  - Legal risk

### Pros
- Very popular with sailors/water sports community
- Good spot-specific forecasts
- Widget embedding possible for display

### Cons
- **No forecast API** - cannot programmatically access forecast data
- Would need to scrape (risky, unreliable, potentially illegal)
- Station API only works for own physical stations
- Not suitable for backend integration

---

## 6. Copernicus Marine Service (CMEMS)

### Overview
The EU's Copernicus Marine Service provides high-quality oceanographic data products. The **IBI (Iberian-Biscay-Irish) region** products are directly relevant to Luarca.

### Key Product for Luarca
**IBI Wave Analysis and Forecast**
- **Product ID:** `IBI_ANALYSISFORECAST_WAV_005_005`
- **Title:** "Atlantic-Iberian Biscay Irish- Ocean Wave Analysis and Forecast"
- **Resolution:** ~0.0278° (~3km) - very good for a regional model
- **Variables:** Significant wave height, peak period, mean direction, wind waves, swell components
- **Temporal:** Hourly
- **Forecast range:** Multiple days
- **Geographic coverage:** -19° to 5° longitude, 26° to 56° latitude (covers entire Bay of Biscay)

### Other Relevant Products
- IBI physical analysis/forecast (currents, SST, salinity)
- IBI sea level forecast
- Global wave products for longer-range forecasts

### Data Access
- **Registration:** Free at https://marine.copernicus.eu (create account)
- **Python Toolbox:** `pip install copernicusmarine`
  ```python
  import copernicusmarine
  copernicusmarine.subset(
      dataset_id="cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i",
      variables=["VHM0", "VTPK", "VMDR"],
      minimum_longitude=-7.0,
      maximum_longitude=-6.0,
      minimum_latitude=43.0,
      maximum_latitude=44.0,
      start_datetime="2026-03-28",
      end_datetime="2026-03-31"
  )
  ```
- **Formats:** NetCDF, Zarr (cloud-optimized)
- **Access methods:** Python API, CLI, WMS, OpenDAP

### Pros
- Very high quality IBI wave model (~3km resolution)
- Free, EU-funded service
- Professional-grade data used by operational services
- Python toolbox makes integration straightforward
- Includes wave, current, SST, salinity
- Long historical record for climatology

### Cons
- Not a simple REST/JSON API - requires Python toolbox or NetCDF parsing
- Data can be delayed (not real-time observations)
- Model data only (no in-situ observations)
- Requires understanding of oceanographic data formats
- Overkill for a simple app if you just need basic conditions
- API has learning curve
- 3km resolution still may miss local coastal effects near Luarca port

---

## 7. IHM Tide Predictions (Instituto Hidrográfico de la Marina)

### Overview
The IHM (Spanish Navy Hydrographic Institute) publishes the official "Anuario de Mareas" (tide yearbook) and provides an API for tide predictions at Spanish ports. This is **the official and most authoritative source for tide data**.

### API Details
- **Base URL:** `http://ideihm.covam.es/api-ihm/getmarea?`
- **Documentation:** https://ideihm.covam.es/ayuda_api_mareas.html
- **Portal:** https://ideihm.covam.es/portal/en/tidal-api/
- **Cost:** Free, no API key required
- **Format:** JSON, XML, TXT, or graphical (GRA)

### Endpoints

#### Get Station List
```
http://ideihm.covam.es/api-ihm/getmarea?request=getlist&format=json
```

#### Get Tide Prediction for a Port
```
http://ideihm.covam.es/api-ihm/getmarea?request=gettide&id={ID}&format=json&date=YYYYMMDD
```

### Nearest Stations to Luarca

| ID | Port | Latitude | Longitude | Distance from Luarca |
|----|------|----------|-----------|---------------------|
| **8** | **Cudillero** | 43.567 | -6.150 | **~25km east** |
| **9** | **Navia** | 43.542 | -6.725 | **~15km west** |
| 10 | Tapia | 43.572 | -6.945 | ~30km west |
| 7 | Avilés (San Juan de Nieva) | 43.592 | -5.930 | ~45km east |
| 6 | Gijón | 43.558 | -5.698 | ~65km east |

**IMPORTANT: Luarca is NOT in the IHM station list.** The nearest stations are:
- **Navia (ID 9)** - ~15km west - best option
- **Cudillero (ID 8)** - ~25km east

For a recreational boat app, interpolation between Navia and Cudillero would give reasonable results for Luarca. The tidal range on this coast is relatively uniform (mesotidal, ~3-4m spring tides).

### Parameters
| Parameter | Values | Description |
|-----------|--------|-------------|
| REQUEST | getlist, gettide | Request type |
| ID | Integer | Port numeric ID |
| PORT | String | Port short name |
| FORMAT | json, xml, txt, gra | Output format |
| DATE | YYYYMMDD | Specific date |
| MONTH | YYYYMM | Full month data |
| TIME | 1H, 30min, 5min | Prediction interval |

### Example API Call
```
http://ideihm.covam.es/api-ihm/getmarea?request=gettide&id=9&format=json&date=20260328
```
(Gets today's tide for Navia)

### Pros
- Official, authoritative tide predictions
- Free, no authentication required
- Simple REST API with JSON support
- Multiple time resolutions (down to 5-minute intervals)
- Both daily and monthly queries
- Navia station is reasonably close to Luarca

### Cons
- Luarca itself is not a reference station
- HTTP only (not HTTPS) - security concern
- Predictions only (astronomical tides), no storm surge adjustments
- Limited to tides - no other oceanographic data
- No real-time tide observations (for that, use Puertos del Estado REDMAR)

---

## 8. MeteoGalicia / MeteoSIX API

### Overview
MeteoGalicia is Galicia's regional weather service. While Luarca is in Asturias (not Galicia), MeteoGalicia's MeteoSIX API covers the broader region including the Cantabrian coast, and their oceanographic models extend beyond Galician waters.

### API Details
- **Base URL:** `https://servizos.meteogalicia.es/apiv4/`
- **Documentation:** https://www.meteogalicia.gal/datosred/infoweb/meteo/proxectos/meteosix/API_MeteoSIX_v4_es.pdf
- **API Key:** Required - obtained by emailing with subject "Solicitud de clave"
- **Format:** JSON/GeoJSON
- **Methods:** HTTP GET and POST

### Available Variables
**Atmospheric:**
- Sky condition, temperature
- Wind speed and direction
- Snow level, relative humidity
- Precipitation, cloud coverage
- Sea level pressure

**Oceanographic:**
- Wave height, wave period, wave direction
- Water temperature
- Salinity

**Other:**
- Tide predictions
- Sunrise/sunset times

### Geographic Coverage
- Primarily Galicia but extends to cover SW Europe and coast
- Over 29,500 towns and 820 beaches searchable
- Cantabrian coast maritime forecast available at: https://www.meteogalicia.gal/web/predicion/maritima/1
- **NOTE:** Coverage for Asturias may be limited compared to Galicia proper

### Pros
- Free API with good documentation
- Includes both atmospheric and oceanographic variables
- JSON/GeoJSON format - easy to parse
- Maritime forecasts extend to Cantabrian coast
- Higher resolution models for NW Iberia than global models

### Cons
- Luarca is outside their primary coverage area (Galicia)
- API key requires manual email request
- Documentation in Spanish/Galician
- May have lower resolution/accuracy for Asturias vs Galicia
- Less support for non-Galician locations
- Could be considered secondary to AEMET for Asturias

---

## Summary: Recommended Data Source Strategy

### Primary Sources (Must Integrate)

| Data Need | Best Source | Backup Source |
|-----------|-----------|---------------|
| **Current wind** | AEMET Cabo Busto (1283U) | Open-Meteo |
| **Wind forecast** | AEMET municipality (33034) | Open-Meteo / PdE HARMONIE |
| **Wave height/period** | Open-Meteo Marine API | CMEMS IBI / PdE THREDDS |
| **Swell data** | Open-Meteo Marine API | CMEMS IBI |
| **Tides** | IHM API (Navia ID:9) | StormGlass |
| **Rain forecast** | AEMET municipality (33034) | Open-Meteo |
| **Air temperature** | AEMET Cabo Busto (1283U) | Open-Meteo |
| **Sea temperature** | Open-Meteo (SST) | PdE Cabo Peñas buoy |
| **Pressure** | AEMET Cabo Busto (1283U) | Open-Meteo |
| **Visibility** | AEMET maritime forecast | StormGlass |
| **Maritime text forecast** | AEMET costera (can1) | MeteoGalicia |

### Recommended Architecture

**Tier 1 - Core (Free, must have):**
1. **AEMET OpenData** - Local observations (Cabo Busto), municipality forecasts, maritime text forecasts, beach forecasts
2. **IHM Tide API** - Authoritative tide predictions (Navia + Cudillero stations)
3. **Open-Meteo Marine API** - Wave/swell forecasts, SST, easy JSON integration

**Tier 2 - Enhanced (Free, worth adding):**
4. **Puertos del Estado THREDDS** - High-res wave models for Asturias coast, HARMONIE 1km wind model, Cabo Peñas buoy real-time data
5. **CMEMS IBI** - 3km wave model for the region, professional-grade data

**Tier 3 - Optional (Paid or limited):**
6. **StormGlass** - Nice unified API but expensive; only worth it if you need a single-API solution
7. **MeteoGalicia** - Supplementary, especially for western Asturias near Galician border

**Not recommended:**
- **Windguru** - No usable API for forecast data

### Cost Analysis

| Source | Cost | Limitation |
|--------|------|------------|
| AEMET | Free | 50 req/min, key renewal every 3 months |
| IHM Tides | Free | None |
| Open-Meteo | Free (non-commercial) | Attribution required |
| Puertos del Estado | Free | No redistribution allowed |
| CMEMS | Free | Registration required |
| StormGlass | EUR 0-129/mo | Free tier: 10 req/day |
| MeteoGalicia | Free | API key via email |

### Data Coverage Matrix

| Parameter | AEMET | PdE | Open-Meteo | StormGlass | IHM | CMEMS |
|-----------|-------|-----|------------|------------|-----|-------|
| Wind (current) | YES (Cabo Busto) | YES (buoy) | No | No | - | - |
| Wind (forecast) | YES (48h hourly) | YES (HARMONIE 1km) | YES | YES | - | - |
| Wave height | Text only | YES (buoy+model) | YES | YES | - | YES |
| Wave period | Text only | YES | YES | YES | - | YES |
| Wave direction | Text only | YES | YES | YES | - | YES |
| Swell | Text only | Limited | YES | YES | - | YES |
| Rain | YES | - | YES | YES | - | - |
| Air temp | YES | YES (buoy) | YES | YES | - | - |
| Sea temp | Beach forecast | YES (buoy) | YES | YES | - | YES |
| Tides | - | Real-time gauge | Limited | YES | YES (best) | - |
| Visibility | YES (text) | - | Limited | YES | - | - |
| Pressure | YES | YES (buoy) | YES | YES | - | - |
| Currents | - | YES (SAMOA) | Limited | YES | - | YES |

---

## Source Links

- AEMET OpenData: https://opendata.aemet.es/
- AEMET API Key: https://opendata.aemet.es/centrodedescargas/obtencionAPIKey
- AEMET Swagger: https://opendata.aemet.es/dist/index.html
- Puertos del Estado Portus: https://portus.puertos.es
- Puertos del Estado THREDDS: http://opendap.puertos.es/thredds/catalog.html
- Open-Meteo Marine API: https://open-meteo.com/en/docs/marine-weather-api
- StormGlass: https://stormglass.io/
- StormGlass Pricing: https://stormglass.io/pricing/
- StormGlass Docs: https://docs.stormglass.io
- Windguru Luarca: https://www.windguru.cz/100034
- CMEMS Data Store: https://data.marine.copernicus.eu/products
- CMEMS Toolbox: https://pypi.org/project/copernicusmarine/
- IHM Tidal API: http://ideihm.covam.es/api-ihm/getmarea?request=getlist&format=json
- IHM API Docs: https://ideihm.covam.es/ayuda_api_mareas.html
- MeteoGalicia MeteoSIX: https://www.meteogalicia.gal/web/proxectos/meteosix.action
- MeteoGalicia API Docs: https://www.meteogalicia.gal/datosred/infoweb/meteo/proxectos/meteosix/API_MeteoSIX_v4_es.pdf
