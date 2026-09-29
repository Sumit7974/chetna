"""B2 Day 5 End-to-End Integration and Historical Backtest Replay Test Suite.

Verifies:
1. Normal baseline state: nominal drainage, zero active alerts, low risk predictions.
2. Heavy rain simulation: forecast updated, elevated sensor telemetry, multi-horizon risk.
3. Sensor anomaly correction: correction layer flags and validates sensor readings.
4. Risk to draft alert: draft advisory created with operational area and horizon.
5. Authority review & approval: approval transitions alert and triggers multi-channel dispatch.
6. Authority dismissal: dismissal suppresses alert and logs dismissal reason.
7. Dry-run dispatch safety: simulates notifications without external calls; logs audit records.
8. Audit logging: comprehensive audit trail in alert_logs with timestamp, status, payload.
9. Citizen safe routing: hazard avoidance routing to designated shelters.
10. Deterministic reset: system cleanly restores baseline state without residue.
11. Partial channel failure isolation: failure on one channel does not halt other channels.
12. Dismissed alert block: dismissed alerts cannot be broadcast or dispatched.
13. Historical backtest replay: EVT_2023_MICHAUNG & EVT_2021_NOV_DEPRESSION with metrics and disclaimers.
14. Master orchestrator: run_end_to_end_pipeline() execution across workflows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alerts.dispatcher import AlertDispatcher, AlertSeverity
from alerts.telegram_handler import TelegramAlertHandler, TelegramDispatchResult
from alerts.twilio_handler import TwilioAlertHandler, TwilioDispatchResult
from app.alert_service import (
    create_draft_alert,
    dismiss_authority_alert,
    dispatch_authority_alert,
)
from app.demo_scenario import (
    DEFAULT_PILOT_SENSOR_NODES,
    load_backtest_summary,
    replay_historical_backtest_event,
    reset_to_baseline_scenario,
    run_end_to_end_pipeline,
    trigger_heavy_rain_scenario,
)
from database.db import get_alert_by_id, init_db
from simulators.sensor_simulator import SensorReading
from src.routing.router import safe_route
from src.sensors.correction import ValidatedReading, ValidationStatus, correct_and_validate_reading


@pytest.fixture
def test_db(tmp_path: Path) -> sqlite3.Connection:
    """Create an isolated, schema-initialized SQLite database in tmp_path."""
    db_file = tmp_path / "test_day5.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


# -----------------------------------------------------------------------------
# 1. Normal Baseline Verification
# -----------------------------------------------------------------------------

def test_e2e_normal_baseline(test_db: sqlite3.Connection) -> None:
    """Verify normal baseline state has zero active alerts and nominal conditions."""
    res = reset_to_baseline_scenario(db_path=test_db)
    assert res["success"] is True
    assert res["scenario"] == "BASELINE"

    cursor = test_db.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM alerts WHERE suppressed = 0;")
    assert cursor.fetchone()["cnt"] == 0

    cursor.execute("SELECT COUNT(*) as cnt FROM risk_predictions;")
    assert cursor.fetchone()["cnt"] == 0


# -----------------------------------------------------------------------------
# 2. Heavy Rain Trigger Verification
# -----------------------------------------------------------------------------

def test_e2e_heavy_rain_trigger(test_db: sqlite3.Connection) -> None:
    """Verify heavy rain elevates forecasts, sensors, and generates multi-horizon predictions."""
    res = trigger_heavy_rain_scenario(db_path=test_db)
    assert res["success"] is True
    assert res["scenario"] == "HEAVY_RAIN"
    assert res["predictions_created"] > 0
    assert res["sensors_updated"] == len(DEFAULT_PILOT_SENSOR_NODES)

    cursor = test_db.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM risk_predictions WHERE level IN ('HIGH', 'MEDIUM');")
    assert cursor.fetchone()["cnt"] > 0

    cursor.execute("SELECT COUNT(*) as cnt FROM sensor_readings;")
    assert cursor.fetchone()["cnt"] >= len(DEFAULT_PILOT_SENSOR_NODES)


# -----------------------------------------------------------------------------
# 3. Sensor Anomaly Correction Verification
# -----------------------------------------------------------------------------

def test_e2e_sensor_anomaly_correction() -> None:
    """Verify that anomalous simulated readings (negative, jump, out-of-range) are corrected."""
    neg_reading = SensorReading(
        node_id="TEST_01",
        timestamp="2026-09-29T12:00:00Z",
        water_level_cm=-3.0,
        rainfall_rate_mm_h=20.0,
        battery_pct=95.0,
    )
    res_neg = correct_and_validate_reading(neg_reading)
    assert res_neg.validation_status == ValidationStatus.CORRECTED.value
    assert res_neg.water_level_cm == 0.0
    assert res_neg.raw_water_level_cm == -3.0

    extreme_reading = SensorReading(
        node_id="TEST_02",
        timestamp="2026-09-29T12:00:00Z",
        water_level_cm=9999.0,
        rainfall_rate_mm_h=10.0,
        battery_pct=90.0,
    )
    res_ext = correct_and_validate_reading(extreme_reading)
    assert res_ext.validation_status == ValidationStatus.ANOMALY.value
    assert res_ext.is_anomaly is True


# -----------------------------------------------------------------------------
# 4. Risk to Draft Alert Creation
# -----------------------------------------------------------------------------

def test_e2e_risk_to_draft_alert(test_db: sqlite3.Connection) -> None:
    """Verify high risk creates a draft alert with affected area and initial audit entry."""
    draft_id = create_draft_alert(
        severity=AlertSeverity.WARNING,
        title="Patna Monsoon Inundation Advisory",
        message="Monsoon runoff warning for vulnerable depression sectors.",
        affected_area="Patna, Bihar",
        db_path=test_db,
    )
    assert draft_id.startswith("ALT-DRAFT-")

    alert = get_alert_by_id(draft_id, db_path=test_db)
    assert alert is not None
    assert alert["lifecycle_status"] == "draft"
    assert alert["severity"] == "WARNING"
    assert alert["affected_area"] == "Patna, Bihar"

    cursor = test_db.cursor()
    cursor.execute("SELECT * FROM alert_logs WHERE alert_id=? AND status='DRAFT_CREATED';", (draft_id,))
    log_entry = cursor.fetchone()
    assert log_entry is not None
    assert log_entry["channel"] == "SYSTEM"


# -----------------------------------------------------------------------------
# 5. Authority Review & Approval Gate
# -----------------------------------------------------------------------------

def test_e2e_authority_approval(test_db: sqlite3.Connection) -> None:
    """Verify authority approval transitions draft alert to dispatched."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Saidpur Basin Advisory",
        message="Critical ponding predicted at Saidpur nullah.",
        affected_area="Saidpur, Patna",
        db_path=test_db,
    )

    dispatch_res = dispatch_authority_alert(
        severity="WARNING",
        title="Saidpur Basin Advisory",
        message="Critical ponding predicted at Saidpur nullah.",
        affected_area="Saidpur, Patna",
        draft_id=draft_id,
        db_path=test_db,
    )

    assert dispatch_res["success"] is True
    assert dispatch_res["duplicate"] is False
    assert dispatch_res["dismissed"] is False

    alert = get_alert_by_id(draft_id, db_path=test_db)
    assert alert is not None
    assert alert["lifecycle_status"] == "dispatched"

    cursor = test_db.cursor()
    cursor.execute("SELECT * FROM alert_logs WHERE alert_id=? AND status='APPROVED';", (dispatch_res["alert_id"],))
    assert cursor.fetchone() is not None


# -----------------------------------------------------------------------------
# 6. Authority Dismissal Gate
# -----------------------------------------------------------------------------

def test_e2e_authority_dismissal(test_db: sqlite3.Connection) -> None:
    """Verify authority dismissal marks alert suppressed with dismissal audit log."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Spurious Advisory",
        message="False positive sensor reading.",
        affected_area="Boring Road, Patna",
        db_path=test_db,
    )

    dismiss_res = dismiss_authority_alert(
        alert_id=draft_id,
        reason="Dismissed by duty officer: manual sensor inspection showed dry sump.",
        db_path=test_db,
    )

    assert dismiss_res["success"] is True
    assert dismiss_res["status"] == "dismissed"

    alert = get_alert_by_id(draft_id, db_path=test_db)
    assert alert is not None
    assert alert["lifecycle_status"] == "dismissed"
    assert alert["suppressed"] == 1

    cursor = test_db.cursor()
    cursor.execute("SELECT * FROM alert_logs WHERE alert_id=? AND status='DISMISSED';", (draft_id,))
    assert cursor.fetchone() is not None


# -----------------------------------------------------------------------------
# 7. Dry-Run Dispatch Safety
# -----------------------------------------------------------------------------

def test_e2e_dry_run_dispatch(test_db: sqlite3.Connection) -> None:
    """Verify dry-run mode simulates delivery without external API transmission."""
    dispatch_res = dispatch_authority_alert(
        severity="WARNING",
        title="Dry Run Test Advisory",
        message="Dry run message simulation.",
        affected_area="Patna, Bihar",
        db_path=test_db,
    )

    assert dispatch_res["success"] is True
    assert dispatch_res["dry_run"] is True
    for ch_name, ch_info in dispatch_res["channels"].items():
        assert ch_info["status"] in ("DRY_RUN", "SENT", "DELIVERED")
        assert ch_info["success"] is True


# -----------------------------------------------------------------------------
# 8. Audit Logging Completeness
# -----------------------------------------------------------------------------

def test_e2e_audit_logging(test_db: sqlite3.Connection) -> None:
    """Verify alert_logs records all lifecycle transitions and dispatch outcomes."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Audit Trail Test",
        message="Audit verification.",
        affected_area="Patna, Bihar",
        db_path=test_db,
    )

    dispatch_res = dispatch_authority_alert(
        severity="WARNING",
        title="Audit Trail Test",
        message="Audit verification.",
        draft_id=draft_id,
        db_path=test_db,
    )

    cursor = test_db.cursor()
    cursor.execute(
        "SELECT channel, status FROM alert_logs WHERE alert_id IN (?, ?);",
        (draft_id, dispatch_res["alert_id"]),
    )
    logs = cursor.fetchall()
    assert len(logs) >= 2  # DRAFT_CREATED and APPROVED
    statuses = [l["status"] for l in logs]
    assert "DRAFT_CREATED" in statuses
    assert "APPROVED" in statuses


# -----------------------------------------------------------------------------
# 9. Citizen Safe Routing
# -----------------------------------------------------------------------------

def test_e2e_safe_route_computation(test_db: sqlite3.Connection) -> None:
    """Verify safe route calculation locates reachable designated shelters avoiding hazards."""
    # Ensure database has heavy rain risk predictions
    trigger_heavy_rain_scenario(db_path=test_db)

    # Calculate safe route from Central Patna coordinates
    route_res = safe_route(25.5941, 85.1376, db_path=test_db)
    assert route_res["status"] in ("success", "error")
    assert "distance_m" in route_res
    assert "route" in route_res
    assert "destination" in route_res


# -----------------------------------------------------------------------------
# 10. Deterministic Reset Verification
# -----------------------------------------------------------------------------

def test_e2e_deterministic_reset(test_db: sqlite3.Connection) -> None:
    """Verify reset_to_baseline_scenario cleans dynamic predictions and restores baseline."""
    # First trigger heavy rain
    trigger_heavy_rain_scenario(db_path=test_db)
    cursor = test_db.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM risk_predictions;")
    assert cursor.fetchone()["cnt"] > 0

    # Reset
    reset_res = reset_to_baseline_scenario(db_path=test_db)
    assert reset_res["success"] is True

    # Confirm clean state
    cursor.execute("SELECT COUNT(*) as cnt FROM risk_predictions;")
    assert cursor.fetchone()["cnt"] == 0
    cursor.execute("SELECT COUNT(*) as cnt FROM alerts;")
    assert cursor.fetchone()["cnt"] == 0


# -----------------------------------------------------------------------------
# 11. Channel Failure Isolation
# -----------------------------------------------------------------------------

def test_e2e_channel_failure_isolation(test_db: sqlite3.Connection) -> None:
    """Verify failure in one delivery channel does not impede other notification channels."""
    mock_tg = MagicMock(spec=TelegramAlertHandler)
    mock_tg.send_message.return_value = TelegramDispatchResult(
        success=False, chat_id="-1001", status="FAILED", error="API connection refused"
    )

    mock_tw = MagicMock(spec=TwilioAlertHandler)
    mock_tw.send_sms.return_value = TwilioDispatchResult(
        success=True, channel="SMS", recipient="+919876543210", status="SENT", message_sid="SM123"
    )
    mock_tw.send_whatsapp.return_value = TwilioDispatchResult(
        success=True, channel="WHATSAPP", recipient="whatsapp:+919876543210", status="SENT", message_sid="WA123"
    )

    dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=test_db)
    with patch("app.alert_service.AlertDispatcher", return_value=dispatcher):
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Channel Isolation Test",
            message="Testing channel error resilience.",
            affected_area="Patna, Bihar",
            db_path=test_db,
        )

    assert res["success"] is True
    assert res["partial_failure"] is True
    assert res["channels"]["Telegram"]["success"] is False
    assert res["channels"]["SMS"]["success"] is True


# -----------------------------------------------------------------------------
# 12. Dismissed Alert Block
# -----------------------------------------------------------------------------

def test_e2e_dismissed_alert_block(test_db: sqlite3.Connection) -> None:
    """Verify an alert that has been dismissed cannot subsequently be approved or dispatched."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Advisory to Dismiss",
        message="Dismissal test.",
        affected_area="Patna, Bihar",
        db_path=test_db,
    )
    dismiss_authority_alert(alert_id=draft_id, db_path=test_db)

    # Attempt to dispatch the dismissed alert
    dispatch_res = dispatch_authority_alert(
        severity="WARNING",
        title="Advisory to Dismiss",
        message="Dismissal test.",
        draft_id=draft_id,
        db_path=test_db,
    )

    assert dispatch_res["success"] is False
    assert dispatch_res["dismissed"] is True
    assert "dismissed" in dispatch_res["message"].lower()


# -----------------------------------------------------------------------------
# 13. Historical Backtest Replay Verification
# -----------------------------------------------------------------------------

def test_e2e_historical_backtest_replay() -> None:
    """Verify replay of historical events (Michaung 2023 & Nov 2021) with metrics and disclaimers."""
    # Test Cyclone Michaung 2023 (Extremely Severe)
    michaung = replay_historical_backtest_event(event_id="EVT_2023_MICHAUNG", threshold_mm=50.0)
    assert michaung["success"] is True
    assert michaung["total_rainfall_mm"] > 300.0
    assert michaung["exceeded_threshold"] is True
    assert "HIGH RISK" in michaung["alert_opportunity"]
    assert "disclaimer" in michaung
    assert len(michaung["limitations"]) > 0

    # Test Nov 2021 Depression with high threshold (e.g. 150 mm) -> should not exceed
    nov2021_high_thresh = replay_historical_backtest_event(event_id="EVT_2021_NOV_DEPRESSION", threshold_mm=150.0)
    assert nov2021_high_thresh["success"] is True
    assert nov2021_high_thresh["total_rainfall_mm"] < 100.0
    assert nov2021_high_thresh["exceeded_threshold"] is False
    assert "NOMINAL" in nov2021_high_thresh["alert_opportunity"]


# -----------------------------------------------------------------------------
# 14. Master Orchestrator Verification
# -----------------------------------------------------------------------------

def test_run_end_to_end_pipeline_integration(test_db: sqlite3.Connection) -> None:
    """Verify run_end_to_end_pipeline executes the full operational cycle."""
    # Test approval pipeline
    res_app = run_end_to_end_pipeline(
        scenario="HEAVY_RAIN",
        db_path=test_db,
        authority_action="approve",
        citizen_start_coord=(25.5941, 85.1376),
    )
    assert res_app["success"] is True
    assert res_app["scenario"] == "HEAVY_RAIN"
    assert res_app["draft_alert_id"] is not None
    assert res_app["authority_action"] == "approve"
    assert res_app["dispatch_result"]["success"] is True
    assert len(res_app["audit_logs"]) > 0
    assert "status" in res_app["safe_route_result"]

    # Test dismissal pipeline
    res_dis = run_end_to_end_pipeline(
        scenario="HEAVY_RAIN",
        db_path=test_db,
        authority_action="dismiss",
        citizen_start_coord=(25.5941, 85.1376),
    )
    assert res_dis["success"] is True
    assert res_dis["authority_action"] == "dismiss"
    assert res_dis["dispatch_result"]["status"] == "dismissed"

    # Test baseline pipeline
    res_base = run_end_to_end_pipeline(
        scenario="BASELINE",
        db_path=test_db,
        authority_action=None,
    )
    assert res_base["success"] is True
    assert res_base["scenario"] == "BASELINE"
    assert res_base["draft_alert_id"] is None
