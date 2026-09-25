"""Alert deduplication and cooldown manager for Chetna B2.

Prevents repeated identical alerts from being forwarded to external
providers (Telegram/Twilio) during a configurable cooldown window.

Escalations to a *higher* severity are always allowed through.

Usage:
    cooldown = AlertCooldown(cooldown_seconds=300)
    if cooldown.should_send(node_id="NODE_01", severity=AlertSeverity.WARNING):
        dispatcher.dispatch(...)
        cooldown.record(node_id="NODE_01", severity=AlertSeverity.WARNING)
    else:
        logger.info("Suppressed duplicate alert for NODE_01 WARNING")
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from alerts.dispatcher import AlertSeverity

logger = logging.getLogger(__name__)

# Numeric rank of each severity (higher = more severe)
_SEVERITY_RANK: Dict[AlertSeverity, int] = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
    AlertSeverity.EMERGENCY: 3,
}


@dataclass
class _CooldownEntry:
    severity: AlertSeverity
    sent_at: datetime.datetime


class AlertCooldown:
    """In-memory cooldown tracker keyed by (node_id, severity).

    Thread-safety note: This implementation is sufficient for a single-threaded
    alert evaluation loop. Extend with a threading.Lock if needed.

    Cooldown is configurable via ALERT_COOLDOWN_SECONDS in .env / settings.
    Escalation to a higher severity always bypasses cooldown.
    """

    def __init__(self, cooldown_seconds: int = 300) -> None:
        self.cooldown_seconds = cooldown_seconds
        # Maps (node_id) -> last sent CooldownEntry (tracks highest severity in window)
        self._state: Dict[str, _CooldownEntry] = {}

    def _key(self, node_id: str) -> str:
        return node_id

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def should_send(self, node_id: str, severity: AlertSeverity) -> bool:
        """Return True if this alert should be forwarded to external providers.

        Rules:
        - Always send if no prior entry for this node.
        - Always send if new severity is higher than the last sent severity.
        - Suppress if the same (or lower) severity was sent within cooldown_seconds.
        """
        key = self._key(node_id)
        entry = self._state.get(key)

        if entry is None:
            return True

        new_rank = _SEVERITY_RANK[severity]
        old_rank = _SEVERITY_RANK[entry.severity]

        # Escalation always sends
        if new_rank > old_rank:
            return True

        # Within cooldown window and same/lower severity -> suppress
        elapsed = (self._now() - entry.sent_at).total_seconds()
        if elapsed < self.cooldown_seconds:
            logger.info(
                "Suppressing %s alert for node %s (cooldown: %.0fs remaining)",
                severity.value,
                node_id,
                self.cooldown_seconds - elapsed,
            )
            return False

        return True

    def record(self, node_id: str, severity: AlertSeverity) -> None:
        """Record that an alert was sent for this node at this severity."""
        self._state[self._key(node_id)] = _CooldownEntry(
            severity=severity,
            sent_at=self._now(),
        )

    def reset(self, node_id: str) -> None:
        """Clear cooldown state for a node (e.g., after resolve)."""
        self._state.pop(self._key(node_id), None)

    def clear_all(self) -> None:
        """Reset all cooldown state."""
        self._state.clear()
