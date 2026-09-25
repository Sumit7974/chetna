"""Unified alert dispatcher routing flood warnings by severity level."""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import List, Optional, Union
import sqlite3
from pathlib import Path

from config.settings import settings
from alerts.telegram_handler import TelegramAlertHandler
from alerts.twilio_handler import TwilioAlertHandler
from database.db import DEFAULT_DB_PATH, log_alert_dispatch

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Graduated alert severity scale for flood notifications."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertDispatcher:
    """Orchestrates notification dispatch across SMS, Voice, and Telegram channels."""

    def __init__(
        self,
        twilio_handler: Optional[TwilioAlertHandler] = None,
        telegram_handler: Optional[TelegramAlertHandler] = None,
        db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    ) -> None:
        self.twilio = twilio_handler or TwilioAlertHandler(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_phone=settings.twilio_phone_number,
            dry_run=settings.alert_dry_run,
        )
        self.telegram = telegram_handler or TelegramAlertHandler(
            bot_token=settings.telegram_bot_token,
            default_chat_id=settings.telegram_chat_id,
            dry_run=settings.alert_dry_run,
        )
        self.db_path = db_path

    def dispatch(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        affected_area: str,
        sms_recipients: Optional[List[str]] = None,
        telegram_chat_id: Optional[str] = None,
    ) -> str:
        """Route alert according to severity tier and log audit trail."""
        alert_id = f"ALT-{uuid.uuid4().hex[:8].upper()}"
        formatted_tg = (
            f"🌊 *[CHETNA FLOOD ALERT: {severity.value}]*\n"
            f"*Area:* {affected_area}\n"
            f"*{title}*\n\n"
            f"{message}\n\n"
            f"⚠️ _Stay tuned to official disaster management guidelines._"
        )
        formatted_sms = f"[CHETNA {severity.value}] {title} in {affected_area}. {message}"

        # 1. Telegram delivery for all tiers
        tg_res = self.telegram.send_message(
            text=formatted_tg,
            chat_id=telegram_chat_id,
        )
        log_alert_dispatch(
            alert_id=alert_id,
            severity=severity.value,
            channel="TELEGRAM",
            recipient=tg_res.chat_id or "default",
            message=formatted_tg,
            status=tg_res.status,
            response_payload=str(tg_res.message_id or tg_res.error),
            db_path=self.db_path,
        )

        # 2. SMS delivery for WARNING, CRITICAL, EMERGENCY
        recipients = sms_recipients or settings.emergency_broadcast_numbers
        if severity in (
            AlertSeverity.WARNING,
            AlertSeverity.CRITICAL,
            AlertSeverity.EMERGENCY,
        ):
            for phone in recipients:
                sms_res = self.twilio.send_sms(to_phone=phone, body=formatted_sms)
                log_alert_dispatch(
                    alert_id=alert_id,
                    severity=severity.value,
                    channel="TWILIO_SMS",
                    recipient=phone,
                    message=formatted_sms,
                    status=sms_res.status,
                    response_payload=str(sms_res.message_sid or sms_res.error),
                    db_path=self.db_path,
                )

        # 3. Automated Voice Calls for EMERGENCY tier
        if severity == AlertSeverity.EMERGENCY:
            voice_prompt = (
                f"Emergency flood warning for {affected_area}. "
                f"{message}. Please move to higher ground immediately."
            )
            for phone in recipients:
                call_res = self.twilio.make_voice_call(
                    to_phone=phone,
                    twiml_url_or_say=voice_prompt,
                )
                log_alert_dispatch(
                    alert_id=alert_id,
                    severity=severity.value,
                    channel="TWILIO_VOICE",
                    recipient=phone,
                    message=voice_prompt,
                    status=call_res.status,
                    response_payload=str(call_res.call_sid or call_res.error),
                    db_path=self.db_path,
                )

        logger.info("Alert %s (%s) dispatched successfully.", alert_id, severity.value)
        return alert_id
