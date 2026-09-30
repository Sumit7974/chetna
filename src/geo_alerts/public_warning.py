"""Automatic Geo-Targeted Public Warning Engine for Chetna.

Orchestrates:
Risk Detection
    ↓
Affected Zone Identification (GeoTargetingService)
    ↓
Automatic Threshold Evaluation (PublicWarningPolicy)
    ↓
Duplicate Protection & Cooldown
    ↓
Bilingual Geo-Targeted Warning Generation (MessageBuilder)
    ↓
Simulated Public Broadcast (SimulatedCellBroadcastAdapter)
    ↓
Database Audit Logging (alert_logs & public_warnings)
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from database.db import DEFAULT_DB_PATH, get_db_connection
from src.geo_alerts.broadcast_adapter import PublicBroadcastAdapter, SimulatedCellBroadcastAdapter
from src.geo_alerts.message_builder import (
    BilingualWarningMessage,
    PublicWarningMessageBuilder,
    build_bilingual_warning,
)
from src.geo_alerts.policy import PublicWarningAction, PublicWarningPolicy
from src.geo_alerts.zone_targeting import GeoTargetingService, GeoZoneTarget

logger = logging.getLogger(__name__)

# Severity hierarchy for escalation detection
SEVERITY_RANKS: Dict[str, int] = {
    "INFO": 0,
    "LOW": 0,
    "MEDIUM": 1,
    "WARNING": 1,
    "HIGH": 2,
    "CRITICAL": 3,
    "SEVERE": 3,
    "EMERGENCY": 4,
}


@dataclass
class _ZoneCooldownEntry:
    severity: str
    sent_at: datetime.datetime
    warning_type: str


@dataclass
class PublicWarningResult:
    """Structured result of evaluating and optionally dispatching a public warning."""

    triggered: bool
    action: PublicWarningAction
    target_zone: GeoZoneTarget
    warning_message: Optional[BilingualWarningMessage] = None
    delivery_result: Optional[Dict[str, Any]] = None
    suppressed: bool = False
    suppression_reason: Optional[str] = None
    is_prototype: bool = True
    audit_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "triggered": self.triggered,
            "action": self.action.value,
            "target_zone": self.target_zone.to_dict(),
            "warning_message": self.warning_message.to_dict() if self.warning_message else None,
            "delivery_result": self.delivery_result,
            "suppressed": self.suppressed,
            "suppression_reason": self.suppression_reason,
            "is_prototype": self.is_prototype,
            "audit_id": self.audit_id,
        }


class PublicWarningEngine:
    """Engine executing automated geo-targeted public warnings for Chetna."""

    def __init__(
        self,
        geo_service: Optional[GeoTargetingService] = None,
        policy: Optional[PublicWarningPolicy] = None,
        message_builder: Optional[PublicWarningMessageBuilder] = None,
        adapter: Optional[PublicBroadcastAdapter] = None,
        cooldown_seconds: int = 300,
        db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    ) -> None:
        self.geo_service = geo_service or GeoTargetingService()
        self.policy = policy or PublicWarningPolicy()
        self.message_builder = message_builder or PublicWarningMessageBuilder()
        self.adapter = adapter or SimulatedCellBroadcastAdapter()
        self.cooldown_seconds = cooldown_seconds
        self.db_path = db_path
        self._zone_cooldown: Dict[str, _ZoneCooldownEntry] = {}
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure the public_warnings audit table exists in the target database."""
        ddl = """
        CREATE TABLE IF NOT EXISTS public_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            warning_id TEXT UNIQUE NOT NULL,
            zone_id TEXT NOT NULL,
            zone_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            warning_type TEXT NOT NULL,
            headline_en TEXT NOT NULL,
            headline_hi TEXT NOT NULL,
            message_en TEXT NOT NULL,
            message_hi TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT 'GEO_ZONE',
            channel TEXT NOT NULL DEFAULT 'CELL_BROADCAST_SIMULATION',
            status TEXT NOT NULL DEFAULT 'SIMULATED_DELIVERED',
            is_prototype BOOLEAN NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'chetna',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_pub_warnings_zone ON public_warnings (zone_id);
        CREATE INDEX IF NOT EXISTS idx_pub_warnings_created ON public_warnings (created_at);
        """
        try:
            with get_db_connection(self.db_path) as conn:
                conn.executescript(ddl)
        except Exception as exc:
            logger.debug("Public warning table initialization notice: %s", exc)

    def reset_cooldown(self) -> None:
        """Reset all active zone cooldowns."""
        self._zone_cooldown.clear()

    def _should_suppress_duplicate(self, zone_id: str, severity: str) -> Tuple[bool, Optional[str]]:
        """Determine whether to suppress warning due to cooldown or duplicate state."""
        entry = self._zone_cooldown.get(zone_id)
        if not entry:
            return False, None

        now = datetime.datetime.now(datetime.timezone.utc)
        elapsed = (now - entry.sent_at).total_seconds()

        current_rank = SEVERITY_RANKS.get(severity.upper(), 0)
        previous_rank = SEVERITY_RANKS.get(entry.severity.upper(), 0)

        # Escalation to higher severity bypasses cooldown
        if current_rank > previous_rank:
            return False, None

        # Within cooldown window and same or lower severity -> suppress
        if elapsed < self.cooldown_seconds:
            remaining = self.cooldown_seconds - elapsed
            return True, f"Duplicate warning suppressed within cooldown window ({remaining:.0f}s remaining for {zone_id})"

        return False, None

    def evaluate_and_broadcast(
        self,
        risk_source: Any = None,
        cell_id: Optional[str] = None,
        node_id: Optional[str] = None,
        location_name: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        risk_level: Optional[str] = None,
        risk_score: Optional[float] = None,
        water_level_cm: Optional[float] = None,
        rainfall_rate_mm_h: Optional[float] = None,
        force: bool = False,
    ) -> PublicWarningResult:
        """Evaluate incoming risk and automatically trigger geo-targeted warning if warranted.

        Workflow:
            1. Resolve affected geographic zone
            2. Evaluate policy threshold (EMERGENCY_BROADCAST vs PUBLIC_ADVISORY vs NONE)
            3. Apply deterministic duplicate protection (cooldown & escalation check)
            4. Generate bilingual warning (English and Hindi)
            5. Broadcast via simulated Cell Broadcast adapter
            6. Record in audit trail (alert_logs and public_warnings)
        """
        # 1. Resolve Affected Zone
        target = self.geo_service.resolve_zone(
            risk_source=risk_source,
            cell_id=cell_id,
            node_id=node_id,
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            risk_level=risk_level,
            risk_score=risk_score,
        )

        effective_level = target.risk_level.upper()
        effective_score = target.risk_score

        # 2. Evaluate Policy Threshold
        action = self.policy.evaluate(effective_level, effective_score)

        if action == PublicWarningAction.NONE:
            return PublicWarningResult(
                triggered=False,
                action=action,
                target_zone=target,
                suppressed=False,
                suppression_reason=f"Risk level {effective_level} is below public warning threshold",
            )

        # Ensure that qualifying emergency broadcast severity is at least CRITICAL
        if action == PublicWarningAction.EMERGENCY_BROADCAST and effective_level not in self.policy.emergency_severities:
            effective_level = "CRITICAL"
            target.risk_level = "CRITICAL"
        elif action == PublicWarningAction.PUBLIC_ADVISORY and effective_level not in self.policy.advisory_severities:
            effective_level = "HIGH"
            target.risk_level = "HIGH"

        # 3. Duplicate Protection
        if not force:
            suppress, reason = self._should_suppress_duplicate(target.zone_id, effective_level)
            if suppress:
                logger.info("Public warning suppressed: %s", reason)
                return PublicWarningResult(
                    triggered=False,
                    action=action,
                    target_zone=target,
                    suppressed=True,
                    suppression_reason=reason,
                )

        # 4. Generate Bilingual Message
        msg = self.message_builder.build_warning(
            target=target,
            action=action,
            water_level_cm=water_level_cm,
            rainfall_rate_mm_h=rainfall_rate_mm_h,
        )

        # 5. Broadcast via Adapter (Simulated Cell Broadcast) with Fail-Safe Handling
        try:
            delivery = self.adapter.broadcast(
                target_zone=target,
                severity=effective_level,
                message=msg.full_text_en,
                language="en/hi",
                source="chetna",
                metadata={
                    "warning_type": msg.warning_type,
                    "message_hi": msg.full_text_hi,
                    "action": action.value,
                },
            )
            is_success = delivery.get("status") == "SIMULATED_DELIVERED"
        except Exception as exc:
            logger.error("Broadcast adapter failure: %s", exc)
            delivery = {
                "status": "FAILED",
                "reason": str(exc),
                "channel": getattr(self.adapter, "CHANNEL_NAME", "CELL_BROADCAST_SIMULATION"),
                "target_type": "GEO_ZONE",
                "target_zone": target.zone_id,
                "zone_name": target.zone_name,
                "message_id": f"PUB-WARN-FAIL-{target.zone_id}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "severity": effective_level,
                "language": "en/hi",
                "message": msg.full_text_en,
                "prototype": True,
                "source": "chetna",
                "gateway": getattr(self.adapter, "GATEWAY_NAME", "PROTOTYPE_CELL_BROADCAST_SIMULATION_GATEWAY"),
                "metadata": {"error": str(exc)},
            }
            is_success = False

        if is_success:
            # Record Cooldown only when broadcast succeeded
            self._zone_cooldown[target.zone_id] = _ZoneCooldownEntry(
                severity=effective_level,
                sent_at=datetime.datetime.now(datetime.timezone.utc),
                warning_type=msg.warning_type,
            )

        # 6. Record in Database / Audit
        audit_id = delivery.get("message_id")
        self._record_audit(target, action, msg, delivery)

        return PublicWarningResult(
            triggered=is_success,
            action=action,
            target_zone=target,
            warning_message=msg,
            delivery_result=delivery,
            suppressed=False,
            is_prototype=True,
            audit_id=audit_id,
        )

    def _record_audit(
        self,
        target: GeoZoneTarget,
        action: PublicWarningAction,
        msg: BilingualWarningMessage,
        delivery: Dict[str, Any],
    ) -> None:
        """Persist warning to both alert_logs and public_warnings tables."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        warning_id = delivery.get("message_id", f"PUB-WARN-{target.zone_id}")

        # Insert into public_warnings
        sql_pw = """
        INSERT OR IGNORE INTO public_warnings (
            warning_id, zone_id, zone_name, severity, warning_type,
            headline_en, headline_hi, message_en, message_hi,
            target_type, channel, status, is_prototype, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        # Insert into alert_logs
        sql_logs = """
        INSERT INTO alert_logs (
            alert_id, zone_id, severity, channel, provider,
            recipient, message, status, response_payload, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        payload = json.dumps({
            "target_type": "GEO_ZONE",
            "zone_id": target.zone_id,
            "zone_name": target.zone_name,
            "action": action.value,
            "headline_en": msg.headline_en,
            "headline_hi": msg.headline_hi,
            "message_hi": msg.full_text_hi,
            "is_prototype": True,
            "simulated": True,
        })

        try:
            with get_db_connection(self.db_path) as conn:
                conn.execute(sql_pw, (
                    warning_id,
                    target.zone_id,
                    target.zone_name,
                    target.risk_level,
                    msg.warning_type,
                    msg.headline_en,
                    msg.headline_hi,
                    msg.full_text_en,
                    msg.full_text_hi,
                    "GEO_ZONE",
                    delivery.get("channel", "CELL_BROADCAST_SIMULATION"),
                    delivery.get("status", "SIMULATED_DELIVERED"),
                    1,
                    "chetna",
                    now,
                ))
                conn.execute(sql_logs, (
                    warning_id,
                    target.zone_id,
                    target.risk_level,
                    delivery.get("channel", "CELL_BROADCAST_SIMULATION"),
                    delivery.get("gateway", "PROTOTYPE_CELL_BROADCAST_GATEWAY"),
                    f"GEO_ZONE:{target.zone_name}",
                    msg.full_text_en,
                    delivery.get("status", "SIMULATED_DELIVERED"),
                    payload,
                    now,
                ))
        except Exception as exc:
            logger.warning("Could not persist public warning audit: %s", exc)

    def get_recent_warnings(
        self,
        limit: int = 10,
        db_path: Optional[Union[str, Path, sqlite3.Connection]] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent public warnings for UI dashboard and audit review."""
        target_db = db_path if db_path is not None else self.db_path
        sql = """
        SELECT warning_id, zone_id, zone_name, severity, warning_type,
               headline_en, headline_hi, message_en, message_hi,
               target_type, channel, status, is_prototype, source, created_at
        FROM public_warnings
        ORDER BY id DESC
        LIMIT ?;
        """
        try:
            with get_db_connection(target_db) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (limit,))
                return [dict(r) for r in cursor.fetchall()]
        except Exception as exc:
            logger.debug("Could not query public_warnings table: %s", exc)
            return []

    def get_latest_warning_for_zone(
        self,
        zone_id: Optional[str] = None,
        db_path: Optional[Union[str, Path, sqlite3.Connection]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent public warning for a zone (or overall if zone_id is None)."""
        target_db = db_path if db_path is not None else self.db_path
        if zone_id:
            sql = """
            SELECT warning_id, zone_id, zone_name, severity, warning_type,
                   headline_en, headline_hi, message_en, message_hi,
                   target_type, channel, status, is_prototype, source, created_at
            FROM public_warnings
            WHERE zone_id = ? OR zone_name LIKE ?
            ORDER BY id DESC
            LIMIT 1;
            """
            params = (zone_id, f"%{zone_id}%")
        else:
            sql = """
            SELECT warning_id, zone_id, zone_name, severity, warning_type,
                   headline_en, headline_hi, message_en, message_hi,
                   target_type, channel, status, is_prototype, source, created_at
            FROM public_warnings
            ORDER BY id DESC
            LIMIT 1;
            """
            params = ()

        try:
            with get_db_connection(target_db) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.debug("Could not query latest public warning: %s", exc)
            return None


# Global singleton instance
_default_engine = PublicWarningEngine()


def get_public_warning_engine(db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH) -> PublicWarningEngine:
    """Retrieve or instantiate a PublicWarningEngine."""
    if db_path != DEFAULT_DB_PATH:
        return PublicWarningEngine(db_path=db_path)
    return _default_engine


def evaluate_and_broadcast_public_warning(
    risk_source: Any = None,
    cell_id: Optional[str] = None,
    node_id: Optional[str] = None,
    location_name: Optional[str] = None,
    risk_level: Optional[str] = None,
    risk_score: Optional[float] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> PublicWarningResult:
    """Convenience helper to evaluate and automatically broadcast a public warning."""
    engine = get_public_warning_engine(db_path=db_path)
    return engine.evaluate_and_broadcast(
        risk_source=risk_source,
        cell_id=cell_id,
        node_id=node_id,
        location_name=location_name,
        risk_level=risk_level,
        risk_score=risk_score,
    )
