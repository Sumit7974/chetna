"""M1 Day 3: Multi-Horizon XGBoost Flood-Risk Predictor for Chetna.

Predicts dynamic flood risk probabilities across horizons (+1h, +3h, +6h) using
XGBoost models trained on calibrated proxy development datasets.

Preserves the standard Chetna RiskPrediction contract and SQLite persistence.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import xgboost as xgb

from database.db import DEFAULT_DB_PATH, get_db_connection
from src.model.ml_dataset import (
    FEATURE_COLUMNS,
    load_static_cell_catalog,
)
from src.model.ml_explainability import (
    PredictionExplanation,
    explain_prediction,
)
from src.model.predictor import FloodRiskPredictor, RiskPrediction

logger = logging.getLogger(__name__)

DEFAULT_MODELS_DIR = Path("data/m1/models")


class XGBoostFloodModel:
    """Manages horizon-specific XGBoost models for +1h, +3h, and +6h flood risk."""

    def __init__(
        self,
        random_state: int = 42,
        n_estimators: int = 100,
        max_depth: int = 4,
        learning_rate: float = 0.08,
    ) -> None:
        self.random_state = random_state
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.models: Dict[int, xgb.XGBClassifier] = {}
        self.metadata: Dict[str, Any] = {
            "version": "1.0",
            "model_type": "xgboost",
            "random_state": random_state,
            "feature_columns": FEATURE_COLUMNS,
            "horizons": [1, 3, 6],
            "trained_at": None,
            "horizon_metrics": {},
        }

    @property
    def is_trained(self) -> bool:
        """Returns True if models are available for all required horizons (1, 3, 6)."""
        return all(h in self.models for h in (1, 3, 6))

    def train_horizon(
        self,
        horizon: int,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
    ) -> xgb.XGBClassifier:
        """Trains an XGBoost classifier for a single horizon."""
        h = int(horizon)
        if h not in (1, 3, 6):
            raise ValueError(f"Unsupported horizon: {horizon}. Expected 1, 3, or 6.")

        clf = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            eval_metric="logloss",
            tree_method="hist",
        )

        eval_set = [(X_val, y_val)] if (X_val is not None and y_val is not None) else None
        clf.fit(X_train, y_train, eval_set=eval_set, verbose=False)
        self.models[h] = clf
        return clf

    def predict_proba(self, horizon: int, X: np.ndarray) -> np.ndarray:
        """Predicts positive class probabilities in [0.0, 1.0] for the specified horizon."""
        h = int(horizon)
        if h not in self.models:
            raise RuntimeError(f"XGBoost model for horizon +{h}h has not been trained or loaded.")

        clf = self.models[h]
        if X.ndim == 1:
            X = X.reshape(1, -1)

        probs = clf.predict_proba(X)[:, 1]
        return np.clip(probs, 0.0, 1.0)

    def save(self, model_dir: Union[str, Path]) -> None:
        """Serializes trained horizon models and metadata to disk."""
        target_dir = Path(model_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        for h, model in self.models.items():
            model_path = target_dir / f"model_h{h}.json"
            model.save_model(str(model_path))

        meta_path = target_dir / "model_metadata.json"
        self.metadata["trained_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

        logger.info("Saved XGBoost models and metadata to %s", target_dir)

    def load(self, model_dir: Union[str, Path]) -> None:
        """Loads serialized XGBoost models and metadata from disk."""
        source_dir = Path(model_dir)
        if not source_dir.is_dir():
            raise FileNotFoundError(f"Model directory not found at {source_dir}")

        meta_path = source_dir / "model_metadata.json"
        if meta_path.is_file():
            with open(meta_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)

        for h in (1, 3, 6):
            model_file = source_dir / f"model_h{h}.json"
            if not model_file.is_file():
                raise FileNotFoundError(f"Model file {model_file} not found for horizon +{h}h")
            clf = xgb.XGBClassifier()
            clf.load_model(str(model_file))
            self.models[h] = clf

        logger.info("Loaded XGBoost models for horizons %s from %s", list(self.models.keys()), source_dir)

    def get_feature_importances(self, horizon: int) -> Dict[str, float]:
        """Returns feature importances for a specific horizon model."""
        h = int(horizon)
        if h not in self.models:
            return {}
        importances = self.models[h].feature_importances_
        return {
            col: round(float(imp), 4)
            for col, imp in zip(FEATURE_COLUMNS, importances)
        }


class XGBoostRiskPredictor:
    """Production flood-risk predictor using calibrated multi-horizon XGBoost models.

    Conforms to the standard Chetna RiskPrediction API and SQLite database contract.
    Provides automatic fallback to heuristic prediction if ML models are unavailable.
    """

    def __init__(
        self,
        db_path: Any = DEFAULT_DB_PATH,
        model_dir: Optional[Union[str, Path]] = DEFAULT_MODELS_DIR,
        static_risk_file: Optional[Union[str, Path]] = None,
        allow_fallback: bool = True,
    ) -> None:
        self.db_path = db_path
        self.model_dir = Path(model_dir) if model_dir else None
        self.allow_fallback = allow_fallback
        self.model = XGBoostFloodModel()
        self.heuristic_predictor = FloodRiskPredictor(db_path=db_path)
        self.cell_catalog = load_static_cell_catalog(static_risk_file)

        # Attempt automatic model loading if model_dir exists
        if self.model_dir and (self.model_dir / "model_h1.json").exists():
            try:
                self.model.load(self.model_dir)
            except Exception as exc:
                logger.warning("Could not auto-load XGBoost models from %s: %s", self.model_dir, exc)

    def build_feature_dict(
        self,
        rainfall_mm: float,
        cell_id: str,
        horizon: int,
        vulnerability: Optional[float] = None,
        rain_past_24h: float = 0.0,
    ) -> Dict[str, float]:
        """Constructs an aligned feature dictionary for the given cell and horizon."""
        cid = str(cell_id)
        static_info = self.cell_catalog.get(cid, {})

        try:
            elev = float(static_info.get("elevation", 10.0))
            if math.isnan(elev) or math.isinf(elev): elev = 10.0
        except (ValueError, TypeError):
            elev = 10.0

        try:
            slp = float(static_info.get("slope", 1.0))
            if math.isnan(slp) or math.isinf(slp): slp = 1.0
        except (ValueError, TypeError):
            slp = 1.0

        try:
            flow_acc = float(static_info.get("flow_accumulation", 1000.0))
            if math.isnan(flow_acc) or math.isinf(flow_acc): flow_acc = 1000.0
        except (ValueError, TypeError):
            flow_acc = 1000.0

        try:
            imp = float(static_info.get("imperviousness", 0.60))
            if math.isnan(imp) or math.isinf(imp): imp = 0.60
        except (ValueError, TypeError):
            imp = 0.60

        # Vulnerability passed explicitly overrides catalog
        if vulnerability is not None:
            try:
                v_val = float(vulnerability)
                if math.isnan(v_val) or math.isinf(v_val):
                    v_score = static_info.get("vulnerability_score", 0.50)
                else:
                    v_score = max(0.0, min(1.0, v_val))
            except (ValueError, TypeError):
                v_score = static_info.get("vulnerability_score", 0.50)
        else:
            v_score = static_info.get("vulnerability_score", 0.50)

        if math.isnan(v_score) or math.isinf(v_score):
            v_score = 0.50

        try:
            rp24 = float(rain_past_24h)
            if math.isnan(rp24) or math.isinf(rp24): rp24 = 0.0
            rp24 = max(0.0, rp24)
        except (ValueError, TypeError):
            rp24 = 0.0

        # Known hotspot cell flag (supports Patna pilot and historical codes)
        hotspot_codes = [
            "RAJ", "KAN", "SAI", "BOR", "BAI", "GAN", "PAT", "ANI", "DIG", "BAZ",
            "VEL", "MAD", "MUD", "TNG", "PUL", "VYA", "PRM", "KYM", "MNP", "PLK",
        ]
        is_hotspot = 1.0 if (
            any(h_code in cid for h_code in hotspot_codes)
            or static_info.get("is_hotspot", 0.0) >= 0.5
        ) else 0.0

        return {
            "rainfall_mm": float(rainfall_mm),
            "rain_past_24h": float(rp24),
            "elevation": float(elev),
            "slope": float(slp),
            "flow_accumulation": float(flow_acc),
            "imperviousness": float(imp),
            "vulnerability_score": float(v_score),
            "is_hotspot": float(is_hotspot),
        }

    def build_feature_vector(
        self,
        rainfall_mm: float,
        cell_id: str,
        horizon: int,
        vulnerability: Optional[float] = None,
        rain_past_24h: float = 0.0,
    ) -> np.ndarray:
        """Constructs an aligned feature vector for the given cell and horizon."""
        fdict = self.build_feature_dict(
            rainfall_mm=rainfall_mm,
            cell_id=cell_id,
            horizon=horizon,
            vulnerability=vulnerability,
            rain_past_24h=rain_past_24h,
        )
        return np.array([fdict[col] for col in FEATURE_COLUMNS], dtype=np.float32)

    def explain_forecast(
        self,
        rainfall_mm: float,
        cell_id: str,
        horizon: int,
        vulnerability: Optional[float] = None,
        timestamp: Optional[str] = None,
        rain_past_24h: float = 0.0,
    ) -> PredictionExplanation:
        """Generates a comprehensive PredictionExplanation for a specific cell and horizon."""
        h = int(horizon)
        if h not in (1, 3, 6):
            raise ValueError(f"Invalid horizon: {horizon}. Expected 1, 3, or 6.")

        r = max(0.0, float(rainfall_mm) if rainfall_mm is not None else 0.0)
        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()

        fdict = self.build_feature_dict(
            rainfall_mm=r,
            cell_id=cell_id,
            horizon=h,
            vulnerability=vulnerability,
            rain_past_24h=rain_past_24h,
        )
        importances = self.model.get_feature_importances(h) if self.model.is_trained else {}

        # Compute probability
        if self.model.is_trained:
            feat_vec = np.array([fdict[col] for col in FEATURE_COLUMNS], dtype=np.float32)
            prob = float(self.model.predict_proba(horizon=h, X=feat_vec)[0])
        else:
            v_score = fdict["vulnerability_score"]
            r_crit = 50.0 + (h - 1) * 14.0
            prob = 0.65 * min(1.0, r / r_crit) + 0.35 * v_score

        prob = max(0.0, min(1.0, round(prob, 4)))
        if prob >= 0.70:
            level = "HIGH"
        elif prob >= 0.40:
            level = "MEDIUM"
        else:
            level = "LOW"

        return explain_prediction(
            feature_dict=fdict,
            feature_importances=importances,
            risk_level=level,
            probability=prob,
            horizon=h,
            cell_id=str(cell_id),
            timestamp=ts,
        )

    def predict_with_explanation(
        self,
        rainfall_mm: float,
        cell_id: str,
        horizon: int,
        vulnerability: Optional[float] = None,
        timestamp: Optional[str] = None,
        rain_past_24h: float = 0.0,
        persist: bool = True,
    ) -> Tuple[RiskPrediction, PredictionExplanation]:
        """Convenience method returning both RiskPrediction dataclass and PredictionExplanation."""
        h = int(horizon)
        r = max(0.0, float(rainfall_mm) if rainfall_mm is not None else 0.0)
        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()

        expl = self.explain_forecast(
            rainfall_mm=r,
            cell_id=cell_id,
            horizon=h,
            vulnerability=vulnerability,
            timestamp=ts,
            rain_past_24h=rain_past_24h,
        )
        pred = RiskPrediction(
            cell_id=str(cell_id),
            timestamp=str(ts),
            horizon=h,
            level=expl.risk_level,
            probability=expl.probability,
            persisted=False,
            explanation=expl.to_dict(),
            mode="ml" if self.model.is_trained else "heuristic_fallback",
        )
        if persist:
            self._save_prediction(pred)
        return pred, expl

    def predict_from_forecast(
        self,
        rainfall_mm: float,
        cell_id: str,
        horizon: int,
        vulnerability: Optional[float] = None,
        timestamp: Optional[str] = None,
        rain_past_24h: float = 0.0,
        persist: bool = True,
        explain: bool = False,
    ) -> RiskPrediction:
        """Generates ML flood-risk prediction for a cell at a specific horizon.

        Args:
            rainfall_mm: Cumulative rainfall for the forecast horizon (+1h, +3h, +6h).
            cell_id: Grid cell identifier.
            horizon: Forecast horizon (1, 3, or 6).
            vulnerability: Optional static terrain vulnerability override.
            timestamp: Prediction reference timestamp.
            rain_past_24h: Antecedent 24h precipitation (defaults to 0.0).
            persist: Whether to save prediction to SQLite 'risk_predictions' table.
            explain: Whether to compute and attach explainability metadata.

        Returns:
            RiskPrediction dataclass adhering to Chetna contract.
        """
        h = int(horizon)
        if h not in (1, 3, 6):
            raise ValueError(f"Invalid horizon: {horizon}. Expected 1, 3, or 6.")

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

        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()

        # If models are not trained/loaded, use fallback or raise error
        if not self.model.is_trained:
            if self.allow_fallback:
                logger.info("XGBoost models not loaded; falling back to heuristic predictor for cell %s", cell_id)
                fallback_pred = self.heuristic_predictor.predict_from_forecast(
                    rainfall_mm=r,
                    cell_id=cell_id,
                    horizon=h,
                    vulnerability=vulnerability,
                    timestamp=ts,
                    persist=persist,
                    explain=explain,
                )
                fallback_pred.mode = "heuristic_fallback"
                if fallback_pred.explanation is not None:
                    fallback_pred.explanation["prediction_mode"] = "heuristic_fallback"
                    fallback_pred.explanation["fallback_used"] = True
                return fallback_pred
            else:
                raise RuntimeError("XGBoost models are not loaded and fallback is disabled.")

        # Build feature vector and run inference
        feat = self.build_feature_vector(
            rainfall_mm=r,
            cell_id=cell_id,
            horizon=h,
            vulnerability=vulnerability,
            rain_past_24h=rain_past_24h,
        )

        prob = float(self.model.predict_proba(horizon=h, X=feat)[0])
        prob = max(0.0, min(1.0, round(prob, 4)))

        # 3-tier risk classification matching framework contract
        if prob >= 0.70:
            level = "HIGH"
        elif prob >= 0.40:
            level = "MEDIUM"
        else:
            level = "LOW"

        explanation_dict: Optional[Dict[str, Any]] = None
        if explain:
            expl_obj = self.explain_forecast(
                rainfall_mm=r,
                cell_id=cell_id,
                horizon=h,
                vulnerability=vulnerability,
                timestamp=ts,
                rain_past_24h=rain_past_24h,
            )
            explanation_dict = expl_obj.to_dict()

        pred = RiskPrediction(
            cell_id=str(cell_id),
            timestamp=str(ts),
            horizon=h,
            level=level,
            probability=prob,
            persisted=False,
            explanation=explanation_dict,
            mode="ml",
        )

        if persist:
            self._save_prediction(pred)

        return pred

    def _save_prediction(self, pred: RiskPrediction) -> None:
        """Stores a single prediction result in the database."""
        expl_json = json.dumps(pred.explanation) if pred.explanation is not None else None
        try:
            with get_db_connection(self.db_path) as conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (pred.cell_id, pred.timestamp, pred.horizon, pred.level, pred.probability, expl_json),
                    )
                except Exception:
                    # Fallback for databases without explanation column
                    conn.execute(
                        """
                        INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (pred.cell_id, pred.timestamp, pred.horizon, pred.level, pred.probability),
                    )
            pred.persisted = True
        except Exception as exc:
            logger.error("Could not write ML risk prediction for cell %s: %s", pred.cell_id, exc)
            pred.persisted = False

    def save_predictions_batch(self, preds: List[RiskPrediction]) -> int:
        """Stores multiple prediction results in the database in a single transaction."""
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
