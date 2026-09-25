"""Tests for Chetna B2 database schema and query helpers."""

from __future__ import annotations

import sqlite3
import unittest
from database.db import (
    init_db,
    log_alert_dispatch,
    register_sensor_node,
    save_sensor_reading,
)


class TestDatabase(unittest.TestCase):
    """Test suite for SQLite schema DDL, sensor tables, and audit logs."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_schema_creates_all_b2_tables(self) -> None:
        """Verify all essential B2 tables exist in the initialized schema."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cursor.fetchall()}
        expected = {
            "forecasts",
            "sensor_nodes",
            "sensor_readings",
            "alert_subscribers",
            "alert_logs",
        }
        self.assertTrue(expected.issubset(tables))

    def test_register_sensor_node_and_save_reading(self) -> None:
        """Verify registering a sensor node and appending telemetry readings."""
        register_sensor_node(
            node_id="NODE_TEST_01",
            name="Adyar River Bridge",
            latitude=13.0012,
            longitude=80.2565,
            sensor_type="water_level",
            db_path=self.conn,
        )

        reading_id = save_sensor_reading(
            node_id="NODE_TEST_01",
            timestamp="2026-09-24T18:00:00Z",
            water_level_cm=42.5,
            rainfall_rate_mm_h=12.0,
            battery_pct=95.0,
            is_anomaly=0,
            db_path=self.conn,
        )
        self.assertGreater(reading_id, 0)

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM sensor_readings WHERE id = ?;", (reading_id,)
        )
        row = cursor.fetchone()
        self.assertEqual(row["node_id"], "NODE_TEST_01")
        self.assertAlmostEqual(row["water_level_cm"], 42.5)

    def test_log_alert_dispatch(self) -> None:
        """Verify alert dispatch logs are appended with correct metadata."""
        log_id = log_alert_dispatch(
            alert_id="ALT-TEST-99",
            severity="CRITICAL",
            channel="TWILIO_SMS",
            recipient="+919876543210",
            message="Water level breach test",
            status="SENT",
            response_payload="SM12345",
            db_path=self.conn,
        )
        self.assertGreater(log_id, 0)

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM alert_logs WHERE id = ?;", (log_id,))
        row = cursor.fetchone()
        self.assertEqual(row["alert_id"], "ALT-TEST-99")
        self.assertEqual(row["severity"], "CRITICAL")
        self.assertEqual(row["status"], "SENT")
