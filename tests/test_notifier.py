"""Unit tests for alerts/test_notifier.py."""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from alerts.test_notifier import send_test_alert
from database.init_db import get_alert_by_id, init_db


class TestNotifier(unittest.TestCase):
    """Test suite for Day 1 notifier with Twilio and Telegram fallback."""

    def setUp(self) -> None:
        self.mem_conn = sqlite3.connect(":memory:")
        self.mem_conn.row_factory = sqlite3.Row
        init_db(self.mem_conn)

    def tearDown(self) -> None:
        self.mem_conn.close()

    @patch("alerts.test_notifier._send_twilio_message")
    def test_send_test_alert_twilio_success(self, mock_twilio) -> None:
        """When Twilio succeeds, status is SENT and provider is TWILIO_SMS."""
        mock_twilio.return_value = {
            "provider": "TWILIO_SMS",
            "sid": "SM_MOCK_123456",
            "status": "SENT",
            "recipient": "+919876543210",
        }

        res = send_test_alert(
            channel="twilio",
            message="Flood System Setup Test: Day 1 Complete",
            zone_id="ZONE_ADYAR",
            db_path=self.mem_conn,
        )

        self.assertEqual(res["status"], "SENT")
        self.assertEqual(res["provider"], "TWILIO_SMS")
        self.assertIn("SM_MOCK_123456", res["details"])

        # Check SQLite alert_logs
        alert = get_alert_by_id(res["alert_id"], db_path=self.mem_conn)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["status"], "SENT")
        self.assertEqual(alert["provider"], "TWILIO_SMS")
        self.assertEqual(alert["zone_id"], "ZONE_ADYAR")

    @patch("alerts.test_notifier._send_telegram_message")
    @patch("alerts.test_notifier._send_twilio_message")
    def test_send_test_alert_twilio_fails_telegram_fallback_success(
        self, mock_twilio, mock_tg
    ) -> None:
        """When Twilio fails, notifier falls back to Telegram and logs FALLBACK_SENT."""
        mock_twilio.side_effect = RuntimeError("Twilio network error / invalid credentials")
        mock_tg.return_value = {
            "provider": "TELEGRAM_BOT",
            "message_id": 98765,
            "status": "SENT",
            "recipient": "-100123456789",
        }

        res = send_test_alert(
            channel="twilio",
            message="Flood System Setup Test: Day 1 Complete",
            zone_id="ZONE_VELACHERY",
            db_path=self.mem_conn,
        )

        self.assertEqual(res["status"], "FALLBACK_SENT")
        self.assertEqual(res["provider"], "TELEGRAM_BOT")
        self.assertIn("98765", res["details"])

        # Check SQLite audit trail
        alert = get_alert_by_id(res["alert_id"], db_path=self.mem_conn)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["status"], "FALLBACK_SENT")
        self.assertEqual(alert["provider"], "TELEGRAM_BOT")

    @patch("alerts.test_notifier._send_telegram_message")
    @patch("alerts.test_notifier._send_twilio_message")
    def test_send_test_alert_both_fail(self, mock_twilio, mock_tg) -> None:
        """When both Twilio and Telegram fail, logs FAILED status to alert_logs."""
        mock_twilio.side_effect = ValueError("Twilio credentials missing")
        mock_tg.side_effect = RuntimeError("Telegram Bot unreachable")

        res = send_test_alert(
            channel="twilio",
            message="Flood System Setup Test: Day 1 Complete",
            zone_id="ZONE_FAIL_SAFE",
            db_path=self.mem_conn,
        )

        self.assertEqual(res["status"], "FAILED")
        self.assertEqual(res["provider"], "FAILED_ALL")

        # Check SQLite audit trail
        alert = get_alert_by_id(res["alert_id"], db_path=self.mem_conn)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["status"], "FAILED")
        self.assertEqual(alert["provider"], "FAILED_ALL")
