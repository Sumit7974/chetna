"""Unit and integration tests for Chetna B1 Day 2 Open-Meteo Forecast Fetcher + JSON Cache + DB Integration."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from database.db import init_db as init_full_db
from src.db.forecasts import (
    get_db_connection,
    get_forecast_by_timestamp,
    get_forecast_history,
    get_latest_forecast,
    init_db,
    save_forecast,
)
from src.ingestion.pilot_config import PILOT_CENTER_LAT, PILOT_CENTER_LON
from src.ingestion.weather import (
    DataParsingError,
    HourlyForecastRecord,
    OpenMeteoAPIError,
    OpenMeteoClient,
    OpenMeteoConnectionError,
    RainfallSummary,
    WeatherForecastResult,
    fetch_and_store_forecast,
    fetch_weather_forecast,
    load_mock_forecast,
    parse_weather_response,
)
from src.pipeline import run_pipeline


@pytest.fixture
def sample_json():
    """Load the sample Open-Meteo response fixture."""
    fixture_path = Path("tests/fixtures/sample_openmeteo_response.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_openmeteo_response_parsing_fixture(sample_json):
    """Successful Open-Meteo response parsing using local fixture data."""
    result = parse_weather_response(sample_json, reference_time="2026-09-24T00:00")

    assert isinstance(result, WeatherForecastResult)
    assert round(result.latitude, 4) == 13.0827
    assert round(result.longitude, 4) == 80.2707
    assert result.timezone == "Asia/Kolkata"
    assert result.reference_time == "2026-09-24T00:00"
    assert len(result.hourly_records) == 48

    # Check data contract fields
    assert result.location_name == "Chennai Pilot Area"
    assert result.source == "Open-Meteo"
    assert result.retrieval_timestamp is not None
    assert result.summary.rain_1h >= 0.0
    assert result.summary.rain_3h >= 0.0
    assert result.summary.rain_6h >= 0.0


def test_extract_next_6_hours(sample_json):
    """Extraction of the next 6 hours of forecast data required by the framework."""
    result = parse_weather_response(sample_json, reference_time="2026-09-24T00:00")

    next_6 = result.next_6h_records
    assert len(next_6) == 6

    # Verify chronological sequence and timestamps
    expected_times = [
        "2026-09-24T00:00",
        "2026-09-24T01:00",
        "2026-09-24T02:00",
        "2026-09-24T03:00",
        "2026-09-24T04:00",
        "2026-09-24T05:00",
    ]
    for rec, exp_t in zip(next_6, expected_times):
        assert isinstance(rec, HourlyForecastRecord)
        assert rec.timestamp == exp_t
        assert rec.rain_mm >= 0.0

    # Verify cumulative horizon matches sum of hourly
    sum_1h = next_6[0].rain_mm
    sum_3h = sum(r.rain_mm for r in next_6[:3])
    sum_6h = sum(r.rain_mm for r in next_6[:6])

    assert round(result.summary.rain_1h, 2) == round(sum_1h, 2)
    assert round(result.summary.rain_3h, 2) == round(sum_3h, 2)
    assert round(result.summary.rain_6h, 2) == round(sum_6h, 2)
    assert result.get_horizon_rain(1) == result.summary.rain_1h
    assert result.get_horizon_rain(3) == result.summary.rain_3h
    assert result.get_horizon_rain(6) == result.summary.rain_6h


def test_json_cache_creation_and_loading(tmp_path, sample_json):
    """JSON cache files are created with deterministic location/timestamp naming and loaded."""
    client = OpenMeteoClient(cache_dir=tmp_path)

    # Save cache
    cache_file = client._get_cache_filepath(13.0827, 80.2707)
    assert "forecast_13_0827_80_2707_latest.json" in cache_file.name

    client._save_cache(cache_file, sample_json)

    # Verify cache file exists
    assert cache_file.exists()

    # Load cache directly
    loaded_data = client._load_cache(cache_file)
    assert loaded_data["latitude"] == sample_json["latitude"]

    # Verify _find_cached_file locates the cache
    found = client._find_cached_file(13.0827, 80.2707)
    assert found is not None
    assert found.exists()


def test_cache_fallback_on_network_failure(tmp_path, sample_json):
    """Graceful fallback to local JSON cache when network/API call fails."""
    client = OpenMeteoClient(cache_dir=tmp_path)
    cache_file = client._get_cache_filepath(13.0827, 80.2707)
    client._save_cache(cache_file, sample_json)

    # Simulate network failure during fetch_raw_forecast
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network down")):
        data, from_cache = client.fetch_raw_forecast(
            13.0827,
            80.2707,
            use_cache_on_failure=True,
        )

        assert from_cache is True
        assert data["latitude"] == sample_json["latitude"]

        # Parse and verify from_cache flag propagates
        result = client.parse_forecast(data, from_cache=from_cache)
        assert result.from_cache is True
        assert result.used_cached_data is True


def test_database_persistence(tmp_path, sample_json):
    """Database integration stores forecast data with full metadata contract."""
    db_file = tmp_path / "test_forecasts.db"
    init_db(db_file)

    result = parse_weather_response(sample_json, reference_time="2026-09-24T00:00")
    row_id = result.save_to_db(db_path=db_file)
    assert row_id > 0

    latest = get_latest_forecast(db_path=db_file)
    assert latest is not None
    assert latest["timestamp"] == "2026-09-24T00:00"
    assert latest["rain_1h"] == result.summary.rain_1h
    assert latest["rain_3h"] == result.summary.rain_3h
    assert latest["rain_6h"] == result.summary.rain_6h
    assert latest["location"] == "Chennai Pilot Area"
    assert latest["source"] == "Open-Meteo"
    assert "retrieval_timestamp" in latest


def test_malformed_and_empty_api_response():
    """Malformed or empty API responses raise DataParsingError without crash."""
    client = OpenMeteoClient()

    # Empty dictionary
    with pytest.raises(DataParsingError, match="Missing required key"):
        client.parse_forecast({})

    # Missing hourly key
    with pytest.raises(DataParsingError, match="Missing required key 'hourly'"):
        client.parse_forecast({"latitude": 13.0, "longitude": 80.0})

    # Empty time array
    with pytest.raises(DataParsingError, match="No hourly timestamps found"):
        client.parse_forecast({"latitude": 13.0, "longitude": 80.0, "hourly": {"time": []}})

    # Empty precipitation array
    with pytest.raises(DataParsingError, match="Empty forecast"):
        client.parse_forecast({
            "latitude": 13.0,
            "longitude": 80.0,
            "hourly": {"time": ["2026-09-24T00:00"], "precipitation": []},
        })


def test_network_failure_without_cache(tmp_path):
    """Network failure with no cache available raises OpenMeteoConnectionError."""
    client = OpenMeteoClient(cache_dir=tmp_path)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(OpenMeteoConnectionError):
            client.fetch_raw_forecast(
                13.0827,
                80.2707,
                use_cache_on_failure=True,
            )


def test_invalid_coordinate_configuration():
    """Non-numeric coordinates raise ValueError."""
    client = OpenMeteoClient()

    with pytest.raises(ValueError):
        client.fetch_raw_forecast("invalid_lat", 80.0)

    with pytest.raises(ValueError):
        client.fetch_raw_forecast(13.0, "invalid_lon")


def test_b1_day3_pipeline_compatibility(tmp_path, sample_json):
    """Verify B1 Day 3 pipeline executes seamlessly using the cached forecast."""
    db_file = tmp_path / "test_pipeline.db"
    cache_dir = tmp_path / "cache"

    # Initialize full schema (forecasts, cells, risk_predictions)
    init_full_db(db_file)

    # Pre-seed forecast cache
    client = OpenMeteoClient(cache_dir=cache_dir)
    cache_file = client._get_cache_filepath(PILOT_CENTER_LAT, PILOT_CENTER_LON)
    client._save_cache(cache_file, sample_json)

    # Populate sample cells
    conn = sqlite3.connect(str(db_file))
    with conn:
        for i in range(1, 4):
            conn.execute(
                "INSERT INTO cells (id, elevation, slope, flow_acc, vulnerability) VALUES (?, ?, ?, ?, ?)",
                (f"CELL_{i:03d}", 8.0, 1.2, 100.0, 0.45),
            )
    conn.close()

    # Execute B1 Day 3 pipeline with simulated network failure (cache fallback)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Offline")):
        pipeline_result = run_pipeline(
            latitude=PILOT_CENTER_LAT,
            longitude=PILOT_CENTER_LON,
            db_path=db_file,
            cache_dir=cache_dir,
            use_cache_on_failure=True,
            reference_time="2026-09-24T00:00",
        )

    assert pipeline_result.cells_processed == 3
    assert pipeline_result.predictions_created == 9  # 3 cells x 3 horizons
    assert pipeline_result.used_cached_forecast is True

    # Verify risk_predictions table contains populated predictions
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM risk_predictions")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 9
