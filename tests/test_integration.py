"""Integration tests: SensorReading -> Evaluator -> Dispatcher -> alert_logs.

Verifies the complete B2 alert pipeline end-to-end using in-memory SQLite
and mocked Twilio/Telegram handlers. No real credentials or network calls.
"""

from __future__ import annotations

import datetime
import sqlite3
import unittest
from unittest.mock import MagicMock

from alerts.cooldown import AlertCooldown
from alerts.dispatcher import AlertDispatcher, AlertSeverity
from alerts.pipeline import AlertPipeline, acknowledge_alert, resolve_alert
from alerts.telegram_handler import TelegramAlertHandler, TelegramDispatchResult
from alerts.twilio_handler import TwilioAlertHandler, TwilioDispatchResult
from database.db import init_db
from simulators.sensor_simulator import SensorReading, SensorSimulator, SimulationScenario
from simulators.sensor_db_bridge import persist_reading, persist_batch
from src.alerts.evaluator import AlertEvaluator


def _mem_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _mock_twilio(success: bool = True) -> TwilioAlertHandler:
    handler = MagicMock(spec=TwilioAlertHandler)
    handler.send_sms.return_value = TwilioDispatchResult(
        success=success,
        channel="TWILIO_SMS",
        recipient="+919876543210",
        message_sid="SM_MOCK_123" if success else None,
        status="DRY_RUN" if success else "FAILED",
        error=None if success else "mock failure",
    )
    handler.make_voice_call.return_value = TwilioDispatchResult(
        success=success,
        channel="TWILIO_VOICE",
        recipient="+919876543210",
        call_sid="CA_MOCK_456" if success else None,
        status="DRY_RUN" if success else "FAILED",
        error=None if success else "mock failure",
    )
    return handler


def _mock_telegram(success: bool = True) -> TelegramAlertHandler:
    handler = MagicMock(spec=TelegramAlertHandler)
    handler.send_message.return_value = TelegramDispatchResult(
        success=success,
        chat_id="-10099999",
        message_id=12345 if success else None,
        status="DRY_RUN" if success else "FAILED",
        error=None if success else "mock failure",
    )
    return handler


def _make_reading(
    water_level_cm: float = 20.0,
    rainfall_rate_mm_h: float = 5.0,
    is_anomaly: bool = False,
    node_id: str = "NODE_INT_01",
) -> SensorReading:
    return SensorReading(
        node_id=node_id,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        water_level_cm=water_level_cm,
        rainfall_rate_mm_h=rainfall_rate_mm_h,
        battery_pct=90.0,
        is_anomaly=is_anomaly,
    )


class TestSensorToDatabaseIntegration(unittest.TestCase):
    """Sensor -> database persistence integration tests."""

    def setUp(self) -> None:
        self.conn = _mem_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_persist_single_reading_inserts_row(self) -> None:
        reading = _make_reading(water_level_cm=45.0, rainfall_rate_mm_h=10.0)
        # auto_register_node requires a file path; use in-memory connection directly
        from database.db import register_sensor_node, save_sensor_reading
        register_sensor_node(
            node_id=reading.node_id,
            name="Test Node",
            latitude=13.08, longitude=80.27,
            sensor_type="combined",
            db_path=self.conn,
        )
        row_id = save_sensor_reading(
            node_id=reading.node_id,
            timestamp=reading.timestamp,
            water_level_cm=reading.water_level_cm,
            rainfall_rate_mm_h=reading.rainfall_rate_mm_h,
            battery_pct=reading.battery_pct,
            is_anomaly=int(reading.is_anomaly),
            db_path=self.conn,
        )
        self.assertGreater(row_id, 0)
        row = self.conn.execute(
            "SELECT * FROM sensor_readings WHERE id=?", (row_id,)
        ).fetchone()
        self.assertAlmostEqual(row["water_level_cm"], 45.0)
        self.assertAlmostEqual(row["rainfall_rate_mm_h"], 10.0)
        self.assertEqual(row["is_anomaly"], 0)

    def test_persist_batch_readings(self) -> None:
        from database.db import register_sensor_node, save_sensor_reading
        register_sensor_node(
            node_id="BATCH_NODE",
            name="Batch Test Node",
            latitude=13.08, longitude=80.27,
            sensor_type="combined",
            db_path=self.conn,
        )
        readings = [
            _make_reading(water_level_cm=float(30 + i), node_id="BATCH_NODE")
            for i in range(5)
        ]
        for r in readings:
            save_sensor_reading(
                node_id=r.node_id,
                timestamp=r.timestamp,
                water_level_cm=r.water_level_cm,
                rainfall_rate_mm_h=r.rainfall_rate_mm_h,
                battery_pct=r.battery_pct,
                is_anomaly=int(r.is_anomaly),
                db_path=self.conn,
            )
        rows = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM sensor_readings WHERE node_id='BATCH_NODE'"
        ).fetchone()
        self.assertEqual(rows["cnt"], 5)


class TestEvaluatorToDispatcherIntegration(unittest.TestCase):
    """Evaluator -> Dispatcher -> alert_logs integration tests."""

    def setUp(self) -> None:
        self.conn = _mem_conn()
        self.twilio = _mock_twilio()
        self.telegram = _mock_telegram()
        self.dispatcher = AlertDispatcher(
            twilio_handler=self.twilio,
            telegram_handler=self.telegram,
            db_path=self.conn,
        )
        self.evaluator = AlertEvaluator(
            affected_area="Velachery",
            warning_water_cm=75.0,
            critical_water_cm=120.0,
            warning_rain_mm=30.0,
            critical_rain_mm=60.0,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def _dispatch_reading(self, reading: SensorReading) -> str:
        result = self.evaluator.evaluate(reading)
        return self.dispatcher.dispatch(
            severity=result.severity,
            title=result.title,
            message=result.reason,
            affected_area=result.affected_area,
            sms_recipients=["+919876543210"],
        )

    def test_info_only_reaches_telegram(self) -> None:
        """INFO severity: only Telegram is called; SMS and Voice are NOT called."""
        reading = _make_reading(water_level_cm=20.0, rainfall_rate_mm_h=5.0)
        self._dispatch_reading(reading)
        self.telegram.send_message.assert_called_once()
        self.twilio.send_sms.assert_not_called()
        self.twilio.make_voice_call.assert_not_called()

    def test_warning_reaches_telegram_and_sms(self) -> None:
        """WARNING severity: Telegram + SMS. Voice NOT called."""
        reading = _make_reading(water_level_cm=80.0, rainfall_rate_mm_h=5.0)
        self._dispatch_reading(reading)
        self.telegram.send_message.assert_called_once()
        self.twilio.send_sms.assert_called_once()
        self.twilio.make_voice_call.assert_not_called()

    def test_critical_reaches_telegram_and_sms_not_voice(self) -> None:
        """CRITICAL severity: Telegram + SMS. Voice NOT called."""
        reading = _make_reading(water_level_cm=125.0, rainfall_rate_mm_h=10.0)
        self._dispatch_reading(reading)
        self.telegram.send_message.assert_called_once()
        self.twilio.send_sms.assert_called_once()
        self.twilio.make_voice_call.assert_not_called()

    def test_emergency_reaches_telegram_sms_and_voice(self) -> None:
        """EMERGENCY severity: Telegram + SMS + Voice all called."""
        reading = _make_reading(water_level_cm=130.0, rainfall_rate_mm_h=70.0)
        self._dispatch_reading(reading)
        self.telegram.send_message.assert_called_once()
        self.twilio.send_sms.assert_called_once()
        self.twilio.make_voice_call.assert_called_once()

    def test_audit_logs_written_to_database(self) -> None:
        """All dispatch attempts must be recorded in alert_logs table."""
        reading = _make_reading(water_level_cm=130.0, rainfall_rate_mm_h=70.0)
        self._dispatch_reading(reading)
        logs = self.conn.execute("SELECT * FROM alert_logs;").fetchall()
        # EMERGENCY: 1 Telegram + 1 SMS + 1 Voice = at least 3 rows
        self.assertGreaterEqual(len(logs), 3)
        channels = {row["channel"] for row in logs}
        self.assertIn("TELEGRAM", channels)
        self.assertIn("TWILIO_SMS", channels)
        self.assertIn("TWILIO_VOICE", channels)


class TestAlertPipelineIntegration(unittest.TestCase):
    """Full AlertPipeline integration tests including cooldown and lifecycle."""

    def setUp(self) -> None:
        self.conn = _mem_conn()
        self.twilio = _mock_twilio()
        self.telegram = _mock_telegram()
        self.dispatcher = AlertDispatcher(
            twilio_handler=self.twilio,
            telegram_handler=self.telegram,
            db_path=self.conn,
        )
        self.evaluator = AlertEvaluator(
            affected_area="Adyar",
            warning_water_cm=75.0,
            critical_water_cm=120.0,
            warning_rain_mm=30.0,
            critical_rain_mm=60.0,
        )
        self.cooldown = AlertCooldown(cooldown_seconds=300)
        self.pipeline = AlertPipeline(
            dispatcher=self.dispatcher,
            evaluator=self.evaluator,
            cooldown=self.cooldown,
            db_path=self.conn,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_pipeline_processes_and_returns_result(self) -> None:
        """Pipeline returns a PipelineResult for every reading."""
        reading = _make_reading(water_level_cm=30.0)
        result = self.pipeline.process(reading, persist=False)
        self.assertIsNotNone(result.alert_id)
        self.assertIsNotNone(result.evaluation)

    def test_pipeline_suppresses_repeated_warning(self) -> None:
        """Second identical WARNING from the same node within cooldown is suppressed."""
        reading = _make_reading(water_level_cm=80.0)
        r1 = self.pipeline.process(reading, persist=False, sms_recipients=["+91123"])
        r2 = self.pipeline.process(reading, persist=False, sms_recipients=["+91123"])
        self.assertFalse(r1.suppressed)
        self.assertTrue(r2.suppressed)

    def test_escalation_bypasses_cooldown(self) -> None:
        """Escalation from WARNING to CRITICAL bypasses cooldown."""
        warning_reading = _make_reading(water_level_cm=80.0)
        self.pipeline.process(warning_reading, persist=False)

        critical_reading = _make_reading(water_level_cm=125.0)
        r = self.pipeline.process(critical_reading, persist=False, sms_recipients=["+91123"])
        self.assertFalse(r.suppressed)
        self.assertTrue(r.dispatched)

    def test_alert_lifecycle_status_dispatched(self) -> None:
        """A dispatched alert must have lifecycle_status='dispatched' in alerts table."""
        reading = _make_reading(water_level_cm=30.0)
        result = self.pipeline.process(reading, persist=False)
        row = self.conn.execute(
            "SELECT lifecycle_status FROM alerts WHERE alert_id=?",
            (result.alert_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["lifecycle_status"], "dispatched")

    def test_suppressed_alert_has_suppressed_lifecycle(self) -> None:
        """A suppressed alert must have lifecycle_status='suppressed'."""
        reading = _make_reading(water_level_cm=80.0)
        self.pipeline.process(reading, persist=False)  # first: dispatched
        r2 = self.pipeline.process(reading, persist=False)  # second: suppressed
        row = self.conn.execute(
            "SELECT lifecycle_status, suppressed FROM alerts WHERE alert_id=?",
            (r2.alert_id,),
        ).fetchone()
        self.assertEqual(row["lifecycle_status"], "suppressed")
        self.assertEqual(row["suppressed"], 1)

    def test_acknowledge_and_resolve_lifecycle(self) -> None:
        """acknowledge_alert() and resolve_alert() must update lifecycle_status."""
        reading = _make_reading(water_level_cm=30.0)
        result = self.pipeline.process(reading, persist=False)
        alert_id = result.alert_id

        acknowledge_alert(alert_id, db_path=self.conn)
        row = self.conn.execute(
            "SELECT lifecycle_status FROM alerts WHERE alert_id=?", (alert_id,)
        ).fetchone()
        self.assertEqual(row["lifecycle_status"], "acknowledged")

        resolve_alert(alert_id, db_path=self.conn)
        row = self.conn.execute(
            "SELECT lifecycle_status FROM alerts WHERE alert_id=?", (alert_id,)
        ).fetchone()
        self.assertEqual(row["lifecycle_status"], "resolved")
