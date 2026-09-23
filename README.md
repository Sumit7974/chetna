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
