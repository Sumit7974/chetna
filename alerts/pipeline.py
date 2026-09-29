"""End-to-end alert pipeline for Chetna B2.

Implements the full pipeline:
    SensorReading
        -> AlertEvaluator  (decides severity)
        -> AlertCooldown   (deduplication / suppress repeated alerts)
        -> AlertDispatcher (routes to Telegram / Twilio)
        -> alert_logs      (database audit trail)

Also includes alert lifecycle management helpers:
    - generate_alert()    : create an alert record with 'generated' status
    - mark_dispatched()   : advance to 'dispatched'
    - acknowledge_alert() : advance to 'acknowledged'
    - resolve_alert()     : advance to 'resolved'

Usage:
    from alerts.pipeline import AlertPipeline
    pipeline = AlertPipeline()
    result = pipeline.process(reading, affected_area="Velachery")
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from alerts.cooldown import AlertCooldown
from alerts.dispatcher import AlertDispatcher, AlertSeverity
from database.db import DEFAULT_DB_PATH, get_db_connection, init_db
from simulators.sensor_db_bridge import persist_reading
from simulators.sensor_simulator import SensorReading
from src.alerts.evaluator import AlertEvaluator, EvaluationResult
from src.model.predictor import FloodRiskPredictor

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Outcome of processing one SensorReading through the full pipeline."""

    reading: SensorReading
    evaluation: EvaluationResult
    alert_id: Optional[str]   # None if suppressed by cooldown
    dispatched: bool
    suppressed: bool
    lifecycle_status: str     # 'generated', 'dispatched', 'suppressed'


class AlertPipeline:
    """Connects the full B2 alert pipeline end-to-end.

    Instantiate once per service loop; reuse across readings so the
    cooldown state is preserved between evaluations.
    """

    def __init__(
        self,
        dispatcher: Optional[AlertDispatcher] = None,
        evaluator: Optional[AlertEvaluator] = None,
        cooldown: Optional[AlertCooldown] = None,
        cooldown_seconds: int = 300,
        db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
        sms_recipients: Optional[List[str]] = None,
    ) -> None:
        self.dispatcher = dispatcher or AlertDispatcher(db_path=db_path)
        self.evaluator = evaluator or AlertEvaluator()
        self.cooldown = cooldown or AlertCooldown(cooldown_seconds=cooldown_seconds)
        self.db_path = db_path
        self.sms_recipients = sms_recipients or []
        self.predictor = FloodRiskPredictor(db_path=db_path)

        # Ensure schema is ready
        if not isinstance(db_path, sqlite3.Connection):
            init_db(db_path)

    def process(
        self,
        reading: SensorReading,
        affected_area: Optional[str] = None,
        persist: bool = True,
        sms_recipients: Optional[List[str]] = None,
    ) -> PipelineResult:
        """Process one SensorReading through the complete alert pipeline.

        Steps:
            1. (Optional) Persist reading to database.
            2. Evaluate severity.
            3. Write 'generated' lifecycle record.
            4. Check cooldown — suppress if duplicate within window.
            5. Dispatch to Telegram/Twilio based on severity.
            6. Update lifecycle status.

        Args:
            reading:        SensorReading from simulator or real sensor.
            affected_area:  Human-readable zone/area label (overrides evaluator default).
            persist:        If True, save the reading to sensor_readings table first.
            sms_recipients: Phone numbers for SMS/Voice; falls back to self.sms_recipients.
        """
        recipients = sms_recipients or self.sms_recipients

        # Step 0: Sensor Correction & Validation
        from src.sensors.correction import ValidatedReading, correct_and_validate_reading
        validated = (
            reading
            if isinstance(reading, ValidatedReading)
            else correct_and_validate_reading(reading)
        )

        # Step 1: persist validated reading with audit trail
        if persist and not isinstance(self.db_path, sqlite3.Connection):
            persist_reading(validated, db_path=self.db_path)

        if affected_area:
            self.evaluator.affected_area = affected_area

        # Step 2: Handle invalid sensor readings
        if getattr(validated, "validation_status", "VALID") == "INVALID":
            evaluation = self.evaluator.evaluate(validated)
            alert_id = f"ALT-{uuid.uuid4().hex[:8].upper()}"
            self._write_lifecycle(
                alert_id=alert_id,
                evaluation=evaluation,
                lifecycle_status="suppressed",
            )
            return PipelineResult(
                reading=validated,
                evaluation=evaluation,
                alert_id=alert_id,
                dispatched=False,
                suppressed=True,
                lifecycle_status="suppressed",
            )

        # Step 3: Evaluate (with risk prediction on validated/corrected telemetry)
        risk_level = None
        if validated.validation_status in ("VALID", "CORRECTED"):
            try:
                pred = self.predictor.predict(
                    water_level_cm=validated.water_level_cm,
                    rainfall_rate_mm_h=validated.rainfall_rate_mm_h,
                    cell_id=validated.node_id,
                    persist=persist,
                )
                risk_level = pred.level
            except Exception as exc:
                logger.warning("Predictor error in pipeline: %s", exc)

        evaluation = self.evaluator.evaluate(validated, risk_level=risk_level)

        # Step 4: Write lifecycle record
        alert_id = f"ALT-{uuid.uuid4().hex[:8].upper()}"
        self._write_lifecycle(
            alert_id=alert_id,
            evaluation=evaluation,
            lifecycle_status="generated",
        )

        # Step 5: Cooldown check
        if not self.cooldown.should_send(validated.node_id, evaluation.severity):
            self._update_lifecycle(alert_id, "suppressed")
            return PipelineResult(
                reading=validated,
                evaluation=evaluation,
                alert_id=alert_id,
                dispatched=False,
                suppressed=True,
                lifecycle_status="suppressed",
            )

        # Step 6: Dispatch
        try:
            if getattr(evaluation, "alert_type", "FLOOD_ALERT") == "SENSOR_QUALITY":
                # Diagnostic dispatch to Telegram/logs only; suppress citizen evacuation calls
                formatted_diag = (
                    f"🔧 *[CHETNA SENSOR QUALITY ALERT]*\n"
                    f"*Node:* {validated.node_id}\n"
                    f"*Area:* {evaluation.affected_area}\n"
                    f"{evaluation.reason}\n\n"
                    f"⚠️ _Sensor maintenance flagged. Physical flood alert withheld._"
                )
                self.dispatcher.telegram.send_message(text=formatted_diag)
            else:
                self.dispatcher.dispatch(
                    severity=evaluation.severity,
                    title=evaluation.title,
                    message=evaluation.reason,
                    affected_area=evaluation.affected_area,
                    sms_recipients=recipients if recipients else None,
                )
            self.cooldown.record(validated.node_id, evaluation.severity)
            self._update_lifecycle(alert_id, "dispatched")
            lifecycle_status = "dispatched"
            dispatched = True
        except Exception as exc:
            logger.error("Dispatch failed for alert %s: %s", alert_id, exc)
            self._update_lifecycle(alert_id, "generated")
            lifecycle_status = "generated"
            dispatched = False

        return PipelineResult(
            reading=reading,
            evaluation=evaluation,
            alert_id=alert_id,
            dispatched=dispatched,
            suppressed=False,
            lifecycle_status=lifecycle_status,
        )

    # ------------------------------------------------------------------
    # Alert lifecycle persistence helpers
    # ------------------------------------------------------------------

    def _write_lifecycle(
        self,
        alert_id: str,
        evaluation: EvaluationResult,
        lifecycle_status: str,
    ) -> None:
        """Insert an alert record into the 'alerts' lifecycle table."""
        sql = """
        INSERT OR IGNORE INTO alerts (
            alert_id, node_id, severity, lifecycle_status,
            title, message, affected_area, reason, suppressed, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        suppressed = 1 if lifecycle_status == "suppressed" else 0
        try:
            with get_db_connection(self.db_path) as conn:
                conn.execute(sql, (
                    alert_id,
                    evaluation.node_id,
                    evaluation.severity.value,
                    lifecycle_status,
                    evaluation.title,
                    evaluation.reason,
                    evaluation.affected_area,
                    evaluation.reason,
                    suppressed,
                    now,
                    now,
                ))
        except Exception as exc:
            logger.warning("Could not write lifecycle record for %s: %s", alert_id, exc)

    def _update_lifecycle(self, alert_id: str, lifecycle_status: str) -> None:
        """Update the lifecycle_status of an existing alert record."""
        sql = """
        UPDATE alerts SET lifecycle_status=?, suppressed=?, updated_at=?
        WHERE alert_id=?;
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        suppressed = 1 if lifecycle_status == "suppressed" else 0
        try:
            with get_db_connection(self.db_path) as conn:
                conn.execute(sql, (lifecycle_status, suppressed, now, alert_id))
        except Exception as exc:
            logger.warning("Could not update lifecycle for %s: %s", alert_id, exc)


# ------------------------------------------------------------------
# Standalone lifecycle management functions
# ------------------------------------------------------------------

def acknowledge_alert(
    alert_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Advance an alert to 'acknowledged' lifecycle state."""
    _set_lifecycle(alert_id, "acknowledged", db_path)


def resolve_alert(
    alert_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Advance an alert to 'resolved' lifecycle state."""
    _set_lifecycle(alert_id, "resolved", db_path)


def dismiss_alert(
    alert_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Dismiss an alert, transitioning it to 'dismissed' and marking it suppressed."""
    _set_lifecycle(alert_id, "dismissed", db_path)


def _set_lifecycle(
    alert_id: str,
    status: str,
    db_path: Union[str, Path, sqlite3.Connection],
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    suppressed = 1 if status in ("suppressed", "dismissed") else 0
    with get_db_connection(db_path) as conn:
        conn.execute(
            "UPDATE alerts SET lifecycle_status=?, suppressed=?, updated_at=? WHERE alert_id=?;",
            (status, suppressed, now, alert_id),
        )
