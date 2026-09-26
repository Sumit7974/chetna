"""Backend forecast-to-risk pipeline for Chetna (B1 Day 3).

Connects:
    Open-Meteo forecast
            ↓
    stored forecasts
            ↓
    existing spatial/static cell data
            ↓
    risk prediction
            ↓
    risk_predictions table

Produces risk predictions across required forecast horizons (+1h, +3h, +6h)
and persists results into the existing SQLite database contract.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from database.db import DEFAULT_DB_PATH, get_db_connection
from src.db.forecasts import get_latest_forecast
from src.ingestion.weather import (
    WeatherForecastResult,
    WeatherIngestionError,
    fetch_and_store_forecast,
)
from src.model.predictor import FloodRiskPredictor, RiskPrediction

logger = logging.getLogger(__name__)

# Default Chennai pilot coordinates
DEFAULT_LATITUDE = 13.0827
DEFAULT_LONGITUDE = 80.2707

# Authoritative forecast horizons
REQUIRED_HORIZONS: List[int] = [1, 3, 6]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PipelineError(Exception):
    """Base exception for pipeline execution failures."""
    pass


class EmptyCellsError(PipelineError, ValueError):
    """Raised when the database 'cells' table is empty or missing."""
    pass


class ForecastUnavailableError(PipelineError, RuntimeError):
    """Raised when weather forecast data cannot be fetched or retrieved from database."""
    pass


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class PipelineResult(dict):
    """Structured summary of pipeline execution supporting both dict and attribute access."""

    def __init__(
        self,
        forecast_timestamp: str,
        cells_processed: int,
        predictions_created: int,
        horizons_processed: List[int],
        used_cached_forecast: bool,
        forecast_id: Optional[int] = None,
        forecast_rain_1h: float = 0.0,
        forecast_rain_3h: float = 0.0,
        forecast_rain_6h: float = 0.0,
        predictions: Optional[List[RiskPrediction]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            forecast_timestamp=forecast_timestamp,
            cells_processed=cells_processed,
            predictions_created=predictions_created,
            horizons_processed=horizons_processed,
            used_cached_forecast=used_cached_forecast,
            forecast_id=forecast_id,
            forecast_rain_1h=forecast_rain_1h,
            forecast_rain_3h=forecast_rain_3h,
            forecast_rain_6h=forecast_rain_6h,
            **kwargs,
        )
        self.predictions: List[RiskPrediction] = predictions or []

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        raise AttributeError(f"'PipelineResult' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "predictions":
            super().__setattr__(name, value)
        else:
            self[name] = value


# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------

def _get_cells_from_db(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Query available cells from the 'cells' table."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        # Verify table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cells';")
        if not cursor.fetchone():
            return []
        cursor.execute("SELECT id, geometry, elevation, slope, flow_acc, vulnerability FROM cells ORDER BY id;")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Core Pipeline Execution
# ---------------------------------------------------------------------------

def run_pipeline(
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    horizons: Optional[Sequence[int]] = None,
    reference_time: Optional[Union[datetime.datetime, str]] = None,
    cache_dir: Optional[Union[str, Path]] = "data/cache",
    use_cache_on_failure: bool = True,
    persist: bool = True,
) -> PipelineResult:
    """Execute the end-to-end B1 Day 3 forecast-to-risk prediction pipeline.

    Workflow:
        1. Fetch/store latest Open-Meteo forecast into SQLite 'forecasts' table.
        2. Read latest forecast record from SQLite.
        3. Query spatial cells and vulnerability scores from 'cells' table.
        4. Generate horizon-specific risk predictions (+1h, +3h, +6h) using FloodRiskPredictor.
        5. Persist predictions into the 'risk_predictions' table.
        6. Return execution summary.

    Args:
        latitude: Target pilot latitude (default: Chennai 13.0827).
        longitude: Target pilot longitude (default: Chennai 80.2707).
        db_path: Target SQLite database file or connection (default: data/chetna.db).
        horizons: List of forecast horizons to process (default: [1, 3, 6]).
        reference_time: Optional reference timestamp for forecast window.
        cache_dir: Directory for storing raw weather JSON cache files.
        use_cache_on_failure: Fallback to cached responses on network failure.
        persist: Whether to save predictions to database (default: True).

    Returns:
        PipelineResult summary containing metrics and generated predictions.

    Raises:
        EmptyCellsError: If the 'cells' table is empty or missing.
        ForecastUnavailableError: If forecast data cannot be fetched or read.
    """
    target_horizons = list(horizons) if horizons is not None else REQUIRED_HORIZONS
    used_cached_forecast = False

    logger.info("Executing Chetna B1 Day 3 pipeline for (lat=%.4f, lon=%.4f)", latitude, longitude)

    # 1. Fetch & Store Open-Meteo Forecast
    try:
        weather_result, _ = fetch_and_store_forecast(
            latitude=latitude,
            longitude=longitude,
            db_path=db_path,
            reference_time=reference_time,
            cache_dir=cache_dir,
            use_cache_on_failure=use_cache_on_failure,
        )
        used_cached_forecast = getattr(weather_result, "used_cached_data", False)
    except Exception as exc:
        logger.warning("Weather ingestion encountered issue: %s. Attempting database fallback.", exc)
        used_cached_forecast = True

    # 2. Read Latest Forecast from SQLite
    latest_forecast = get_latest_forecast(db_path=db_path)
    if not latest_forecast:
        raise ForecastUnavailableError(
            f"No forecast record available in SQLite database at '{db_path}'. "
            "Ensure Open-Meteo ingestion succeeded or pre-seed forecasts."
        )

    forecast_ts = str(latest_forecast["timestamp"])
    rain_1h = float(latest_forecast["rain_1h"])
    rain_3h = float(latest_forecast["rain_3h"])
    rain_6h = float(latest_forecast["rain_6h"])

    logger.info(
        "Loaded forecast %s: rain_1h=%.2f mm, rain_3h=%.2f mm, rain_6h=%.2f mm",
        forecast_ts, rain_1h, rain_3h, rain_6h
    )

    # 3. Read Available Spatial Cells
    cells = _get_cells_from_db(db_path=db_path)
    if not cells:
        raise EmptyCellsError(
            f"No spatial cells found in database table 'cells' at '{db_path}'. "
            "Please initialize and populate cells before running the risk pipeline."
        )

    logger.info("Found %d cells in 'cells' table to assess", len(cells))

    # 4. Generate Predictions for Required Horizons
    horizon_rainfall_map: Dict[int, float] = {
        1: rain_1h,
        3: rain_3h,
        6: rain_6h,
    }

    predictor = FloodRiskPredictor(db_path=db_path)
    all_predictions: List[RiskPrediction] = []

    for horizon in target_horizons:
        rainfall = horizon_rainfall_map.get(horizon, rain_1h)
        for cell in cells:
            cell_id = str(cell.get("id") or cell.get("cell_id"))
            vuln = cell.get("vulnerability")

            pred = predictor.predict_from_forecast(
                rainfall_mm=rainfall,
                cell_id=cell_id,
                horizon=horizon,
                vulnerability=vuln,
                timestamp=forecast_ts,
                persist=False,
            )
            all_predictions.append(pred)

    # 5. Persist Predictions to SQLite
    if persist and all_predictions:
        saved_count = predictor.save_predictions_batch(all_predictions)
        logger.info("Persisted %d risk predictions into 'risk_predictions' table", saved_count)

    # 6. Return Structured Execution Summary
    result = PipelineResult(
        forecast_timestamp=forecast_ts,
        cells_processed=len(cells),
        predictions_created=len(all_predictions),
        horizons_processed=target_horizons,
        used_cached_forecast=used_cached_forecast,
        forecast_id=latest_forecast.get("id"),
        forecast_rain_1h=rain_1h,
        forecast_rain_3h=rain_3h,
        forecast_rain_6h=rain_6h,
        predictions=all_predictions,
    )
    logger.info("Pipeline run complete: %d predictions across %s horizons", len(all_predictions), target_horizons)
    return result


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line interface for executing the B1 Day 3 pipeline."""
    parser = argparse.ArgumentParser(description="Chetna B1 Day 3 Forecast-to-Risk Pipeline")
    parser.add_argument("--lat", type=float, default=DEFAULT_LATITUDE, help="Latitude (default: Chennai 13.0827)")
    parser.add_argument("--lon", type=float, default=DEFAULT_LONGITUDE, help="Longitude (default: Chennai 80.2707)")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH), help="SQLite database path")
    parser.add_argument("--cache-dir", type=str, default="data/cache", help="Forecast cache directory")
    parser.add_argument("--no-persist", action="store_true", help="Do not persist predictions to DB")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        res = run_pipeline(
            latitude=args.lat,
            longitude=args.lon,
            db_path=args.db_path,
            cache_dir=args.cache_dir,
            persist=not args.no_persist,
        )
        print("\n--- Chetna B1 Day 3 Pipeline Summary ---")
        print(f"Forecast Timestamp : {res.forecast_timestamp}")
        print(f"Cells Processed    : {res.cells_processed}")
        print(f"Predictions Created: {res.predictions_created}")
        print(f"Horizons Processed : {res.horizons_processed}")
        print(f"Used Cache         : {res.used_cached_forecast}")
        print(f"Rainfall (+1h/+3h/+6h): {res.forecast_rain_1h:.1f} / {res.forecast_rain_3h:.1f} / {res.forecast_rain_6h:.1f} mm")
    except Exception as err:
        logger.error("Pipeline execution failed: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
