"""Public warning threshold policy configuration for Chetna.

Evaluates whether a detected risk state warrants:
- An automated geo-targeted emergency warning (CRITICAL / SEVERE / EMERGENCY)
- A localized public advisory (HIGH)
- No public warning (MEDIUM / LOW / INFO)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set


class PublicWarningAction(str, Enum):
    """Categorization of public warning action."""
    EMERGENCY_BROADCAST = "EMERGENCY_BROADCAST"
    PUBLIC_ADVISORY = "PUBLIC_ADVISORY"
    NONE = "NONE"


@dataclass
class PublicWarningPolicy:
    """Configurable policy thresholds for public emergency broadcast trigger."""

    emergency_severities: Set[str] = field(
        default_factory=lambda: {"CRITICAL", "SEVERE", "EMERGENCY"}
    )
    advisory_severities: Set[str] = field(
        default_factory=lambda: {"HIGH"}
    )
    critical_probability_threshold: float = 0.70
    high_probability_threshold: float = 0.50

    def evaluate(
        self,
        risk_level: str,
        risk_score: Optional[float] = None,
    ) -> PublicWarningAction:
        """Evaluate the public warning action for a given risk level and optional score."""
        norm_level = str(risk_level or "LOW").upper()

        # Check if severity or score indicates critical emergency broadcast
        if norm_level in self.emergency_severities:
            return PublicWarningAction.EMERGENCY_BROADCAST
        if risk_score is not None and risk_score >= self.critical_probability_threshold:
            return PublicWarningAction.EMERGENCY_BROADCAST

        # Check if severity indicates advisory (HIGH)
        if norm_level in self.advisory_severities:
            return PublicWarningAction.PUBLIC_ADVISORY

        # Conditions normal, low, or medium: no emergency broadcast
        return PublicWarningAction.NONE

    def should_broadcast_emergency(
        self,
        risk_level: str,
        risk_score: Optional[float] = None,
    ) -> bool:
        """Check if risk state warrants an automated emergency broadcast."""
        return self.evaluate(risk_level, risk_score) == PublicWarningAction.EMERGENCY_BROADCAST

    def should_issue_advisory(
        self,
        risk_level: str,
        risk_score: Optional[float] = None,
    ) -> bool:
        """Check if risk state warrants a localized public advisory."""
        return self.evaluate(risk_level, risk_score) == PublicWarningAction.PUBLIC_ADVISORY


_default_policy = PublicWarningPolicy()


def evaluate_public_warning_policy(
    risk_level: str,
    risk_score: Optional[float] = None,
    policy: Optional[PublicWarningPolicy] = None,
) -> PublicWarningAction:
    """Convenience evaluator using default or custom policy."""
    active_policy = policy or _default_policy
    return active_policy.evaluate(risk_level, risk_score)
