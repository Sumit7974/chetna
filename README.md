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
  model/              Risk prediction (heuristic model)
  sensors/            Sensor ingestion and simulation
  routing/            Safe-route planning (future work)
  alerts/             Human-approved notifications
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

## Flood Hotspots & Backtesting Events Dataset (M1 Day 1)

Chetna establishes a deterministic machine-learning data foundation combining documented chronic urban flood hotspots, historical heavy-rainfall event series, and calibrated proxy inundation observations linked to ~200 m metric grid cells.

### What the Day 1 Dataset Represents
- **10 Documented Urban Flood Hotspots**: High-vulnerability locations across South, Central, and North Chennai documented in Greater Chennai Corporation (GCC) and TNSDMA flood records:
  - `HS01` — Velachery Vijayanagar Junction (`CELL_VEL_01`, 7.5 m elev, basin depression)
  - `HS02` — Madipakkam Ram Nagar (`CELL_MAD_01`, 6.8 m elev, marsh fringe depression)
  - `HS03` — Mudichur Varadharajapuram (`CELL_MUD_01`, 12.2 m elev, Adyar floodplain)
  - `HS04` — T. Nagar Usman Road Central (`CELL_TNG_01`, 10.5 m elev, canal overflow)
  - `HS05` — Pulianthope Demellows Road Basin (`CELL_PUL_01`, 5.8 m elev, low-lying canal basin)
  - `HS06` — Vyasarpadi Ganesapuram Subway (`CELL_VYA_01`, 4.2 m elev, railway subway depression)
  - `HS07` — Perambur Stephenson Road Subway (`CELL_PRM_01`, 6.2 m elev, canal underpass)
  - `HS08` — Koyambedu Wholesale Market (`CELL_KYM_01`, 11.0 m elev, Cooum river meander)
  - `HS09` — Manapakkam MIOT Hospital Corridor (`CELL_MNP_01`, 9.4 m elev, Adyar hospital floodplain)
  - `HS10` — Pallikaranai 200 Feet Radial Link Road (`CELL_PLK_01`, 6.0 m elev, wetland chokepoint)
- **2 Significant Historical Heavy-Rain Backtest Events**:
  - `EVT_2023_MICHAUNG`: Cyclone Michaung (Dec 3–5, 2023), 72 hours, 324.1 mm total precipitation, 26.1 mm peak hourly rainfall.
  - `EVT_2021_NOV_DEPRESSION`: November 2021 Deep Depression (Nov 6–8, 2021), 72 hours, 89.0 mm total precipitation, 7.0 mm peak hourly rainfall.
- **1,008 Hourly Observation Records**: Evaluates rainfall accumulation horizons (`rain_1h`, `rain_3h`, `rain_6h`, `rain_past_24h`) and calibrated proxy inundation depth for each affected hotspot across all 72 hours of both events.

### Data Provenance & Real vs. Proxy Classification
- **Real-Sourced Components (`is_real_sourced = True`)**:
  - Hotspot names, coordinates, zones, wards, ground elevations, and vulnerability mechanisms are sourced from GCC Chronic Waterlogging registries, TNSDMA flood audit reviews, and CWC Adyar/Cooum river basin reports.
  - Historical hourly precipitation and rainfall time series are Copernicus ERA5 reanalysis data ingested via the Open-Meteo Historical Archive API.
- **Proxy/Synthetic Development Components (`is_proxy = True`)**:
  - Continuous centimetre-scale water depth sensor logs for past events do not exist across all city intersections. Hourly waterlogging indicators (`waterlogged_proxy`) and inundation depth estimates (`inundation_depth_proxy_m`) are proxy development labels calibrated to official GCC 1h/6h trigger rainfall thresholds and topographic basin depths.
  - All proxy records are explicitly tagged with `is_proxy=True` and documented in dataset metadata to maintain absolute research transparency.

### Limitations
- Rainfall inputs represent regional radar/satellite reanalysis (single representative pilot centroid series).
- Drain network backflow and tidal choking are approximated using static trigger thresholds rather than hydraulic 1D/2D pipe models.
- Proxy labels provide calibration and backtesting targets for ML development until physical IoT sensor nodes are deployed.

### Generation & Usage

#### Generating via CLI
```powershell
# Generate deterministic JSON/CSV files and persist to SQLite:
python scripts/generate_m1_dataset.py --verify

# Generate to a custom directory without modifying the default database:
python scripts/generate_m1_dataset.py --output-dir data/m1_test --no-db
```

#### Programmatic Usage
```python
from src.static_risk import (
    load_hotspots,
    load_m1_development_dataset,
    load_hotspot_observations_from_db,
)

# Load development dataset with 1,008 observations:
dataset = load_m1_development_dataset()
print(f"Loaded {len(dataset.hotspots)} hotspots and {len(dataset.observations)} observations")

# Query observations from SQLite:
observations = load_hotspot_observations_from_db(
    event_id="EVT_2023_MICHAUNG",
    hotspot_id="HS01",
)
for obs in observations[:5]:
    print(obs.timestamp, obs.rain_1h, obs.waterlogged_proxy, obs.inundation_depth_proxy_m)
```

## Static Flood Vulnerability Layer (M1 Day 2)

Chetna computes a deterministic, explainable static flood vulnerability score ($V \in [0.0, 1.0]$) for every grid cell from terrain and environmental features without an ML black box.

### Features & Directional Hydrological Rationale
1. **Elevation (Weight: 0.35)**:
   - *Rationale*: Low-lying depressions and basins accumulate stormwater; coastal and river delta plains flood first.
   - *Direction*: Inverted normalization — **lower elevation strictly increases flood vulnerability**.
   - *Formula*: $\text{norm}(E) = \frac{E_{max} - E}{E_{max} - E_{min}}$
2. **Slope (Weight: 0.15)**:
   - *Rationale*: Flat ground causes stormwater pooling and slow drainage; steeper slopes shed runoff rapidly.
   - *Direction*: Inverted normalization — **flatter terrain increases local stagnation risk**.
   - *Formula*: $\text{norm}(S) = \frac{S_{max} - S}{S_{max} - S_{min}}$
3. **Flow Accumulation (Weight: 0.25)**:
   - *Rationale*: Larger upstream catchment surface area routes larger cumulative water volumes into the cell.
   - *Direction*: Logarithmic normalization — accounts for extreme exponential ranges in hydrological networks.
   - *Formula*: $\text{norm}(FA) = \frac{\ln(1 + FA) - \ln(1 + FA_{min})}{\ln(1 + FA_{max}) - \ln(1 + FA_{min})}$
4. **Imperviousness (Weight: 0.25)**:
   - *Rationale*: Asphalt, concrete, and roof surfaces prevent natural soil infiltration, generating immediate surface runoff.
   - *Direction*: Direct scaling — **higher imperviousness increases runoff vulnerability**.
   - *Formula*: $\text{norm}(I) = \frac{I - I_{min}}{I_{max} - I_{min}}$

### Combined Vulnerability Formula
$$V = 0.35 \cdot \text{norm}(elevation) + 0.15 \cdot \text{norm}(slope) + 0.25 \cdot \text{norm}(\log(flow\_acc)) + 0.25 \cdot \text{norm}(imperv)$$

The score $V$ is mathematically bounded strictly within $[0.0, 1.0]$. For every cell, the four constituent contributions are saved alongside the raw and normalized values for explainability.

### Risk Classification Thresholds
- **LOW**: $V < 0.40$
- **MEDIUM**: $0.40 \le V < 0.70$
- **HIGH**: $V \ge 0.70$

### Scientific & Prototype Limitations
> [!IMPORTANT]
> - **Not a Dynamic Probability**: The static vulnerability score $V$ represents baseline topographic and land-use susceptibility to waterlogging. It is **not** a calibrated dynamic probability of flooding without forecast rainfall integration (which is computed dynamically in Day 3).
> - **Synthetic Development Data**: In early prototype development, the 38-cell grid features (`data/m1/synthetic_grid_features.json`) are calibrated proxy fixtures representing known Chennai hotspot topographies, clearly flagged with `is_synthetic = True`. When real GIS rasters (Copernicus DEM and ESA WorldCover) are processed, the same scoring pipeline operates identically without code modifications.

### How to Run the Calculation Locally

#### Using the CLI Generator
```powershell
# Compute scores from synthetic grid features, save to JSON/CSV, and store in SQLite 'cells' table:
python scripts/compute_static_risk.py --verify

# Compute static vulnerability directly from SQLite spatial tables:
python scripts/compute_static_risk.py --source data/chetna.db --verify
```

#### Programmatic Usage
```python
from src.static_risk import compute_static_vulnerability

# Computes scores, exports to JSON/CSV, and stores into SQLite 'cells' table:
result = compute_static_vulnerability(
    source="data/m1/synthetic_grid_features.json",
    save_json_path="data/m1/static_risk_scores.json",
    save_csv_path="data/m1/static_risk_scores.csv",
    save_db_path="data/chetna.db",
)

# Inspect cell explainability:
cell = result.get_cell("CELL_VEL_01")
print(f"Cell {cell.cell_id}: Score={cell.vulnerability_score:.2f} ({cell.risk_level_upper})")
print("Contributions:", cell.feature_contributions)
```

## Prototype ML Flood-Risk Prediction Layer (M1 Day 3)

Chetna introduces a prototype machine learning flood-risk prediction engine connecting historical reanalysis, chronic hotspot calibration thresholds, and static terrain vulnerability into multi-horizon dynamic risk predictions.

$$\text{Proxy Labels} \longrightarrow \text{Hotspot Calibration} \longrightarrow \text{Feature Engineering} \longrightarrow \text{Multi-Horizon XGBoost} \longrightarrow \text{+1h / +3h / +6h Risk Predictions} \longrightarrow \text{risk\_predictions Table}$$

### Deterministic Proxy Label Generation & Hotspot Calibration
- **Deterministic Proxy Targets**:
  - `waterlogged_proxy`: Binary classification target ($1$ if cell waterlogs within forecast horizon, $0$ otherwise).
  - `flood_risk_proxy`: Continuous dynamic flood severity score in $[0.0, 1.0]$.
  - `proxy_risk_tier`: 3-tier categorization (`Low`, `Medium`, `High`).
- **Physical Calibration Logic**:
  Base trigger rainfall thresholds documented by the Greater Chennai Corporation (GCC) for chronic hotspots (e.g. 15–35 mm for 1h, 35–80 mm for 6h) are calibrated dynamically for each cell based on its M1 Day 2 static terrain vulnerability $V$:
  $$R_{crit}(H, V) = T_{hotspot}(H) \cdot (1.35 - 0.70 \cdot V)$$
  - High-vulnerability depression cells ($V \approx 0.92$) experience waterlogging at ~28% lower rainfall.
  - Saturated soil adjustment: When antecedent 24-hour rainfall $\text{rain\_past\_24h} \ge 35.0\text{ mm}$, infiltration is impaired and $R_{crit}$ is reduced by an additional 15%.
- **Provenance & Prototype Transparency**:
  All generated observations are explicitly tagged with `is_proxy = True` and data provenance metadata. They represent calibrated development proxy labels derived from municipal records and historical reanalysis, not raw physical water-depth sensor logs.

### Leakage-Free Feature Engineering
To prevent temporal and horizon leakage:
- **Horizon-Specific Weather Features**: When predicting horizon $+H\text{h}$ ($H \in \{1, 3, 6\}$), the dynamic rainfall feature $\text{rainfall\_mm}$ strictly reflects cumulative forecast rain for that horizon. Model H1 never accesses $+3\text{h}$ or $+6\text{h}$ future rainfall.
- **Strict Backward-Looking Antecedent Precipitation**: $\text{rain\_past\_24h}$ sums rainfall strictly before reference time $t$ ($t_{past} < t$).
- **Static Terrain & Infrastructure Features**:
  - `elevation`: Ground elevation in meters from 30m DEM.
  - `slope`: Surface gradient in degrees.
  - `flow_accumulation`: Upstream catchment flow accumulation.
  - `imperviousness`: Fraction of sealed urban surface $[0.0, 1.0]$.
  - `vulnerability_score`: M1 Day 2 composite terrain vulnerability $V \in [0.0, 1.0]$.
- **Hotspot Context Features**:
  - `trigger_rain_threshold`: Calibrated effective trigger rainfall in mm.
  - `is_hotspot`: Indicator flag ($1.0$ for chronic hotspots, $0.0$ for general grid cells).

### Multi-Horizon XGBoost Architecture
- **Dedicated Horizon Classifiers**: Separate models are trained for $+1\text{h}$, $+3\text{h}$, and $+6\text{h}$ to reflect distinct hydrologic flooding dynamics:
  - `model_h1.json`: Localized flash waterlogging driven predominantly by static terrain depression and short-burst cloudbursts.
  - `model_h3.json`: Drainage bottlenecking driven by intermediate cumulative volume and surface imperviousness.
  - `model_h6.json`: Widespread inundation governed by multi-hour storm volume, slope drainage limits, and basin morphology.
- **Reproducibility**: All models are trained with a fixed random seed (`random_state=42`, `n_estimators=100`, `max_depth=4`, `learning_rate=0.08`, `eval_metric='logloss'`).
- **Native JSON Serialization**: Models are saved natively to JSON format in `data/m1/models/` and `data/models/` alongside `model_metadata.json` for reproducible, platform-independent loading without Python pickle risks.

### Standard Output Contract & Risk Tiers
Every prediction generates a standard `RiskPrediction` object:
- `cell_id`: Target metric grid cell identifier.
- `timestamp`: Forecast reference ISO timestamp.
- `horizon`: Integer forecast horizon ($1$, $3$, or $6$).
- `probability`: Model predicted flood probability in $[0.0, 1.0]$.
- `level`: Categorical risk classification matching framework thresholds:
  - **LOW**: $\text{probability} < 0.40$
  - **MEDIUM**: $0.40 \le \text{probability} < 0.70$
  - **HIGH**: $\text{probability} \ge 0.70$
- **Database Persistence**: Saved directly into SQLite `risk_predictions` table via single-record or batch transactions.

### Prototype Validation & Evaluation Results
Evaluation on a stratified 20% validation split (1,095 samples per horizon across 38 cells during Cyclone Michaung and Nov 2021 backtests):

| Horizon | Validation Samples | Positive Proxy Events | Precision | Recall | F1-Score | ROC-AUC | Brier Score |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **+1h** | 1,095 | 56 (5.1%) | 1.0000 | 0.9821 | 0.9910 | 0.9999 | 0.0013 |
| **+3h** | 1,095 | 123 (11.2%) | 0.9593 | 0.9593 | 0.9593 | 0.9995 | 0.0054 |
| **+6h** | 1,095 | 160 (14.6%) | 1.0000 | 0.9750 | 0.9873 | 0.9998 | 0.0041 |

#### Top Feature Importances by Horizon
- **Horizon +1h**: `vulnerability_score` (0.426), `rainfall_mm` (0.346), `slope` (0.089), `trigger_rain_threshold` (0.075)
- **Horizon +3h**: `rainfall_mm` (0.506), `imperviousness` (0.134), `slope` (0.117), `trigger_rain_threshold` (0.097)
- **Horizon +6h**: `rainfall_mm` (0.487), `slope` (0.246), `trigger_rain_threshold` (0.095), `elevation` (0.073)

### How to Run Training & Inference

#### CLI Training
```powershell
# Train multi-horizon XGBoost models, evaluate metrics, and save artifacts:
python scripts/train_m1_model.py
```

#### Programmatic Prediction
```python
from src.model import XGBoostRiskPredictor, FloodRiskPredictor

# Option 1: Direct XGBoost Predictor
predictor = XGBoostRiskPredictor(model_dir="data/m1/models")
pred = predictor.predict_from_forecast(
    rainfall_mm=55.0,
    cell_id="CELL_VEL_01",
    horizon=3,
    persist=True,
)
print(f"Cell {pred.cell_id} +{pred.horizon}h Risk: {pred.level} (p={pred.probability:.3f})")

# Option 2: Via Unified FloodRiskPredictor
unified_predictor = FloodRiskPredictor(mode="ml", model_dir="data/m1/models")
pred_unified = unified_predictor.predict_from_forecast(rainfall_mm=55.0, cell_id="CELL_VEL_01", horizon=3)

# Option 3: Via End-to-End Pipeline
from src.pipeline import run_pipeline
pipeline_result = run_pipeline(predictor_mode="ml", model_dir="data/m1/models")
print(f"Created {pipeline_result.predictions_created} ML risk predictions across {pipeline_result.cells_processed} cells")
```

### Prototype Limitations
> [!IMPORTANT]
> 1. **Proxy Target Nature**: Models are trained and evaluated against deterministic proxy labels derived from municipal trigger rainfall heuristics, not real-time physical water-level sensor telemetry.
> 2. **Rainfall Granularity**: ERA5 historical reanalysis and Open-Meteo forecasts provide regional precipitation. Local convective micro-bursts and sub-kilometer rainfall variations require future integration with Doppler weather radar and high-density rain gauges.
> 3. **Hydraulic Routing**: The model captures terrain and rainfall thresholds empirically; 1D/2D hydrodynamic pipe network backflow modeling will further enhance urban flood extent estimation in subsequent phases.

## Model Explainability & Integration Layer (M1 Day 4)

Chetna implements a lightweight, deterministic explainability layer for multi-horizon flood-risk predictions. For every cell prediction at horizons +1h, +3h, and +6h, the engine answers:

> *"Why was this cell classified at this risk level?"*

### Explainability Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │   Prediction Request (Rainfall, Cell, H)     │
                    └──────────────────────┬───────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │        XGBoost Horizon-Specific Model        │
                    │        Global Feature Weights (W_i)          │
                    └──────────────────────┬───────────────────────┘
                                           │
             ┌─────────────────────────────┼─────────────────────────────┐
             │                             │                             │
┌────────────▼───────────┐   ┌─────────────▼─────────────┐   ┌───────────▼───────────┐
│ Dynamic Weather Factor │   │  Static Susceptibility    │   │ Hotspot Context Factor│
│ - Forecast rainfall    │   │ - M1 Day 2 terrain vuln   │   │ - Documented hotspot  │
│ - Antecedent 24h rain  │   │ - Elevation & slope       │   │ - Calibrated threshold│
│ - Threshold ratio      │   │ - Flow accumulation & imp │   │ - Historical frequency│
└────────────┬───────────┘   └─────────────┬─────────────┘   └───────────┬───────────┘
             │                             │                             │
             └─────────────────────────────┼─────────────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │  Deterministic Attribution & Direction       │
                    │  - Local weight scaling: L_i = W_i * mult_i  │
                    │  - Direction: increases / decreases / neutral│
                    │  - Ranked Top Factors (normalized sum = 1.0) │
                    └──────────────────────┬───────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │  Structured Output & Objective Summary       │
                    │  - PredictionExplanation JSON contract       │
                    │  - Non-exaggerated meteorological phrasing   │
                    │  - Scientific non-causal disclaimer attached │
                    └──────────────────────────────────────────────┘
```

### Static vs. Dynamic Factor Breakdown
1. **Dynamic Weather Factors (`category: "dynamic"`)**:
   - `rainfall_mm`: Forecast cumulative rainfall for the active horizon window (+1h, +3h, or +6h).
   - `rain_past_24h`: Antecedent 24-hour rainfall ($t_{past} < t$) indicating prior soil saturation.
   - `threshold_ratio`: Ratio of forecast precipitation to local calibrated trigger threshold.
2. **Static Terrain Factors (`category: "static"`)**:
   - `vulnerability_score`: M1 Day 2 composite topographic vulnerability $V \in [0.0, 1.0]$.
   - `elevation`: Ground elevation from 30m DEM (lower elevations increase pooling susceptibility).
   - `slope`: Ground inclination in degrees (flatter surfaces impede stormwater drainage).
   - `flow_accumulation`: Overland drainage catchment contributing runoff into the cell.
   - `imperviousness`: Fraction of paved artificial surface preventing natural infiltration.
   - Constituent static contributions: Exact breakdown from Day 2 formula.
3. **Hotspot Context Factors (`category: "hotspot_context"`)**:
   - `is_hotspot`: Whether cell contains an officially documented GCC/TNSDMA chronic flooding location.
   - `trigger_rain_threshold`: Calibrated effective trigger rainfall in mm.

### Horizon-Aware Attributions (+1h, +3h, +6h)
To eliminate temporal leakage, each horizon model uses its own learned feature attribution:
- **+1h Horizon**: Local terrain vulnerability ($V$) and cloudburst precipitation dominate short-burst flash waterlogging.
- **+3h Horizon**: Intermediate storm volume and urban surface imperviousness drive drainage saturation.
- **+6h Horizon**: Multi-hour cumulative storm precipitation and slope discharge constraints govern widespread inundation.

### Example Structured Explanation Output
```json
{
  "cell_id": "CELL_VEL_01",
  "timestamp": "2026-09-27T01:25:00Z",
  "horizon": 3,
  "risk_level": "HIGH",
  "probability": 0.9983,
  "top_factors": [
    {
      "feature": "rainfall_mm",
      "display_name": "Forecast Rainfall",
      "category": "dynamic",
      "importance": 0.632,
      "direction": "increases_risk",
      "value": 55.0,
      "unit": "mm",
      "description": "Cumulative precipitation forecast for the requested horizon window"
    },
    {
      "feature": "imperviousness",
      "display_name": "Surface Imperviousness",
      "category": "static",
      "importance": 0.098,
      "direction": "increases_risk",
      "value": 0.88,
      "unit": "fraction",
      "description": "Proportion of artificial, sealed, and paved urban surface preventing infiltration"
    },
    {
      "feature": "slope",
      "display_name": "Terrain Slope",
      "category": "static",
      "importance": 0.086,
      "direction": "increases_risk",
      "value": 0.2,
      "unit": "degrees",
      "description": "Ground surface inclination; flatter terrain impedes drainage discharge"
    }
  ],
  "static_factors": {
    "vulnerability_score": 0.9208,
    "elevation_m": 6.5,
    "slope_deg": 0.2,
    "flow_accumulation": 85000.0,
    "imperviousness": 0.88,
    "static_contributions": {
      "elevation": 0.3286,
      "slope": 0.148,
      "flow_accumulation": 0.218,
      "imperviousness": 0.2262
    }
  },
  "dynamic_factors": {
    "rainfall_mm": 55.0,
    "horizon_hours": 3,
    "rain_past_24h_mm": 38.0,
    "threshold_ratio": 1.22
  },
  "hotspot_context": {
    "is_hotspot": true,
    "trigger_threshold_mm": 45.0
  },
  "summary": "High forecast rainfall (55.0 mm in +3h) combined with high static terrain vulnerability (0.92) at a documented chronic waterlogging hotspot, compounded by saturated ground conditions (38.0 mm of antecedent rainfall) indicates elevated flood probability (p=1.00).",
  "methodology": "deterministic_feature_attribution",
  "disclaimer": "Scientific provenance and non-causal disclaimer: Explanations reflect model-associated feature contributions and empirical thresholds, NOT proven physical causation. Prototype system trained on calibrated proxy development data."
}
```

### Deterministic Human-Readable Summaries
The engine generates clear, non-exaggerated summaries across all three risk tiers:
- **LOW**: *"Low forecast rainfall (2.0 mm in +1h) over moderate static terrain vulnerability (0.50) indicates low flood probability (p=0.00) under current conditions."*
- **MEDIUM**: *"Moderate forecast rainfall (22.0 mm in +1h) combined with moderate static terrain vulnerability (0.65) indicates moderate flood risk (p=0.55) warranting monitoring."*
- **HIGH**: *"High forecast rainfall (60.0 mm in +3h) combined with high static terrain vulnerability (0.92) at a documented chronic waterlogging hotspot, compounded by saturated ground conditions (40.0 mm of antecedent rainfall) indicates elevated flood probability (p=0.88)."*

### How to Use Explanations in Code

```python
from src.model import XGBoostRiskPredictor, FloodRiskPredictor
from src.pipeline import run_pipeline

# 1. Direct Predictor with Explanation
predictor = XGBoostRiskPredictor(model_dir="data/m1/models")
pred, expl = predictor.predict_with_explanation(
    rainfall_mm=55.0,
    cell_id="CELL_VEL_01",
    horizon=3,
)
print("Risk Level:", expl.risk_level)
print("Summary:", expl.summary)
print("Top Factor:", expl.top_factors[0].display_name, expl.top_factors[0].importance)

# 2. Standard predict_from_forecast() with explain=True
pred_attached = predictor.predict_from_forecast(
    rainfall_mm=55.0,
    cell_id="CELL_VEL_01",
    horizon=3,
    explain=True,
)
print("Attached explanation summary:", pred_attached.explanation["summary"])

# 3. End-to-End Pipeline with Explanations
pipeline_result = run_pipeline(
    predictor_mode="ml",
    model_dir="data/m1/models",
    include_explanations=True,
)
for p in pipeline_result.predictions[:2]:
    print(p.cell_id, f"+{p.horizon}h", p.level, p.explanation["summary"])
```

### Scientific Limitations & Causal Boundaries
> [!IMPORTANT]
> 1. **Non-Causal Feature Attribution**: Feature importance values and directional indicators denote statistical correlations within the tree model and physical heuristic bounds. They do **not** constitute a formal hydrodynamic proof of physical causation.
> 2. **Proxy Calibration Artifacts**: The training target is derived from calibrated municipal trigger rainfall heuristics, not direct physical depth sensor telemetry.
> 3. **Validation Requirements**: Real-world field instrumentation (IoT ultrasonic level gauges and municipal telemetry) is essential before operational flood evacuation directives are issued based on explainability scores.

## Model Backtesting & Baseline Comparison (M1 Day 5)

Chetna M1 Day 5 implements a rigorous, leak-free backtesting and comparative evaluation framework for the prototype ML flood-risk prediction system. It benchmarks the calibrated XGBoost model against the deterministic heuristic predictor and a simple rainfall-threshold baseline across historical storm events.

### Compared Prediction Methods
1. **Method A — Calibrated XGBoost ML Model (`XGBoostRiskPredictor`)**:
   - Uses multi-feature inputs: rainfall horizon, 24h antecedent rainfall, static terrain vulnerability ($V$), elevation, slope, flow accumulation, imperviousness, and hotspot proximity.
   - Outputs continuous calibrated probability ($0.0 \le P \le 1.0$) and multi-class risk (`LOW`, `MEDIUM`, `HIGH`).
2. **Method B — Heuristic Rule-Based Predictor (`FloodRiskPredictor(mode="heuristic")`)**:
   - Production default: $P = 0.65 \cdot S_{rain} + 0.35 \cdot V$.
   - Uses both dynamic forecast rainfall and static terrain vulnerability.
3. **Method C — Simple Rainfall-Threshold Baseline (`RainfallThresholdBaseline`)**:
   - Zero-terrain baseline relying solely on rainfall accumulation thresholds:
     - +1h: $P \ge 0.5$ if rain $\ge 50$ mm; $P \ge 0.8$ if rain $\ge 70$ mm
     - +3h: $P \ge 0.5$ if rain $\ge 80$ mm; $P \ge 0.8$ if rain $\ge 110$ mm
     - +6h: $P \ge 0.5$ if rain $\ge 120$ mm; $P \ge 0.8$ if rain $\ge 150$ mm
   - Explicitly does NOT utilize terrain elevation, slope, flow accumulation, imperviousness, or historical hotspot designations.

### Historical Backtesting Events
- **`EVT_2023_MICHAUNG` (Cyclone Michaung, Dec 3–4, 2023)**:
  - Severe extreme tropical cyclone event delivering up to 324.0 mm cumulative rainfall.
  - 48 hourly timesteps across 38 pilot grid cells (1,824 cell-timesteps; 5,472 multi-horizon evaluations).
- **`EVT_2021_NOV_DEPRESSION` (November 2021 Depression, Nov 10–12, 2021)**:
  - Moderate persistent coastal depression delivering up to 89.0 mm cumulative rainfall.
  - 48 hourly timesteps across 38 pilot grid cells (1,824 cell-timesteps; 5,472 multi-horizon evaluations).
- **Combined Aggregate Evaluation**: 3,648 cell-timesteps totaling 10,944 multi-horizon predictions (5,472 samples per horizon). All records explicitly carry `is_proxy = True`.

### Comparative Performance Metrics (Aggregate)

| Horizon | Method | Precision | Recall | F1 Score | ROC-AUC | PR-AUC | Brier Score | TP | FP | FN | TN |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **+1h** | **ML (XGBoost)** | 1.0000 | 0.9965 | 0.9982 | 1.0000 | 1.0000 | 0.0007 | 281 | 0 | 1 | 5,190 |
| | **Heuristic** | 1.0000 | 0.6950 | 0.8201 | 0.9977 | 0.9632 | 0.0953 | 196 | 0 | 86 | 5,190 |
| | **Rainfall Baseline** | N/A* | 0.0000 | 0.0000 | 0.9838 | 0.8291 | 0.0264 | 0 | 0 | 282 | 5,190 |
| **+3h** | **ML (XGBoost)** | 0.9903 | 0.9919 | 0.9911 | 0.9999 | 0.9992 | 0.0017 | 612 | 6 | 5 | 4,849 |
| | **Heuristic** | 0.9980 | 0.8071 | 0.8925 | 0.9971 | 0.9647 | 0.1034 | 498 | 1 | 119 | 4,854 |
| | **Rainfall Baseline** | 0.9868 | 0.1216 | 0.2165 | 0.9829 | 0.8295 | 0.0370 | 75 | 1 | 542 | 4,854 |
| **+6h** | **ML (XGBoost)** | 1.0000 | 0.9950 | 0.9975 | 1.0000 | 1.0000 | 0.0012 | 798 | 0 | 4 | 4,670 |
| | **Heuristic** | 1.0000 | 0.8516 | 0.9199 | 0.9960 | 0.9669 | 0.1053 | 683 | 0 | 119 | 4,670 |
| | **Rainfall Baseline** | 0.9850 | 0.3267 | 0.4907 | 0.9814 | 0.8295 | 0.0371 | 262 | 4 | 540 | 4,666 |

*\*Note: Precision is undefined (reported as N/A / None) when the method predicts zero positive cases.*

### Event-Level Performance Summary

- **Cyclone Michaung 2023 (Severe Event — Peak Rain 324 mm)**:
  - At +6h, the ML model achieves Recall=0.9950, F1=0.9975; the Heuristic model achieves Recall=0.8516, F1=0.9199.
  - The rainfall threshold baseline achieves high precision (0.9850) but limited recall (0.3267), triggering only during peak downpours and missing early depression accumulation.
- **November 2021 Depression (Moderate Event — Peak Rain 89 mm)**:
  - 0 positive proxy flood labels observed under municipal trigger criteria across all 38 cells.
  - Both ML and Heuristic models maintain 100% specificity (0 false positives; TN=1,824 for every horizon).
  - Rainfall threshold baseline predicts 0 positives (no false alarms).

### Temporal & Feature Leakage Safeguards
1. **Strict Horizon Isolation**: Each horizon evaluation uses solely meteorological forecast information available at or before the simulated forecast origin time $T$. Future rainfall increments beyond $T + h$ are never accessible.
2. **Feature Integrity**: Zero label leakage; target label `flood_risk_proxy` is excluded from predictor feature vectors.
3. **No Test-Time Peeking**: All baseline and model evaluations process timesteps sequentially without lookahead.

### Running Backtests via CLI
```powershell
# Run full backtesting across all events and horizons:
python scripts/backtest_m1.py

# Run for a specific historical event:
python scripts/backtest_m1.py --event EVT_2023_MICHAUNG

# Run with custom output directory:
python scripts/backtest_m1.py --output-dir data/m1/backtest
```

Structured output artifacts are generated at:
- `data/m1/backtest/results.json`: Complete metrics breakdown per event and aggregate.
- `data/m1/backtest/results.csv`: Tabular CSV of all performance metrics.
- `data/m1/backtest/confusion_matrices.json`: Full TP/FP/FN/TN contingency tables and counts.

### Scientific Limitations & In-Sample Benchmarking Disclaimer
> [!WARNING]
> 1. **Proxy Target Nature**: Ground truth target labels are synthetic proxy indicators generated from municipal waterlogging heuristics and historical flood reports, not direct calibrated gauge telemetry.
> 2. **In-Sample Benchmark Boundary**: The current prototype XGBoost model was trained on dataset partitions derived from the same pilot events. High ML metric scores reflect in-sample fitting capacity and baseline comparative behavior, **not** out-of-sample operational generalization.
> 3. **Non-Operational Status**: The default pipeline predictor remains `"heuristic"`. The ML model is a prototype evaluation layer and must NOT be used for operational flood warning or evacuation decisions without physical gauge validation.

## Robustness & Failure Testing (M1 Day 6)

Chetna M1 Day 6 establishes a comprehensive failure-testing, edge-case validation, and error-isolation layer across the entire M1 pipeline. It verifies that corrupt inputs, missing artifacts, extreme meteorological events, and database anomalies fail safely, isolate gracefully, and never produce invalid probabilities or uncaught crashes.

### Tested Failure Classes & Expected Behaviors

1. **Input & Spatial Data Failures**:
   - *Missing DEM / Grid Files*: Raises explicit `FileNotFoundError`.
   - *Empty Grid Dataset*: Rejected with `ValueError("Cannot process empty grid_cells list")`.
   - *Missing or NaN Static Features*: Imputes with physical terrain defaults (`elevation=12.0m`, `slope=1.0°`, `flow_acc=5000`, `imperviousness=0.50`) and flags `was_imputed=True`; scores remain finite in $[0.0, 1.0]$.
   - *Uniform / Zero-Variance Terrain*: Normalizes to neutral `0.50` without `ZeroDivisionError`.
   - *Malformed / Out-of-Bound Hotspots*: Hotspots with invalid latitude ($> 90^\circ$ or $< -90^\circ$), longitude, or negative trigger precipitation are rejected at instantiation.
   - *Negative Rainfall*: Physically clamped to $0.0\text{ mm}$ (non-negative precipitation).
   - *NaN / Infinite Rainfall*: Strictly rejected with `ValueError("Rainfall must be a finite number")`; never propagates `NaN` into probability matrices.
   - *Extreme Storm Rainfall*: Cumulative rainfall up to $10,000\text{ mm}$ caps probability at $1.0$ without numeric overflow or infinite loops.
   - *Incomplete Telemetry*: Missing or `NaN` sensor water levels default to baseline $0.0\text{ cm}$ without crashing.

2. **Model Robustness & Horizon Boundaries**:
   - Evaluated across $+1\text{h}$, $+3\text{h}$, and $+6\text{h}$ with rainfall at $0\text{ mm}$, below critical threshold ($R_{\text{crit}} - \epsilon$), exact threshold ($R_{\text{crit}}$), and extreme storms.
   - Evaluated across static terrain vulnerability boundaries: $V = 0.0$, $V = 1.0$, $V = \text{None}$ (defaults to $0.50$).
   - Validated threshold cutoffs: probabilities at $< 0.40$ classify as `LOW`, $[0.40, 0.70)$ classify as `MEDIUM`, and $\ge 0.70$ classify as `HIGH`.
   - Invalid horizons (e.g. 0, 2, 4, 12, -1) raise explicit `ValueError("Invalid horizon: expected 1, 3, or 6")`.

3. **ML Artifact Failures & Fallback Transparency**:
   - *Missing Horizon Model / Metadata*: Direct model load raises `FileNotFoundError`.
   - *Corrupted Model Files*: Parsing invalid model JSON raises an explicit deserialization error.
   - *Documented Heuristic Fallback*: When `allow_fallback=True`, missing ML models automatically trigger heuristic prediction. Crucially, the returned `RiskPrediction` explicitly records `mode = "heuristic_fallback"` and `explanation["fallback_used"] = True`. The system never silently masquerades a fallback heuristic as an ML prediction.
   - *Disabled Fallback*: When `allow_fallback=False`, missing models raise `RuntimeError` immediately.

4. **Pipeline Error Isolation & Partial Success Reporting**:
   - Individual cell anomalies (e.g. invalid telemetry or localized inference exceptions) are isolated in a per-cell try/except block.
   - The pipeline continues executing for all valid cells.
   - Failures are recorded as structured `CellFailureRecord` objects:
     ```json
     {
       "cell_id": "CELL_BAD_01",
       "stage": "prediction",
       "error_type": "RuntimeError",
       "message": "Corrupted cell telemetry / sensor divergence",
       "recoverable": true,
       "horizon": 1
     }
     ```
   - `PipelineResult` exposes `cells_processed`, `predictions_created`, `failed_cells`, and `failed_cell_count`.

5. **Explainability Robustness**:
   - Generates valid `PredictionExplanation` across `LOW`, `MEDIUM`, and `HIGH` predictions.
   - Handles empty feature importances, zero rainfall, and extreme rainfall without division by zero.
   - Maintains non-causal language and displays scientific disclaimer on every explanation.

6. **Backtest Metric Robustness**:
   - Empty sample sets return `None` for all metrics rather than fabricating zeros or crashing.
   - Events with zero positive labels return `None` for ROC-AUC and PR-AUC.
   - Zero predicted positives return `None` for precision and F1 rather than manufactured numbers.

7. **Data Contract Validation**:
   - Strict runtime validators: `validate_risk_prediction_contract()` and `validate_sensor_reading_contract()` enforce type integrity, required fields, and valid value ranges.

### Failure Classification & Handling Matrix

| Failure Scenario | Classification | System Behavior | Recoverable? |
|---|---|---|---|
| **Missing ML Model Artifacts** | Graceful Fallback | Falls back to heuristic predictor; flags `mode="heuristic_fallback"` | Yes (Automatic) |
| **Transient Weather API Outage** | Graceful Fallback | Reads from local JSON cache or SQLite `forecasts` table | Yes (Automatic) |
| **Negative Rainfall Input** | Input Sanitization | Clamped to non-negative physical boundary ($0.0\text{ mm}$) | Yes (Automatic) |
| **NaN / Inf Static Features** | Input Sanitization | Imputed with standard geomorphological defaults; flagged | Yes (Automatic) |
| **Individual Cell Prediction Error** | Partial Pipeline Failure | Cell isolated into `failed_cells`; remaining cells processed | Yes (Partial Success) |
| **NaN / Inf Rainfall Input** | Rejection | Rejected with `ValueError`; caught in per-cell isolation | Yes (Per-cell) |
| **Invalid Horizon (e.g. +2h)** | Rejection | Rejected with `ValueError("Invalid horizon: expected 1, 3, or 6")` | Yes (Caller Fix) |
| **Empty Grid / Empty Database** | Hard Failure | Pipeline raises `EmptyCellsError` / `ForecastUnavailableError` | No (Operator Intervention) |
| **Missing Database Schema Tables** | Hard Failure | Unrecoverable schema error; requires running `database/init_db.py` | No (Operator Intervention) |

### Prototype Boundaries & Real-World Validation Notice
> [!CAUTION]
> Chetna is an active research prototype. All error handling, fallback mechanisms, and robustness tests validate software resilience and algorithmic safety bounds under simulated and calibrated proxy environments. They do **NOT** validate hydrodynamic physical accuracy or real-world municipal flood warning readiness. Field deployment requires operational validation against physical streamflow and ultrasonic water-depth telemetry.

## Final Validation Rehearsal (M1 Day 7)

M1 Day 7 is a read-only end-to-end final validation pass over the complete M1 system.
No architecture changes. No new features. No commits were made during this day.

### M1 Day-by-Day Status

| Day | Focus | Status |
|---|---|---|
| **M1 Day 1** | Hotspot / event dataset, historical events, proxy labeling, grid mapping | ✅ COMPLETE |
| **M1 Day 2** | Elevation / slope / flow accumulation / imperviousness vulnerability score | ✅ COMPLETE |
| **M1 Day 3** | Proxy dataset, hotspot calibration, XGBoost H1/H3/H6, heuristic fallback | ✅ COMPLETE |
| **M1 Day 4** | ML/static/dynamic explanation, persistence, human-readable summary | ✅ COMPLETE |
| **M1 Day 5** | ML vs heuristic vs rainfall-baseline backtest, confusion matrices | ✅ COMPLETE |
| **M1 Day 6** | Input/model/pipeline failure isolation, boundary & contract validation | ✅ COMPLETE |
| **M1 Day 7** | Final end-to-end validation rehearsal, report generation | ✅ COMPLETE |

### Final Test Results (M1 Day 7 Verified)

- **M1 Day 6 robustness tests**: 66 / 66 passed
- **Full test suite**: 283 / 283 passed
- **`git diff --check`**: Clean (exit 0, no trailing-whitespace errors)
- **End-to-end pipeline**: 9 predictions / 3 cells x 3 horizons / 0 failures
- **Model contract**: H1/H3/H6 ML and heuristic predictions valid in [0,1]
- **Graceful fallback**: Confirmed -- `mode="heuristic_fallback"` correctly set
- **Backtest output**: 18 event records x 3 methods x 2 events x H1/H3/H6
- **Prototype limitations**: Retained in all metric records and metadata

### Demo-Readiness Checklist

- [x] Static vulnerability map (M1 Day 2, `data/m1/static_risk_scores.*`)
- [x] Forecast ingestion (B1 Day 2, Open-Meteo + JSON cache + SQLite)
- [x] H1/H3/H6 predictions (M1 Day 3 + B1 Day 3 pipeline)
- [x] Risk tiers (LOW / MEDIUM / HIGH at prob <0.40 / <0.70 / ≥0.70)
- [x] Risk explanations with non-causal disclaimer (M1 Day 4)
- [x] Backtest results (ML / heuristic / rainfall-baseline, M1 Day 5)
- [x] Failure handling & structured error isolation (M1 Day 6)
- [x] Existing B1/B2 integration preserved (283/283 tests pass)
- [x] Dashboard integration stubs present (B2 Day 2–4, F1/F2)
- [x] No broken tests

> [!IMPORTANT]
> Validated 2026-09-27. No commits or pushes were made during M1 Day 7. See `docs/M1_FINAL_VALIDATION.md` for the full validation report.

## Geospatial Data Ingestion & Pilot Grid (B1 Day 1)


Chetna establishes the core spatial foundation for the Chennai flood early-warning pilot area, implementing a uniform ~200 m metric grid, digital elevation model (DEM) ingestion and preprocessing, OpenStreetMap (OSM) infrastructure ingestion, and an extended SQLite spatial schema.

### Pilot Area & Spatial Configuration
- **Pilot Bounds**: Chennai Metropolitan pilot area covering:
  - Latitude: `12.9150° N – 13.1110° N`
  - Longitude: `80.0640° E – 80.2660° E`
  - Pilot Center: `[13.0827, 80.2707]` (matches dashboard default)
- **Authoritative CRS**:
  - **Geographic CRS**: `EPSG:4326` (WGS 84) — Used for interchange, API calls, Folium maps, and GeoJSON export.
  - **Projected Metric CRS**: `EPSG:32644` (WGS 84 / UTM Zone 44N) — Authoritative metric projection for Chennai (~80.27° E). Metric grid generation, distance measurements, and road lengths are computed in this projected space.
- **Grid Resolution**: Uniform `200 m x 200 m` metric cells (`40,000 m²` nominal area per cell).
  - Generates 11,990 regular cells covering the pilot area.
  - Deterministic cell ID format: `CELL_R{row:03d}_C{col:03d}`.
  - Each cell contains: `cell_id`, `row`, `col`, `centroid_lat`, `centroid_lon`, `elevation_m`, `geometry` (Polygon in EPSG:4326), `resolution_m`, `crs`, and `projected_crs`.

### Data Ingestion & Sources
1. **Digital Elevation Model (DEM)**:
   - **Source**: Copernicus DEM GLO-30 (30m resolution) / SRTM 30m.
   - **Downloader**: `src/ingestion/dem.py` supports download via OpenTopography API (`download_dem_opentopography`).
   - **Preprocessing**: `attach_elevation_to_grid` samples DEM raster values at cell centroids using `rasterio`, validates CRS alignments, handles nodata values, and populates `elevation_m` for every grid cell.
   - **Local Cache**: Saved to `data/dem/chennai_dem_30m.tif`.
2. **OpenStreetMap (OSM) Critical Infrastructure**:
   - **Source**: OpenStreetMap via Overpass API / OSMnx 2.1.1.
   - **Layers Ingested**:
     - *Roads*: Arterial and collector transit network (`highway` motorway, trunk, primary, secondary, tertiary, residential). Metric lengths computed in UTM 44N.
     - *Hospitals*: Healthcare and emergency trauma centers (`amenity=hospital`).
     - *Schools*: Educational institutions and potential relief staging sites (`amenity=school, college, university`).
     - *Shelters*: Designated flood relief and community shelters (`amenity=shelter, community_centre, social_facility`).
   - **Local Cache**: Saved to `data/osm/chennai_{layer}.geojson`.

### Distinction: Real Data vs. Synthetic Fixtures
| Asset | Production / Real Path | Synthetic Test Fixture | Notes |
| :--- | :--- | :--- | :--- |
| **Grid** | `data/b1/grid_200m.geojson` | N/A (deterministic algorithm) | 11,990 cells generated deterministically from UTM 44N bounds. |
| **DEM Raster** | `data/dem/chennai_dem_30m.tif` | `tests/fixtures/chennai_dem_fixture.tif` | Fixture is a procedural gradient tagged with `is_synthetic: "true"`. |
| **OSM Roads** | `data/osm/chennai_roads.geojson` | `tests/fixtures/osm_roads_fixture.geojson` | Fixture contains 5 major Chennai corridors; tagged with `is_synthetic: true`. |
| **Hospitals** | `data/osm/chennai_hospitals.geojson` | `tests/fixtures/osm_hospitals_fixture.geojson` | Fixture contains 5 verified Chennai medical centers; tagged with `is_synthetic: true`. |
| **Schools** | `data/osm/chennai_schools.geojson` | `tests/fixtures/osm_schools_fixture.geojson` | Fixture contains 5 verified institutions; tagged with `is_synthetic: true`. |
| **Shelters** | `data/osm/chennai_shelters.geojson` | `tests/fixtures/osm_shelters_fixture.geojson` | Fixture contains 5 elevated transit/community hubs; tagged with `is_synthetic: true`. |

*Note: The 38-cell synthetic M1 grid (`data/m1/synthetic_grid_features.json`) remains isolated for M1 static risk test coverage and is not conflated with the B1 Day 1 pilot grid.*

### SQLite Spatial Schema
Extends `data/chetna.db` without altering the existing `forecasts` table:
- `grid_cells`: Stores all 200m cells (`cell_id`, `row`, `col`, `centroid_lat`, `centroid_lon`, `elevation_m`, `geometry_geojson`, `crs`, `projected_crs`, `resolution_m`).
- `roads`: Stores road segments (`osm_id`, `name`, `highway`, `length_m`, `geometry_geojson`, `source`, `is_synthetic`).
- `hospitals`: Stores hospital locations (`osm_id`, `name`, `latitude`, `longitude`, `geometry_geojson`, `source`, `is_synthetic`).
- `schools`: Stores school locations (`osm_id`, `name`, `latitude`, `longitude`, `geometry_geojson`, `source`, `is_synthetic`).
- `shelters`: Stores emergency shelter locations (`osm_id`, `name`, `latitude`, `longitude`, `geometry_geojson`, `source`, `is_synthetic`).
- `spatial_metadata`: Records dataset provenance, source, CRS, and record counts.

### Running Ingestion & Tests Locally
```powershell
# 1. Run full B1 Day 1 ingestion pipeline (offline mode using verified fixtures):
python scripts/ingest_b1_data.py

# 2. Run with live OSM download (requires active network):
python scripts/ingest_b1_data.py --live-osm

# 3. Run with live DEM download (requires OPENTOPOGRAPHY_API_KEY environment variable):
python scripts/ingest_b1_data.py --live-dem

# 4. Run automated tests offline:
pytest tests/test_b1_spatial_data.py -v
pytest -v
```

## Forecast-to-Risk Pipeline (B1 Day 3)

Chetna B1 Day 3 connects weather ingestion, stored forecasts, spatial vulnerability cells, and heuristic risk modeling into an automated risk prediction pipeline.

### Pipeline Flow
```text
Open-Meteo Weather Forecast API
             ↓
fetch_and_store_forecast() & JSON caching
             ↓
SQLite forecasts table (rain_1h, rain_3h, rain_6h)
             ↓
SQLite cells table (elevation, slope, flow_acc, vulnerability)
             ↓
FloodRiskPredictor.predict_from_forecast()
  • rain_1h → Horizon 1 (+1h)
  • rain_3h → Horizon 3 (+3h)
  • rain_6h → Horizon 6 (+6h)
  • Dynamic Probability: P = 0.65 * S_rain + 0.35 * Vulnerability
             ↓
SQLite risk_predictions table (cell_id, timestamp, horizon, level, probability)
```

### Heuristic Risk Scoring Formula
- **Horizon Critical Rainfall**:
  - Horizon 1 (+1h): $R_{crit} = 50.0\text{ mm}$
  - Horizon 3 (+3h): $R_{crit} = 80.0\text{ mm}$
  - Horizon 6 (+6h): $R_{crit} = 120.0\text{ mm}$
- **Rainfall Factor**: $S_{rain} = \min(1.0, \frac{\text{rainfall\_mm}}{R_{crit}})$
- **Static Vulnerability Factor**: $V = \text{clamp}(vulnerability, 0.0, 1.0)$ (defaults to 0.50 if unspecified)
- **Combined Probability**: $P = 0.65 \cdot S_{rain} + 0.35 \cdot V$ (bounded $0.0 \le P \le 1.0$)
- **Classification**:
  - **HIGH**: $P \ge 0.70$
  - **MEDIUM**: $0.40 \le P < 0.70$
  - **LOW**: $P < 0.40$

### Running the Pipeline
```powershell
# Run programmatically
python -c "from src.pipeline import run_pipeline; res = run_pipeline(); print(res)"

# Run via CLI module
python -m src.pipeline

# Run via scripts wrapper
python scripts/run_pipeline.py
```

## Safe-Routing and Safest-Location Engine (B1 Day 4)

Chetna B1 Day 4 implements the safest-location engine that connects road networks, ~200 m flood-risk predictions, and emergency shelters using an A* pathfinding algorithm.

### Architecture & Routing Engine
```text
Origin Location (lat, lon)
           ↓
Candidate Shelters (B1 OSM Shelters / DB)
           ↓
Proximity Ranking & Flood Safety Pre-Filter
           ↓
Road Network Graph (B1 Spatial Roads / OSMnx)
           ↓
Connect Graph Nodes to 200m Risk Grid (cells / risk_predictions)
           ↓
A* Pathfinding with Dynamic Hazard Penalties
  • HIGH Risk Cells: Blocked / Heavily Penalized (+100,000 m)
  • MEDIUM Risk Cells: Moderately Penalized (+500 m)
           ↓
Safe Route to Nearest Reachable Safe Shelter
```

### Key Functions
- `safe_route(lat, lon, horizon=1, db_path=DEFAULT_DB_PATH, ...)`: Framework function to calculate a safe route from origin to the nearest reachable shelter.
- `build_road_graph_from_roads(roads_gdf)`: Converts road LineStrings into a bidirectional NetworkX `MultiDiGraph`.
- `connect_graph_to_grid(graph, grid_cells)`: Maps graph nodes to ~200 m metric grid cells.
- `apply_risk_predictions_to_graph(graph, risk_predictions)`: Applies multi-horizon dynamic flood predictions to graph nodes.

### Usage
```python
from src.routing import safe_route

# Find safe route from current location
result = safe_route(13.0, 80.0)
if result["found"]:
    print(f"Safe route found to {result['destination']['name']} ({result['distance_m']} m)")
    for pt in result["route"]:
        print(f" -> {pt['lat']}, {pt['lon']}")
else:
    print(result["message"])
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
