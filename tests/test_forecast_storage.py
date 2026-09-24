"""Tests for Chetna Day 2 B1 forecast database storage and 6-hour forecast pipeline integration."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.forecasts import (
    DEFAULT_DB_PATH,
    get_db_connection,
    get_forecast_by_timestamp,
    get_forecast_history,
    get_latest_forecast,
    init_db,
    save_forecast,
)
from src.ingestion.weather import (
    HourlyForecastRecord,
    OpenMeteoClient,
    RainfallSummary,
    WeatherForecastResult,
    fetch_and_store_forecast,
    load_mock_forecast,
    store_forecast_result,
    store_mock_forecast,
)


class TestForecastStorage(unittest.TestCase):
    """Unit tests for SQLite forecast storage, 6-hour forecast retrieval, and caching."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_path = Path(__file__).parent / "fixtures" / "sample_openmeteo_response.json"
        with open(cls.fixture_path, "r", encoding="utf-8") as f:
            cls.sample_json = json.load(f)

    def setUp(self) -> None:
        # Use an in-memory SQLite database connection for isolation
        self.mem_conn = sqlite3.connect(":memory:")
        self.mem_conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.mem_conn.close()

    def test_database_initialization_is_idempotent(self) -> None:
        """Verify database and schema can be initialized repeatedly without error or data loss."""
        # Initialize first time
        init_db(self.mem_conn)

        # Check table exists
        cursor = self.mem_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='forecasts';"
        )
        self.assertIsNotNone(cursor.fetchone())

        # Insert a sample row
        save_forecast(
            {"timestamp": "2026-09-24T00:00", "rain_1h": 2.5, "rain_3h": 7.0, "rain_6h": 15.0},
            db_path=self.mem_conn,
        )

        # Re-initialize; must be safe and preserve existing data
        init_db(self.mem_conn)
        latest = get_latest_forecast(self.mem_conn)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["timestamp"], "2026-09-24T00:00")
        self.assertAlmostEqual(latest["rain_1h"], 2.5)

    def test_save_and_retrieve_forecast(self) -> None:
        """Verify storing and retrieving a forecast record via dict, RainfallSummary, and WeatherForecastResult."""
        # 1. From dict
        row_id_1 = save_forecast(
            {"timestamp": "2026-09-24T01:00", "rain_1h": 3.0, "rain_3h": 8.5, "rain_6h": 18.0},
            db_path=self.mem_conn,
        )
        self.assertGreater(row_id_1, 0)

        # 2. From RainfallSummary
        summary = RainfallSummary(
            timestamp="2026-09-24T02:00",
            rain_1h=4.5,
            rain_3h=12.0,
            rain_6h=25.0,
            rain_past_24h=10.0,
        )
        row_id_2 = save_forecast(summary, db_path=self.mem_conn)
        self.assertGreater(row_id_2, row_id_1)

        # 3. Retrieve latest
        latest = get_latest_forecast(self.mem_conn)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["timestamp"], "2026-09-24T02:00")
        self.assertAlmostEqual(latest["rain_1h"], 4.5)
        self.assertAlmostEqual(latest["rain_3h"], 12.0)
        self.assertAlmostEqual(latest["rain_6h"], 25.0)

        # 4. Retrieve by specific timestamp
        record_t1 = get_forecast_by_timestamp("2026-09-24T01:00", db_path=self.mem_conn)
        self.assertIsNotNone(record_t1)
        self.assertAlmostEqual(record_t1["rain_1h"], 3.0)

    def test_historical_forecast_preservation(self) -> None:
        """Verify new pipeline runs append forecasts and do not delete existing historical data."""
        timestamps = ["2026-09-24T00:00", "2026-09-24T01:00", "2026-09-24T02:00", "2026-09-24T03:00"]
        for i, ts in enumerate(timestamps):
            save_forecast(
                {"timestamp": ts, "rain_1h": float(i), "rain_3h": float(i * 2), "rain_6h": float(i * 3)},
                db_path=self.mem_conn,
            )

        history = get_forecast_history(self.mem_conn, limit=10)
        self.assertEqual(len(history), 4)
        # Newest first
        self.assertEqual(history[0]["timestamp"], "2026-09-24T03:00")
        self.assertEqual(history[-1]["timestamp"], "2026-09-24T00:00")

    def test_6hour_forecast_records_property(self) -> None:
        """Verify WeatherForecastResult.next_6h_records extracts exactly 6 hours from reference time."""
        result = load_mock_forecast(self.fixture_path, reference_time="2026-09-24T00:00")

        six_hours = result.next_6h_records
        self.assertEqual(len(six_hours), 6)
        expected_timestamps = [
            "2026-09-24T00:00",
            "2026-09-24T01:00",
            "2026-09-24T02:00",
            "2026-09-24T03:00",
            "2026-09-24T04:00",
            "2026-09-24T05:00",
        ]
        self.assertEqual([rec.timestamp for rec in six_hours], expected_timestamps)
        # Verify rain values
        self.assertEqual([rec.rain_mm for rec in six_hours], [4.5, 8.2, 12.0, 15.5, 20.0, 18.2])

    def test_result_save_to_db_method(self) -> None:
        """Verify WeatherForecastResult.save_to_db helper."""
        result = load_mock_forecast(self.fixture_path, reference_time="2026-09-24T00:00")
        row_id = result.save_to_db(db_path=self.mem_conn)
        self.assertGreater(row_id, 0)

        latest = get_latest_forecast(self.mem_conn)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["timestamp"], "2026-09-24T00:00")
        self.assertAlmostEqual(latest["rain_1h"], 4.5)
        self.assertAlmostEqual(latest["rain_3h"], 24.7)
        self.assertAlmostEqual(latest["rain_6h"], 78.4)

    def test_fetch_and_store_forecast_with_mocked_network(self) -> None:
        """Verify fetch_and_store_forecast fetches, caches JSON, and stores 6h forecast in DB."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_file = tmp_path / "test_chetna.db"
            cache_dir = tmp_path / "cache"

            mock_http_response = MagicMock()
            mock_http_response.getcode.return_value = 200
            mock_http_response.read.return_value = json.dumps(self.sample_json).encode("utf-8")
            mock_http_response.__enter__.return_value = mock_http_response

            with patch("urllib.request.urlopen", return_value=mock_http_response):
                forecast_res, row_id = fetch_and_store_forecast(
                    latitude=13.0827,
                    longitude=80.2707,
                    db_path=db_file,
                    reference_time="2026-09-24T00:00",
                    cache_dir=cache_dir,
                )

            # 1. Result checks
            self.assertIsInstance(forecast_res, WeatherForecastResult)
            self.assertGreater(row_id, 0)
            self.assertFalse(forecast_res.from_cache)
            self.assertAlmostEqual(forecast_res.summary.rain_6h, 78.4)

            # 2. Database checks
            stored = get_latest_forecast(db_file)
            self.assertIsNotNone(stored)
            self.assertEqual(stored["timestamp"], "2026-09-24T00:00")
            self.assertAlmostEqual(stored["rain_1h"], 4.5)
            self.assertAlmostEqual(stored["rain_3h"], 24.7)
            self.assertAlmostEqual(stored["rain_6h"], 78.4)

            # 3. JSON cache check
            cache_files = list(cache_dir.glob("*.json"))
            self.assertEqual(len(cache_files), 1)
            with open(cache_files[0], "r", encoding="utf-8") as f:
                cached_json = json.load(f)
            self.assertEqual(cached_json["latitude"], self.sample_json["latitude"])

    def test_fetch_and_store_forecast_offline_cache_fallback(self) -> None:
        """Verify fetch_and_store_forecast falls back to cached JSON when API is down."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_file = tmp_path / "offline_chetna.db"
            cache_dir = tmp_path / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            # Pre-seed cache file
            client = OpenMeteoClient(cache_dir=cache_dir)
            cache_file = client._get_cache_filepath(13.0827, 80.2707)
            self.assertIsNotNone(cache_file)
            with open(cache_file, "w", encoding="utf-8") as f:  # type: ignore
                json.dump(self.sample_json, f)

            # Simulate network failure
            with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
                res, row_id = client.fetch_and_store_forecast(
                    latitude=13.0827,
                    longitude=80.2707,
                    db_path=db_file,
                    reference_time="2026-09-24T00:00",
                    use_cache_on_failure=True,
                )

            self.assertTrue(res.from_cache)
            self.assertGreater(row_id, 0)

            stored = get_latest_forecast(db_file)
            self.assertIsNotNone(stored)
            self.assertEqual(stored["timestamp"], "2026-09-24T00:00")
            self.assertAlmostEqual(stored["rain_6h"], 78.4)

    def test_save_forecast_invalid_record_validation(self) -> None:
        """Verify validation errors when attempting to store invalid forecast records."""
        # Missing required field
        with self.assertRaises(ValueError):
            save_forecast({"timestamp": "2026-09-24T00:00", "rain_1h": 1.0}, db_path=self.mem_conn)

        # Empty timestamp
        with self.assertRaises(ValueError):
            save_forecast(
                {"timestamp": "  ", "rain_1h": 1.0, "rain_3h": 2.0, "rain_6h": 3.0},
                db_path=self.mem_conn,
            )

        # Non-numeric rain value
        with self.assertRaises(ValueError):
            save_forecast(
                {"timestamp": "2026-09-24T00:00", "rain_1h": "invalid", "rain_3h": 2.0, "rain_6h": 3.0},
                db_path=self.mem_conn,
            )

        # Invalid object type
        with self.assertRaises(TypeError):
            save_forecast([1, 2, 3], db_path=self.mem_conn)  # type: ignore


if __name__ == "__main__":
    unittest.main()
