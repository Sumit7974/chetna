import pytest
from src.routing.router import OSMRouter, haversine
from src.api.routing_api import get_safe_route

@pytest.fixture
def mock_router(monkeypatch):
    router = OSMRouter()
    # Force use of mock graph
    monkeypatch.setattr("src.routing.router.HAS_OSMNX", False)
    return router

def test_haversine_distance():
    # Roughly distance between 13.0, 80.0 and 13.01, 80.0
    dist = haversine(13.0, 80.0, 13.01, 80.0)
    assert 1100 < dist < 1200  # Should be ~1.11 km

def test_basic_a_star_routing(mock_router):
    result = mock_router.find_safe_route((13.0, 80.0), (13.01, 80.01))
    assert result["status"] == "success"
    assert len(result["route"]) > 0
    assert "distance_m" in result
    assert "estimated_time_min" in result

def test_hazard_avoidance(mock_router):
    # Place a medium hazard on Node 2 (13.01, 80.0)
    # The router should prefer going through Node 3 (13.0, 80.01)
    hazard_zones = [{"lat": 13.01, "lon": 80.0, "radius_m": 100, "risk_level": "MEDIUM"}]
    
    result = mock_router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones)
    assert result["status"] == "success"
    
    # Check that route avoids Node 2. Route should be Node 1 -> Node 3 -> Node 4
    lats = [r["lat"] for r in result["route"]]
    lons = [r["lon"] for r in result["route"]]
    
    assert 13.0 in lats  # Start
    assert 13.01 in lats # End
    
    # Node 3 is (13.0, 80.01). If we avoid Node 2, the intermediate is (13.0, 80.01)
    # Node 2 is (13.01, 80.0). It should NOT be in the route.
    assert {"lat": 13.01, "lon": 80.0} not in result["route"]
    assert {"lat": 13.0, "lon": 80.01} in result["route"]

def test_blocked_road_no_safe_route(mock_router):
    # Place a HIGH hazard blocking BOTH intermediate nodes
    hazard_zones = [
        {"lat": 13.01, "lon": 80.0, "radius_m": 100, "risk_level": "HIGH"},
        {"lat": 13.0, "lon": 80.01, "radius_m": 100, "risk_level": "HIGH"}
    ]
    
    result = mock_router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones)
    assert result["status"] == "error"
    assert result["message"] == "No safe route is currently available."

def test_routing_api_validation(monkeypatch):
    # Invalid lat
    res = get_safe_route(100.0, 80.0, 13.0, 80.0)
    assert res["status"] == "error"
    assert "Invalid latitude" in res["message"]
    
    # Invalid lon
    res = get_safe_route(13.0, 200.0, 13.0, 80.0)
    assert res["status"] == "error"
    assert "Invalid longitude" in res["message"]
    
    # Missing
    res = get_safe_route(None, 80.0, 13.0, 80.0)
    assert res["status"] == "error"
    assert "required" in res["message"]


# ==============================================================================
# B2 DAY 4 ENHANCED TEST SUITE: LIFECYCLE, APPROVAL, DELIVERY, AUDIT & ROUTING
# ==============================================================================

import sqlite3
from unittest.mock import MagicMock, patch
from alerts.dispatcher import AlertDispatcher, AlertSeverity
from alerts.pipeline import dismiss_alert
from alerts.telegram_handler import TelegramAlertHandler, TelegramDispatchResult
from alerts.twilio_handler import TwilioAlertHandler, TwilioDispatchResult
from app.alert_service import (
    create_draft_alert,
    dismiss_authority_alert,
    dispatch_authority_alert,
    format_draft_alert_text,
)
from database.db import get_alert_by_id, init_db, log_alert_dispatch
from src.routing.router import safe_route


@pytest.fixture
def mem_db():
    """Isolated in-memory database initialized with full Chetna schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ------------------------------------------------------------------------------
# 1. ALERT LIFECYCLE TESTS
# ------------------------------------------------------------------------------

def test_alert_lifecycle_draft_creation(mem_db):
    """Verify draft alert is created with 'draft' lifecycle status and logged in audit trail."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Urban Flood Warning (+1h)",
        message="Stormwater stagnation at underpasses.",
        affected_area="Patna, Bihar",
        db_path=mem_db,
    )
    assert draft_id.startswith("ALT-DRAFT-")

    record = get_alert_by_id(draft_id, db_path=mem_db)
    assert record is not None
    assert record["lifecycle_status"] == "draft"
    assert record["severity"] == "WARNING"
    assert record["suppressed"] == 0
    assert record["affected_area"] == "Patna, Bihar"

    # Audit log check
    logs = mem_db.execute("SELECT * FROM alert_logs WHERE alert_id=?;", (draft_id,)).fetchall()
    assert len(logs) >= 1
    assert logs[0]["status"] == "DRAFT_CREATED"
    assert logs[0]["channel"] == "SYSTEM"


def test_alert_lifecycle_approval_and_dispatch(mem_db):
    """Verify approving a draft transitions lifecycle to 'dispatched' and logs approval."""
    draft_id = create_draft_alert(
        severity="CRITICAL",
        title="Severe Inundation Advisory",
        message="Critical water level reached.",
        affected_area="Patna, Bihar",
        db_path=mem_db,
    )

    res = dispatch_authority_alert(
        severity="CRITICAL",
        title="Severe Inundation Advisory",
        message="Critical water level reached.",
        affected_area="Patna, Bihar",
        db_path=mem_db,
        draft_id=draft_id,
    )

    assert res["success"] is True
    assert res["duplicate"] is False
    assert res["dismissed"] is False
    assert res["dry_run"] is True

    # Draft record updated to dispatched
    updated_draft = get_alert_by_id(draft_id, db_path=mem_db)
    assert updated_draft["lifecycle_status"] == "dispatched"

    # Approval event logged
    appr_logs = mem_db.execute(
        "SELECT * FROM alert_logs WHERE status='APPROVED';"
    ).fetchall()
    assert len(appr_logs) >= 1
    assert appr_logs[0]["channel"] == "SYSTEM"
    assert appr_logs[0]["recipient"] == "AUTHORITY_OPS"


def test_alert_lifecycle_dismiss(mem_db):
    """Verify dismissal terminates the draft, marks it suppressed, and prevents subsequent dispatch."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Test Waterlogging Warning",
        message="Advisory test",
        affected_area="Patna, Bihar",
        db_path=mem_db,
    )

    dis_res = dismiss_authority_alert(
        alert_id=draft_id,
        reason="Field inspection shows drainage cleared.",
        db_path=mem_db,
    )
    assert dis_res["success"] is True
    assert dis_res["status"] == "dismissed"

    # Check alert record
    record = get_alert_by_id(draft_id, db_path=mem_db)
    assert record["lifecycle_status"] == "dismissed"
    assert record["suppressed"] == 1

    # Check audit log
    dis_logs = mem_db.execute(
        "SELECT * FROM alert_logs WHERE alert_id=? AND status='DISMISSED';",
        (draft_id,),
    ).fetchall()
    assert len(dis_logs) >= 1
    assert "Field inspection shows drainage cleared" in dis_logs[0]["message"]

    # Subsequent dispatch attempt on dismissed alert must be prevented
    try_disp = dispatch_authority_alert(
        severity="WARNING",
        title="Attempted Broadcast",
        message="Should fail",
        db_path=mem_db,
        draft_id=draft_id,
    )
    assert try_disp["success"] is False
    assert try_disp["dismissed"] is True
    assert "Cannot dispatch a dismissed alert" in try_disp["message"]


def test_alert_lifecycle_duplicate_approval_protection(mem_db):
    """Verify duplicate approval attempts on an already dispatched draft are rejected."""
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Flood Warning",
        message="Test message",
        db_path=mem_db,
    )

    # First approval
    first_res = dispatch_authority_alert(
        severity="WARNING",
        title="Flood Warning",
        message="Test message",
        db_path=mem_db,
        draft_id=draft_id,
    )
    assert first_res["success"] is True

    # Second approval attempt on the same draft_id
    second_res = dispatch_authority_alert(
        severity="WARNING",
        title="Flood Warning",
        message="Test message",
        db_path=mem_db,
        draft_id=draft_id,
    )
    assert second_res["success"] is False
    assert second_res["duplicate"] is True
    assert "already been approved and dispatched" in second_res["message"]


def test_pipeline_standalone_dismiss_helper(mem_db):
    """Verify standalone dismiss_alert from alerts.pipeline properly marks alert dismissed."""
    from alerts.pipeline import AlertPipeline
    pipeline = AlertPipeline(db_path=mem_db)
    alert_id = "ALT-STANDALONE-001"
    mem_db.execute(
        "INSERT INTO alerts (alert_id, severity, lifecycle_status, message) VALUES (?, 'INFO', 'generated', 'Test');",
        (alert_id,),
    )
    dismiss_alert(alert_id, db_path=mem_db)

    row = mem_db.execute("SELECT lifecycle_status, suppressed FROM alerts WHERE alert_id=?;", (alert_id,)).fetchone()
    assert row["lifecycle_status"] == "dismissed"
    assert row["suppressed"] == 1


# ------------------------------------------------------------------------------
# 2. NOTIFICATION DELIVERY & FAILURE HANDLING TESTS
# ------------------------------------------------------------------------------

def test_notification_dry_run_safety(mem_db):
    """Dry-run mode should simulate dispatch safely without sending external network messages."""
    res = dispatch_authority_alert(
        severity="WARNING",
        title="Advisory Warning",
        message="Monsoon rain stagnation",
        affected_area="Patna, Bihar",
        db_path=mem_db,
    )
    assert res["success"] is True
    assert res["dry_run"] is True
    assert "Dry-run: notification simulated" in res["message"]

    channels = res["channels"]
    assert "Telegram" in channels
    assert "WhatsApp" in channels
    assert "SMS" in channels
    assert channels["Telegram"]["status"] == "DRY_RUN"
    assert channels["WhatsApp"]["status"] == "DRY_RUN"
    assert channels["SMS"]["status"] == "DRY_RUN"


def test_notification_partial_channel_failure(mem_db):
    """When one channel fails and others succeed, report partial_failure=True, success=True."""
    mock_tg = MagicMock(spec=TelegramAlertHandler)
    mock_tg.send_message.return_value = TelegramDispatchResult(
        success=False, chat_id="-1001", status="FAILED", error="Telegram network timeout"
    )

    mock_tw = MagicMock(spec=TwilioAlertHandler)
    mock_tw.send_sms.return_value = TwilioDispatchResult(
        success=True, channel="SMS", recipient="+919876543210", status="SENT", message_sid="SM123"
    )
    mock_tw.send_whatsapp.return_value = TwilioDispatchResult(
        success=True, channel="WHATSAPP", recipient="whatsapp:+919876543210", status="SENT", message_sid="WA123"
    )

    dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=mem_db)
    with patch("app.alert_service.AlertDispatcher", return_value=dispatcher):
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Warning Test",
            message="Partial fail test",
            affected_area="Patna, Bihar",
            db_path=mem_db,
        )

    assert res["success"] is True
    assert res["partial_failure"] is True
    assert "partial channel failures" in res["message"]
    assert res["channels"]["Telegram"]["success"] is False
    assert res["channels"]["SMS"]["success"] is True


def test_notification_complete_channel_failure(mem_db):
    """When all channels fail, report success=False and record 'failed' lifecycle status."""
    mock_tg = MagicMock(spec=TelegramAlertHandler)
    mock_tg.send_message.return_value = TelegramDispatchResult(
        success=False, chat_id="-1001", status="FAILED", error="API connection refused"
    )

    mock_tw = MagicMock(spec=TwilioAlertHandler)
    mock_tw.send_sms.return_value = TwilioDispatchResult(
        success=False, channel="SMS", recipient="+919876543210", status="FAILED", error="Gateway unavailable"
    )
    mock_tw.send_whatsapp.return_value = TwilioDispatchResult(
        success=False, channel="WHATSAPP", recipient="whatsapp:+919876543210", status="FAILED", error="Gateway unavailable"
    )

    dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=mem_db)
    with patch("app.alert_service.AlertDispatcher", return_value=dispatcher):
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Outage Test",
            message="All fail test",
            affected_area="Patna, Bihar",
            db_path=mem_db,
        )

    assert res["success"] is False
    assert "all channels reported delivery failure" in res["message"]


def test_notification_channel_exception_resilience(mem_db):
    """When a handler throws an unhandled exception, dispatcher catches it, logs FAILED, and continues."""
    mock_tg = MagicMock(spec=TelegramAlertHandler)
    mock_tg.send_message.side_effect = RuntimeError("Fatal socket crash in Telegram")

    mock_tw = MagicMock(spec=TwilioAlertHandler)
    mock_tw.send_sms.return_value = TwilioDispatchResult(
        success=True, channel="SMS", recipient="+919876543210", status="SENT", message_sid="SM999"
    )
    mock_tw.send_whatsapp.return_value = TwilioDispatchResult(
        success=True, channel="WHATSAPP", recipient="whatsapp:+919876543210", status="SENT", message_sid="WA999"
    )

    dispatcher = AlertDispatcher(twilio_handler=mock_tw, telegram_handler=mock_tg, db_path=mem_db)
    alert_id = dispatcher.dispatch(
        severity=AlertSeverity.WARNING,
        title="Exception Resilience Test",
        message="Resilience test message",
        affected_area="Patna, Bihar",
        sms_recipients=["+919876543210", "whatsapp:+919876543210"],
    )

    assert alert_id.startswith("ALT-")
    # Verify Telegram failure was logged as FAILED without stopping Twilio SMS/WhatsApp
    logs = mem_db.execute("SELECT channel, status, response_payload FROM alert_logs WHERE alert_id=?;", (alert_id,)).fetchall()
    channels_logged = {row["channel"]: row["status"] for row in logs}
    assert channels_logged.get("TELEGRAM") == "FAILED"
    assert channels_logged.get("TWILIO_SMS") == "SENT"
    assert channels_logged.get("TWILIO_WHATSAPP") == "SENT"


def test_missing_credentials_graceful_operation(mem_db):
    """Handlers with missing or placeholder credentials operate in dry_run or fail gracefully."""
    unconfigured_twilio = TwilioAlertHandler(
        account_sid="", auth_token="", from_phone="", dry_run=False
    )
    assert not unconfigured_twilio.is_configured
    sms_res = unconfigured_twilio.send_sms("+919876543210", "Test missing")
    assert sms_res.success is True
    assert sms_res.status == "DRY_RUN"

    unconfigured_tg = TelegramAlertHandler(bot_token="", default_chat_id="", dry_run=False)
    assert not unconfigured_tg.is_configured
    tg_res = unconfigured_tg.send_message("Test missing")
    assert tg_res.success is False
    assert tg_res.status == "FAILED"


# ------------------------------------------------------------------------------
# 3. AUDIT TRAIL TESTS
# ------------------------------------------------------------------------------

def test_audit_trail_captures_all_events(mem_db):
    """Full lifecycle produces an auditable record with timestamps, channels, and statuses."""
    draft_id = create_draft_alert(
        severity="CRITICAL",
        title="Audit Test Advisory",
        message="Checking audit trail fields.",
        affected_area="Patna Municipal Area",
        db_path=mem_db,
    )

    res = dispatch_authority_alert(
        severity="CRITICAL",
        title="Audit Test Advisory",
        message="Checking audit trail fields.",
        affected_area="Patna Municipal Area",
        db_path=mem_db,
        draft_id=draft_id,
    )

    assert res["success"] is True
    alert_id = res["alert_id"]

    logs = mem_db.execute(
        "SELECT * FROM alert_logs WHERE alert_id IN (?, ?) ORDER BY id ASC;",
        (draft_id, alert_id),
    ).fetchall()

    statuses = [r["status"] for r in logs]
    channels = [r["channel"] for r in logs]

    assert "DRAFT_CREATED" in statuses
    assert "APPROVED" in statuses
    assert "TELEGRAM" in channels
    assert any("SMS" in ch or "TWILIO" in ch for ch in channels)

    # Check timestamps and non-empty messages
    for row in logs:
        assert row["timestamp"] is not None
        assert len(row["message"]) > 0


def test_audit_trail_no_sensitive_secrets(mem_db):
    """Verify that credentials or API secrets are never stored in the audit trail."""
    dispatch_authority_alert(
        severity="WARNING",
        title="Security Check",
        message="Verifying credential protection",
        db_path=mem_db,
    )
    logs = mem_db.execute("SELECT * FROM alert_logs;").fetchall()
    sensitive_words = ["auth_token", "secret", "sk_live", "password", "api_key"]
    for row in logs:
        for col in ["message", "response_payload", "recipient"]:
            val = str(row[col]).lower() if row[col] else ""
            for word in sensitive_words:
                assert word not in val, f"Sensitive secret '{word}' found in audit log {col}: {val}"


# ------------------------------------------------------------------------------
# 4. SAFE ROUTE & CITIZEN EXPERIENCE TESTS
# ------------------------------------------------------------------------------

def test_safe_route_found_with_real_backend():
    """Verify safe_route calculates valid path to shelter using existing backend."""
    res = safe_route(lat=25.594, lon=85.158, horizon=1)
    assert res["status"] == "success"
    assert res["found"] is True
    assert len(res["route"]) >= 1
    assert res["distance_m"] >= 0.0
    assert res["estimated_time_min"] >= 0.0
    assert "destination" in res
    assert res["destination"] is not None
    assert "name" in res["destination"]


def test_safe_route_no_route_when_unreachable():
    """Verify unreachable coordinates return found=False and empty route without crashing."""
    res = safe_route(lat=999.0, lon=999.0, horizon=1)
    assert res["status"] == "error"
    assert res["found"] is False
    assert len(res["route"]) == 0
    assert "out of bounds" in res["message"].lower() or "invalid" in res["message"].lower()


def test_safe_route_decision_support_disclaimer_present():
    """Verify decision-support route disclaimer wording in citizen view."""
    import inspect
    import app.citizen_view as cv
    src = inspect.getsource(cv.render_citizen_safe_route)
    assert "Decision-support navigation path only; not a guaranteed safe evacuation route" in src
    assert "ROUTE STATUS: NO SAFE ROUTE FOUND" in src


def test_safe_route_no_fabricated_geometry():
    """Verify returned route geometry points are valid geographic coordinates."""
    res = safe_route(lat=25.594, lon=85.158, horizon=1)
    if res["found"]:
        for pt in res["route"]:
            assert "lat" in pt and "lon" in pt
            assert 24.0 <= pt["lat"] <= 27.0  # Patna region
            assert 84.0 <= pt["lon"] <= 87.0


# ------------------------------------------------------------------------------
# 5. FRONTEND INTEGRATION TESTS
# ------------------------------------------------------------------------------

def test_f1_review_alert_format_contract():
    """Verify draft alert formatting generates authority-appropriate operational advisory."""
    draft = format_draft_alert_text(
        active_horizon="+3h",
        affected_area="Patna, Bihar",
        high_cells_count=8,
        asset_summary={"hospitals": 2, "schools": 4, "shelters": 3},
    )
    assert "[CHETNA FLOOD ADVISORY — Horizon: +3h]" in draft
    assert "Patna, Bihar" in draft
    assert "8 monitored sectors" in draft
    assert "2 Hospitals, 4 Schools, 3 Shelters" in draft
    assert "Deploy mobile sumps" in draft


def test_f2_bilingual_advisory_contract():
    """Verify F2 citizen portal supports English and Hindi advisories without developer jargon."""
    from app.citizen_view import get_bilingual_messages
    msgs = get_bilingual_messages()
    for lang in ("en", "hi"):
        assert "title" in msgs[lang]
        assert "safety_tips" in msgs[lang]
        assert len(msgs[lang]["safety_tips"]) >= 3
        # No developer jargon in citizen facing messages
        for tip in msgs[lang]["safety_tips"]:
            assert "Day 4" not in tip
            assert "milestone" not in tip.lower()
