"""Flood-risk prediction model simulating an ML heuristic."""

import datetime
import logging
from dataclasses import dataclass
from typing import Optional

from database.db import get_db_connection, DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

@dataclass
class RiskPrediction:
    cell_id: str
    timestamp: str
    horizon: int
    level: str
    probability: float

class FloodRiskPredictor:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = db_path

    def predict(
        self,
        water_level_cm: float,
        rainfall_rate_mm_h: float,
        cell_id: str = "DEFAULT_CELL",
        persist: bool = True
    ) -> RiskPrediction:
        """
        Simulate an ML flood-risk prediction based on available features.
        In a real application, this would load a trained model (e.g. Scikit-learn, PyTorch).
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
            probability=probability
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
        except Exception as exc:
            logger.warning("Could not write risk prediction for cell %s: %s", pred.cell_id, exc)
