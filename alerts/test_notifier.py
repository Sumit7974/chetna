"""Test notification runner for Chetna AI flood early-warning system (Day 1).

Fulfills Day 1 messaging goals:
1. Loads environment variables via python-dotenv for Twilio and Telegram.
2. Implements send_test_alert(channel="twilio") with automatic fallback to Telegram.
3. Supports Twilio SMS and Twilio WhatsApp Sandbox delivery.
4. Logs full delivery audit outcomes to stdout and into SQLite `alert_logs` table in `data/flood_warning.db`.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Ensure project root is accessible in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment configuration (.env)
try:
    from dotenv import load_dotenv

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
    else:
        # Fallback to .env.example if .env has not been generated yet
        load_dotenv(dotenv_path=PROJECT_ROOT / ".env.example")
except ImportError:
    pass

import requests
from database.init_db import DEFAULT_DB_PATH, init_db, insert_alert_log

# Configure logger with crisp standard output formatting
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alerts.test_notifier")


def _is_placeholder(val: Optional[str]) -> bool:
    """Check if an environment value is empty or a placeholder template."""
    if not val:
        return True
    val_clean = val.strip().lower()
    placeholders = ("acxxxx", "your_", "example", "123456789:abc", "+1234567890")
    return any(p in val_clean for p in placeholders)


def _send_twilio_message(
    body: str,
    account_sid: str,
    auth_token: str,
    from_phone: str,
    to_phone: str,
    is_whatsapp: bool = False,
) -> Dict[str, Any]:
    """Execute a Twilio SMS or WhatsApp delivery call."""
    if _is_placeholder(account_sid) or _is_placeholder(auth_token) or _is_placeholder(from_phone):
        raise ValueError("Twilio credentials are missing or using placeholder templates.")

    if not to_phone or _is_placeholder(to_phone):
        raise ValueError("Twilio recipient phone number is not specified or is a placeholder.")

    # Lazy import twilio client
    from twilio.rest import Client  # type: ignore

    client = Client(account_sid, auth_token)

    from_target = from_phone
    to_target = to_phone

    # Format numbers for WhatsApp Sandbox if requested or specified in sender
    if is_whatsapp or from_phone.startswith("whatsapp:") or to_phone.startswith("whatsapp:"):
        from_target = from_phone if from_phone.startswith("whatsapp:") else f"whatsapp:{from_phone}"
        to_target = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"
        provider_name = "TWILIO_WHATSAPP"
    else:
        provider_name = "TWILIO_SMS"

    logger.info("Attempting dispatch via %s (from: %s to: %s)...", provider_name, from_target, to_target)
    message = client.messages.create(
        body=body,
        from_=from_target,
        to=to_target,
    )
    return {
        "provider": provider_name,
        "sid": message.sid,
        "status": message.status.upper() if message.status else "SENT",
        "recipient": to_target,
    }


def _send_telegram_message(
    body: str,
    bot_token: str,
    chat_id: str,
) -> Dict[str, Any]:
    """Execute Telegram Bot API sendMessage call via HTTP POST."""
    if _is_placeholder(bot_token) or _is_placeholder(chat_id):
        raise ValueError("Telegram Bot Token or Chat ID is missing or using placeholder templates.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": body,
        "parse_mode": "Markdown",
    }

    logger.info("Attempting dispatch via TELEGRAM_BOT to chat_id: %s...", chat_id)
    resp = requests.post(url, json=payload, timeout=10)
    data = resp.json()

    if resp.status_code == 200 and data.get("ok"):
        msg_id = data.get("result", {}).get("message_id")
        return {
            "provider": "TELEGRAM_BOT",
            "message_id": msg_id,
            "status": "SENT",
            "recipient": chat_id,
        }
    else:
        error_desc = data.get("description", f"HTTP {resp.status_code}")
        raise RuntimeError(f"Telegram API rejected message: {error_desc}")


def send_test_alert(
    channel: str = "twilio",
    message: str = "Flood System Setup Test: Day 1 Complete",
    zone_id: str = "ZONE_TEST_01",
    to_phone: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Send test alert with primary channel and automatic fallback to Telegram.

    Logs the outcome to stdout and commits the audit record into SQLite `alert_logs`.
    """
    # 1. Ensure SQLite database & alert_logs table exist
    init_db(db_path)

    # 2. Resolve credentials from environment
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from = os.getenv("TWILIO_PHONE_NUMBER", "")
    target_phone = to_phone or os.getenv("TWILIO_TO_PHONE") or os.getenv("EMERGENCY_BROADCAST_NUMBERS", "").split(",")[0]

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    channel_norm = channel.strip().lower()

    status = "PENDING"
    provider_used = "UNKNOWN"
    delivery_details = ""
    error_summary = None

    logger.info("--- Starting Test Alert Dispatch [Primary: %s, Zone: %s] ---", channel.upper(), zone_id)

    # 3. Primary Dispatch Attempt (Twilio SMS / WhatsApp)
    primary_success = False
    if channel_norm in ("twilio", "sms", "whatsapp"):
        is_whatsapp = (channel_norm == "whatsapp")
        try:
            res = _send_twilio_message(
                body=message,
                account_sid=twilio_sid,
                auth_token=twilio_token,
                from_phone=twilio_from,
                to_phone=target_phone,
                is_whatsapp=is_whatsapp,
            )
            provider_used = res["provider"]
            status = "SENT"
            delivery_details = f"SID: {res['sid']}"
            primary_success = True
            logger.info(">>> SUCCESS via Primary [%s] -> Status: %s (%s)", provider_used, status, delivery_details)

        except Exception as twilio_err:
            logger.warning(">>> WARNING: Primary Twilio dispatch failed: %s", twilio_err)
            error_summary = f"Twilio Failure: {twilio_err}"

    # 4. Fallback to Telegram Bot if primary failed or Telegram was directly requested
    if not primary_success:
        if channel_norm in ("twilio", "sms", "whatsapp"):
            logger.info(">>> FALLBACK TRIGGERED: Attempting automated failover to TELEGRAM_BOT...")

        try:
            tg_res = _send_telegram_message(
                body=f"🚨 *[FALLBACK ALERT]*\n{message}\n\n_Note: Primary channel ({channel.upper()}) was unavailable._"
                if channel_norm != "telegram"
                else message,
                bot_token=tg_token,
                chat_id=tg_chat,
            )
            provider_used = "TELEGRAM_BOT"
            status = "FALLBACK_SENT" if channel_norm != "telegram" else "SENT"
            delivery_details = f"MessageID: {tg_res['message_id']}"
            logger.info(">>> SUCCESS via Fallback [%s] -> Status: %s (%s)", provider_used, status, delivery_details)

        except Exception as tg_err:
            logger.error(">>> FAILURE: Telegram delivery also failed: %s", tg_err)
            provider_used = "FAILED_ALL"
            status = "FAILED"
            combined_err = f"{error_summary} | Telegram Failure: {tg_err}" if error_summary else str(tg_err)
            delivery_details = f"Errors: {combined_err}"

    # 5. Log final audit trail to standard output
    print("\n" + "=" * 70)
    print(f"  ALERT DISPATCH OUTCOME REPORT (Day 1 Test)")
    print("=" * 70)
    print(f"  Timestamp    : {timestamp_iso}")
    print(f"  Zone ID      : {zone_id}")
    print(f"  Status       : {status}")
    print(f"  Provider     : {provider_used}")
    print(f"  Details      : {delivery_details}")
    print(f"  Message Body : '{message}'")
    print("=" * 70 + "\n")

    # 6. Commit outcome into SQLite `alert_logs` table
    alert_log_id = insert_alert_log(
        zone_id=zone_id,
        status=status,
        provider=provider_used,
        raw_message=f"{message} | details={delivery_details}",
        timestamp=timestamp_iso,
        db_path=db_path,
    )
    logger.info("Audit log written to SQLite [alert_logs ID: %d] at '%s'", alert_log_id, db_path)

    return {
        "alert_id": alert_log_id,
        "timestamp": timestamp_iso,
        "zone_id": zone_id,
        "status": status,
        "provider": provider_used,
        "details": delivery_details,
        "message": message,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Day 1 Flood Alert Notifier Test with Twilio & Telegram Fallback")
    parser.add_argument("--channel", default="twilio", choices=["twilio", "whatsapp", "sms", "telegram"], help="Primary channel")
    parser.add_argument("--message", default="Flood System Setup Test: Day 1 Complete", help="Test message body")
    parser.add_argument("--zone", default="ZONE_TEST_01", help="Target monitoring zone ID")
    parser.add_argument("--phone", default=None, help="Target recipient phone number")
    parser.add_argument("--chat-id", default=None, help="Target Telegram chat ID")

    args = parser.parse_args()

    result = send_test_alert(
        channel=args.channel,
        message=args.message,
        zone_id=args.zone,
        to_phone=args.phone,
        telegram_chat_id=args.chat_id,
    )
    sys.exit(0 if result["status"] in ("SENT", "FALLBACK_SENT") else 1)
