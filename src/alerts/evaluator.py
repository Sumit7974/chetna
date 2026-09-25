"""Alert evaluation engine for Chetna B2 flood early-warning system.

Evaluates SensorReading objects against configurable thresholds from
config/settings.py and returns structured EvaluationResult objects.

This module intentionally does NOT send notifications.
Notification routing is handled by alerts.dispatcher.AlertDispatcher.

Severity levels:
    INFO      - Conditions normal; informational only
    WARNING   - Water level or rainfall approaching thresholds
    CRITICAL  - Threshold crossed; action required
    EMERGENCY - Severe threshold crossed OR sensor anomaly detected
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional

from alerts.dispatcher import AlertSeverity
from config.settings import settings
from simulators.sensor_simulator import SensorReading


@dataclass
class EvaluationResult:
    """Structured output of the alert evaluator for a single sensor reading."""

    severity: AlertSeverity
    reason: str
    node_id: str
    timestamp: str
    affected_area: str
    water_level_cm: Optional[float] = None
    rainfall_rate_mm_h: Optional[float] = None
    is_anomaly: bool = False
    evaluated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    @property
    def title(self) -> str:
        """Short human-readable title for use in alert message formatting."""
        titles = {
            AlertSeverity.INFO: "Conditions Normal",
            AlertSeverity.WARNING: "Flood Warning Issued",
            AlertSeverity.CRITICAL: "Critical Flood Level Reached",
            AlertSeverity.EMERGENCY: "Emergency Flood Evacuation",
        }
        return titles.get(self.severity, "Flood Alert")

    def to_dict(self) -> dict:
        """Serialise result for logging or API output."""
        return {
            "severity": self.severity.value,
            "reason": self.reason,
            "node_id": self.node_id,
            "timestamp": self.timestamp,
            "affected_area": self.affected_area,
            "water_level_cm": self.water_level_cm,
            "rainfall_rate_mm_h": self.rainfall_rate_mm_h,
            "is_anomaly": self.is_anomaly,
            "title": self.title,
            "evaluated_at": self.evaluated_at,
        }


class AlertEvaluator:
    """Evaluates SensorReadings against configured thresholds.

    Threshold precedence (highest wins):
        1. Sensor anomaly flag                 -> EMERGENCY
        2. water_level >= critical_threshold   -> EMERGENCY  (if rainfall also critical)
           water_level >= critical_threshold   -> CRITICAL
        3. rainfall_rate >= critical_mm        -> CRITICAL
        4. water_level >= warning_threshold    -> WARNING
        5. rainfall_rate >= warning_mm         -> WARNING
        6. Otherwise                           -> INFO
    """

    def __init__(
        self,
        affected_area: str = "Chennai",
        warning_water_cm: Optional[float] = None,
        critical_water_cm: Optional[float] = None,
        warning_rain_mm: Optional[float] = None,
        critical_rain_mm: Optional[float] = None,
    ) -> None:
        self.affected_area = affected_area
        # Allow caller to override; otherwise use global settings
        self.warning_water_cm = warning_water_cm or settings.water_level_warning_threshold_cm
        self.critical_water_cm = critical_water_cm or settings.water_level_critical_threshold_cm
        self.warning_rain_mm = warning_rain_mm or settings.rainfall_hourly_warning_mm
        self.critical_rain_mm = critical_rain_mm or settings.rainfall_hourly_critical_mm

    def evaluate(self, reading: SensorReading) -> EvaluationResult:
        """Evaluate a single sensor reading and return a structured result."""
        wl = reading.water_level_cm
        rr = reading.rainfall_rate_mm_h
        anomaly = reading.is_anomaly

        # --- EMERGENCY: sensor malfunction or combined extreme conditions ---
        if anomaly:
            return EvaluationResult(
                severity=AlertSeverity.EMERGENCY,
                reason=(
                    f"Sensor anomaly detected on node {reading.node_id}. "
                    "Readings are unreliable; possible sensor failure or extreme event."
                ),
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                affected_area=self.affected_area,
                water_level_cm=wl,
                rainfall_rate_mm_h=rr,
                is_anomaly=True,
            )

        water_critical = wl is not None and wl >= self.critical_water_cm
        rain_critical = rr is not None and rr >= self.critical_rain_mm
        water_warning = wl is not None and wl >= self.warning_water_cm
        rain_warning = rr is not None and rr >= self.warning_rain_mm

        # EMERGENCY: both water level and rainfall in critical zone simultaneously
        if water_critical and rain_critical:
            return EvaluationResult(
                severity=AlertSeverity.EMERGENCY,
                reason=(
                    f"Simultaneous critical water level ({wl:.1f} cm >= {self.critical_water_cm} cm) "
                    f"and critical rainfall ({rr:.1f} mm/h >= {self.critical_rain_mm} mm/h). "
                    "Imminent flash flood risk."
                ),
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                affected_area=self.affected_area,
                water_level_cm=wl,
                rainfall_rate_mm_h=rr,
            )

        # CRITICAL: water level alone past critical threshold
        if water_critical:
            return EvaluationResult(
                severity=AlertSeverity.CRITICAL,
                reason=(
                    f"Water level critical: {wl:.1f} cm >= {self.critical_water_cm} cm threshold "
                    f"on node {reading.node_id}."
                ),
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                affected_area=self.affected_area,
                water_level_cm=wl,
                rainfall_rate_mm_h=rr,
            )

        # CRITICAL: rainfall alone past critical threshold
        if rain_critical:
            return EvaluationResult(
                severity=AlertSeverity.CRITICAL,
                reason=(
                    f"Rainfall rate critical: {rr:.1f} mm/h >= {self.critical_rain_mm} mm/h "
                    f"on node {reading.node_id}."
                ),
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                affected_area=self.affected_area,
                water_level_cm=wl,
                rainfall_rate_mm_h=rr,
            )

        # WARNING: water level in warning zone
        if water_warning:
            return EvaluationResult(
                severity=AlertSeverity.WARNING,
                reason=(
                    f"Water level elevated: {wl:.1f} cm >= {self.warning_water_cm} cm "
                    f"on node {reading.node_id}. Monitor closely."
                ),
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                affected_area=self.affected_area,
                water_level_cm=wl,
                rainfall_rate_mm_h=rr,
            )

        # WARNING: rainfall in warning zone
        if rain_warning:
            return EvaluationResult(
                severity=AlertSeverity.WARNING,
                reason=(
                    f"Rainfall rate elevated: {rr:.1f} mm/h >= {self.warning_rain_mm} mm/h "
                    f"on node {reading.node_id}."
                ),
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                affected_area=self.affected_area,
                water_level_cm=wl,
                rainfall_rate_mm_h=rr,
            )

        # INFO: all within normal bounds
        return EvaluationResult(
            severity=AlertSeverity.INFO,
            reason=(
                f"Node {reading.node_id}: water level {wl:.1f} cm, "
                f"rainfall {rr:.1f} mm/h — within normal operating bounds."
            ),
            node_id=reading.node_id,
            timestamp=reading.timestamp,
            affected_area=self.affected_area,
            water_level_cm=wl,
            rainfall_rate_mm_h=rr,
        )
