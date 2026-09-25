"""Telegram Bot notification handler for flood alerts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)


@dataclass
class TelegramDispatchResult:
    """Outcome of a Telegram delivery attempt."""

    success: bool
    chat_id: str
    message_id: Optional[int] = None
    status: str = "PENDING"
    error: Optional[str] = None


class TelegramAlertHandler:
    """Delivers rich markdown flood alerts to Telegram channels and individuals."""

    TELEGRAM_API_BASE = "https://api.telegram.org/bot"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        default_chat_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.dry_run = dry_run

    @property
    def is_configured(self) -> bool:
        """Check if real bot token is provided."""
        return bool(
            self.bot_token
            and "example" not in self.bot_token
            and not self.bot_token.startswith("123456789:ABC")
        )

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> TelegramDispatchResult:
        """Send formatted text alert to Telegram."""
        target_chat = chat_id or self.default_chat_id
        if not target_chat:
            return TelegramDispatchResult(
                success=False,
                chat_id="",
                status="FAILED",
                error="No target chat_id provided",
            )

        if self.dry_run or not self.is_configured:
            logger.info(
                "[DRY_RUN Telegram] Broadcast to %s: %s",
                target_chat,
                text,
            )
            return TelegramDispatchResult(
                success=True,
                chat_id=target_chat,
                message_id=999999,
                status="DRY_RUN",
            )

        url = f"{self.TELEGRAM_API_BASE}{self.bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                msg_id = data.get("result", {}).get("message_id")
                logger.info("Sent Telegram message to %s (ID: %s)", target_chat, msg_id)
                return TelegramDispatchResult(
                    success=True,
                    chat_id=target_chat,
                    message_id=msg_id,
                    status="SENT",
                )
            else:
                err_desc = data.get("description", f"HTTP {resp.status_code}")
                logger.error("Telegram API error for chat %s: %s", target_chat, err_desc)
                return TelegramDispatchResult(
                    success=False,
                    chat_id=target_chat,
                    status="FAILED",
                    error=err_desc,
                )
        except Exception as ex:
            logger.error("Network error delivering Telegram alert: %s", ex)
            return TelegramDispatchResult(
                success=False,
                chat_id=target_chat,
                status="FAILED",
                error=str(ex),
            )
