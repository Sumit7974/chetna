"""Tests for Chetna B1 Day 3 Forecast-to-Risk Pipeline.

Verifies:
1. Pipeline executes offline using cached / mock weather fixtures.
2. Forecast values (rain_1h, rain_3h, rain_6h, timestamp) are read correctly from SQLite.
3. Spatial cells from the 'cells' table are correctly queried and processed.
4. Horizons +1h, +3h, and +6h are generated for every cell.
5. 'risk_predictions' receives the exact cell_id values.
6. 'risk_predictions' records horizons 1, 3, and 6 for every cell.
7. Probabilities are strictly bounded between 0.0 and 1.0.
8. Risk levels are strictly categorized as LOW, MEDIUM, or HIGH.
9. Pipeline execution does not break or overwrite existing B2 tables (sensor_nodes, alerts, etc.).
10. Empty 'cells' table raises a clean, descriptive EmptyCellsError.
11. Pipeline gracefully falls back to cached forecast data when network fails.
12. FloodRiskPredictor.predict_from_forecast() heuristic logic and bounds.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from database.db import init_db
from src.ingestion.weather import (
    HourlyForecastRecord,
    OpenMeteoConnectionError,
    RainfallSummary,
    WeatherForecastResult,
    load_mock_forecast,
)
from src.model.predictor import FloodRiskPredictor, RiskPrediction
from src.pipeline import (
    EmptyCellsError,
    ForecastUnavailableError,
    PipelineResult,
    run_pipeline,
)

FIXTURES_DIR = Path("tests/fixtures")
SAMPLE_WEATHER_FIXTURE = FIXTURES_DIR / "sample_openmeteo_response.json"


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Create a temporary SQLite database initialized with Chetna schema."""
    db_file = tmp_path / "test_chetna_b1_day3.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def populated_temp_db(temp_db_path: Path) -> Path:
    """Provide a temporary database populated with representative spatial cells."""
    sample_cells = [
        ("CELL_VEL_01", '{"type":"Polygon","coordinates":[]}', 6.5, 0.2, 85000.0, 0.88),
        ("CELL_MAD_02", '{"type":"Polygon","coordinates":[]}', 7.2, 0.4, 62000.0, 0.74),
        ("CELL_MUD_03", '{"type":"Polygon","coordinates":[]}', 12.0, 1.2, 12000.0, 0.35),
        ("CELL_TAM_04", '{"type":"Polygon","coordinates":[]}', 22.0, 3.5, 3000.0, 0.18),
    ]
    with sqlite3.connect(str(temp_db_path)) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO cells (id, geometry, elevation, slope, flow_acc, vulnerability)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            sample_cells,
        )
    return temp_db_path


@pytest.fixture
def mock_weather_result() -> WeatherForecastResult:
    """Load mock WeatherForecastResult from existing sample fixture."""
    return load_mock_forecast(SAMPLE_WEATHER_FIXTURE)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_pipeline_offline_with_fixture(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """1. Pipeline runs completely offline when patched with existing weather fixture."""
    with patch("src.pipeline.fetch_and_store_forecast") as mock_fetch:
        # Simulate fetch_and_store_forecast saving to db and returning result
        def fake_fetch(*args, **kwargs):
            mock_weather_result.save_to_db(populated_temp_db)
            mock_weather_result.used_cached_data = True
            return mock_weather_result, 1

        mock_fetch.side_effect = fake_fetch

        result = run_pipeline(
            latitude=13.0827,
            longitude=80.2707,
            db_path=populated_temp_db,
            use_cache_on_failure=True,
        )

        assert isinstance(result, PipelineResult)
        assert result.cells_processed == 4
        assert result.predictions_created == 12  # 4 cells * 3 horizons
        assert result.horizons_processed == [1, 3, 6]
        assert result.used_cached_forecast is True


def test_forecast_read_correctly_from_sqlite(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """2. Verify forecast values are read faithfully from SQLite table 'forecasts'."""
    # Pre-seed forecast into database
    row_id = mock_weather_result.save_to_db(populated_temp_db)

    with patch("src.pipeline.fetch_and_store_forecast") as mock_fetch:
        mock_fetch.return_value = (mock_weather_result, row_id)

        result = run_pipeline(db_path=populated_temp_db)

        # Inspect SQLite row
        with sqlite3.connect(str(populated_temp_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM forecasts WHERE id = ?", (row_id,)).fetchone()

        assert result.forecast_timestamp == row["timestamp"]
        assert result.forecast_rain_1h == row["rain_1h"]
        assert result.forecast_rain_3h == row["rain_3h"]
        assert result.forecast_rain_6h == row["rain_6h"]


def test_existing_cells_processed(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """3. Verify all available cells from 'cells' table are processed."""
    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        result = run_pipeline(db_path=populated_temp_db)
        assert result["cells_processed"] == 4
        assert result.cells_processed == 4


def test_horizons_1_3_6_generated(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """4. Verify risk predictions are produced for each required horizon (+1h, +3h, +6h)."""
    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        result = run_pipeline(db_path=populated_temp_db)
        horizons_in_preds = {p.horizon for p in result.predictions}
        assert horizons_in_preds == {1, 3, 6}


def test_risk_predictions_receives_correct_cell_ids(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """5. Verify 'risk_predictions' table records contain the exact source cell_ids."""
    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        run_pipeline(db_path=populated_temp_db)

    expected_ids = {"CELL_VEL_01", "CELL_MAD_02", "CELL_MUD_03", "CELL_TAM_04"}
    with sqlite3.connect(str(populated_temp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT DISTINCT cell_id FROM risk_predictions;").fetchall()
        db_cell_ids = {r["cell_id"] for r in rows}

    assert db_cell_ids == expected_ids


def test_risk_predictions_receives_horizons_1_3_6(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """6. Verify 'risk_predictions' table stores horizons 1, 3, and 6 for every cell."""
    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        run_pipeline(db_path=populated_temp_db)

    with sqlite3.connect(str(populated_temp_db)) as conn:
        conn.row_factory = sqlite3.Row
        for cell_id in ["CELL_VEL_01", "CELL_MAD_02", "CELL_MUD_03", "CELL_TAM_04"]:
            rows = conn.execute(
                "SELECT horizon FROM risk_predictions WHERE cell_id = ? ORDER BY horizon;",
                (cell_id,),
            ).fetchall()
            cell_horizons = [r["horizon"] for r in rows]
            assert cell_horizons == [1, 3, 6], f"Cell {cell_id} did not have horizons [1, 3, 6]"


def test_probabilities_bounded_between_0_and_1(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """7. Verify all predicted probabilities are numeric and within [0.0, 1.0]."""
    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        result = run_pipeline(db_path=populated_temp_db)

    for p in result.predictions:
        assert isinstance(p.probability, float)
        assert 0.0 <= p.probability <= 1.0, f"Probability out of range: {p.probability}"

    with sqlite3.connect(str(populated_temp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT probability FROM risk_predictions;").fetchall()
        for r in rows:
            prob = float(r["probability"])
            assert 0.0 <= prob <= 1.0


def test_risk_levels_valid_categories(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """8. Verify all risk levels are categorized strictly as LOW, MEDIUM, or HIGH."""
    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        result = run_pipeline(db_path=populated_temp_db)

    valid_levels = {"LOW", "MEDIUM", "HIGH"}
    for p in result.predictions:
        assert p.level in valid_levels, f"Invalid risk level: {p.level}"


def test_running_pipeline_does_not_break_b2_tables(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """9. Verify pipeline execution does not overwrite or corrupt existing B2 tables."""
    # Seed B2 tables
    with sqlite3.connect(str(populated_temp_db)) as conn:
        conn.execute(
            """
            INSERT INTO sensor_nodes (node_id, name, latitude, longitude, sensor_type)
            VALUES ('NODE_VEL_01', 'Velachery Lake Monitor', 12.98, 80.22, 'water_level');
            """
        )
        conn.execute(
            """
            INSERT INTO alerts (alert_id, severity, message)
            VALUES ('ALT_TEST_01', 'CRITICAL', 'Simulated water level alert');
            """
        )

    mock_weather_result.save_to_db(populated_temp_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        run_pipeline(db_path=populated_temp_db)

    # Verify B2 tables remain intact
    with sqlite3.connect(str(populated_temp_db)) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute("SELECT * FROM sensor_nodes WHERE node_id = 'NODE_VEL_01';").fetchone()
        assert node is not None
        assert node["name"] == "Velachery Lake Monitor"

        alert = conn.execute("SELECT * FROM alerts WHERE alert_id = 'ALT_TEST_01';").fetchone()
        assert alert is not None
        assert alert["severity"] == "CRITICAL"


def test_empty_cells_table_handled_cleanly(temp_db_path: Path, mock_weather_result: WeatherForecastResult):
    """10. Verify empty 'cells' table raises a clean EmptyCellsError without fabricating data."""
    mock_weather_result.save_to_db(temp_db_path)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(mock_weather_result, 1)):
        with pytest.raises(EmptyCellsError, match="No spatial cells found"):
            run_pipeline(db_path=temp_db_path)


def test_cached_forecast_used_when_openmeteo_unavailable(populated_temp_db: Path, mock_weather_result: WeatherForecastResult):
    """11. Verify pipeline falls back to cached/stored forecast when Open-Meteo API is unreachable."""
    # Pre-seed a forecast into the database
    mock_weather_result.save_to_db(populated_temp_db)

    # Simulate network failure during fetch
    with patch("src.pipeline.fetch_and_store_forecast") as mock_fetch:
        mock_fetch.side_effect = OpenMeteoConnectionError("Connection timed out to api.open-meteo.com")

        result = run_pipeline(db_path=populated_temp_db, use_cache_on_failure=True)

        assert result.used_cached_forecast is True
        assert result.cells_processed == 4
        assert result.predictions_created == 12


def test_predictor_predict_from_forecast_heuristic(temp_db_path: Path):
    """12. Unit test FloodRiskPredictor.predict_from_forecast heuristic formula."""
    predictor = FloodRiskPredictor(db_path=temp_db_path)

    # Test A: Zero rainfall on low vulnerability cell -> LOW risk
    pred_dry = predictor.predict_from_forecast(rainfall_mm=0.0, cell_id="CELL_TEST", horizon=1, vulnerability=0.1)
    assert pred_dry.level == "LOW"
    assert pred_dry.probability < 0.40

    # Test B: Torrential rain (70 mm in 1h) -> HIGH risk
    pred_storm = predictor.predict_from_forecast(rainfall_mm=70.0, cell_id="CELL_TEST", horizon=1, vulnerability=0.8)
    assert pred_storm.level == "HIGH"
    assert pred_storm.probability >= 0.70

    # Test C: Moderate rain (25 mm in 1h) with moderate vulnerability -> MEDIUM risk
    pred_mod = predictor.predict_from_forecast(rainfall_mm=25.0, cell_id="CELL_TEST", horizon=1, vulnerability=0.6)
    assert pred_mod.level == "MEDIUM"
    assert 0.40 <= pred_mod.probability < 0.70

    # Test D: Invalid horizon raises ValueError
    with pytest.raises(ValueError, match="Invalid horizon"):
        predictor.predict_from_forecast(rainfall_mm=10.0, cell_id="CELL_TEST", horizon=2)


def test_pipeline_missing_forecast_fails_gracefully(populated_temp_db: Path):
    """Verify pipeline raises ForecastUnavailableError when no forecast exists anywhere."""
    with patch("src.pipeline.fetch_and_store_forecast", side_effect=RuntimeError("Network offline and no cache")):
        with pytest.raises(ForecastUnavailableError, match="No forecast record available"):
            run_pipeline(db_path=populated_temp_db)
