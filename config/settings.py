"""Configuration and environment settings loader for Chetna B2."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Attempt to load .env using python-dotenv if present
try:
    from dotenv import load_dotenv

    # Search for .env at repository root
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass


def _bool_from_env(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


def _float_from_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _int_from_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass
class Settings:
    """Application settings for Chetna Backend & Alert delivery."""

    # Twilio Configuration
    twilio_account_sid: str = field(
        default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", "")
    )
    twilio_auth_token: str = field(
        default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", "")
    )
    twilio_phone_number: str = field(
        default_factory=lambda: os.getenv("TWILIO_PHONE_NUMBER", "")
    )

    # Telegram Bot Configuration
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )
    telegram_chat_id: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", "")
    )

    # Operational & Safety Flags
    alert_dry_run: bool = field(
        default_factory=lambda: _bool_from_env("ALERT_DRY_RUN", default=True)
    )
    alert_log_level: str = field(
        default_factory=lambda: os.getenv("ALERT_LOG_LEVEL", "INFO")
    )
    alert_retry_attempts: int = field(
        default_factory=lambda: _int_from_env("ALERT_RETRY_ATTEMPTS", default=3)
    )

    # Database
    database_path: str = field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "data/chetna.db")
    )

    # Thresholds
    water_level_warning_threshold_cm: float = field(
        default_factory=lambda: _float_from_env(
            "WATER_LEVEL_WARNING_THRESHOLD_CM", default=75.0
        )
    )
    water_level_critical_threshold_cm: float = field(
        default_factory=lambda: _float_from_env(
            "WATER_LEVEL_CRITICAL_THRESHOLD_CM", default=120.0
        )
    )
    rainfall_hourly_warning_mm: float = field(
        default_factory=lambda: _float_from_env(
            "RAINFALL_HOURLY_WARNING_MM", default=30.0
        )
    )
    rainfall_hourly_critical_mm: float = field(
        default_factory=lambda: _float_from_env(
            "RAINFALL_HOURLY_CRITICAL_MM", default=60.0
        )
    )

    # Emergency Broadcast Phone Numbers
    emergency_broadcast_numbers: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        raw_numbers = os.getenv("EMERGENCY_BROADCAST_NUMBERS", "")
        if raw_numbers:
            self.emergency_broadcast_numbers = [
                n.strip() for n in raw_numbers.split(",") if n.strip()
            ]

    @property
    def has_valid_twilio_credentials(self) -> bool:
        """Verify whether Twilio credentials appear configured and not placeholders."""
        return bool(
            self.twilio_account_sid
            and not self.twilio_account_sid.startswith("ACxxxx")
            and self.twilio_auth_token
            and "your_" not in self.twilio_auth_token
            and self.twilio_phone_number
        )

    @property
    def has_valid_telegram_credentials(self) -> bool:
        """Verify whether Telegram credentials appear configured and not placeholders."""
        return bool(
            self.telegram_bot_token
            and "example" not in self.telegram_bot_token
            and self.telegram_chat_id
        )

    def __repr__(self) -> str:
        """Mask secrets in logging and repr outputs."""
        masked_twilio = (
            f"{self.twilio_account_sid[:6]}...***"
            if self.twilio_account_sid
            else "<unset>"
        )
        masked_telegram = (
            f"{self.telegram_bot_token[:6]}...***"
            if self.telegram_bot_token
            else "<unset>"
        )
        return (
            f"Settings(twilio_sid={masked_twilio}, "
            f"telegram_bot={masked_telegram}, "
            f"dry_run={self.alert_dry_run}, "
            f"db_path={self.database_path})"
        )


# Singleton instance ready for import across project
settings = Settings()
