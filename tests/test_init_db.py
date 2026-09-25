"""Tests for database/init_db.py module."""

from __future__ import annotations

import datetime
import sqlite3
import unittest

from database.init_db import (
    get_alert_by_id,
    get_alert_logs,
    get_db_connection,
    get_latest_risk_predictions,
    get_latest_sensor_reading,
    get_sensor_readings,
    init_db,
    insert_alert_log,
    insert_risk_prediction,
    insert_sensor_reading,
    insert_sensor_readings_batch,
)


class TestInitDb(unittest.TestCase):
    """Test suite for SQLite schema creation and CRUD helpers."""

    def setUp(self) -> None:
        self.mem_conn = sqlite3.connect(":memory:")
        self.mem_conn.row_factory = sqlite3.Row
        init_db(self.mem_conn)

    def tearDown(self) -> None:
        self.mem_conn.close()

    def test_schema_creates_contract_tables(self) -> None:
        """Verify sensor_table, alert_logs, and risk_predictions are created."""
        cursor = self.mem_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cursor.fetchall()}
        self.assertIn("sensor_table", tables)
        self.assertIn("alert_logs", tables)
        self.assertIn("risk_predictions", tables)

    def test_idempotent_init_db(self) -> None:
        """Calling init_db multiple times should not raise errors or duplicate tables."""
        init_db(self.mem_conn)
        init_db(self.mem_conn)

    def test_sensor_reading_crud(self) -> None:
        """Test insert, query, and latest reading fetch for sensor_table."""
        t1 = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat()
        t2 = datetime.datetime.now(datetime.timezone.utc).isoformat()

        id1 = insert_sensor_reading(
            sensor_id="SENS_01",
            level_cm=45.2,
            timestamp=t1,
            status="ACTIVE",
            source="simulated",
            db_path=self.mem_conn,
        )
        self.assertGreater(id1, 0)

        id2 = insert_sensor_reading(
            sensor_id="SENS_01",
            level_cm=88.7,
            timestamp=t2,
            status="ACTIVE",
            source="simulated",
            db_path=self.mem_conn,
        )
        self.assertGreater(id2, id1)

        # Query all
        all_readings = get_sensor_readings(sensor_id="SENS_01", db_path=self.mem_conn)
        self.assertEqual(len(all_readings), 2)
        # Should be ordered descending by timestamp
        self.assertAlmostEqual(all_readings[0]["level_cm"], 88.7)

        # Query latest
        latest = get_latest_sensor_reading("SENS_01", db_path=self.mem_conn)
        self.assertIsNotNone(latest)
        self.assertAlmostEqual(latest["level_cm"], 88.7)

    def test_batch_sensor_readings_insert(self) -> None:
        """Test bulk insertion of sensor readings."""
        batch = [
            {"sensor_id": "SENS_02", "level_cm": 30.0, "status": "ACTIVE", "source": "real"},
            {"sensor_id": "SENS_02", "level_cm": 35.5, "status": "ACTIVE", "source": "real"},
            {"sensor_id": "SENS_03", "level_cm": 15.0, "status": "ACTIVE", "source": "simulated"},
        ]
        count = insert_sensor_readings_batch(batch, db_path=self.mem_conn)
        self.assertEqual(count, 3)

        readings = get_sensor_readings(source="real", db_path=self.mem_conn)
        self.assertEqual(len(readings), 2)

    def test_alert_logs_crud(self) -> None:
        """Test insert and query operations on alert_logs."""
        alert_id = insert_alert_log(
            zone_id="ZONE_ADYAR_NORTH",
            status="SENT",
            provider="TWILIO_SMS",
            raw_message="Urgent: Flood warning stage reached in Adyar.",
            db_path=self.mem_conn,
        )
        self.assertGreater(alert_id, 0)

        alert = get_alert_by_id(alert_id, db_path=self.mem_conn)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["zone_id"], "ZONE_ADYAR_NORTH")
        self.assertEqual(alert["status"], "SENT")
        self.assertEqual(alert["provider"], "TWILIO_SMS")

        logs = get_alert_logs(zone_id="ZONE_ADYAR_NORTH", db_path=self.mem_conn)
        self.assertEqual(len(logs), 1)

    def test_risk_predictions_crud(self) -> None:
        """Test insert and query operations on risk_predictions."""
        pred_id = insert_risk_prediction(
            cell_id="CELL_1308_8027",
            horizon=3,
            level="HIGH",
            probability=0.87,
            db_path=self.mem_conn,
        )
        self.assertGreater(pred_id, 0)

        preds = get_latest_risk_predictions(cell_id="CELL_1308_8027", horizon=3, db_path=self.mem_conn)
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["level"], "HIGH")
        self.assertAlmostEqual(preds[0]["probability"], 0.87)
