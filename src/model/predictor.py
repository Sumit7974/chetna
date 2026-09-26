"""Heuristic flood-risk prediction model for Chetna."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from database.db import DEFAULT_DB_PATH, get_db_connection

logger = logging.getLogger(__name__)

CREATE_RISK_PREDICTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS risk_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    horizon INTEGER NOT NULL,
    level TEXT NOT NULL,
    probability REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Thresholds for heuristic rainfall normalization (in mm for each horizon)
# Derived from Chennai urban drainage saturation thresholds
HORIZON_CRITICAL_RAINFALL: Dict[int, float] = {
    1: 50.0,   # 50 mm in 1 hour (intense cloudburst / flash flood threshold)
    3: 80.0,   # 80 mm in 3 hours (drainage network capacity threshold)
    6: 120.0,  # 120 mm in 6 hours (widespread urban inundation threshold)
}


@dataclass
class RiskPrediction:
    cell_id: str
    timestamp: str
    horizon: int
    level: str
    probability: float
    persisted: bool = False


class FloodRiskPredictor:
    def __init__(self, db_path: Any = DEFAULT_DB_PATH):
        self.db_path = db_path

    def predict(
        self,
        water_level_cm: float,
        rainfall_rate_mm_h: float,
        cell_id: str = "DEFAULT_CELL",
        persist: bool = True
    ) -> RiskPrediction:
        """
        Heuristic flood-risk prediction based on sensor water level and rain rate.
        Preserved for B2 Day 3/Day 4 telemetry operations (horizon=1).
        """
        wl = water_level_cm or 0.0
        rr = rainfall_rate_mm_h or 0.0

        if wl > 100 or rr > 50:
            probability = 0.85
            level = "HIGH"
        elif wl > 60 or rr > 20:
            probability = 0.55
            level = "MEDIUM"
        else:
            probability = 0.15
            level = "LOW"
            
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        pred = RiskPrediction(
            cell_id=cell_id,
            timestamp=now,
            horizon=1,
            level=level,
            probability=probability,
            persisted=False
        )
        
        if persist:
            self._save_prediction(pred)
            
        return pred

    def predict_from_forecast(
        self,
        rainfall_mm: float,
        cell_id: str,
        horizon: int,
        vulnerability: Optional[float] = None,
        timestamp: Optional[str] = None,
        persist: bool = True,
    ) -> RiskPrediction:
        """
        Deterministic, horizon-aware flood-risk prediction based on forecast rainfall and static vulnerability.

        Combines forecast rainfall (rain_1h, rain_3h, rain_6h) with the static vulnerability
        score of the cell into a bounded probability and 3-tier risk classification.

        Formula:
            rainfall_factor = min(1.0, max(0.0, rainfall_mm / critical_rainfall(horizon)))
            vulnerability_factor = clamp(vulnerability, 0.0, 1.0) or default (0.50)
            probability = 0.65 * rainfall_factor + 0.35 * vulnerability_factor

        Classification:
            - HIGH:   probability >= 0.70
            - MEDIUM: 0.40 <= probability < 0.70
            - LOW:    probability < 0.40
        """
        h = int(horizon)
        if h not in (1, 3, 6):
            raise ValueError(f"Invalid horizon: {horizon}. Expected 1, 3, or 6.")

        r = max(0.0, float(rainfall_mm) if rainfall_mm is not None else 0.0)

        # Baseline static vulnerability: clamp to [0.0, 1.0], default 0.50 if not provided
        if vulnerability is not None:
            try:
                v = max(0.0, min(1.0, float(vulnerability)))
            except (ValueError, TypeError):
                v = 0.50
        else:
            v = 0.50

        # Critical cumulative rainfall threshold for Chennai urban flooding
        r_crit = HORIZON_CRITICAL_RAINFALL.get(h, 50.0 + (h - 1) * 14.0)
        s_rain = min(1.0, r / r_crit)

        # Combined dynamic probability (65% weather forcing, 35% static terrain vulnerability)
        prob = 0.65 * s_rain + 0.35 * v
        prob = max(0.0, min(1.0, round(float(prob), 4)))

        # Risk level categorization
        if prob >= 0.70:
            level = "HIGH"
        elif prob >= 0.40:
            level = "MEDIUM"
        else:
            level = "LOW"

        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        pred = RiskPrediction(
            cell_id=str(cell_id),
            timestamp=str(ts),
            horizon=h,
            level=level,
            probability=prob,
            persisted=False,
        )

        if persist:
            self._save_prediction(pred)

        return pred

    def _save_prediction(self, pred: RiskPrediction) -> None:
        """Store prediction result in the database."""
        sql = """
        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability)
        VALUES (?, ?, ?, ?, ?)
        """
        try:
            with get_db_connection(self.db_path) as conn:
                conn.execute(
                    sql,
                    (pred.cell_id, pred.timestamp, pred.horizon, pred.level, pred.probability)
                )
            pred.persisted = True
        except Exception as exc:
            logger.error("Could not write risk prediction for cell %s: %s", pred.cell_id, exc)
            pred.persisted = False

    def save_predictions_batch(self, preds: List[RiskPrediction]) -> int:
        """Store multiple prediction results in the database in a single transaction."""
        if not preds:
            return 0
        sql = """
        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability)
        VALUES (?, ?, ?, ?, ?)
        """
        records = [
            (p.cell_id, p.timestamp, p.horizon, p.level, p.probability)
            for p in preds
        ]
        try:
            with get_db_connection(self.db_path) as conn:
                conn.executemany(sql, records)
            for p in preds:
                p.persisted = True
            return len(records)
        except Exception as exc:
            logger.error("Could not write batch risk predictions (%d records): %s", len(preds), exc)
            for p in preds:
                p.persisted = False
            return 0
