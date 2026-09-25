"""Tests for alert deduplication / cooldown (alerts/cooldown.py)."""

from __future__ import annotations

import datetime
import unittest

from alerts.cooldown import AlertCooldown
from alerts.dispatcher import AlertSeverity


class TestAlertCooldown(unittest.TestCase):
    """Test suite for AlertCooldown deduplication logic."""

    def setUp(self) -> None:
        self.cooldown = AlertCooldown(cooldown_seconds=300)

    # ------------------------------------------------------------------
    # Basic send / suppress
    # ------------------------------------------------------------------
    def test_first_alert_always_sends(self) -> None:
        """No prior state: first alert for any severity must be forwarded."""
        for sev in AlertSeverity:
            fresh = AlertCooldown(cooldown_seconds=300)
            self.assertTrue(fresh.should_send("NODE_01", sev))

    def test_same_severity_suppressed_within_cooldown(self) -> None:
        """Same severity repeated within cooldown window -> suppress."""
        self.cooldown.record("NODE_01", AlertSeverity.WARNING)
        self.assertFalse(self.cooldown.should_send("NODE_01", AlertSeverity.WARNING))

    def test_lower_severity_suppressed_within_cooldown(self) -> None:
        """Lower severity after higher -> suppress (e.g., CRITICAL sent, then WARNING)."""
        self.cooldown.record("NODE_01", AlertSeverity.CRITICAL)
        self.assertFalse(self.cooldown.should_send("NODE_01", AlertSeverity.WARNING))

    # ------------------------------------------------------------------
    # Escalation always sends
    # ------------------------------------------------------------------
    def test_escalation_from_info_to_warning_is_allowed(self) -> None:
        """Escalation from INFO -> WARNING must bypass cooldown."""
        self.cooldown.record("NODE_01", AlertSeverity.INFO)
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.WARNING))

    def test_escalation_from_warning_to_critical_is_allowed(self) -> None:
        self.cooldown.record("NODE_01", AlertSeverity.WARNING)
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.CRITICAL))

    def test_escalation_from_warning_to_emergency_is_allowed(self) -> None:
        self.cooldown.record("NODE_01", AlertSeverity.WARNING)
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.EMERGENCY))

    def test_escalation_from_critical_to_emergency_is_allowed(self) -> None:
        self.cooldown.record("NODE_01", AlertSeverity.CRITICAL)
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.EMERGENCY))

    # ------------------------------------------------------------------
    # Node isolation
    # ------------------------------------------------------------------
    def test_different_nodes_are_independent(self) -> None:
        """Cooldown for one node must not affect a different node."""
        self.cooldown.record("NODE_01", AlertSeverity.CRITICAL)
        # NODE_02 has no entry; should always send
        self.assertTrue(self.cooldown.should_send("NODE_02", AlertSeverity.CRITICAL))

    def test_same_severity_suppressed_on_same_node_not_other(self) -> None:
        self.cooldown.record("NODE_01", AlertSeverity.WARNING)
        self.assertFalse(self.cooldown.should_send("NODE_01", AlertSeverity.WARNING))
        self.assertTrue(self.cooldown.should_send("NODE_02", AlertSeverity.WARNING))

    # ------------------------------------------------------------------
    # After cooldown expires (simulated via expired entry)
    # ------------------------------------------------------------------
    def test_expired_cooldown_allows_same_severity(self) -> None:
        """After cooldown expires, same severity should be allowed again."""
        # Inject a past entry simulating expiry
        import datetime as dt
        from alerts.cooldown import _CooldownEntry
        expired_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=600)
        self.cooldown._state["NODE_01"] = _CooldownEntry(
            severity=AlertSeverity.WARNING,
            sent_at=expired_time,
        )
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.WARNING))

    # ------------------------------------------------------------------
    # Reset / clear
    # ------------------------------------------------------------------
    def test_reset_clears_specific_node(self) -> None:
        self.cooldown.record("NODE_01", AlertSeverity.CRITICAL)
        self.cooldown.reset("NODE_01")
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.CRITICAL))

    def test_clear_all_resets_entire_state(self) -> None:
        self.cooldown.record("NODE_01", AlertSeverity.CRITICAL)
        self.cooldown.record("NODE_02", AlertSeverity.WARNING)
        self.cooldown.clear_all()
        self.assertTrue(self.cooldown.should_send("NODE_01", AlertSeverity.CRITICAL))
        self.assertTrue(self.cooldown.should_send("NODE_02", AlertSeverity.WARNING))
