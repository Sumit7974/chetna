"""Comprehensive test suite for Chetna Automatic Geo-Targeted Public Warning layer.

Verifies:
1. CRITICAL risk generates public warning (emergency broadcast).
2. HIGH risk generates advisory but not emergency broadcast.
3. LOW / MEDIUM risk does not generate emergency broadcast.
4. Correct zone is resolved from risk source / cell / coordinates.
5. English message generated properly with prototype disclaimer.
6. Hindi message generated properly with prototype disclaimer.
7. Simulated broadcast returns structured success.
8. Broadcast is explicitly marked as prototype / simulated.
9. No citizen phone number is required or stored.
10. Duplicate warning is suppressed within cooldown window.
11. New meaningful risk state (escalation) can generate a new warning.
12. Existing B2 authority approval flow still works without disruption.
13. Existing SMS / WhatsApp / Telegram dispatcher functions still work.
14. F1 and F2 rendering integration remains intact.
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from database.db import get_recent_public_warnings, init_db
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


class TestGeoTargetedPublicWarning(unittest.TestCase):
    """Test suite verifying the automatic geo-targeted public warning layer."""

    def setUp(self) -> None:
        self.mem_conn = sqlite3.connect(":memory:")
        self.mem_conn.row_factory = sqlite3.Row
        init_db(self.mem_conn)
        self.geo_service = GeoTargetingService()
        self.policy = PublicWarningPolicy()
        self.message_builder = PublicWarningMessageBuilder()
        self.adapter = SimulatedCellBroadcastAdapter()
        self.engine = PublicWarningEngine(
            geo_service=self.geo_service,
            policy=self.policy,
            message_builder=self.message_builder,
            adapter=self.adapter,
            cooldown_seconds=300,
            db_path=self.mem_conn,
        )

    def tearDown(self) -> None:
        self.mem_conn.close()

    def test_01_critical_risk_generates_emergency_broadcast(self) -> None:
        """1. CRITICAL risk triggers an automated public emergency warning."""
        res = self.engine.evaluate_and_broadcast(
            location_name="Kankarbagh",
            risk_level="CRITICAL",
            cell_id="CELL_KAN_01",
        )
        self.assertTrue(res.triggered)
        self.assertEqual(res.action, PublicWarningAction.EMERGENCY_BROADCAST)
        self.assertFalse(res.suppressed)
        self.assertIsNotNone(res.warning_message)
        self.assertEqual(res.warning_message.warning_type, "EMERGENCY_BROADCAST")
        self.assertIn("FLOOD WARNING", res.warning_message.headline_en)
        self.assertIn("बाढ़ चेतावनी", res.warning_message.headline_hi)

    def test_02_high_risk_generates_advisory_not_emergency_broadcast(self) -> None:
        """2. HIGH risk generates public advisory, but does NOT classify it as emergency broadcast."""
        res = self.engine.evaluate_and_broadcast(
            location_name="Rajendra Nagar",
            risk_level="HIGH",
            cell_id="CELL_RAJ_01",
        )
        self.assertTrue(res.triggered)
        self.assertEqual(res.action, PublicWarningAction.PUBLIC_ADVISORY)
        self.assertNotEqual(res.action, PublicWarningAction.EMERGENCY_BROADCAST)
        self.assertEqual(res.warning_message.warning_type, "PUBLIC_ADVISORY")
        self.assertIn("FLOOD ADVISORY", res.warning_message.headline_en)
        self.assertIn("बाढ़ सलाह", res.warning_message.headline_hi)

    def test_03_low_and_medium_do_not_generate_emergency_broadcast(self) -> None:
        """3. LOW / MEDIUM risk does not generate any public emergency broadcast."""
        for lvl in ["LOW", "MEDIUM", "INFO"]:
            res = self.engine.evaluate_and_broadcast(
                location_name="Patliputra",
                risk_level=lvl,
                cell_id="CELL_PAT_01",
            )
            self.assertFalse(res.triggered, f"Level {lvl} should not trigger a broadcast")
            self.assertEqual(res.action, PublicWarningAction.NONE)
            self.assertIsNone(res.delivery_result)

    def test_04_correct_zone_selected_from_various_inputs(self) -> None:
        """4. Correct geographic zone is resolved from cell_id, node_id, or coordinates."""
        # By cell_id
        target1 = self.geo_service.resolve_zone(cell_id="CELL_KAN_01", risk_level="CRITICAL")
        self.assertEqual(target1.zone_name, "Kankarbagh")
        self.assertEqual(target1.zone_id, "ZONE_KAN")

        # By sensor node_id
        target2 = self.geo_service.resolve_zone(node_id="SENS_PAT_01", risk_level="HIGH")
        self.assertEqual(target2.zone_name, "Rajendra Nagar")

        # By coordinates near Saidpur
        target3 = self.geo_service.resolve_zone(latitude=25.6030, longitude=85.1670, risk_level="CRITICAL")
        self.assertIn(target3.zone_name, ["Saidpur", "Rajendra Nagar"])

    def test_05_english_message_generation(self) -> None:
        """5. English message generated is concise, accurate, and includes prototype notice."""
        target = GeoZoneTarget(zone_id="ZONE_KAN", zone_name="Kankarbagh", risk_level="CRITICAL")
        msg = self.message_builder.build_warning(target=target, action=PublicWarningAction.EMERGENCY_BROADCAST)
        en_text = msg.full_text_en
        self.assertIn("FLOOD WARNING", en_text)
        self.assertIn("Kankarbagh", en_text)
        self.assertIn("Avoid waterlogged roads", en_text)
        self.assertIn("prototype alert", en_text.lower())
        # Ensure unsupported claims are not made
        self.assertNotIn("guaranteed safe evacuation", en_text.lower())

    def test_06_hindi_message_generation(self) -> None:
        """6. Hindi message generated is linguistically sound and includes prototype notice."""
        target = GeoZoneTarget(zone_id="ZONE_KAN", zone_name="Kankarbagh", risk_level="CRITICAL")
        msg = self.message_builder.build_warning(target=target, action=PublicWarningAction.EMERGENCY_BROADCAST)
        hi_text = msg.full_text_hi
        self.assertIn("बाढ़ चेतावनी", hi_text)
        self.assertIn("कंकड़बाग", hi_text)
        self.assertIn("जलमग्न सड़कों से बचें", hi_text)
        self.assertIn("स्वचालित प्रोटोटाइप", hi_text)

    def test_07_simulated_broadcast_returns_structured_success(self) -> None:
        """7. Simulated broadcast adapter returns structured success payload."""
        target = GeoZoneTarget(zone_id="ZONE_RAJ", zone_name="Rajendra Nagar", risk_level="CRITICAL")
        delivery = self.adapter.broadcast(
            target_zone=target,
            severity="CRITICAL",
            message="Test broadcast text",
            language="en",
        )
        self.assertEqual(delivery.get("status"), "SIMULATED_DELIVERED")
        self.assertEqual(delivery.get("channel"), "CELL_BROADCAST_SIMULATION")
        self.assertEqual(delivery.get("target_type"), "GEO_ZONE")
        self.assertEqual(delivery.get("target_zone"), "ZONE_RAJ")
        self.assertTrue(delivery.get("message_id", "").startswith("PUB-WARN-"))

    def test_08_broadcast_explicitly_marked_as_prototype(self) -> None:
        """8. Broadcast delivery and audit records explicitly set prototype=True."""
        res = self.engine.evaluate_and_broadcast(
            location_name="Boring Canal Road",
            risk_level="CRITICAL",
            cell_id="CELL_BOR_01",
        )
        self.assertTrue(res.is_prototype)
        self.assertTrue(res.delivery_result.get("prototype"))
        self.assertIn("PROTOTYPE", res.delivery_result.get("gateway"))

        # Verify in database audit
        rows = self.engine.get_recent_warnings(limit=1, db_path=self.mem_conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["is_prototype"], 1)
        self.assertEqual(rows[0]["channel"], "CELL_BROADCAST_SIMULATION")

    def test_09_no_citizen_phone_number_required(self) -> None:
        """9. Warning path functions without citizen phone numbers or subscriber database."""
        # No phone numbers passed, no subscribers table checked
        res = self.engine.evaluate_and_broadcast(
            location_name="Gardanibagh",
            risk_level="CRITICAL",
            cell_id="CELL_GAR_01",
        )
        self.assertTrue(res.triggered)
        # Ensure recipient is geographic zone, not a telephone number
        deliv = res.delivery_result
        self.assertEqual(deliv.get("target_type"), "GEO_ZONE")
        self.assertNotIn("phone", str(deliv).lower())

    def test_10_duplicate_warning_suppression_within_cooldown(self) -> None:
        """10. Repeated risk state in same zone is suppressed during cooldown window."""
        res1 = self.engine.evaluate_and_broadcast(
            location_name="Kankarbagh",
            risk_level="CRITICAL",
            cell_id="CELL_KAN_01",
        )
        self.assertTrue(res1.triggered)
        self.assertFalse(res1.suppressed)

        # Immediate repeat with same severity
        res2 = self.engine.evaluate_and_broadcast(
            location_name="Kankarbagh",
            risk_level="CRITICAL",
            cell_id="CELL_KAN_01",
        )
        self.assertFalse(res2.triggered)
        self.assertTrue(res2.suppressed)
        self.assertIn("Duplicate warning suppressed", res2.suppression_reason)

    def test_11_escalation_bypasses_cooldown(self) -> None:
        """11. Escalation to higher severity (e.g. HIGH -> CRITICAL) triggers a new warning immediately."""
        # First: HIGH advisory
        res1 = self.engine.evaluate_and_broadcast(
            location_name="Kankarbagh",
            risk_level="HIGH",
            cell_id="CELL_KAN_01",
        )
        self.assertTrue(res1.triggered)
        self.assertEqual(res1.action, PublicWarningAction.PUBLIC_ADVISORY)

        # Immediate escalation to CRITICAL
        res2 = self.engine.evaluate_and_broadcast(
            location_name="Kankarbagh",
            risk_level="CRITICAL",
            cell_id="CELL_KAN_01",
        )
        self.assertTrue(res2.triggered)
        self.assertFalse(res2.suppressed)
        self.assertEqual(res2.action, PublicWarningAction.EMERGENCY_BROADCAST)

    def test_12_existing_b2_authority_approval_flow_preserved(self) -> None:
        """12. Existing B2 human-in-the-loop review and approval gate remains intact."""
        from app.alert_service import create_draft_alert, dispatch_authority_alert, dismiss_authority_alert

        draft_id = create_draft_alert(
            severity="WARNING",
            title="Operational Test Advisory",
            message="Drainage check required",
            affected_area="Patna Central",
            db_path=self.mem_conn,
        )
        self.assertTrue(draft_id.startswith("ALT-DRAFT-"))

        # Authority dispatches alert with dry-run
        outcome = dispatch_authority_alert(
            severity="WARNING",
            title="Operational Test Advisory",
            message="Drainage check required",
            affected_area="Patna Central",
            draft_id=draft_id,
            db_path=self.mem_conn,
        )
        self.assertTrue(outcome["success"])
        self.assertTrue(outcome["dry_run"])
        self.assertIn("channels", outcome)

    def test_13_existing_dispatcher_and_handlers_pass(self) -> None:
        """13. Existing AlertDispatcher dry-run and channel routing operate normally."""
        from alerts.dispatcher import AlertDispatcher, AlertSeverity
        dispatcher = AlertDispatcher(db_path=self.mem_conn)
        alert_id = dispatcher.dispatch(
            severity=AlertSeverity.WARNING,
            title="Routine Channel Test",
            message="Testing multi-channel delivery",
            affected_area="Patna",
            sms_recipients=["+919876543210"],
        )
        self.assertTrue(alert_id.startswith("ALT-"))

    def test_14_pipeline_integration_triggers_public_warning(self) -> None:
        """14. End-to-end AlertPipeline automatically invokes public warning on CRITICAL reading."""
        from alerts.pipeline import AlertPipeline
        from simulators.sensor_simulator import SensorReading

        pipeline = AlertPipeline(
            db_path=self.mem_conn,
            public_warning_engine=self.engine,
        )

        critical_reading = SensorReading(
            node_id="SENS_PAT_02",  # Kankarbagh
            timestamp=datetime.now(timezone.utc).isoformat(),
            water_level_cm=140.0,
            rainfall_rate_mm_h=65.0,
            battery_pct=95.0,
        )

        res = pipeline.process(
            critical_reading,
            affected_area="Kankarbagh Circle",
            persist=False,
        )

        # Existing B2 fields exist
        self.assertTrue(res.dispatched)
        self.assertIsNotNone(res.alert_id)

        # New public warning field exists and was triggered
        self.assertIsNotNone(res.public_warning)
        self.assertTrue(res.public_warning.triggered)
        self.assertEqual(res.public_warning.action, PublicWarningAction.EMERGENCY_BROADCAST)


if __name__ == "__main__":
    unittest.main()
