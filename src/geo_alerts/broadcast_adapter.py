"""Simulated public broadcast adapter for Chetna.

Provides an architectural integration adapter representing an authorized
public warning / Cell Broadcast gateway.

IMPORTANT REAL-WORLD BOUNDARY:
Chetna is an AI flood early-warning research and decision-support prototype.
It does not connect to live telecom switching centers (CBCs), telecom operators,
or government emergency broadcast facilities. All broadcasts produced by this
adapter are strictly simulated in-memory and logged for prototype validation.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union

from src.geo_alerts.zone_targeting import GeoZoneTarget

logger = logging.getLogger(__name__)


class PublicBroadcastAdapter(ABC):
    """Abstract interface representing a public emergency warning broadcast gateway."""

    @abstractmethod
    def broadcast(
        self,
        target_zone: GeoZoneTarget,
        severity: str,
        message: str,
        language: str = "en",
        timestamp: Optional[str] = None,
        source: str = "chetna",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Broadcast a public emergency warning to an entire geographic zone."""
        pass


class SimulatedCellBroadcastAdapter(PublicBroadcastAdapter):
    """Prototype adapter simulating geo-targeted Cell Broadcast delivery to a geographic zone.

    Guarantees:
    - Never requires or stores citizen telephone numbers
    - Never uses external SMS APIs or sends real messages
    - Explicitly marks all delivery confirmations as SIMULATED / PROTOTYPE ONLY
    """

    GATEWAY_NAME = "PROTOTYPE_CELL_BROADCAST_SIMULATION_GATEWAY"
    CHANNEL_NAME = "CELL_BROADCAST_SIMULATION"

    def __init__(self, simulate_network_delay: bool = False) -> None:
        self.simulate_network_delay = simulate_network_delay

    def broadcast(
        self,
        target_zone: GeoZoneTarget,
        severity: str,
        message: str,
        language: str = "en",
        timestamp: Optional[str] = None,
        source: str = "chetna",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Simulate geo-targeted delivery to all mobile devices within the target zone polygon."""
        now_ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        message_id = f"PUB-WARN-{uuid.uuid4().hex[:8].upper()}"

        meta = dict(metadata or {})
        meta["gateway_notice"] = "Simulated delivery for prototype evaluation. No telecom transmission."

        delivery_result = {
            "status": "SIMULATED_DELIVERED",
            "channel": self.CHANNEL_NAME,
            "target_type": "GEO_ZONE",
            "target_zone": target_zone.zone_id,
            "zone_name": target_zone.zone_name,
            "message_id": message_id,
            "timestamp": now_ts,
            "severity": str(severity).upper(),
            "language": language,
            "message": message,
            "prototype": True,
            "source": source,
            "gateway": self.GATEWAY_NAME,
            "metadata": meta,
        }

        logger.info(
            "Simulated Cell Broadcast dispatched [ID: %s] | Zone: %s (%s) | Severity: %s | Lang: %s",
            message_id,
            target_zone.zone_name,
            target_zone.zone_id,
            severity,
            language,
        )

        return delivery_result
