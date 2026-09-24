"""Unit tests for the Open-Meteo weather and rainfall forecast ingestion module."""

import io
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ingestion.weather import (
    DataParsingError,
    HourlyForecastRecord,
    OpenMeteoAPIError,
    OpenMeteoClient,
    OpenMeteoConnectionError,
    RainfallSummary,
    WeatherForecastResult,
    WeatherIngestionError,
    fetch_weather_forecast,
    load_mock_forecast,
    parse_weather_response,
)


class TestWeatherIngestion(unittest.TestCase):
    """Test suite for weather data ingestion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_path = Path(__file__).parent / "fixtures" / "sample_openmeteo_response.json"
        with open(cls.fixture_path, "r", encoding="utf-8") as f:
            cls.sample_json = json.load(f)

    def test_parse_sample_mock_response(self) -> None:
        """Requirement 9: Ingestion function works with sample/mock response without real API."""
        result = load_mock_forecast(self.fixture_path, reference_time="2026-09-24T00:00")

        self.assertIsInstance(result, WeatherForecastResult)
        self.assertAlmostEqual(result.latitude, 13.0827, places=4)
        self.assertAlmostEqual(result.longitude, 80.2707, places=4)
        self.assertEqual(result.timezone, "Asia/Kolkata")
        self.assertEqual(result.elevation, 12.0)
        self.assertEqual(result.reference_time, "2026-09-24T00:00")
        self.assertEqual(len(result.hourly_records), 48)
        self.assertFalse(result.from_cache)

        # First hourly entry check
        first_entry = result.hourly_records[0]
        self.assertIsInstance(first_entry, HourlyForecastRecord)
        self.assertEqual(first_entry.timestamp, "2026-09-23T00:00")
        self.assertEqual(first_entry.rain_mm, 0.0)

    def test_rainfall_summary_aggregation(self) -> None:
        """Verify +1h, +3h, +6h forecast rain and past 24h rain calculation."""
        result = parse_weather_response(self.sample_json, reference_time="2026-09-24T00:00")
        summary = result.summary

        self.assertIsInstance(summary, RainfallSummary)
        self.assertEqual(summary.timestamp, "2026-09-24T00:00")

        # In sample_openmeteo_response.json, index 24 is "2026-09-24T00:00":
        # Values from index 24 onward: [4.5, 8.2, 12.0, 15.5, 20.0, 18.2, ...]
        # Next 1 hour: 4.5
        # Next 3 hours: 4.5 + 8.2 + 12.0 = 24.7
        # Next 6 hours: 4.5 + 8.2 + 12.0 + 15.5 + 20.0 + 18.2 = 78.4
        self.assertAlmostEqual(summary.rain_1h, 4.5, places=2)
        self.assertAlmostEqual(summary.rain_3h, 24.7, places=2)
        self.assertAlmostEqual(summary.rain_6h, 78.4, places=2)

        # Past 24 hours (indices 0 to 23): sum is 17.5 mm
        self.assertAlmostEqual(summary.rain_past_24h, 17.5, places=2)

    def test_sqlite_forecasts_table_contract(self) -> None:
        """Requirement 8: Structured forecast data matching Chetna forecasts SQLite table."""
        result = parse_weather_response(self.sample_json, reference_time="2026-09-24T00:00")
        db_record = result.to_db_record()

        expected_columns = {"timestamp", "rain_1h", "rain_3h", "rain_6h"}
        self.assertEqual(set(db_record.keys()), expected_columns)
        self.assertIsInstance(db_record["timestamp"], str)
        self.assertIsInstance(db_record["rain_1h"], float)
        self.assertIsInstance(db_record["rain_3h"], float)
        self.assertIsInstance(db_record["rain_6h"], float)

        # Also check dictionary export for downstream features
        result_dict = result.to_dict()
        self.assertIn("summary", result_dict)
        self.assertIn("rain_past_24h", result_dict["summary"])

    def test_null_and_negative_rainfall_handling(self) -> None:
        """Ensure None/null and anomalous negative rainfall values are safely normalized."""
        anomalous_data = {
            "latitude": 13.0,
            "longitude": 80.0,
            "timezone": "UTC",
            "elevation": 10.0,
            "hourly": {
                "time": ["2026-09-24T00:00", "2026-09-24T01:00", "2026-09-24T02:00"],
                "precipitation": [None, -5.0, 3.2],
                "rain": [None, -5.0, 3.2],
            },
        }
        result = parse_weather_response(anomalous_data, reference_time="2026-09-24T00:00")
        self.assertEqual(result.hourly_records[0].rain_mm, 0.0)
        self.assertEqual(result.hourly_records[1].rain_mm, 0.0)
        self.assertEqual(result.hourly_records[2].rain_mm, 3.2)
        self.assertAlmostEqual(result.summary.rain_3h, 3.2, places=2)

    def test_network_connection_failure(self) -> None:
        """Requirement 7: Clear error handling for network failures / DNS errors."""
        client = OpenMeteoClient(base_url="https://api.open-meteo.com/v1/forecast")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("DNS lookup failed")):
            with self.assertRaises(OpenMeteoConnectionError) as ctx:
                client.fetch_raw_forecast(13.0827, 80.2707, use_cache_on_failure=False)
            self.assertIn("DNS lookup failed", str(ctx.exception))

    def test_network_timeout_failure(self) -> None:
        """Requirement 7: Clear error handling for socket/network timeouts."""
        client = OpenMeteoClient()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
            with self.assertRaises(OpenMeteoConnectionError) as ctx:
                client.fetch_raw_forecast(13.0827, 80.2707, use_cache_on_failure=False)
            self.assertIn("Request timed out", str(ctx.exception))

    def test_api_http_error(self) -> None:
        """Requirement 7: Clear error handling for API HTTP errors (e.g., 400 Bad Request)."""
        client = OpenMeteoClient()
        http_err = urllib.error.HTTPError(
            url="https://api.open-meteo.com/v1/forecast",
            code=400,
            msg="Bad Request",
            hdrs={},  # type: ignore
            fp=io.BytesIO(b'{"error": true, "reason": "Invalid latitude"}'),
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(OpenMeteoAPIError) as ctx:
                client.fetch_raw_forecast(999.0, 999.0, use_cache_on_failure=False)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Invalid latitude", ctx.exception.response_body)

    def test_malformed_response_handling(self) -> None:
        """Requirement 7: Handling of malformed JSON or missing schema keys."""
        client = OpenMeteoClient()
        with self.assertRaises(DataParsingError):
            client.parse_forecast({"invalid_key": 123})

        with self.assertRaises(DataParsingError):
            client.parse_forecast("not a dict")  # type: ignore

        with self.assertRaises(DataParsingError):
            client.parse_forecast({
                "latitude": 13.0,
                "longitude": 80.0,
                "hourly": {"time": ["2026-09-24T00:00"], "precipitation": []},  # length mismatch
            })

    def test_caching_and_offline_fallback(self) -> None:
        """Verify automatic response caching and fallback when internet/API is down."""
        with tempfile.TemporaryDirectory() as temp_dir:
            client = OpenMeteoClient(cache_dir=temp_dir)

            # Step 1: Successful fetch and cache
            mock_http_response = MagicMock()
            mock_http_response.getcode.return_value = 200
            mock_http_response.read.return_value = json.dumps(self.sample_json).encode("utf-8")
            mock_http_response.__enter__.return_value = mock_http_response

            with patch("urllib.request.urlopen", return_value=mock_http_response):
                data, from_cache = client.fetch_raw_forecast(13.0827, 80.2707)
                self.assertFalse(from_cache)
                self.assertEqual(data["latitude"], self.sample_json["latitude"])

            # Verify cache file was written to disk
            cache_file = client._get_cache_filepath(13.0827, 80.2707)
            self.assertIsNotNone(cache_file)
            self.assertTrue(cache_file.exists())  # type: ignore

            # Step 2: Simulate internet outage, client should fall back to cache
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("No route to host")):
                fallback_data, from_cache_flag = client.fetch_raw_forecast(
                    13.0827, 80.2707, use_cache_on_failure=True
                )
                self.assertTrue(from_cache_flag)
                self.assertEqual(fallback_data["latitude"], self.sample_json["latitude"])

                # High-level get_forecast should also flag from_cache
                forecast_res = client.get_forecast(
                    13.0827, 80.2707, reference_time="2026-09-24T00:00", use_cache_on_failure=True
                )
                self.assertTrue(forecast_res.from_cache)
                self.assertAlmostEqual(forecast_res.summary.rain_3h, 24.7, places=2)


if __name__ == "__main__":
    unittest.main()
