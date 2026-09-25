# Chetna

Chetna is a seven-day prototype for neighborhood-scale flood monitoring and early warnings. It combines rainfall forecasts, terrain and OpenStreetMap data, simulated sensor readings, and a live alert pipeline to estimate flood risk, display it on a map, and send human-approved Telegram and Twilio SMS/Voice alerts.


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
# Using pytest (recommended):
.venv\Scripts\python.exe -m pytest -v

# Using unittest discovery:
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

## End-to-End Alert Pipeline (B2 Day 1)

Chetna B2 Day 1 delivers a fully connected, dry-run-safe alert pipeline.

### Architecture

```text
SensorSimulator
    └─> SensorReading (water_level_cm, rainfall_rate_mm_h, is_anomaly)
            └─> sensor_db_bridge.persist_reading()   → sensor_readings table
            └─> AlertEvaluator.evaluate()             → EvaluationResult (severity, reason)
                    └─> AlertCooldown.should_send()   → suppress / escalate
                            └─> AlertDispatcher.dispatch()
                                    ├─> TelegramAlertHandler  → Telegram
                                    ├─> TwilioAlertHandler    → SMS
                                    ├─> TwilioAlertHandler    → Voice (EMERGENCY only)
                                    └─> database.db.log_alert_dispatch() → alert_logs
                            └─> alerts table (lifecycle: generated → dispatched → acknowledged → resolved)
```

### Database Tables (Canonical: `data/chetna.db`)

| Table | Purpose |
|---|---|
| `forecasts` | Open-Meteo rainfall forecast records (B1 contract) |
| `sensor_nodes` | Registered sensor node metadata |
| `sensor_readings` | Time-series sensor telemetry |
| `alert_logs` | Full audit trail of every dispatch attempt |
| `alerts` | Alert lifecycle state machine |
| `cells` | M1 static vulnerability scores |
| `risk_predictions` | Dynamic risk model predictions |
| `sensor_table` | Legacy compatibility telemetry store |

> **Database resolution**: `database/db.py` + `database/schema.sql` → `data/chetna.db` is the canonical B2 store.
> `database/init_db.py` + its `sensor_table` / `risk_predictions` schema target `data/flood_warning.db` and remain
> isolated for backward compatibility with the notifier test suite.

### Alert Severity Flow

| Severity | Water Level | Rainfall Rate | Anomaly | Channels |
|---|---|---|---|---|
| INFO | < 75 cm | < 30 mm/h | No | Telegram only |
| WARNING | ≥ 75 cm | ≥ 30 mm/h | No | Telegram + SMS |
| CRITICAL | ≥ 120 cm | ≥ 60 mm/h | No | Telegram + SMS |
| EMERGENCY | ≥ 120 cm AND ≥ 60 mm/h | both critical | YES | Telegram + SMS + Voice |

Thresholds are configurable via `.env`:
```
WATER_LEVEL_WARNING_THRESHOLD_CM=75.0
WATER_LEVEL_CRITICAL_THRESHOLD_CM=120.0
RAINFALL_HOURLY_WARNING_MM=30.0
RAINFALL_HOURLY_CRITICAL_MM=60.0
ALERT_COOLDOWN_SECONDS=300
```

### Alert Deduplication / Cooldown
The `AlertCooldown` class suppresses repeated identical alerts within a configurable window
(`ALERT_COOLDOWN_SECONDS`, default 300 s). Escalations to a higher severity always bypass the cooldown.

### Dry-Run Safety
`ALERT_DRY_RUN=true` (the default) causes all Telegram and Twilio handlers to log
messages locally without making any real API calls. No real credentials are required
for testing or CI.

### Running the End-to-End Simulated Alert Flow
```powershell
# 1. Flash-flood simulation: sensor -> evaluator -> dispatcher (dry-run)
.venv\Scripts\python.exe -c "
from simulators.sensor_simulator import SensorSimulator, SimulationScenario
from alerts.pipeline import AlertPipeline
import sqlite3, logging
logging.basicConfig(level=logging.INFO)
pipeline = AlertPipeline()
sim = SensorSimulator(node_id='NODE_DEMO')
readings = sim.generate_batch(count=5, scenario=SimulationScenario.FLASH_FLOOD)
for r in readings:
    result = pipeline.process(r, affected_area='Velachery', persist=False)
    print(f'{r.water_level_cm:.1f} cm -> {result.evaluation.severity.value}',
          '(SUPPRESSED)' if result.suppressed else '(DISPATCHED)')
"

# 2. Run the full test suite:
.venv\Scripts\python.exe -m pytest -v
```

### B2 Day 1 Module Index
| Module | Description |
|---|---|
| `simulators/sensor_simulator.py` | IoT sensor emulator (NORMAL/RISING/FLASH_FLOOD/ANOMALY) |
| `simulators/sensor_db_bridge.py` | Sensor → database persistence bridge |
| `src/alerts/evaluator.py` | Threshold-based severity evaluator |
| `alerts/cooldown.py` | Per-node deduplication / cooldown manager |
| `alerts/pipeline.py` | Full pipeline orchestrator + lifecycle helpers |
| `alerts/dispatcher.py` | Notification routing by severity |
| `alerts/telegram_handler.py` | Telegram Bot HTTP handler |
| `alerts/twilio_handler.py` | Twilio SMS + Voice handler |
| `database/db.py` | Canonical B2 database API |
| `database/schema.sql` | Complete unified SQLite schema |
| `config/settings.py` | Centralized configuration from `.env` |
