"""Tests for src/alerts/evaluator.py — AlertEvaluator."""

from __future__ import annotations

import datetime
import unittest

from alerts.dispatcher import AlertSeverity
from simulators.sensor_simulator import SensorReading, SimulationScenario
from src.alerts.evaluator import AlertEvaluator, EvaluationResult


def _make_reading(
    water_level_cm: float = 20.0,
    rainfall_rate_mm_h: float = 5.0,
    is_anomaly: bool = False,
    node_id: str = "NODE_TEST_01",
) -> SensorReading:
    return SensorReading(
        node_id=node_id,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        water_level_cm=water_level_cm,
        rainfall_rate_mm_h=rainfall_rate_mm_h,
        battery_pct=90.0,
        is_anomaly=is_anomaly,
    )


class TestAlertEvaluator(unittest.TestCase):
    """Test suite for the threshold-based AlertEvaluator."""

    def setUp(self) -> None:
        """Use tightly controlled thresholds for predictable testing."""
        self.evaluator = AlertEvaluator(
            affected_area="Velachery",
            warning_water_cm=75.0,
            critical_water_cm=120.0,
            warning_rain_mm=30.0,
            critical_rain_mm=60.0,
        )

    # ------------------------------------------------------------------
    # INFO cases
    # ------------------------------------------------------------------
    def test_normal_reading_produces_info(self) -> None:
        """Normal water and rainfall levels should produce INFO severity."""
        reading = _make_reading(water_level_cm=30.0, rainfall_rate_mm_h=5.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.INFO)
        self.assertEqual(result.node_id, "NODE_TEST_01")
        self.assertEqual(result.affected_area, "Velachery")
        self.assertFalse(result.is_anomaly)

    def test_zero_water_and_rainfall_is_info(self) -> None:
        reading = _make_reading(water_level_cm=0.0, rainfall_rate_mm_h=0.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.INFO)

    # ------------------------------------------------------------------
    # WARNING cases
    # ------------------------------------------------------------------
    def test_water_at_warning_threshold_produces_warning(self) -> None:
        """Water level exactly at warning threshold should produce WARNING."""
        reading = _make_reading(water_level_cm=75.0, rainfall_rate_mm_h=5.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.WARNING)

    def test_water_above_warning_below_critical_is_warning(self) -> None:
        reading = _make_reading(water_level_cm=90.0, rainfall_rate_mm_h=10.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.WARNING)

    def test_rainfall_at_warning_threshold_is_warning(self) -> None:
        """Rainfall at warning threshold (below critical water) -> WARNING."""
        reading = _make_reading(water_level_cm=30.0, rainfall_rate_mm_h=30.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.WARNING)

    # ------------------------------------------------------------------
    # CRITICAL cases
    # ------------------------------------------------------------------
    def test_water_at_critical_threshold_is_critical(self) -> None:
        """Water level at critical threshold produces CRITICAL."""
        reading = _make_reading(water_level_cm=120.0, rainfall_rate_mm_h=10.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.CRITICAL)

    def test_high_water_only_critical_not_emergency(self) -> None:
        """Water critical alone (rainfall below critical) = CRITICAL not EMERGENCY."""
        reading = _make_reading(water_level_cm=130.0, rainfall_rate_mm_h=20.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.CRITICAL)

    def test_critical_rainfall_alone_is_critical(self) -> None:
        """Critical rainfall rate without critical water -> CRITICAL."""
        reading = _make_reading(water_level_cm=50.0, rainfall_rate_mm_h=65.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.CRITICAL)

    # ------------------------------------------------------------------
    # EMERGENCY cases
    # ------------------------------------------------------------------
    def test_anomaly_flag_produces_emergency(self) -> None:
        """Sensor anomaly flag unconditionally escalates to EMERGENCY."""
        reading = _make_reading(water_level_cm=20.0, rainfall_rate_mm_h=5.0, is_anomaly=True)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.EMERGENCY)
        self.assertTrue(result.is_anomaly)

    def test_combined_critical_water_and_critical_rain_is_emergency(self) -> None:
        """Both water and rainfall in critical zone simultaneously -> EMERGENCY."""
        reading = _make_reading(water_level_cm=125.0, rainfall_rate_mm_h=65.0)
        result = self.evaluator.evaluate(reading)
        self.assertEqual(result.severity, AlertSeverity.EMERGENCY)

    # ------------------------------------------------------------------
    # Structured result validation
    # ------------------------------------------------------------------
    def test_evaluation_result_has_required_fields(self) -> None:
        """EvaluationResult must contain all required fields."""
        reading = _make_reading(water_level_cm=80.0, rainfall_rate_mm_h=35.0)
        result = self.evaluator.evaluate(reading)
        self.assertIsInstance(result, EvaluationResult)
        self.assertIsNotNone(result.severity)
        self.assertIsNotNone(result.reason)
        self.assertIsNotNone(result.node_id)
        self.assertIsNotNone(result.timestamp)
        self.assertIsNotNone(result.affected_area)
        self.assertIsNotNone(result.title)

    def test_to_dict_contains_all_keys(self) -> None:
        """to_dict() must include all required serialisable keys."""
        reading = _make_reading()
        result = self.evaluator.evaluate(reading)
        d = result.to_dict()
        for key in ("severity", "reason", "node_id", "timestamp", "affected_area",
                    "water_level_cm", "rainfall_rate_mm_h", "is_anomaly", "title"):
            self.assertIn(key, d, f"Missing key '{key}' in EvaluationResult.to_dict()")

    def test_reason_is_non_empty_string(self) -> None:
        reading = _make_reading(water_level_cm=30.0)
        result = self.evaluator.evaluate(reading)
        self.assertIsInstance(result.reason, str)
        self.assertGreater(len(result.reason), 10)

    # ------------------------------------------------------------------
    # Affected area override
    # ------------------------------------------------------------------
    def test_affected_area_is_propagated(self) -> None:
        evaluator = AlertEvaluator(affected_area="Adyar")
        reading = _make_reading()
        result = evaluator.evaluate(reading)
        self.assertEqual(result.affected_area, "Adyar")
