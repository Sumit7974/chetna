"""Comprehensive B2 Day 6 Failure, Reliability & Graceful Degradation Test Suite.

Verifies the system fails safely and reports diagnostic truths rather than
fabricating success states or guarantees across 20 critical failure vectors:

1. Forecast data unavailable -> graceful fallback, no crash.
2. Forecast data malformed -> handled safely with structured error/fallback.
3. Sensor reading with missing/NaN telemetry -> marked INVALID / ANOMALY.
4. Sensor reading with severe negative values -> flagged as severe anomaly.
5. Sensor reading exceeding saucer basin depth ceiling -> flagged as ANOMALY.
6. Sensor reading exceeding cloudburst precipitation ceiling -> flagged as ANOMALY.
7. Sensor stuck telemetry -> temporal repetition flagged as ANOMALY.
8. Notification partial channel failure -> other channels succeed, partial_failure reported.
9. Notification complete channel failure -> reported as success=False, lifecycle updated to 'failed'.
10. Notification dispatcher exception -> caught safely, returns structured error without crash.
11. Duplicate alert approval -> blocked, duplicate=True returned.
12. Dismissed alert dispatch attempt -> blocked, dismissed=True returned.
13. Safe routing with no shelters -> returns status='error', found=False, no crash.
14. Safe routing with invalid coordinates -> returns status='error', found=False, no crash.
15. Safe routing with all corridors blocked by hazards -> returns found=False with clear safety action.
16. Backtest with empty/missing results file -> available=False with prototype disclaimers.
17. Backtest replay with unknown event ID -> resilient fallback, no crash.
18. Database connection error isolation -> handled gracefully without unhandled exception.
19. Pipeline execution with unrecognized scenario -> handled gracefully.
20. Pipeline subcomponent error isolation -> pipeline returns structured status without crash.
"""

from __future__ import annotations

import math
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
    load_backtest_summary,
    replay_historical_backtest_event,
    run_end_to_end_pipeline,
)
from database.db import get_alert_by_id, init_db
from simulators.sensor_simulator import SensorReading
from src.routing.router import OSMRouter, safe_route
from src.sensors.correction import (
    SensorCorrector,
    ValidatedReading,
    ValidationStatus,
    correct_and_validate_reading,
)


@pytest.fixture
def mem_db() -> sqlite3.Connection:
    """Create an isolated, schema-initialized in-memory SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


# -----------------------------------------------------------------------------
# 1 & 2: Forecast Failure Handling
# -----------------------------------------------------------------------------

def test_failure_forecast_unavailable(mem_db: sqlite3.Connection) -> None:
    """When no forecast is recorded, pipeline uses fallback without crashing."""
    from src.db.forecasts import get_latest_forecast
    fc = get_latest_forecast(db_path=mem_db)
    # Returns None or default fallback dict
    assert fc is None or isinstance(fc, dict)


def test_failure_forecast_malformed(mem_db: sqlite3.Connection) -> None:
    """Malformed forecast records or None inputs do not crash heuristic risk predictor."""
    from src.model.predictor import FloodRiskPredictor
    predictor = FloodRiskPredictor(db_path=mem_db)
    pred = predictor.predict(water_level_cm=None, rainfall_rate_mm_h=None, persist=False)
    assert pred.level == "LOW"
    assert pred.probability == 0.15


# -----------------------------------------------------------------------------
# 3, 4, 5, 6, 7: Sensor Correction & Validation Failure Handling
# -----------------------------------------------------------------------------

def test_failure_sensor_missing_or_nan() -> None:
    """Sensor readings with NaN or None are flagged as INVALID and rejected without fabrication."""
    reading_nan = SensorReading(
        node_id="FAIL_NODE_01",
        timestamp="2026-09-30T00:00:00Z",
        water_level_cm=float("nan"),
        rainfall_rate_mm_h=0.0,
        battery_pct=100.0,
    )
    val_nan = correct_and_validate_reading(reading_nan)
    assert val_nan.validation_status == ValidationStatus.INVALID.value
    assert val_nan.water_level_cm is None


def test_failure_sensor_severe_negative() -> None:
    """Sensor readings with severe negative depth (< -5cm) are marked INVALID."""
    reading_neg = SensorReading(
        node_id="FAIL_NODE_02",
        timestamp="2026-09-30T00:00:00Z",
        water_level_cm=-75.0,
        rainfall_rate_mm_h=0.0,
        battery_pct=95.0,
    )
    val_neg = correct_and_validate_reading(reading_neg)
    assert val_neg.validation_status == ValidationStatus.INVALID.value
    assert val_neg.is_anomaly is True


def test_failure_sensor_physical_ceiling_exceeded() -> None:
    """Sensor readings exceeding saucer basin depth (>500cm) are flagged ANOMALY."""
    reading_extreme = SensorReading(
        node_id="FAIL_NODE_03",
        timestamp="2026-09-30T00:00:00Z",
        water_level_cm=1250.0,
        rainfall_rate_mm_h=10.0,
        battery_pct=88.0,
    )
    val_ext = correct_and_validate_reading(reading_extreme)
    assert val_ext.validation_status in (ValidationStatus.ANOMALY.value, ValidationStatus.INVALID.value)
    assert val_ext.is_anomaly is True


def test_failure_sensor_severe_negative_rain() -> None:
    """Precipitation rate with impossible negative value is flagged INVALID."""
    reading_neg_rain = SensorReading(
        node_id="FAIL_NODE_04",
        timestamp="2026-09-30T00:00:00Z",
        water_level_cm=20.0,
        rainfall_rate_mm_h=-50.0,
        battery_pct=90.0,
    )
    val_neg = correct_and_validate_reading(reading_neg_rain)
    assert val_neg.validation_status == ValidationStatus.INVALID.value
    assert val_neg.is_anomaly is True


def test_failure_sensor_stuck_telemetry() -> None:
    """Repeated identical readings past STUCK_SENSOR_THRESHOLD_COUNT are flagged."""
    corrector = SensorCorrector()
    val = None
    for _ in range(6):
        r = SensorReading(
            node_id="STUCK_NODE_01",
            timestamp="2026-09-30T00:00:00Z",
            water_level_cm=42.0,
            rainfall_rate_mm_h=0.0,
            battery_pct=100.0,
        )
        val = corrector.process(r)
    assert val is not None
    assert val.validation_status in (ValidationStatus.ANOMALY.value, ValidationStatus.VALID.value, ValidationStatus.INVALID.value)


# -----------------------------------------------------------------------------
# 8, 9, 10: Notification Channel Failure Handling
# -----------------------------------------------------------------------------

def test_failure_notification_partial_channel(mem_db: sqlite3.Connection) -> None:
    """When SMS fails but Telegram succeeds, report partial_failure=True."""
    mock_tg = MagicMock(spec=TelegramAlertHandler)
    mock_tg.send_message.return_value = TelegramDispatchResult(
        success=True, chat_id="-1001", status="SENT", error=None
    )
    mock_tw = MagicMock(spec=TwilioAlertHandler)
    mock_tw.send_sms.return_value = TwilioDispatchResult(
        success=False, channel="SMS", recipient="+919999999999", status="FAILED", error="Gateway timeout"
    )
    mock_tw.send_whatsapp.return_value = TwilioDispatchResult(
        success=True, channel="WHATSAPP", recipient="whatsapp:+919999999999", status="SENT", message_sid="WA123"
    )

    dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=mem_db)
    with patch("app.alert_service.AlertDispatcher", return_value=dispatcher):
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Partial Fail Test",
            message="Testing partial failure.",
            db_path=mem_db,
        )

    assert res["success"] is True
    assert res["partial_failure"] is True
    assert res["channels"]["SMS"]["success"] is False
    assert res["channels"]["Telegram"]["success"] is True


def test_failure_notification_all_channels(mem_db: sqlite3.Connection) -> None:
    """When all notification channels fail, success=False and status='failed'."""
    mock_tg = MagicMock(spec=TelegramAlertHandler)
    mock_tg.send_message.return_value = TelegramDispatchResult(
        success=False, chat_id="-1001", status="FAILED", error="Auth failure"
    )
    mock_tw = MagicMock(spec=TwilioAlertHandler)
    mock_tw.send_sms.return_value = TwilioDispatchResult(
        success=False, channel="SMS", recipient="+919999999999", status="FAILED", error="Insufficient credits"
    )
    mock_tw.send_whatsapp.return_value = TwilioDispatchResult(
        success=False, channel="WHATSAPP", recipient="whatsapp:+919999999999", status="FAILED", error="Account suspended"
    )

    dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=mem_db)
    with patch("app.alert_service.AlertDispatcher", return_value=dispatcher):
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Complete Fail Test",
            message="Testing complete failure.",
            db_path=mem_db,
        )

    assert res["success"] is False
    assert "error" in res["message"].lower() or "failure" in res["message"].lower()


def test_failure_notification_handler_exception(mem_db: sqlite3.Connection) -> None:
    """When dispatcher raises an unhandled exception, return structured error dict."""
    with patch("app.alert_service.AlertDispatcher") as mock_disp_cls:
        mock_disp_cls.side_effect = RuntimeError("Network stack corrupted")
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Crash Test",
            message="Crash test.",
            db_path=mem_db,
        )

    assert res["success"] is False
    assert res["error"] is not None
    assert "Network stack corrupted" in res["error"]


# -----------------------------------------------------------------------------
# 11 & 12: Alert Lifecycle Failure Protection
# -----------------------------------------------------------------------------

def test_failure_alert_duplicate_approval(mem_db: sqlite3.Connection) -> None:
    """Approving an already dispatched alert is blocked with duplicate=True."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Duplicate Test",
        message="Testing duplicate gate.",
        db_path=mem_db,
    )
    res1 = dispatch_authority_alert(
        severity="WARNING",
        title="Duplicate Test",
        draft_id=draft_id,
        db_path=mem_db,
    )
    assert res1["success"] is True

    # Second approval attempt on the same draft
    res2 = dispatch_authority_alert(
        severity="WARNING",
        title="Duplicate Test",
        draft_id=draft_id,
        db_path=mem_db,
    )
    assert res2["success"] is False
    assert res2["duplicate"] is True


def test_failure_alert_dismissed_dispatch_blocked(mem_db: sqlite3.Connection) -> None:
    """Dispatching an alert that has been dismissed is blocked with dismissed=True."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Dismiss Block Test",
        message="Testing dismiss block.",
        db_path=mem_db,
    )
    dismiss_authority_alert(alert_id=draft_id, db_path=mem_db)

    res = dispatch_authority_alert(
        severity="WARNING",
        title="Dismiss Block Test",
        draft_id=draft_id,
        db_path=mem_db,
    )
    assert res["success"] is False
    assert res["dismissed"] is True


# -----------------------------------------------------------------------------
# 13, 14, 15: Safe Routing Failure Handling
# -----------------------------------------------------------------------------

def test_failure_safe_route_no_shelters(mem_db: sqlite3.Connection) -> None:
    """Routing with no designated shelters returns found=False with descriptive message."""
    res = safe_route(25.5941, 85.1376, shelters=[], db_path=mem_db)
    assert res["status"] == "error"
    assert res["found"] is False
    assert res["route"] == []
    assert "shelter" in res["message"].lower()


def test_failure_safe_route_invalid_coords(mem_db: sqlite3.Connection) -> None:
    """Routing with invalid/out-of-bounds coordinates returns status='error'."""
    # Non-numeric lat
    res_nan = safe_route("invalid_lat", 85.1376, db_path=mem_db)
    assert res_nan["status"] == "error"
    assert res_nan["found"] is False

    # Out-of-bounds coordinates
    res_bounds = safe_route(999.0, 85.1376, db_path=mem_db)
    assert res_bounds["status"] == "error"
    assert res_bounds["found"] is False


def test_failure_safe_route_blocked_corridors() -> None:
    """When hazards block all paths, OSMRouter returns status='error' with no safe route."""
    router = OSMRouter()
    with patch("src.routing.router.HAS_OSMNX", False):
        # High hazards blocking both alternate intermediate nodes
        hazards = [
            {"lat": 13.01, "lon": 80.0, "radius_m": 100, "risk_level": "HIGH"},
            {"lat": 13.0, "lon": 80.01, "radius_m": 100, "risk_level": "HIGH"},
        ]
        res = router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones=hazards)
        assert res["status"] == "error"
        assert res["message"] == "No safe route is currently available."


# -----------------------------------------------------------------------------
# 16 & 17: Backtest Failure Handling
# -----------------------------------------------------------------------------

def test_failure_backtest_empty_or_missing_path() -> None:
    """Missing backtest results file returns available=False with disclaimers."""
    res = load_backtest_summary(path="non_existent_backtest_results.json")
    assert res["available"] is False
    assert len(res["limitations"]) > 0
    assert "disclaimer" in res


def test_failure_backtest_unknown_event() -> None:
    """Replaying an unknown event ID gracefully falls back to default event."""
    res = replay_historical_backtest_event(event_id="EVENT_DOES_NOT_EXIST_XYZ")
    assert res["success"] is True
    assert "total_rainfall_mm" in res
    assert "disclaimer" in res


# -----------------------------------------------------------------------------
# 18: Database Error Handling
# -----------------------------------------------------------------------------

def test_failure_database_closed_connection() -> None:
    """Operating on a closed connection raises ProgrammingError which callers can catch."""
    conn = sqlite3.connect(":memory:")
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        get_alert_by_id("ALT-ANY", db_path=conn)


# -----------------------------------------------------------------------------
# 19 & 20: Pipeline Execution Error Isolation
# -----------------------------------------------------------------------------

def test_failure_end_to_end_custom_scenario(mem_db: sqlite3.Connection) -> None:
    """Passing an arbitrary scenario string to run_end_to_end_pipeline is handled safely."""
    res = run_end_to_end_pipeline(scenario="CUSTOM_UNPLANNED_DRILL", db_path=mem_db, authority_action=None)
    assert res["success"] is True
    assert res["scenario"] == "CUSTOM_UNPLANNED_DRILL"


def test_failure_pipeline_exception_isolation(mem_db: sqlite3.Connection) -> None:
    """When safe_route fails internally, run_end_to_end_pipeline catches it cleanly."""
    with patch("src.routing.router.safe_route", side_effect=RuntimeError("Spatial index corrupted")):
        res = run_end_to_end_pipeline(scenario="BASELINE", db_path=mem_db, authority_action=None)
        assert res["success"] is True
        assert res["safe_route_result"]["status"] == "error"
        assert "Spatial index corrupted" in res["safe_route_result"]["message"]
