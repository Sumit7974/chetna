"""Heuristic flood-risk prediction model for Chetna."""

from __future__ import annotations

import datetime
import json
import logging
import math
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
    explanation: Optional[Dict[str, Any]] = None
    mode: str = "heuristic"


class FloodRiskPredictor:
    def __init__(
        self,
        db_path: Any = DEFAULT_DB_PATH,
        mode: str = "heuristic",
        model_dir: Optional[Any] = None,
    ):
        self.db_path = db_path
        self.mode = mode.lower()
        self._ml_predictor: Optional[Any] = None
        if self.mode == "ml":
            from src.model.ml_predictor import XGBoostRiskPredictor
            self._ml_predictor = XGBoostRiskPredictor(db_path=db_path, model_dir=model_dir)

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
        wl = float(water_level_cm) if (water_level_cm is not None and not math.isnan(water_level_cm) and not math.isinf(water_level_cm)) else 0.0
        rr = float(rainfall_rate_mm_h) if (rainfall_rate_mm_h is not None and not math.isnan(rainfall_rate_mm_h) and not math.isinf(rainfall_rate_mm_h)) else 0.0

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
            persisted=False,
            mode="heuristic",
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
        explain: bool = False,
    ) -> RiskPrediction:
        """
        Deterministic, horizon-aware flood-risk prediction based on forecast rainfall and static vulnerability.
        """
        h = int(horizon)
        if h not in (1, 3, 6):
            raise ValueError(f"Invalid horizon: {horizon}. Expected 1, 3, or 6.")

        if self.mode == "ml" and self._ml_predictor is not None:
            return self._ml_predictor.predict_from_forecast(
                rainfall_mm=rainfall_mm,
                cell_id=cell_id,
                horizon=h,
                vulnerability=vulnerability,
                timestamp=timestamp,
                persist=persist,
                explain=explain,
            )

        if rainfall_mm is None:
            r = 0.0
        else:
            try:
                r_val = float(rainfall_mm)
                if math.isnan(r_val) or math.isinf(r_val):
                    raise ValueError(f"Rainfall must be a finite number: got {rainfall_mm}")
                r = max(0.0, r_val)
            except (ValueError, TypeError) as exc:
                if isinstance(exc, ValueError) and "Rainfall must be a finite number" in str(exc):
                    raise
                raise ValueError(f"Invalid rainfall value: {rainfall_mm}") from exc

        # Baseline static vulnerability: clamp to [0.0, 1.0], default 0.50 if not provided or NaN
        if vulnerability is not None:
            try:
                v_val = float(vulnerability)
                if math.isnan(v_val) or math.isinf(v_val):
                    v = 0.50
                else:
                    v = max(0.0, min(1.0, v_val))
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

        # Build optional heuristic explanation if requested
        explanation_dict: Optional[Dict[str, Any]] = None
        if explain:
            from src.model.ml_explainability import generate_human_readable_summary
            summary = generate_human_readable_summary(
                risk_level=level,
                probability=prob,
                horizon=h,
                rainfall_mm=r,
                vulnerability_score=v,
                cell_id=str(cell_id),
            )
            explanation_dict = {
                "cell_id": str(cell_id),
                "timestamp": str(ts),
                "horizon": h,
                "risk_level": level,
                "probability": prob,
                "top_factors": [
                    {
                        "feature": "rainfall_mm",
                        "display_name": "Forecast Rainfall",
                        "category": "dynamic",
                        "importance": 0.65,
                        "direction": "increases_risk" if s_rain >= 0.50 else "decreases_risk",
                        "value": r,
                        "unit": "mm",
                        "description": "Cumulative precipitation forecast for horizon window",
                    },
                    {
                        "feature": "vulnerability_score",
                        "display_name": "Static Vulnerability",
                        "category": "static",
                        "importance": 0.35,
                        "direction": "increases_risk" if v >= 0.50 else "decreases_risk",
                        "value": v,
                        "unit": "score",
                        "description": "Static terrain and environmental vulnerability score",
                    },
                ],
                "static_factors": {"vulnerability_score": v},
                "dynamic_factors": {"rainfall_mm": r, "horizon_hours": h},
                "hotspot_context": {"critical_rainfall_threshold_mm": r_crit},
                "summary": summary,
                "methodology": "heuristic_linear_combination",
                "disclaimer": "Heuristic model based on linear precipitation and terrain vulnerability combination.",
            }

        pred = RiskPrediction(
            cell_id=str(cell_id),
            timestamp=str(ts),
            horizon=h,
            level=level,
            probability=prob,
            persisted=False,
            explanation=explanation_dict,
            mode="heuristic",
        )

        if persist:
            self._save_prediction(pred)

        return pred

    def _save_prediction(self, pred: RiskPrediction) -> None:
        """Store prediction result in the database."""
        expl_json = json.dumps(pred.explanation) if pred.explanation is not None else None
        try:
            with get_db_connection(self.db_path) as conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (pred.cell_id, pred.timestamp, pred.horizon, pred.level, pred.probability, expl_json)
                    )
                except Exception:
                    # Fallback for databases without explanation column
                    conn.execute(
                        """
                        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability)
                        VALUES (?, ?, ?, ?, ?)
                        """,
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
        try:
            with get_db_connection(self.db_path) as conn:
                try:
                    records_with_expl = [
                        (p.cell_id, p.timestamp, p.horizon, p.level, p.probability, json.dumps(p.explanation) if p.explanation is not None else None)
                        for p in preds
                    ]
                    conn.executemany(
                        """
                        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        records_with_expl
                    )
                except Exception:
                    records_legacy = [
                        (p.cell_id, p.timestamp, p.horizon, p.level, p.probability)
                        for p in preds
                    ]
                    conn.executemany(
                        """
                        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        records_legacy
                    )
            for p in preds:
                p.persisted = True
            return len(preds)
        except Exception as exc:
            logger.error("Could not write batch risk predictions (%d records): %s", len(preds), exc)
            for p in preds:
                p.persisted = False
            return 0
