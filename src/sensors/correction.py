"""Sensor correction, validation, and quality assessment pipeline for Chetna B2.

Implements the deterministic B2 Day 3 pipeline:
    RAW SIMULATED SENSOR
            ↓
    SENSOR CORRECTION
            ↓
    VALIDATION
            ↓
    VALIDATED/CORRECTED READING
            ↓
    RISK / ALERT INTEGRATION
            ↓
    DATABASE

All sensor data remains explicitly SIMULATED. Simulated sensors represent
computational test nodes and are not physical municipal IoT devices.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union

from simulators.sensor_simulator import SensorReading


class ValidationStatus(str, Enum):
    """Validation lifecycle states for telemetry observations."""

    VALID = "VALID"
    CORRECTED = "CORRECTED"
    INVALID = "INVALID"
    ANOMALY = "ANOMALY"


@dataclass
class ValidatedReading(SensorReading):
    """Telemetry reading with explicit preservation of raw and corrected values.

    Inherits from SensorReading for complete backward-compatibility with existing
    alert dispatchers, risk predictors, and mapping layers.
    """

    raw_water_level_cm: Optional[float] = None
    raw_rainfall_rate_mm_h: Optional[float] = None
    validation_status: str = ValidationStatus.VALID.value
    validation_message: str = "Reading verified physically valid"
    source: str = "simulated"
    calibration_offset_cm: float = 0.0

    @property
    def is_valid(self) -> bool:
        """True if the reading is physically valid or safely corrected."""
        return self.validation_status in (
            ValidationStatus.VALID.value,
            ValidationStatus.CORRECTED.value,
        )

    @property
    def is_flood_eligible(self) -> bool:
        """True if this reading can safely contribute to physical flood risk calculation."""
        return self.is_valid and self.water_level_cm is not None

    def to_dict(self) -> dict:
        """Serialize reading including raw audit trail and validation flags."""
        d = super().to_dict()
        d.update(
            {
                "raw_water_level_cm": (
                    round(self.raw_water_level_cm, 2)
                    if self.raw_water_level_cm is not None
                    else None
                ),
                "raw_rainfall_rate_mm_h": (
                    round(self.raw_rainfall_rate_mm_h, 2)
                    if self.raw_rainfall_rate_mm_h is not None
                    else None
                ),
                "validation_status": self.validation_status,
                "validation_message": self.validation_message,
                "source": self.source,
                "calibration_offset_cm": self.calibration_offset_cm,
            }
        )
        return d


class SensorCorrector:
    """Deterministic correction and validation engine for simulated sensors.

    Physical Constants & Thresholds:
      - MIN_PHYSICAL_WATER_LEVEL: 0.0 cm (dry drain / saucer channel)
      - ZERO_DRIFT_TOLERANCE_WL: -5.0 cm (ultrasonic temperature/acoustic zero-drift)
      - ZERO_DRIFT_TOLERANCE_RAIN: -5.0 mm/h (wind flutter / gauge tip drift)
      - MAX_BASIN_WATER_LEVEL: 500.0 cm (physical ceiling of urban saucer depressions)
      - MAX_VALID_RAIN_RATE: 250.0 mm/h (extreme cloudburst rate ceiling)
      - MAX_JUMP_RATE_CM: 80.0 cm within 300s window without cloudburst
      - STUCK_SENSOR_THRESHOLD_COUNT: 5 consecutive identical readings
    """

    ZERO_DRIFT_TOLERANCE_WL: float = -5.0
    ZERO_DRIFT_TOLERANCE_RAIN: float = -5.0
    MAX_BASIN_WATER_LEVEL: float = 500.0
    MAX_VALID_RAIN_RATE: float = 250.0
    MAX_JUMP_RATE_CM: float = 80.0
    STUCK_SENSOR_THRESHOLD_COUNT: int = 5

    def __init__(self) -> None:
        # History per node_id: list of (timestamp_dt, raw_wl, corrected_wl)
        self._node_history: Dict[str, List[Tuple[datetime.datetime, Optional[float], Optional[float]]]] = {}

    def reset_history(self, node_id: Optional[str] = None) -> None:
        """Reset historical tracking state for a single node or all nodes."""
        if node_id:
            self._node_history.pop(node_id, None)
        else:
            self._node_history.clear()

    def process(
        self,
        reading: Union[SensorReading, ValidatedReading],
        calibration_offset_cm: float = 0.0,
    ) -> ValidatedReading:
        """Correct, validate, and preserve raw values of an incoming sensor reading.

        Follows a deterministic, explainable rule pipeline:
          1. Missing/NaN detection -> INVALID (never fabricate data)
          2. Explicit simulator anomaly flag -> ANOMALY
          3. Severe impossible negative water level -> INVALID
          4. Basin ceiling exceedance -> ANOMALY
          5. Minor zero-drift water level -> CORRECTED (clamp to 0.0 cm)
          6. Minor negative rainfall -> CORRECTED (clamp to 0.0 mm/h)
          7. Sensor calibration bias offset -> CORRECTED (subtract offset)
          8. Temporal impossible jump -> ANOMALY
          9. Stuck / repeated sensor check -> ANOMALY
          10. Normal physically compliant bounds -> VALID
        """
        raw_wl = getattr(reading, "raw_water_level_cm", None)
        if raw_wl is None:
            raw_wl = reading.water_level_cm

        raw_rr = getattr(reading, "raw_rainfall_rate_mm_h", None)
        if raw_rr is None:
            raw_rr = reading.rainfall_rate_mm_h

        dt = self._parse_timestamp(reading.timestamp)

        # -------------------------------------------------------------
        # 1. Missing or NaN readings -> INVALID
        # -------------------------------------------------------------
        if raw_wl is None or (isinstance(raw_wl, (int, float)) and math.isnan(raw_wl)):
            return self._record_and_return(
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                dt=dt,
                raw_wl=raw_wl,
                raw_rr=raw_rr,
                corrected_wl=None,
                corrected_rr=max(0.0, raw_rr) if raw_rr is not None and not math.isnan(raw_rr) else 0.0,
                battery_pct=reading.battery_pct,
                is_anomaly=False,
                status=ValidationStatus.INVALID.value,
                message="Missing or NaN water level observation; rejected without fabrication",
                calibration_offset=calibration_offset_cm,
            )

        raw_wl_float = float(raw_wl)
        raw_rr_float = float(raw_rr) if raw_rr is not None and not math.isnan(raw_rr) else 0.0

        # -------------------------------------------------------------
        # 2. Simulator anomaly scenario flag -> ANOMALY
        # -------------------------------------------------------------
        if getattr(reading, "is_anomaly", False):
            # Simulator flagged anomaly scenario
            corrected_rr = 0.0 if raw_rr_float < 0 else raw_rr_float
            return self._record_and_return(
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                dt=dt,
                raw_wl=raw_wl_float,
                raw_rr=raw_rr_float,
                corrected_wl=raw_wl_float if 0.0 <= raw_wl_float <= self.MAX_BASIN_WATER_LEVEL else None,
                corrected_rr=corrected_rr,
                battery_pct=reading.battery_pct,
                is_anomaly=True,
                status=ValidationStatus.ANOMALY.value,
                message="Telemetry anomaly flagged by simulator; flagged as sensor quality failure",
                calibration_offset=calibration_offset_cm,
            )

        # -------------------------------------------------------------
        # 3. Severe impossible negative water level -> INVALID
        # -------------------------------------------------------------
        if raw_wl_float < self.ZERO_DRIFT_TOLERANCE_WL:
            # e.g., -999.0 cm. Cannot be safely corrected; reject
            return self._record_and_return(
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                dt=dt,
                raw_wl=raw_wl_float,
                raw_rr=raw_rr_float,
                corrected_wl=None,
                corrected_rr=max(0.0, raw_rr_float),
                battery_pct=reading.battery_pct,
                is_anomaly=True,
                status=ValidationStatus.INVALID.value,
                message=f"Severe impossible negative water level ({raw_wl_float:.1f} cm); rejected",
                calibration_offset=calibration_offset_cm,
            )

        # -------------------------------------------------------------
        # 4. Basin ceiling exceedance (physical limit) -> ANOMALY
        # -------------------------------------------------------------
        if raw_wl_float > self.MAX_BASIN_WATER_LEVEL:
            # e.g., 850.0 cm in a 3m saucer basin (acoustic echo glitch)
            return self._record_and_return(
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                dt=dt,
                raw_wl=raw_wl_float,
                raw_rr=raw_rr_float,
                corrected_wl=None,
                corrected_rr=max(0.0, raw_rr_float),
                battery_pct=reading.battery_pct,
                is_anomaly=True,
                status=ValidationStatus.ANOMALY.value,
                message=(
                    f"Water level {raw_wl_float:.1f} cm exceeds physical saucer basin ceiling "
                    f"({self.MAX_BASIN_WATER_LEVEL:.0f} cm); flagged as acoustic echo anomaly"
                ),
                calibration_offset=calibration_offset_cm,
            )

        # -------------------------------------------------------------
        # 5. Severe negative or unphysical rainfall rate -> INVALID
        # -------------------------------------------------------------
        if raw_rr_float < self.ZERO_DRIFT_TOLERANCE_RAIN:
            return self._record_and_return(
                node_id=reading.node_id,
                timestamp=reading.timestamp,
                dt=dt,
                raw_wl=raw_wl_float,
                raw_rr=raw_rr_float,
                corrected_wl=raw_wl_float,
                corrected_rr=0.0,
                battery_pct=reading.battery_pct,
                is_anomaly=True,
                status=ValidationStatus.INVALID.value,
                message=f"Severe impossible negative rainfall rate ({raw_rr_float:.1f} mm/h)",
                calibration_offset=calibration_offset_cm,
            )

        # -------------------------------------------------------------
        # Deterministic Correction Phase
        # -------------------------------------------------------------
        corrections_applied: List[str] = []
        effective_wl = raw_wl_float
        effective_rr = raw_rr_float

        # Zero-drift water level clamping (-5.0 cm <= wl < 0.0 cm)
        if -5.0 <= effective_wl < 0.0:
            effective_wl = 0.0
            corrections_applied.append(f"clamped minor negative zero-drift ({raw_wl_float:.1f} cm -> 0.0 cm)")

        # Calibration offset adjustment
        if calibration_offset_cm != 0.0:
            effective_wl = max(0.0, effective_wl - calibration_offset_cm)
            corrections_applied.append(f"adjusted for calibration offset ({calibration_offset_cm:+.1f} cm)")

        # Zero-drift rainfall clamping (-5.0 mm/h <= rr < 0.0 mm/h)
        if -5.0 <= effective_rr < 0.0:
            effective_rr = 0.0
            corrections_applied.append(f"clamped negative rainfall flutter ({raw_rr_float:.1f} mm/h -> 0.0 mm/h)")

        # -------------------------------------------------------------
        # 6. Temporal validation (Jumps & Stuck Sensors)
        # -------------------------------------------------------------
        history = self._node_history.get(reading.node_id, [])
        if history:
            prev_dt, prev_raw_wl, prev_corr_wl = history[-1]
            if prev_dt and dt:
                delta_sec = abs((dt - prev_dt).total_seconds())
                if delta_sec <= 300.0 and prev_corr_wl is not None:
                    delta_wl = abs(effective_wl - prev_corr_wl)
                    # Rapid jump without corresponding torrential rain
                    if delta_wl > self.MAX_JUMP_RATE_CM and effective_rr < 30.0:
                        return self._record_and_return(
                            node_id=reading.node_id,
                            timestamp=reading.timestamp,
                            dt=dt,
                            raw_wl=raw_wl_float,
                            raw_rr=raw_rr_float,
                            corrected_wl=effective_wl,
                            corrected_rr=effective_rr,
                            battery_pct=reading.battery_pct,
                            is_anomaly=True,
                            status=ValidationStatus.ANOMALY.value,
                            message=(
                                f"Impossible sudden jump of {delta_wl:.1f} cm within {delta_sec:.0f}s "
                                f"without heavy rainfall (jump {prev_corr_wl:.1f} cm -> {effective_wl:.1f} cm)"
                            ),
                            calibration_offset=calibration_offset_cm,
                        )

            # Stuck sensor check: identical values across N readings
            if len(history) >= (self.STUCK_SENSOR_THRESHOLD_COUNT - 1):
                recent_wl = [h[2] for h in history[-(self.STUCK_SENSOR_THRESHOLD_COUNT - 1):]]
                if all(w is not None and abs(w - effective_wl) < 0.001 for w in recent_wl):
                    # Identical values during rainfall or extended static state
                    if effective_rr > 10.0 or len(history) >= 10:
                        return self._record_and_return(
                            node_id=reading.node_id,
                            timestamp=reading.timestamp,
                            dt=dt,
                            raw_wl=raw_wl_float,
                            raw_rr=raw_rr_float,
                            corrected_wl=effective_wl,
                            corrected_rr=effective_rr,
                            battery_pct=reading.battery_pct,
                            is_anomaly=True,
                            status=ValidationStatus.ANOMALY.value,
                            message=f"Stuck sensor detected: identical stage ({effective_wl:.1f} cm) for 5+ readings",
                            calibration_offset=calibration_offset_cm,
                        )

        # -------------------------------------------------------------
        # 7. Valid or Corrected Result
        # -------------------------------------------------------------
        if corrections_applied:
            status = ValidationStatus.CORRECTED.value
            message = "Correction applied: " + "; ".join(corrections_applied)
        else:
            status = ValidationStatus.VALID.value
            message = "Reading passed physical bounds and temporal consistency checks"

        return self._record_and_return(
            node_id=reading.node_id,
            timestamp=reading.timestamp,
            dt=dt,
            raw_wl=raw_wl_float,
            raw_rr=raw_rr_float,
            corrected_wl=round(effective_wl, 2),
            corrected_rr=round(effective_rr, 2),
            battery_pct=reading.battery_pct,
            is_anomaly=False,
            status=status,
            message=message,
            calibration_offset=calibration_offset_cm,
        )

    def process_batch(
        self,
        readings: Sequence[SensorReading],
        calibration_offset_cm: float = 0.0,
    ) -> List[ValidatedReading]:
        """Sequentially process a batch of readings, maintaining temporal state."""
        return [self.process(r, calibration_offset_cm=calibration_offset_cm) for r in readings]

    # -----------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------

    def _record_and_return(
        self,
        node_id: str,
        timestamp: str,
        dt: Optional[datetime.datetime],
        raw_wl: Optional[float],
        raw_rr: Optional[float],
        corrected_wl: Optional[float],
        corrected_rr: Optional[float],
        battery_pct: float,
        is_anomaly: bool,
        status: str,
        message: str,
        calibration_offset: float,
    ) -> ValidatedReading:
        """Update node history and construct structured ValidatedReading."""
        if dt:
            history = self._node_history.setdefault(node_id, [])
            history.append((dt, raw_wl, corrected_wl))
            if len(history) > 20:
                history.pop(0)

        return ValidatedReading(
            node_id=node_id,
            timestamp=timestamp,
            water_level_cm=corrected_wl,
            rainfall_rate_mm_h=corrected_rr if corrected_rr is not None else 0.0,
            battery_pct=battery_pct,
            is_anomaly=is_anomaly,
            raw_water_level_cm=raw_wl,
            raw_rainfall_rate_mm_h=raw_rr,
            validation_status=status,
            validation_message=message,
            source="simulated",
            calibration_offset_cm=calibration_offset,
        )

    @staticmethod
    def _parse_timestamp(ts_str: Optional[str]) -> Optional[datetime.datetime]:
        """Safely parse ISO timestamp string into datetime."""
        if not ts_str:
            return None
        try:
            return datetime.datetime.fromisoformat(ts_str)
        except Exception:
            return None


# Global singleton corrector instance for canonical processing
_GLOBAL_CORRECTOR = SensorCorrector()


def correct_and_validate_reading(
    reading: Union[SensorReading, ValidatedReading],
    calibration_offset_cm: float = 0.0,
) -> ValidatedReading:
    """Canonical function to correct and validate a single sensor reading."""
    return _GLOBAL_CORRECTOR.process(reading, calibration_offset_cm=calibration_offset_cm)


def correct_and_validate_batch(
    readings: Sequence[SensorReading],
    calibration_offset_cm: float = 0.0,
) -> List[ValidatedReading]:
    """Canonical function to correct and validate a sequence of sensor readings."""
    return _GLOBAL_CORRECTOR.process_batch(readings, calibration_offset_cm=calibration_offset_cm)
