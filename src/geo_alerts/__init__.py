"""Chetna Geo-Alerts Package.

Provides automated geo-targeted public flood warnings and simulated Cell Broadcasts
without requiring citizen phone numbers or contact databases.
"""

from src.geo_alerts.broadcast_adapter import (
    PublicBroadcastAdapter,
    SimulatedCellBroadcastAdapter,
)
from src.geo_alerts.message_builder import (
    BilingualWarningMessage,
    PublicWarningMessageBuilder,
    build_bilingual_warning,
)
from src.geo_alerts.policy import (
    PublicWarningAction,
    PublicWarningPolicy,
    evaluate_public_warning_policy,
)
from src.geo_alerts.public_warning import (
    PublicWarningEngine,
    PublicWarningResult,
    evaluate_and_broadcast_public_warning,
    get_public_warning_engine,
)
from src.geo_alerts.zone_targeting import (
    GeoTargetingService,
    GeoZoneTarget,
    resolve_geo_zone,
)

__all__ = [
    "GeoZoneTarget",
    "GeoTargetingService",
    "resolve_geo_zone",
    "PublicWarningAction",
    "PublicWarningPolicy",
    "evaluate_public_warning_policy",
    "BilingualWarningMessage",
    "PublicWarningMessageBuilder",
    "build_bilingual_warning",
    "PublicBroadcastAdapter",
    "SimulatedCellBroadcastAdapter",
    "PublicWarningEngine",
    "PublicWarningResult",
    "get_public_warning_engine",
    "evaluate_and_broadcast_public_warning",
]
