"""Comprehensive automated test suite for B2 Day 3: Sensor Correction + Validation + Integration.

Tests:
  - Phase 3: Deterministic sensor correction (zero drift, negative rain, calibration offset)
  - Phase 4: Explicit validation rules (normal, drift, severe negative, missing/NaN, jumps, stuck sensor, boundaries)
  - Phase 5: Raw telemetry preservation in memory and database
  - Phase 6 & 9: Alert and risk pipeline integration (valid flood surge vs invalid suppression vs sensor quality anomaly)
  - Phase 7: Verification of simulator scenarios (NORMAL, RISING, FLASH_FLOOD, ANOMALY)
  - Idempotency and auditability
"""

from __future__ import annotations

import datetime
import math
import sqlite3
import unittest
from unittest.mock import MagicMock

from alerts.dispatcher import AlertDispatcher, AlertSeverity
from alerts.pipeline import AlertPipeline
from alerts.telegram_handler import TelegramAlertHandler
from alerts.twilio_handler import TwilioAlertHandler
from database.db import get_sensor_readings, init_db
from simulators.sensor_db_bridge import persist_batch, persist_reading
from simulators.sensor_simulator import (
    SensorReading,
    SensorSimulator,
    SimulationScenario,
)
from src.alerts.evaluator import AlertEvaluator
from src.sensors.correction import (
    SensorCorrector,
    ValidatedReading,
    ValidationStatus,
    correct_and_validate_batch,
    correct_and_validate_reading,
)


class TestB2Day3SensorCorrectionAndValidation(unittest.TestCase):
    """Test suite for sensor correction and validation layer."""

    def setUp(self) -> None:
        self.corrector = SensorCorrector()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    # -----------------------------------------------------------------
    # Phase 3 & 4: Correction and Validation Rules
    # -----------------------------------------------------------------

    def test_normal_reading_validated(self) -> None:
        """Physically realistic reading passes as VALID with intact values."""
        raw = SensorReading(
            node_id="SENS_PAT_01",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=28.5,
            rainfall_rate_mm_h=4.2,
            battery_pct=95.0,
            is_anomaly=False,
        )
        val = self.corrector.process(raw)
        self.assertEqual(val.validation_status, ValidationStatus.VALID.value)
        self.assertTrue(val.is_valid)
        self.assertTrue(val.is_flood_eligible)
        self.assertEqual(val.raw_water_level_cm, 28.5)
        self.assertEqual(val.water_level_cm, 28.5)
        self.assertEqual(val.raw_rainfall_rate_mm_h, 4.2)
        self.assertEqual(val.rainfall_rate_mm_h, 4.2)
        self.assertFalse(val.is_anomaly)

    def test_minor_negative_zero_drift_corrected(self) -> None:
        """Minor ultrasonic sensor temperature zero-drift (-5cm to 0cm) is clamped to 0cm."""
        raw = SensorReading(
            node_id="SENS_PAT_01",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=-2.4,
            rainfall_rate_mm_h=0.0,
            battery_pct=94.0,
            is_anomaly=False,
        )
        val = self.corrector.process(raw)
        self.assertEqual(val.validation_status, ValidationStatus.CORRECTED.value)
        self.assertTrue(val.is_valid)
        self.assertEqual(val.raw_water_level_cm, -2.4)
        self.assertEqual(val.water_level_cm, 0.0)
        self.assertIn("clamped minor negative zero-drift", val.validation_message)

    def test_minor_negative_rainfall_corrected(self) -> None:
        """Minor gauge negative flutter (-5mm/h to 0mm/h) is clamped to 0.0mm/h."""
        raw = SensorReading(
            node_id="SENS_PAT_02",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=15.0,
            rainfall_rate_mm_h=-1.2,
            battery_pct=96.0,
            is_anomaly=False,
        )
        val = self.corrector.process(raw)
        self.assertEqual(val.validation_status, ValidationStatus.CORRECTED.value)
        self.assertEqual(val.raw_rainfall_rate_mm_h, -1.2)
        self.assertEqual(val.rainfall_rate_mm_h, 0.0)

    def test_calibration_offset_adjustment(self) -> None:
        """Known sensor mounting height offset is subtracted cleanly."""
        raw = SensorReading(
            node_id="SENS_PAT_03",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=35.0,
            rainfall_rate_mm_h=0.0,
            battery_pct=90.0,
            is_anomaly=False,
        )
        val = self.corrector.process(raw, calibration_offset_cm=5.0)
        self.assertEqual(val.validation_status, ValidationStatus.CORRECTED.value)
        self.assertEqual(val.raw_water_level_cm, 35.0)
        self.assertEqual(val.water_level_cm, 30.0)
        self.assertEqual(val.calibration_offset_cm, 5.0)

    def test_severe_negative_water_level_invalid(self) -> None:
        """Severe impossible negative stage (-999 cm) is marked INVALID and never fabricated."""
        raw = SensorReading(
            node_id="SENS_PAT_04",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=-999.0,
            rainfall_rate_mm_h=0.0,
            battery_pct=85.0,
            is_anomaly=False,
        )
        val = self.corrector.process(raw)
        self.assertEqual(val.validation_status, ValidationStatus.INVALID.value)
        self.assertFalse(val.is_valid)
        self.assertFalse(val.is_flood_eligible)
        self.assertIsNone(val.water_level_cm)
        self.assertEqual(val.raw_water_level_cm, -999.0)
        self.assertIn("Severe impossible negative", val.validation_message)

    def test_missing_and_nan_water_level_invalid(self) -> None:
        """None or NaN water levels are rejected without fabricating values."""
        raw_none = SensorReading(
            node_id="SENS_PAT_05",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=None,  # type: ignore
            rainfall_rate_mm_h=10.0,
            battery_pct=90.0,
        )
        val_none = self.corrector.process(raw_none)
        self.assertEqual(val_none.validation_status, ValidationStatus.INVALID.value)
        self.assertIsNone(val_none.water_level_cm)

        raw_nan = SensorReading(
            node_id="SENS_PAT_05",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=float("nan"),
            rainfall_rate_mm_h=10.0,
            battery_pct=90.0,
        )
        val_nan = self.corrector.process(raw_nan)
        self.assertEqual(val_nan.validation_status, ValidationStatus.INVALID.value)
        self.assertIsNone(val_nan.water_level_cm)

    def test_basin_ceiling_exceedance_anomaly(self) -> None:
        """Levels exceeding saucer basin physical depth (e.g. 850cm acoustic reflection) are ANOMALY."""
        raw = SensorReading(
            node_id="SENS_PAT_06",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=850.0,
            rainfall_rate_mm_h=0.0,
            battery_pct=88.0,
        )
        val = self.corrector.process(raw)
        self.assertEqual(val.validation_status, ValidationStatus.ANOMALY.value)
        self.assertTrue(val.is_anomaly)
        self.assertFalse(val.is_valid)
        self.assertEqual(val.raw_water_level_cm, 850.0)
        self.assertIn("exceeds physical saucer basin ceiling", val.validation_message)

    def test_impossible_sudden_jump_anomaly(self) -> None:
        """Sudden unphysical jump in calm weather (>80cm in <5min) is flagged as ANOMALY."""
        corrector = SensorCorrector()
        t1 = "2026-09-29T10:00:00Z"
        t2 = "2026-09-29T10:02:00Z"  # 2 minutes later

        r1 = SensorReading("SENS_JUMP", t1, water_level_cm=20.0, rainfall_rate_mm_h=0.0, battery_pct=95.0)
        r2 = SensorReading("SENS_JUMP", t2, water_level_cm=140.0, rainfall_rate_mm_h=5.0, battery_pct=95.0)

        v1 = corrector.process(r1)
        self.assertEqual(v1.validation_status, ValidationStatus.VALID.value)

        v2 = corrector.process(r2)
        self.assertEqual(v2.validation_status, ValidationStatus.ANOMALY.value)
        self.assertTrue(v2.is_anomaly)
        self.assertIn("Impossible sudden jump", v2.validation_message)

    def test_stuck_sensor_anomaly(self) -> None:
        """Sensor reporting identical reading for 5+ steps during rain is flagged as ANOMALY."""
        corrector = SensorCorrector()
        now = datetime.datetime(2026, 9, 29, 10, 0, 0, tzinfo=datetime.timezone.utc)

        readings = [
            SensorReading(
                node_id="SENS_STUCK",
                timestamp=(now + datetime.timedelta(minutes=i)).isoformat(),
                water_level_cm=35.0,
                rainfall_rate_mm_h=25.0,  # Rain is falling!
                battery_pct=95.0,
            )
            for i in range(6)
        ]

        vals = corrector.process_batch(readings)
        # First 4 are valid before the 5-reading identical threshold is met
        self.assertEqual(vals[0].validation_status, ValidationStatus.VALID.value)
        self.assertEqual(vals[3].validation_status, ValidationStatus.VALID.value)
        # 5th and 6th reading trigger stuck sensor detection
        self.assertEqual(vals[4].validation_status, ValidationStatus.ANOMALY.value)
        self.assertIn("Stuck sensor detected", vals[4].validation_message)

    def test_valid_boundary_values(self) -> None:
        """Physical boundary conditions (0cm, 75cm, 120cm, 250cm) validate correctly."""
        for level in [0.0, 75.0, 120.0, 250.0]:
            self.corrector.reset_history()
            r = SensorReading(f"SENS_BND_{level}", "2026-09-29T10:00:00Z", water_level_cm=level, rainfall_rate_mm_h=0.0, battery_pct=95.0)
            v = self.corrector.process(r)
            self.assertEqual(v.validation_status, ValidationStatus.VALID.value)
            self.assertEqual(v.water_level_cm, level)

    # -----------------------------------------------------------------
    # Phase 5 & 8: Database Persistence and Raw Data Preservation
    # -----------------------------------------------------------------

    def test_database_persistence_preserves_raw_and_corrected(self) -> None:
        """Persisting corrected reading stores both raw and effective values in SQLite."""
        raw = SensorReading(
            node_id="SENS_PAT_07",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=-3.2,
            rainfall_rate_mm_h=-0.8,
            battery_pct=92.0,
        )
        row_id = persist_reading(raw, db_path=self.conn, auto_register_node=True)
        self.assertGreater(row_id, 0)

        rows = get_sensor_readings(node_id="SENS_PAT_07", db_path=self.conn)
        self.assertEqual(len(rows), 1)
        r = rows[0]

        # Raw values are strictly preserved
        self.assertAlmostEqual(r["raw_water_level_cm"], -3.2)
        self.assertAlmostEqual(r["raw_rainfall_rate_mm_h"], -0.8)

        # Corrected values are stored in effective columns
        self.assertAlmostEqual(r["water_level_cm"], 0.0)
        self.assertAlmostEqual(r["rainfall_rate_mm_h"], 0.0)
        self.assertEqual(r["validation_status"], ValidationStatus.CORRECTED.value)
        self.assertEqual(r["source"], "simulated")

    def test_persist_batch_validates_and_stores(self) -> None:
        """Batch persistence validates each reading and records validation statuses."""
        batch = [
            SensorReading("BATCH_PAT", "2026-09-29T10:01:00Z", water_level_cm=20.0, rainfall_rate_mm_h=0.0, battery_pct=95.0),
            SensorReading("BATCH_PAT", "2026-09-29T10:02:00Z", water_level_cm=-1.5, rainfall_rate_mm_h=0.0, battery_pct=95.0),
            SensorReading("BATCH_PAT", "2026-09-29T10:03:00Z", water_level_cm=-999.0, rainfall_rate_mm_h=0.0, battery_pct=95.0),
        ]
        inserted = persist_batch(batch, db_path=self.conn, auto_register_node=True)
        self.assertEqual(inserted, 3)

        rows = get_sensor_readings(node_id="BATCH_PAT", db_path=self.conn)
        self.assertEqual(len(rows), 3)
        statuses = {row["validation_status"] for row in rows}
        self.assertIn("VALID", statuses)
        self.assertIn("CORRECTED", statuses)
        self.assertIn("INVALID", statuses)

    # -----------------------------------------------------------------
    # Phase 7: Simulator Scenarios
    # -----------------------------------------------------------------

    def test_scenarios_validation_behavior(self) -> None:
        """Simulator scenarios (NORMAL, RISING, FLASH_FLOOD, ANOMALY) produce expected validation results."""
        sim = SensorSimulator(node_id="SENS_SCENARIO", base_water_level_cm=20.0)

        # 1. NORMAL scenario -> All readings VALID within standard saucer limits
        normal_readings = sim.generate_batch(count=5, scenario=SimulationScenario.NORMAL)
        normal_vals = correct_and_validate_batch(normal_readings)
        for v in normal_vals:
            self.assertEqual(v.validation_status, ValidationStatus.VALID.value)
            self.assertGreater(v.water_level_cm, 0.0)
            self.assertLess(v.water_level_cm, 60.0)

        # 2. RISING scenario -> Valid increasing sequence
        rising_readings = sim.generate_batch(count=5, scenario=SimulationScenario.RISING)
        rising_vals = correct_and_validate_batch(rising_readings)
        for v in rising_vals:
            self.assertEqual(v.validation_status, ValidationStatus.VALID.value)
        self.assertGreater(rising_vals[-1].water_level_cm, rising_vals[0].water_level_cm)

        # 3. FLASH_FLOOD scenario -> Valid flood surge crossing critical threshold
        flood_reading = sim.generate_reading(scenario=SimulationScenario.FLASH_FLOOD, step_index=10)
        flood_val = correct_and_validate_reading(flood_reading)
        self.assertEqual(flood_val.validation_status, ValidationStatus.VALID.value)
        self.assertGreater(flood_val.water_level_cm, 120.0)

        # 4. ANOMALY scenario -> Identified as ANOMALY or INVALID
        anomaly_reading = sim.generate_reading(scenario=SimulationScenario.ANOMALY)
        anomaly_val = correct_and_validate_reading(anomaly_reading)
        self.assertIn(anomaly_val.validation_status, (ValidationStatus.ANOMALY.value, ValidationStatus.INVALID.value))
        self.assertTrue(anomaly_val.is_anomaly)

    # -----------------------------------------------------------------
    # Phase 6 & 9: Alert Pipeline Integration
    # -----------------------------------------------------------------

    def test_alert_pipeline_valid_surge_dispatches_flood_alert(self) -> None:
        """Valid critical flood surge dispatches emergency/critical alert."""
        mock_tw = MagicMock(spec=TwilioAlertHandler)
        mock_tw.send_sms.return_value = MagicMock(status="SENT", message_sid="SM1")
        mock_tw.make_voice_call.return_value = MagicMock(status="SENT", call_sid="CA1")

        mock_tg = MagicMock(spec=TelegramAlertHandler)
        mock_tg.send_message.return_value = MagicMock(status="SENT", chat_id="-100", message_id=1)

        dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=self.conn)
        pipeline = AlertPipeline(dispatcher=dispatcher, db_path=self.conn)

        valid_surge = SensorReading(
            node_id="SENS_SURGE",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=135.0,  # Critical water
            rainfall_rate_mm_h=75.0,  # Critical rain
            battery_pct=95.0,
        )
        res = pipeline.process(valid_surge, persist=True)
        self.assertTrue(res.dispatched)
        self.assertFalse(res.suppressed)
        self.assertEqual(res.evaluation.severity, AlertSeverity.EMERGENCY)
        self.assertEqual(res.evaluation.alert_type, "FLOOD_ALERT")

    def test_alert_pipeline_invalid_reading_does_not_alert(self) -> None:
        """Invalid sensor observation (-999cm) is suppressed and NEVER creates a flood alert."""
        mock_tw = MagicMock(spec=TwilioAlertHandler)
        mock_tg = MagicMock(spec=TelegramAlertHandler)
        dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=self.conn)
        pipeline = AlertPipeline(dispatcher=dispatcher, db_path=self.conn)

        invalid_reading = SensorReading(
            node_id="SENS_FAIL",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=-999.0,
            rainfall_rate_mm_h=0.0,
            battery_pct=90.0,
        )
        res = pipeline.process(invalid_reading, persist=True)
        self.assertFalse(res.dispatched)
        self.assertTrue(res.suppressed)
        self.assertEqual(res.evaluation.alert_type, "SUPPRESSED_INVALID")
        # No broadcast calls made
        mock_tw.send_sms.assert_not_called()
        mock_tw.make_voice_call.assert_not_called()

    def test_alert_pipeline_sensor_anomaly_distinguished_from_flooding(self) -> None:
        """Sensor anomaly flags sensor quality problem and does not dispatch citizen evacuation."""
        mock_tw = MagicMock(spec=TwilioAlertHandler)
        mock_tg = MagicMock(spec=TelegramAlertHandler)
        mock_tg.send_message.return_value = MagicMock(status="SENT", chat_id="-100", message_id=99)

        dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=self.conn)
        pipeline = AlertPipeline(dispatcher=dispatcher, db_path=self.conn)

        # Glitched reading: 850cm acoustic bounce
        glitch_reading = SensorReading(
            node_id="SENS_GLITCH",
            timestamp="2026-09-29T10:00:00Z",
            water_level_cm=850.0,
            rainfall_rate_mm_h=0.0,
            battery_pct=90.0,
        )
        res = pipeline.process(glitch_reading, persist=True)
        self.assertEqual(res.evaluation.alert_type, "SENSOR_QUALITY")
        self.assertIn("Sensor anomaly detected", res.evaluation.reason)
        # Suppresses citizen evacuation SMS and Voice calls
        mock_tw.send_sms.assert_not_called()
        mock_tw.make_voice_call.assert_not_called()
        # Diagnostic message routed to Telegram only
        mock_tg.send_message.assert_called_once()
        self.assertIn("SENSOR QUALITY ALERT", mock_tg.send_message.call_args[1]["text"])

    def test_idempotent_validation(self) -> None:
        """Processing an already ValidatedReading preserves raw and does not double-correct."""
        raw = SensorReading("SENS_IDEM", "2026-09-29T10:00:00Z", water_level_cm=-2.0, rainfall_rate_mm_h=0.0, battery_pct=90.0)
        v1 = self.corrector.process(raw)
        v2 = self.corrector.process(v1)

        self.assertEqual(v1.raw_water_level_cm, v2.raw_water_level_cm)
        self.assertEqual(v1.water_level_cm, v2.water_level_cm)
        self.assertEqual(v1.validation_status, v2.validation_status)


if __name__ == "__main__":
    unittest.main()
