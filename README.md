# Chetna

Chetna is a seven-day prototype for neighborhood-scale flood monitoring and early warnings. It combines rainfall forecasts, terrain and OpenStreetMap data, and simulated sensor readings to estimate flood risk, display it on a map, and support human-approved alerts and safe routing.

This repository is at the Day 1 setup stage. The project structure and Python environment are prepared; the ML model, routing, alert delivery, and sensor simulator are not implemented yet.

## Requirements

- Python 3.10 or newer
- Conda (recommended for the GIS dependencies)

## Set up the environment

From the repository root:

```powershell
conda create -n chetna python=3.10 -y
conda activate chetna
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If installation of GeoPandas or Rasterio fails on your platform, install those packages from conda-forge in the active environment, then install the remaining requirements with pip.

## Project layout

```text
data/                 Local input and processed data (do not commit datasets)
src/
  ingestion/          Forecast and geospatial data ingestion
  static_risk/        Terrain and static vulnerability processing
  model/              Risk prediction (future work)
  sensors/            Sensor ingestion and simulation (future work)
  routing/            Safe-route planning (future work)
  alerts/             Human-approved notifications (future work)
  db/                 Database setup and access
app/                  Streamlit dashboard
notebooks/            Exploration and backtesting notebooks
tests/                Automated checks
requirements.txt      Python dependencies
```

SQLite is available through Python's standard library, so it is not an additional dependency.

## Initial technology choices

Python, Open-Meteo, GeoPandas, Rasterio, OSMnx, Streamlit, and Folium. Day 1 should agree the pilot city, grid resolution and projected CRS, and shared data contract before adding pipelines or application behavior.

## Forecast Ingestion and Database Storage (Day 2 B1)

Chetna ingests Open-Meteo rainfall forecasts, aggregates +1h, +3h, and +6h cumulative horizons, caches raw responses as JSON (`data/cache/`), and stores structured forecast records in SQLite (`data/chetna.db`).

### Running automated tests
```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

### Running the forecast ingestion example
```powershell
# Run with offline mock data (no internet required):
python tests/example_ingestion.py

# Optional: Run with live Open-Meteo API:
python tests/example_ingestion.py --live --lat 13.0827 --lon 80.2707
```

### Programmatic usage for pipeline integration
```python
from src.ingestion import fetch_and_store_forecast
from src.db import get_latest_forecast

# Fetches 6-hour forecast, caches JSON, and persists to SQLite:
forecast_result, row_id = fetch_and_store_forecast(latitude=13.0827, longitude=80.2707)

# Retrieve latest stored forecast record:
latest = get_latest_forecast()
print(latest)
# Output: {'id': 1, 'timestamp': '...', 'rain_1h': 4.5, 'rain_3h': 24.7, 'rain_6h': 78.4, 'created_at': '...'}
```

## Static Flood Vulnerability Layer (M1 Day 2)

Chetna computes a deterministic, explainable static flood vulnerability score ($V \in [0.0, 1.0]$) for every grid cell from terrain and environmental features without an ML black box.

### Exact Formula and Weights
$$V = 0.35 \cdot \text{norm}(elevation) + 0.25 \cdot \text{norm}(\log(flow\_acc)) + 0.25 \cdot \text{norm}(imperv) + 0.15 \cdot \text{norm}(slope)$$

| Feature | Weight | Directional Hydrological Rationale | Normalization Strategy |
| :--- | :--- | :--- | :--- |
| **Elevation** | 0.35 | Lower elevation pools water; coastal/delta basins flood first. | Inverted min-max: $\frac{E_{max} - E}{E_{max} - E_{min}}$ |
| **Flow Accumulation** | 0.25 | Higher upstream catchment area routes more water into the cell. | Log min-max: $\frac{\ln(1 + FA) - \ln(1 + FA_{min})}{\ln(1 + FA_{max}) - \ln(1 + FA_{min})}$ |
| **Imperviousness** | 0.25 | Concrete and asphalt prevent infiltration, creating immediate runoff. | Direct scale: $\frac{I - I_{min}}{I_{max} - I_{min}}$ |
| **Slope** | 0.15 | Flat ground causes water stagnation; steep ground drains away. | Inverted min-max: $\frac{S_{max} - S}{S_{max} - S_{min}}$ |

### Risk Classification Thresholds
- **Low**: $V < 0.40$
- **Medium**: $0.40 \le V < 0.70$
- **High**: $V \ge 0.70$

### Computing Static Vulnerability
```python
from src.static_risk import compute_static_vulnerability

# Computes scores, writes JSON/CSV, and stores into SQLite 'cells' table:
result = compute_static_vulnerability(
    source="data/m1/synthetic_grid_features.json",
    save_json_path="data/m1/static_risk_scores.json",
    save_csv_path="data/m1/static_risk_scores.csv",
    save_db_path="data/chetna.db",
)
```

## Streamlit Dashboard and Map Skeleton (F1 Day 1)

Chetna provides an interactive Streamlit operations dashboard integrated with a Folium geospatial map centered on the pilot study city (Chennai, India: `[13.0827, 80.2707]`).

### Components in Day 1 Skeleton:
- **Header & System Status**: Real-time status metrics displaying pilot location, processed terrain vulnerability cells, monitored waterlogging hotspots, and forecast counts in the SQLite database.
- **Folium Interactive Map**: Leaflet map viewport centered on Chennai with initial zoom level 11 and informational pilot center marker.
- **Operations Sidebar**: Dedicated placeholder controls for forecast horizon switching (`+1h`, `+3h`, `+6h`), layer toggles (static vulnerability, hotspots, sensors), and simulation triggers.
- **Risk & Alert Centre**:
  - *Monitored Hotspots Tab*: GCC/TNSDMA chronic waterlogging hotspots preview table.
  - *Alert Centre Tab*: Human-in-the-loop alert approval preview with draft advisories and approval gates.
  - *Static Risk Architecture Tab*: Summary of M1 Day 2 mathematical formulation and weights ready for F1 Day 2 layer rendering.

### Running the Dashboard
From the repository root (recommended project-root entrypoint):
```powershell
python -m streamlit run run_dashboard.py
```
or directly:
```powershell
python -m streamlit run app/dashboard.py
```

Toggle between **🏢 Operations Dashboard** (F1) and **👤 Citizen View** (F2) using the *Portal View* selector in the dark navy sidebar.

## Citizen-Facing View Foundation & Wireframes (F2 Day 1)

Chetna introduces an accessible, resident-oriented Citizen View (`app/citizen_view.py`) accessible via the sidebar navigation.

### Components in F2 Day 1 Foundation:
1. **Plain-Language Situational Awareness**:
   - Prominent status banner informing residents of current conditions (`🟢 Conditions Normal • No Active Flood Warning`) in simple, reassuring language.
2. **Neighborhood Risk Check Input Stub**:
   - Area selector for 10 surveyed Chennai neighborhoods (Velachery, Madipakkam, Mudichur, etc.) and forecast horizons (`Current`, `+1h`, `+3h`, `+6h`). Prototype stub; dynamic prediction activates in Day 3 without browser GPS.
3. **Community Base Map & Sourced At-Risk Facilities**:
   - Folium base map centered on Chennai paired with an at-risk facilities and safe havens panel categorizing verified GCC infrastructure from `data/m1/hotspots.json`:
     - **Hospitals**: MIOT International, Dr. Kamakshi Memorial, Prashanth Hospital, etc.
     - **Schools & Institutions**: Madipakkam High School, Dr. Ambedkar Govt Arts College, etc.
     - **Transit Shelters**: Velachery MRTS elevated station, CMBT Koyambedu, Vyasarpadi Jeeva, etc.
4. **Safe-Route to High Ground Placeholder**:
   - Explanatory wireframe card detailing upcoming Day 4 A* routing milestone with hazard avoidance over OpenStreetMap. Action button is disabled with explicit milestone disclaimer.
5. **Bilingual Emergency Advisory Foundation**:
   - Emergency advisories, situation summaries, and safety guidelines in **English** and **Hindi (हिंदी)** with a normal vs. simulated advisory toggle.
6. **Emergency Helplines Footer**:
   - Chennai-specific emergency contact numbers: GCC Helpline `1913`, National Emergency `112`, Disaster Response `1077`.

### Running Automated Checks
```powershell
python -m unittest discover -s tests -p "test_*.py" -v
# or using pytest:
pytest -v
```



