"""Tests for Chetna B2 alert handlers and dispatcher."""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from alerts.dispatcher import AlertDispatcher, AlertSeverity
from alerts.telegram_handler import TelegramAlertHandler
from alerts.twilio_handler import TwilioAlertHandler
from database.db import init_db


class TestAlerts(unittest.TestCase):
    """Test suite for Twilio, Telegram handlers and multi-tier AlertDispatcher."""

    def setUp(self) -> None:
        self.mem_conn = sqlite3.connect(":memory:")
        self.mem_conn.row_factory = sqlite3.Row
        init_db(self.mem_conn)

    def tearDown(self) -> None:
        self.mem_conn.close()

    def test_twilio_sms_dry_run_mode(self) -> None:
        """Twilio handler in dry_run mode should succeed without real network credentials."""
        handler = TwilioAlertHandler(dry_run=True)
        res = handler.send_sms("+919876543210", "Flood alert test")
        self.assertTrue(res.success)
        self.assertEqual(res.status, "DRY_RUN")
        self.assertEqual(res.recipient, "+919876543210")
        self.assertIsNotNone(res.message_sid)

    def test_twilio_voice_call_dry_run_mode(self) -> None:
        """Twilio voice call in dry_run mode should succeed with simulated SID."""
        handler = TwilioAlertHandler(dry_run=True)
        res = handler.make_voice_call("+919876543210", "Evacuate low lying areas.")
        self.assertTrue(res.success)
        self.assertEqual(res.status, "DRY_RUN")
        self.assertIsNotNone(res.call_sid)

    def test_twilio_sms_with_mocked_client(self) -> None:
        """Twilio handler calls Twilio SDK when credentials and dry_run=False are active."""
        handler = TwilioAlertHandler(
            account_sid="AC_TEST_ACCOUNT_SID",
            auth_token="valid_secret_token",
            from_phone="+12000000000",
            dry_run=False,
        )
        mock_msg = MagicMock()
        mock_msg.sid = "SM_MOCK_SUCCESS_123"
        mock_msg.status = "queued"

        with patch.object(handler, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_msg
            mock_get.return_value = mock_client

            res = handler.send_sms("+919876543210", "Live water level warning")
            self.assertTrue(res.success)
            self.assertEqual(res.message_sid, "SM_MOCK_SUCCESS_123")
            mock_client.messages.create.assert_called_once_with(
                to="+919876543210",
                from_="+12000000000",
                body="Live water level warning",
            )

    def test_telegram_dry_run_mode(self) -> None:
        """Telegram handler in dry_run mode should succeed with simulated message_id."""
        handler = TelegramAlertHandler(default_chat_id="-10099999", dry_run=True)
        res = handler.send_message("🌊 Warning: Rising river levels.")
        self.assertTrue(res.success)
        self.assertEqual(res.status, "DRY_RUN")
        self.assertEqual(res.chat_id, "-10099999")

    @patch("alerts.telegram_handler.requests.post")
    def test_telegram_live_mocked_api_call(self, mock_post) -> None:
        """Telegram handler dispatches HTTP POST payload when configured."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "result": {"message_id": 445566},
        }

        handler = TelegramAlertHandler(
            bot_token="real_bot_token_valid",
            default_chat_id="-10011223344",
            dry_run=False,
        )
        res = handler.send_message("Test Telegram broadcast")
        self.assertTrue(res.success)
        self.assertEqual(res.message_id, 445566)
        mock_post.assert_called_once()

    def test_alert_dispatcher_severity_escalation(self) -> None:
        """Dispatcher delivers to channels according to severity and records DB audit log."""
        mock_twilio = MagicMock(spec=TwilioAlertHandler)
        mock_twilio.send_sms.return_value = MagicMock(
            status="SENT", message_sid="SM1", error=None
        )
        mock_twilio.make_voice_call.return_value = MagicMock(
            status="SENT", call_sid="CA1", error=None
        )

        mock_tg = MagicMock(spec=TelegramAlertHandler)
        mock_tg.send_message.return_value = MagicMock(
            status="SENT", chat_id="-100123", message_id=123, error=None
        )

        dispatcher = AlertDispatcher(
            twilio_handler=mock_twilio,
            telegram_handler=mock_tg,
            db_path=self.mem_conn,
        )

        # 1. INFO tier: Only Telegram
        dispatcher.dispatch(
            severity=AlertSeverity.INFO,
            title="Advisory",
            message="Light showers expected.",
            affected_area="Adyar",
            sms_recipients=["+919876543210"],
        )
        mock_tg.send_message.assert_called_once()
        mock_twilio.send_sms.assert_not_called()
        mock_twilio.make_voice_call.assert_not_called()

        # 2. EMERGENCY tier: Telegram, SMS, and Voice Calls
        mock_tg.reset_mock()
        mock_twilio.reset_mock()

        dispatcher.dispatch(
            severity=AlertSeverity.EMERGENCY,
            title="Flash Flood Evacuation",
            message="Water level reached 140cm.",
            affected_area="Velachery",
            sms_recipients=["+919876543210"],
        )
        mock_tg.send_message.assert_called_once()
        mock_twilio.send_sms.assert_called_once()
        mock_twilio.make_voice_call.assert_called_once()

        # Verify audit logs in SQLite
        logs = self.mem_conn.execute("SELECT * FROM alert_logs;").fetchall()
        self.assertGreaterEqual(len(logs), 4)  # 1 INFO TG + 1 EMG TG + 1 EMG SMS + 1 EMG Voice
