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

from src.ingestion.pilot_config import PILOT_CENTER_LAT, PILOT_CENTER_LON

# Authoritative Patna pilot coordinates
DEFAULT_LATITUDE = PILOT_CENTER_LAT
DEFAULT_LONGITUDE = PILOT_CENTER_LON

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
# Data Models & Failure Reporting (M1 Day 6)
# ---------------------------------------------------------------------------

from src.model.failure_isolation import (
    CellFailureRecord,
    validate_risk_prediction_contract,
    validate_sensor_reading_contract,
)


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
        failed_cells: Optional[List[Dict[str, Any]]] = None,
        failed_cell_count: int = 0,
        **kwargs: Any,
    ) -> None:
        failed_list = failed_cells or []
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
            failed_cells=failed_list,
            failed_cell_count=failed_cell_count or len(failed_list),
            **kwargs,
        )
        self.predictions: List[RiskPrediction] = predictions or []
        self.failed_cells: List[Dict[str, Any]] = failed_list
        self.failed_cell_count: int = failed_cell_count or len(failed_list)

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        raise AttributeError(f"'PipelineResult' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("predictions", "failed_cells", "failed_cell_count"):
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
    predictor_mode: str = "heuristic",
    model_dir: Optional[Union[str, Path]] = None,
    include_explanations: bool = False,
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
        latitude: Target pilot latitude (default: Patna 25.6093).
        longitude: Target pilot longitude (default: Patna 85.1376).
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

    # Resolve location name for forecast persistence contract
    loc_name = "Patna Pilot Municipal Area" if (24.0 <= latitude <= 27.0 and 83.0 <= longitude <= 87.0) else "Chennai Pilot Area"

    # 1. Fetch & Store Open-Meteo Forecast
    try:
        weather_result, _ = fetch_and_store_forecast(
            latitude=latitude,
            longitude=longitude,
            db_path=db_path,
            reference_time=reference_time,
            cache_dir=cache_dir,
            use_cache_on_failure=use_cache_on_failure,
            location_name=loc_name,
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

    predictor = FloodRiskPredictor(db_path=db_path, mode=predictor_mode, model_dir=model_dir)
    all_predictions: List[RiskPrediction] = []
    failed_cells: List[Dict[str, Any]] = []

    for horizon in target_horizons:
        rainfall = horizon_rainfall_map.get(horizon, rain_1h)
        for cell in cells:
            cell_id = str(cell.get("id") or cell.get("cell_id") or "UNKNOWN_CELL")
            vuln = cell.get("vulnerability")

            try:
                pred = predictor.predict_from_forecast(
                    rainfall_mm=rainfall,
                    cell_id=cell_id,
                    horizon=horizon,
                    vulnerability=vuln,
                    timestamp=forecast_ts,
                    persist=False,
                    explain=include_explanations,
                )
                all_predictions.append(pred)
            except Exception as cell_err:
                logger.warning(
                    "Isolated failure for cell %s at horizon +%dh: %s",
                    cell_id, horizon, cell_err
                )
                fail_rec = CellFailureRecord(
                    cell_id=cell_id,
                    stage="prediction",
                    error_type=type(cell_err).__name__,
                    message=str(cell_err),
                    recoverable=True,
                    horizon=horizon,
                )
                failed_cells.append(fail_rec.to_dict())

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
        failed_cells=failed_cells,
        failed_cell_count=len(failed_cells),
    )
    logger.info("Pipeline run complete: %d predictions across %s horizons", len(all_predictions), target_horizons)
    return result


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line interface for executing the B1 Day 3 pipeline."""
    parser = argparse.ArgumentParser(description="Chetna B1 Day 3 Forecast-to-Risk Pipeline")
    parser.add_argument("--lat", type=float, default=DEFAULT_LATITUDE, help=f"Latitude (default: Patna {DEFAULT_LATITUDE})")
    parser.add_argument("--lon", type=float, default=DEFAULT_LONGITUDE, help=f"Longitude (default: Patna {DEFAULT_LONGITUDE})")
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
