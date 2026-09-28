"""Twilio notification handler for SMS, WhatsApp, and Voice emergency alerts."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class TwilioDispatchResult:
    """Outcome of a Twilio delivery attempt."""

    success: bool
    channel: str
    recipient: str
    message_sid: Optional[str] = None
    call_sid: Optional[str] = None
    status: str = "PENDING"
    error: Optional[str] = None


class TwilioAlertHandler:
    """Dispatches SMS, WhatsApp, and Automated Voice Calls via Twilio REST API."""

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_phone: Optional[str] = None,
        whatsapp_from_phone: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_phone = from_phone
        self.whatsapp_from_phone = (
            whatsapp_from_phone
            or os.getenv("TWILIO_WHATSAPP_PHONE_NUMBER")
            or os.getenv("TWILIO_WHATSAPP_FROM")
        )
        self.dry_run = dry_run
        self._client: Any = None

    @property
    def is_configured(self) -> bool:
        """Check if real credentials are present."""
        return bool(
            self.account_sid
            and not self.account_sid.startswith("ACxxxx")
            and self.auth_token
            and "your_" not in self.auth_token
            and (self.from_phone or self.whatsapp_from_phone)
        )

    def _get_client(self) -> Any:
        """Lazy load Twilio Client to allow offline and mocked execution."""
        if self._client is None:
            if not self.is_configured:
                raise ValueError("Twilio credentials are incomplete or invalid.")
            from twilio.rest import Client  # type: ignore

            self._client = Client(self.account_sid, self.auth_token)
        return self._client

    def send_sms(self, to_phone: str, body: str) -> TwilioDispatchResult:
        """Send an urgent SMS alert to a recipient phone number."""
        if not to_phone:
            return TwilioDispatchResult(
                success=False,
                channel="SMS",
                recipient=to_phone,
                status="FAILED",
                error="Empty destination phone number",
            )

        if to_phone.startswith("whatsapp:"):
            return self.send_whatsapp(to_phone=to_phone, body=body)

        clean_to = to_phone[4:] if to_phone.startswith("sms:") else to_phone
        clean_from = (
            self.from_phone[4:]
            if self.from_phone and self.from_phone.startswith("sms:")
            else self.from_phone
        )

        if self.dry_run or not self.is_configured:
            logger.info(
                "[DRY_RUN Twilio SMS] Simulated SMS to %s from %s: %s",
                clean_to,
                clean_from or "<MOCK_FROM>",
                body,
            )
            return TwilioDispatchResult(
                success=True,
                channel="SMS",
                recipient=clean_to,
                message_sid="SM_SIMULATED_MOCK_SID_12345",
                status="DRY_RUN",
            )

        try:
            client = self._get_client()
            message = client.messages.create(
                to=clean_to,
                from_=clean_from,
                body=body,
            )
            logger.info("Sent Twilio SMS to %s (SID: %s)", clean_to, message.sid)
            return TwilioDispatchResult(
                success=True,
                channel="SMS",
                recipient=clean_to,
                message_sid=message.sid,
                status=message.status,
            )
        except Exception as ex:
            logger.error("Failed to send Twilio SMS to %s: %s", clean_to, ex)
            return TwilioDispatchResult(
                success=False,
                channel="SMS",
                recipient=clean_to,
                status="FAILED",
                error=str(ex),
            )

    def send_whatsapp(self, to_phone: str, body: str) -> TwilioDispatchResult:
        """Send an urgent WhatsApp alert via Twilio WhatsApp sandbox or registered sender."""
        if not to_phone:
            return TwilioDispatchResult(
                success=False,
                channel="WHATSAPP",
                recipient=to_phone,
                status="FAILED",
                error="Empty destination phone number",
            )

        # Normalize destination to 'whatsapp:+...'
        clean_phone = to_phone[4:] if to_phone.startswith("sms:") else to_phone
        to_target = (
            clean_phone if clean_phone.startswith("whatsapp:") else f"whatsapp:{clean_phone}"
        )

        # Resolve sender: check whatsapp_from_phone, from_phone, or default Twilio sandbox
        from_raw = (
            self.whatsapp_from_phone
            or (self.from_phone if self.from_phone and self.from_phone.startswith("whatsapp:") else None)
            or (f"whatsapp:{self.from_phone}" if self.from_phone else "whatsapp:+14155238886")
        )
        from_target = from_raw if from_raw.startswith("whatsapp:") else f"whatsapp:{from_raw}"

        if self.dry_run or not self.is_configured:
            logger.info(
                "[DRY_RUN Twilio WhatsApp] Simulated WhatsApp to %s from %s: %s",
                to_target,
                from_target,
                body,
            )
            return TwilioDispatchResult(
                success=True,
                channel="WHATSAPP",
                recipient=to_target,
                message_sid="WA_SIMULATED_MOCK_SID_12345",
                status="DRY_RUN",
            )

        try:
            client = self._get_client()
            message = client.messages.create(
                to=to_target,
                from_=from_target,
                body=body,
            )
            logger.info("Sent Twilio WhatsApp to %s (SID: %s)", to_target, message.sid)
            return TwilioDispatchResult(
                success=True,
                channel="WHATSAPP",
                recipient=to_target,
                message_sid=message.sid,
                status=message.status,
            )
        except Exception as ex:
            logger.error("Failed to send Twilio WhatsApp to %s: %s", to_target, ex)
            return TwilioDispatchResult(
                success=False,
                channel="WHATSAPP",
                recipient=to_target,
                status="FAILED",
                error=str(ex),
            )

    def make_voice_call(
        self,
        to_phone: str,
        twiml_url_or_say: str,
    ) -> TwilioDispatchResult:
        """Place an automated phone call with TwiML or a spoken warning."""
        if not to_phone:
            return TwilioDispatchResult(
                success=False,
                channel="VOICE",
                recipient=to_phone,
                status="FAILED",
                error="Empty destination phone number",
            )

        clean_to = (
            to_phone[4:]
            if to_phone.startswith("sms:")
            else (to_phone[9:] if to_phone.startswith("whatsapp:") else to_phone)
        )

        clean_from = (
            self.from_phone[4:]
            if self.from_phone and self.from_phone.startswith("sms:")
            else self.from_phone
        )

        if self.dry_run or not self.is_configured:
            logger.info(
                "[DRY_RUN Twilio VOICE] Simulated Call to %s: %s",
                clean_to,
                twiml_url_or_say,
            )
            return TwilioDispatchResult(
                success=True,
                channel="VOICE",
                recipient=clean_to,
                call_sid="CA_SIMULATED_MOCK_SID_12345",
                status="DRY_RUN",
            )

        try:
            client = self._get_client()
            if twiml_url_or_say.startswith("http://") or twiml_url_or_say.startswith("https://"):
                call = client.calls.create(
                    to=clean_to,
                    from_=clean_from,
                    url=twiml_url_or_say,
                )
            else:
                twiml_say = f"<Response><Say voice='alice'>{twiml_url_or_say}</Say></Response>"
                call = client.calls.create(
                    to=clean_to,
                    from_=clean_from,
                    twiml=twiml_say,
                )

            logger.info("Placed Twilio Voice call to %s (SID: %s)", to_phone, call.sid)
            return TwilioDispatchResult(
                success=True,
                channel="VOICE",
                recipient=to_phone,
                call_sid=call.sid,
                status=call.status,
            )
        except Exception as ex:
            logger.error("Failed to make Twilio voice call to %s: %s", to_phone, ex)
            return TwilioDispatchResult(
                success=False,
                channel="VOICE",
                recipient=to_phone,
                status="FAILED",
                error=str(ex),
            )
