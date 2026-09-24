"""Automated tests for Chetna M1 Day 1: flood hotspots and historical backtesting events."""

import json
import unittest
from pathlib import Path

from src.static_risk.hotspots import (
    DEFAULT_M1_DATA_DIR,
    BacktestEvent,
    HistoricalRainfallSeries,
    Hotspot,
    get_backtest_event_by_id,
    get_hotspot_by_id,
    load_backtest_events,
    load_historical_rainfall,
    load_hotspots,
)


class TestM1HotspotsAndEvents(unittest.TestCase):
    """Test suite for M1 Day 1 data structures, dataset integrity, and loaders."""

    def test_load_hotspots_count_and_fields(self) -> None:
        """Verify 5–10 known waterlogging spots are identified with required metadata."""
        hotspots = load_hotspots()
        self.assertGreaterEqual(len(hotspots), 5)
        self.assertLessEqual(len(hotspots), 15)
        self.assertEqual(len(hotspots), 10)

        # Check each hotspot adheres to the schema
        for h in hotspots:
            self.assertIsInstance(h, Hotspot)
            self.assertTrue(h.hotspot_id.startswith("HS"))
            self.assertEqual(h.city, "Chennai")
            self.assertEqual(h.state, "Tamil Nadu")
            self.assertTrue(len(h.name) > 0)
            self.assertTrue(len(h.zone) > 0)
            self.assertGreater(h.ward, 0)
            self.assertGreater(h.elevation_m, 0.0)
            self.assertIn(h.severity_tier, ["Severe", "High", "Moderate"])
            self.assertGreater(h.typical_trigger_rain_1h_mm, 0.0)
            self.assertGreaterEqual(h.typical_trigger_rain_6h_mm, h.typical_trigger_rain_1h_mm)
            self.assertTrue(h.is_real_sourced)
            self.assertTrue(len(h.source_reference) > 0)

    def test_hotspots_geospatial_bounds(self) -> None:
        """Verify all hotspots are geographically located within the Chennai Metropolitan Area."""
        hotspots = load_hotspots()
        # Chennai bounding box roughly: Lat 12.8 to 13.3 N, Lon 80.0 to 80.35 E
        for h in hotspots:
            self.assertGreaterEqual(h.latitude, 12.8, f"{h.name} latitude too low")
            self.assertLessEqual(h.latitude, 13.3, f"{h.name} latitude too high")
            self.assertGreaterEqual(h.longitude, 80.0, f"{h.name} longitude too low")
            self.assertLessEqual(h.longitude, 80.35, f"{h.name} longitude too high")

    def test_hotspot_geojson_export(self) -> None:
        """Verify Hotspot.to_geojson_feature generates valid GeoJSON Point feature."""
        hotspot = get_hotspot_by_id("HS01")
        self.assertIsNotNone(hotspot)
        feature = hotspot.to_geojson_feature()  # type: ignore

        self.assertEqual(feature["type"], "Feature")
        self.assertEqual(feature["geometry"]["type"], "Point")
        # GeoJSON is [longitude, latitude]
        self.assertEqual(feature["geometry"]["coordinates"], [hotspot.longitude, hotspot.latitude])  # type: ignore
        self.assertEqual(feature["properties"]["id"], "HS01")
        self.assertEqual(feature["properties"]["name"], "Velachery Vijayanagar Junction")

    def test_hotspot_coordinate_validation_errors(self) -> None:
        """Verify boundary validations raise ValueError on erroneous inputs."""
        with self.assertRaises(ValueError):
            Hotspot(
                hotspot_id="HS_ERR",
                name="Invalid",
                city="Chennai",
                state="TN",
                zone="Z",
                ward=1,
                latitude=999.0,  # Invalid
                longitude=80.2,
                elevation_m=5.0,
                hotspot_type="t",
                severity_tier="High",
                typical_trigger_rain_1h_mm=10.0,
                typical_trigger_rain_6h_mm=20.0,
                historical_inundation_depth_m=1.0,
                primary_vulnerability_cause="cause",
                source_reference="src",
            )

        with self.assertRaises(ValueError):
            Hotspot(
                hotspot_id="HS_ERR",
                name="Invalid",
                city="Chennai",
                state="TN",
                zone="Z",
                ward=1,
                latitude=13.0,
                longitude=80.2,
                elevation_m=5.0,
                hotspot_type="t",
                severity_tier="High",
                typical_trigger_rain_1h_mm=25.0,
                typical_trigger_rain_6h_mm=10.0,  # 6h cannot be less than 1h
                historical_inundation_depth_m=1.0,
                primary_vulnerability_cause="cause",
                source_reference="src",
            )

    def test_load_backtest_events(self) -> None:
        """Verify 1–2 significant heavy-rain events are selected and registered."""
        events = load_backtest_events()
        self.assertGreaterEqual(len(events), 2)

        event_ids = [e.event_id for e in events]
        self.assertIn("EVT_2023_MICHAUNG", event_ids)
        self.assertIn("EVT_2021_NOV_DEPRESSION", event_ids)

        michaung = get_backtest_event_by_id("EVT_2023_MICHAUNG")
        self.assertIsNotNone(michaung)
        self.assertEqual(michaung.city, "Chennai")  # type: ignore
        self.assertAlmostEqual(michaung.total_rainfall_mm, 324.1, places=1)  # type: ignore
        self.assertAlmostEqual(michaung.peak_hourly_rainfall_mm, 26.1, places=1)  # type: ignore
        self.assertEqual(michaung.duration_hours, 72)  # type: ignore
        self.assertTrue(michaung.is_real_sourced)  # type: ignore

    def test_historical_rainfall_series_integrity(self) -> None:
        """Verify historical hourly rainfall series for backtest events."""
        # 1. Michaung
        series_m = load_historical_rainfall("EVT_2023_MICHAUNG")
        self.assertIsInstance(series_m, HistoricalRainfallSeries)
        self.assertEqual(series_m.total_hours, 72)
        self.assertEqual(len(series_m.records), 72)
        self.assertAlmostEqual(series_m.total_precipitation_mm, 324.1, places=1)
        self.assertAlmostEqual(series_m.peak_hourly_precipitation_mm, 26.1, places=1)

        # 2. November 2021
        series_n = load_historical_rainfall("EVT_2021_NOV_DEPRESSION")
        self.assertIsInstance(series_n, HistoricalRainfallSeries)
        self.assertEqual(series_n.total_hours, 72)
        self.assertEqual(len(series_n.records), 72)
        self.assertAlmostEqual(series_n.total_precipitation_mm, 89.0, places=1)
        self.assertAlmostEqual(series_n.peak_hourly_precipitation_mm, 7.0, places=1)

    def test_horizon_rain_calculation_during_replay(self) -> None:
        """Verify replay calculation of +1h, +3h, +6h, and past 24h rainfall during event backtesting."""
        series_m = load_historical_rainfall("EVT_2023_MICHAUNG")

        # Pick peak timestamp: 2023-12-04T07:00
        horizons = series_m.get_horizon_rain("2023-12-04T07:00")
        self.assertIn("rain_1h", horizons)
        self.assertIn("rain_3h", horizons)
        self.assertIn("rain_6h", horizons)
        self.assertIn("rain_past_24h", horizons)

        # The peak hour has 26.1 mm rain
        self.assertAlmostEqual(horizons["rain_1h"], 26.1, places=1)
        self.assertGreater(horizons["rain_3h"], horizons["rain_1h"])
        self.assertGreater(horizons["rain_6h"], horizons["rain_3h"])
        self.assertGreater(horizons["rain_past_24h"], 0.0)

        # Non-existent timestamp should raise KeyError
        with self.assertRaises(KeyError):
            series_m.get_horizon_rain("1999-01-01T00:00")


if __name__ == "__main__":
    unittest.main()
