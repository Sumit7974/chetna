"""Automated tests for Chetna M1 Day 4: Model Explainability and Integration.

Verifies:
1. Explainability layer generates valid structured explanations for ML predictions.
2. Horizon-aware explanations (+1h, +3h, +6h) without future temporal leakage.
3. Top contributing factors correspond to model features with normalized importances.
4. Static vs. dynamic factor decomposition and hotspot context.
5. Deterministic, non-exaggerated human-readable summary generation across risk tiers.
6. Scientific non-causal disclaimer preservation.
7. Prediction API backward compatibility (optional explanation attachment).
8. Heuristic mode behavior preservation and heuristic explainability support.
9. SQLite database persistence with optional explanation JSON column.
10. End-to-end pipeline execution with explanation generation.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database.db import get_db_connection, init_db
from src.model.ml_explainability import (
    SCIENTIFIC_DISCLAIMER,
    FactorContribution,
    PredictionExplanation,
    explain_prediction,
    generate_human_readable_summary,
)
from src.model.ml_predictor import XGBoostRiskPredictor
from src.model.predictor import FloodRiskPredictor, RiskPrediction
from src.pipeline import run_pipeline


class TestM1Day4Explainability(unittest.TestCase):
    """Test suite for M1 Day 4 explainability functions, data models, and integrations."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.predictor = XGBoostRiskPredictor(model_dir="data/m1/models")

    def test_explain_prediction_structure_and_disclaimer(self) -> None:
        """Verifies explain_prediction generates the required contract structure and disclaimer."""
        feature_dict = {
            "rainfall_mm": 50.0,
            "rain_past_24h": 40.0,
            "elevation": 6.5,
            "slope": 0.2,
            "flow_accumulation": 85000.0,
            "imperviousness": 0.88,
            "vulnerability_score": 0.92,
            "trigger_rain_threshold": 25.0,
            "is_hotspot": 1.0,
        }
        importances = {
            "rainfall_mm": 0.40,
            "vulnerability_score": 0.35,
            "slope": 0.15,
            "trigger_rain_threshold": 0.10,
        }

        expl = explain_prediction(
            feature_dict=feature_dict,
            feature_importances=importances,
            risk_level="HIGH",
            probability=0.88,
            horizon=1,
            cell_id="CELL_VEL_01",
        )

        self.assertIsInstance(expl, PredictionExplanation)
        self.assertEqual(expl.cell_id, "CELL_VEL_01")
        self.assertEqual(expl.horizon, 1)
        self.assertEqual(expl.risk_level, "HIGH")
        self.assertAlmostEqual(expl.probability, 0.88)
        self.assertIn("SCIENTIFIC", expl.disclaimer.upper() or expl.disclaimer)
        self.assertIn("proxy", expl.disclaimer.lower())
        self.assertIn("causation", expl.disclaimer.lower())

        # Check dictionary conversion
        d = expl.to_dict()
        self.assertIn("top_factors", d)
        self.assertIn("static_factors", d)
        self.assertIn("dynamic_factors", d)
        self.assertIn("hotspot_context", d)
        self.assertIn("summary", d)

    def test_top_factors_normalized_and_directional(self) -> None:
        """Verifies factor importances are normalized and indicate direction."""
        feature_dict = {
            "rainfall_mm": 65.0,
            "rain_past_24h": 0.0,
            "elevation": 5.0,
            "slope": 0.1,
            "flow_accumulation": 90000.0,
            "imperviousness": 0.85,
            "vulnerability_score": 0.90,
            "trigger_rain_threshold": 30.0,
            "is_hotspot": 1.0,
        }
        importances = self.predictor.model.get_feature_importances(3)

        expl = explain_prediction(
            feature_dict=feature_dict,
            feature_importances=importances,
            risk_level="HIGH",
            probability=0.95,
            horizon=3,
            cell_id="CELL_VEL_01",
            top_n=5,
        )

        self.assertEqual(len(expl.top_factors), 5)
        for f in expl.top_factors:
            self.assertIsInstance(f, FactorContribution)
            self.assertGreaterEqual(f.importance, 0.0)
            self.assertLessEqual(f.importance, 1.0)
            self.assertIn(f.direction, ["increases_risk", "decreases_risk", "neutral"])
            self.assertIn(f.category, ["dynamic", "static", "hotspot_context"])

        # Rainfall should be marked as increasing risk
        rain_factor = next(f for f in expl.top_factors if f.feature == "rainfall_mm")
        self.assertEqual(rain_factor.direction, "increases_risk")

    def test_horizon_awareness_and_no_leakage(self) -> None:
        """Verifies explanations operate independently across +1h, +3h, +6h without temporal leakage."""
        for h in (1, 3, 6):
            expl = self.predictor.explain_forecast(
                rainfall_mm=30.0,
                cell_id="CELL_VEL_01",
                horizon=h,
            )
            self.assertEqual(expl.horizon, h)
            self.assertEqual(expl.dynamic_factors["horizon_hours"], h)
            self.assertEqual(expl.dynamic_factors["rainfall_mm"], 30.0)

            # Check that top factors only include supported feature columns
            feature_names = [f.feature for f in expl.top_factors]
            self.assertNotIn("rain_3h", feature_names)
            self.assertNotIn("rain_6h", feature_names)

    def test_static_dynamic_decomposition(self) -> None:
        """Verifies static vulnerability, dynamic weather, and hotspot context are properly separated."""
        expl = self.predictor.explain_forecast(
            rainfall_mm=55.0,
            cell_id="CELL_VEL_01",
            horizon=3,
            rain_past_24h=38.0,
        )

        # Static decomposition
        self.assertIn("vulnerability_score", expl.static_factors)
        self.assertIn("elevation_m", expl.static_factors)
        self.assertIn("slope_deg", expl.static_factors)
        self.assertIn("static_contributions", expl.static_factors)

        # Dynamic decomposition
        self.assertEqual(expl.dynamic_factors["rainfall_mm"], 55.0)
        self.assertEqual(expl.dynamic_factors["rain_past_24h_mm"], 38.0)
        self.assertGreaterEqual(expl.dynamic_factors["threshold_ratio"], 1.0)

        # Hotspot context
        self.assertTrue(expl.hotspot_context["is_hotspot"])
        self.assertGreater(expl.hotspot_context["trigger_threshold_mm"], 0.0)

    def test_human_readable_summaries_across_risk_tiers(self) -> None:
        """Verifies deterministic summary generator handles LOW, MEDIUM, and HIGH conditions objectively."""
        # High risk scenario
        sum_high = generate_human_readable_summary(
            risk_level="HIGH",
            probability=0.88,
            horizon=3,
            rainfall_mm=60.0,
            vulnerability_score=0.92,
            rain_past_24h=40.0,
            is_hotspot=True,
            cell_id="CELL_VEL_01",
        )
        self.assertIn("High forecast rainfall", sum_high)
        self.assertIn("high static terrain vulnerability", sum_high)
        self.assertIn("chronic waterlogging hotspot", sum_high)
        self.assertIn("saturated", sum_high.lower())
        self.assertNotIn("certain flooding", sum_high)

        # Medium risk scenario
        sum_med = generate_human_readable_summary(
            risk_level="MEDIUM",
            probability=0.55,
            horizon=1,
            rainfall_mm=22.0,
            vulnerability_score=0.65,
            rain_past_24h=10.0,
            is_hotspot=False,
            cell_id="CELL_MAD_02",
        )
        self.assertIn("Moderate forecast rainfall", sum_med)
        self.assertIn("moderate", sum_med.lower())
        self.assertNotIn("certain", sum_med.lower())

        # Low risk scenario
        sum_low = generate_human_readable_summary(
            risk_level="LOW",
            probability=0.08,
            horizon=1,
            rainfall_mm=2.0,
            vulnerability_score=0.25,
            rain_past_24h=0.0,
            is_hotspot=False,
            cell_id="CELL_TAM_04",
        )
        self.assertIn("Low forecast rainfall", sum_low)
        self.assertIn("low static terrain vulnerability", sum_low)
        self.assertIn("low flood probability", sum_low)

    def test_prediction_api_backward_compatibility(self) -> None:
        """Verifies existing predict_from_forecast() defaults to explain=False and preserves RiskPrediction."""
        pred_default = self.predictor.predict_from_forecast(
            rainfall_mm=10.0,
            cell_id="CELL_VEL_01",
            horizon=1,
            persist=False,
        )
        self.assertIsInstance(pred_default, RiskPrediction)
        self.assertIsNone(pred_default.explanation)

        # Requesting explain=True populates explanation
        pred_explained = self.predictor.predict_from_forecast(
            rainfall_mm=10.0,
            cell_id="CELL_VEL_01",
            horizon=1,
            persist=False,
            explain=True,
        )
        self.assertIsInstance(pred_explained, RiskPrediction)
        self.assertIsNotNone(pred_explained.explanation)
        self.assertEqual(pred_explained.explanation["cell_id"], "CELL_VEL_01")
        self.assertEqual(pred_explained.explanation["horizon"], 1)

    def test_predict_with_explanation_convenience_method(self) -> None:
        """Verifies predict_with_explanation returns both dataclass and explanation object."""
        pred, expl = self.predictor.predict_with_explanation(
            rainfall_mm=45.0,
            cell_id="CELL_VEL_01",
            horizon=3,
            persist=False,
        )
        self.assertIsInstance(pred, RiskPrediction)
        self.assertIsInstance(expl, PredictionExplanation)
        self.assertEqual(pred.cell_id, expl.cell_id)
        self.assertEqual(pred.level, expl.risk_level)
        self.assertEqual(pred.probability, expl.probability)
        self.assertEqual(pred.explanation, expl.to_dict())

    def test_heuristic_mode_explainability(self) -> None:
        """Verifies FloodRiskPredictor in heuristic mode provides valid explanations when requested."""
        predictor = FloodRiskPredictor(mode="heuristic")
        pred = predictor.predict_from_forecast(
            rainfall_mm=45.0,
            cell_id="CELL_VEL_01",
            horizon=1,
            vulnerability=0.80,
            persist=False,
            explain=True,
        )
        self.assertIsNotNone(pred.explanation)
        self.assertEqual(pred.explanation["methodology"], "heuristic_linear_combination")
        self.assertEqual(len(pred.explanation["top_factors"]), 2)
        self.assertIn("summary", pred.explanation)

    def test_database_persistence_with_explanation(self) -> None:
        """Verifies predictions with explanations are properly serialized to JSON and persisted."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_expl_db.db"
            init_db(db_path)

            predictor = XGBoostRiskPredictor(db_path=db_path, model_dir="data/m1/models")
            pred = predictor.predict_from_forecast(
                rainfall_mm=55.0,
                cell_id="CELL_VEL_01",
                horizon=1,
                persist=True,
                explain=True,
            )
            self.assertTrue(pred.persisted)

            # Query database
            with get_db_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cell_id, horizon, level, probability, explanation FROM risk_predictions WHERE cell_id='CELL_VEL_01';")
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["cell_id"], "CELL_VEL_01")
                self.assertIsInstance(row["explanation"], str)

                # Parse JSON
                parsed_expl = json.loads(row["explanation"])
                self.assertEqual(parsed_expl["cell_id"], "CELL_VEL_01")
                self.assertIn("top_factors", parsed_expl)
                self.assertIn("summary", parsed_expl)

    def test_pipeline_integration_with_explanations(self) -> None:
        """Verifies run_pipeline(include_explanations=True) generates explanations for all cells and horizons."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_pipe_expl.db"
            init_db(db_path)

            sample_cells = [
                ("CELL_VEL_01", '{"type":"Polygon","coordinates":[]}', 6.5, 0.2, 85000.0, 0.88),
            ]
            with get_db_connection(db_path) as conn:
                conn.executemany(
                    "INSERT INTO cells (id, geometry, elevation, slope, flow_acc, vulnerability) VALUES (?, ?, ?, ?, ?, ?);",
                    sample_cells,
                )

            from src.ingestion.weather import load_mock_forecast
            mock_res = load_mock_forecast("tests/fixtures/sample_openmeteo_response.json")

            with patch("src.pipeline.fetch_and_store_forecast") as mock_fetch:
                def fake_fetch(*args, **kwargs):
                    mock_res.save_to_db(db_path)
                    mock_res.used_cached_data = True
                    return mock_res, 1

                mock_fetch.side_effect = fake_fetch

                result = run_pipeline(
                    latitude=13.0827,
                    longitude=80.2707,
                    db_path=db_path,
                    predictor_mode="ml",
                    model_dir="data/m1/models",
                    include_explanations=True,
                    persist=True,
                )

                self.assertEqual(len(result.predictions), 3)  # 1 cell * 3 horizons
                for p in result.predictions:
                    self.assertIsNotNone(p.explanation)
                    self.assertIn("top_factors", p.explanation)
                    self.assertIn("summary", p.explanation)
                    self.assertEqual(p.explanation["cell_id"], "CELL_VEL_01")


if __name__ == "__main__":
    unittest.main()
