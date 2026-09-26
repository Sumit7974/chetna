"""M1 Day 6: Failure isolation and contract validation helpers for Chetna.

Provides structured failure reporting representations and core data contract validators
for risk predictions and telemetry sensor readings.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class CellFailureRecord:
    """Structured, safe failure representation for per-cell execution issues."""
    cell_id: str
    stage: str
    error_type: str
    message: str
    recoverable: bool = True
    horizon: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_risk_prediction_contract(record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validates that a risk prediction payload strictly adheres to the core Chetna contract:
    - cell_id: non-empty string
    - timestamp: non-empty string
    - horizon: integer in (1, 3, 6)
    - level: string in ('LOW', 'MEDIUM', 'HIGH')
    - probability: float in [0.0, 1.0] without NaN or infinity
    """
    if not record.get("cell_id") or not isinstance(record["cell_id"], str):
        return False, "Invalid or missing 'cell_id': must be non-empty string"
    if not record.get("timestamp") or not isinstance(record["timestamp"], str):
        return False, "Invalid or missing 'timestamp': must be non-empty string"

    h = record.get("horizon")
    if h not in (1, 3, 6):
        return False, f"Invalid 'horizon' {h}: must be 1, 3, or 6"

    lvl = record.get("level")
    if lvl not in ("LOW", "MEDIUM", "HIGH"):
        return False, f"Invalid risk 'level' '{lvl}': must be 'LOW', 'MEDIUM', or 'HIGH'"

    prob = record.get("probability")
    if prob is None or not isinstance(prob, (int, float)):
        return False, "Invalid 'probability': must be a numeric float"
    try:
        p_val = float(prob)
        if math.isnan(p_val) or math.isinf(p_val) or not (0.0 <= p_val <= 1.0):
            return False, f"Invalid 'probability' {prob}: must be a finite float in [0.0, 1.0]"
    except Exception as exc:
        return False, f"Could not parse 'probability': {exc}"

    return True, None


def validate_sensor_reading_contract(record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validates that a telemetry sensor reading adheres to the Chetna sensor contract:
    - sensor_id / node_id: non-empty string
    - timestamp: non-empty string
    - level_cm / water_level_cm: non-negative finite numeric float
    - status: string in ('ACTIVE', 'MAINTENANCE', 'OFFLINE')
    - source: string descriptor
    """
    sid = record.get("sensor_id") or record.get("node_id")
    if not sid or not isinstance(sid, str):
        return False, "Invalid or missing 'sensor_id': must be non-empty string"
    if not record.get("timestamp") or not isinstance(record["timestamp"], str):
        return False, "Invalid or missing 'timestamp': must be non-empty string"

    lvl = record.get("level_cm") if "level_cm" in record else record.get("water_level_cm")
    if lvl is not None:
        try:
            l_val = float(lvl)
            if math.isnan(l_val) or math.isinf(l_val) or l_val < 0.0:
                return False, f"Invalid water level {lvl}: must be non-negative finite float"
        except Exception as exc:
            return False, f"Could not parse water level: {exc}"

    status = record.get("status", "ACTIVE")
    if status.upper() not in ("ACTIVE", "MAINTENANCE", "OFFLINE"):
        return False, f"Invalid sensor status '{status}': must be ACTIVE, MAINTENANCE, or OFFLINE"

    return True, None
