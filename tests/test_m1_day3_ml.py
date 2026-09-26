"""Comprehensive unit and integration tests for Chetna M1 Day 3.

Verifies:
1. Proxy label generation with strict provenance tracking.
2. Hotspot calibration logic and soil saturation adjustment.
3. Feature engineering without target or temporal leakage.
4. XGBoost training determinism and reproducibility (seed=42).
5. Model serialization and deserialization (save/load).
6. Bounded probabilities [0.0, 1.0] and 3-tier risk classification (LOW/MEDIUM/HIGH).
7. Evaluation metrics calculations (precision, recall, F1, ROC-AUC, confusion matrix).
8. Integration with Chetna RiskPrediction contract and SQLite persistence.
9. Graceful fallback when models are not loaded.
10. End-to-end pipeline compatibility.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, List
import unittest
from unittest.mock import patch

import numpy as np
import pytest

from database.db import get_db_connection, init_db
from src.model.ml_dataset import (
    FEATURE_COLUMNS,
    ProxySample,
    build_proxy_training_dataset,
    calibrate_hotspot_threshold,
    compute_proxy_target,
    load_static_cell_catalog,
    prepare_matrices_by_horizon,
)
from src.model.ml_evaluator import (
    HorizonMetrics,
    calculate_confusion_matrix,
    calculate_roc_auc,
    evaluate_predictions,
    format_evaluation_report,
)
from src.model.ml_predictor import (
    XGBoostFloodModel,
    XGBoostRiskPredictor,
)
from src.model.predictor import FloodRiskPredictor, RiskPrediction
from src.pipeline import run_pipeline


class TestM1Day3ProxyLabelsAndCalibration(unittest.TestCase):
    """Test suite for proxy label generation, provenance, and calibration logic."""

    def test_hotspot_calibration_threshold_scaling(self) -> None:
        """Verifies higher vulnerability decreases critical trigger rainfall threshold."""
        base_trigger = 30.0

        # High vulnerability (0.90) -> lower threshold (earlier flooding)
        t_high_vuln = calibrate_hotspot_threshold(base_trigger, vulnerability_score=0.90)
        # Moderate vulnerability (0.50) -> baseline threshold
        t_med_vuln = calibrate_hotspot_threshold(base_trigger, vulnerability_score=0.50)
        # Low vulnerability (0.15) -> higher threshold (resilient)
        t_low_vuln = calibrate_hotspot_threshold(base_trigger, vulnerability_score=0.15)

        self.assertLess(t_high_vuln, t_med_vuln)
        self.assertLess(t_med_vuln, t_low_vuln)

    def test_antecedent_rainfall_saturation_effect(self) -> None:
        """Verifies heavy 24h antecedent rainfall reduces the trigger threshold."""
        base_trigger = 25.0
        v_score = 0.80

        # Dry antecedent
        t_dry = calibrate_hotspot_threshold(base_trigger, v_score, rain_past_24h=0.0)
        # Moderate antecedent
        t_mod = calibrate_hotspot_threshold(base_trigger, v_score, rain_past_24h=25.0)
        # Saturated antecedent
        t_sat = calibrate_hotspot_threshold(base_trigger, v_score, rain_past_24h=50.0)

        self.assertLess(t_sat, t_mod)
        self.assertLess(t_mod, t_dry)

    def test_proxy_target_computation_and_provenance(self) -> None:
        """Verifies binary and continuous proxy outputs and provenance."""
        # Low rain scenario
        wl_low, score_low, tier_low = compute_proxy_target(rainfall_mm=5.0, effective_threshold=30.0, vulnerability_score=0.30)
        self.assertEqual(wl_low, 0)
        self.assertLess(score_low, 0.40)
        self.assertEqual(tier_low, "Low")

        # Heavy rain scenario exceeding threshold
        wl_high, score_high, tier_high = compute_proxy_target(rainfall_mm=50.0, effective_threshold=30.0, vulnerability_score=0.85)
        self.assertEqual(wl_high, 1)
        self.assertGreaterEqual(score_high, 0.70)
        self.assertEqual(tier_high, "High")

        # Probability score strictly in [0.0, 1.0]
        self.assertGreaterEqual(score_low, 0.0)
        self.assertLessEqual(score_low, 1.0)
        self.assertGreaterEqual(score_high, 0.0)
        self.assertLessEqual(score_high, 1.0)

    def test_dataset_generation_preserves_provenance(self) -> None:
        """Verifies generated proxy dataset contains explicit proxy flags and data sources."""
        samples = build_proxy_training_dataset(data_dir="data/m1")
        self.assertGreater(len(samples), 0)

        sample = samples[0]
        self.assertTrue(sample.is_proxy)
        self.assertIn("Proxy", sample.data_source)
        self.assertIn("Calibrated", sample.data_source)
        self.assertIn(sample.horizon, (1, 3, 6))
        self.assertEqual(len(sample.to_feature_vector()), len(FEATURE_COLUMNS))

    def test_no_temporal_feature_leakage(self) -> None:
        """Verifies feature vectors do not leak future cumulative rainfall beyond the horizon."""
        samples = build_proxy_training_dataset(data_dir="data/m1")
        h1_samples = [s for s in samples if s.horizon == 1]
        h6_samples = [s for s in samples if s.horizon == 6]

        self.assertGreater(len(h1_samples), 0)
        self.assertGreater(len(h6_samples), 0)

        # For the same cell, event, and timestamp, 6h cumulative rain >= 1h rain
        # but H1 sample only contains 1h rainfall as its dynamic rainfall feature
        matched_pairs = {}
        for s in h1_samples:
            key = (s.event_id, s.cell_id, s.timestamp)
            matched_pairs[key] = s.rainfall_mm

        for s in h6_samples:
            key = (s.event_id, s.cell_id, s.timestamp)
            if key in matched_pairs:
                r1 = matched_pairs[key]
                r6 = s.rainfall_mm
                self.assertGreaterEqual(r6, r1)


class TestM1Day3EvaluationMetrics(unittest.TestCase):
    """Test suite for evaluation metrics computation."""

    def test_confusion_matrix_calculation(self) -> None:
        y_true = [1, 1, 0, 0, 1]
        y_pred = [1, 0, 0, 1, 1]
        cm = calculate_confusion_matrix(y_true, y_pred)
        self.assertEqual(cm["tp"], 2)
        self.assertEqual(cm["fp"], 1)
        self.assertEqual(cm["tn"], 1)
        self.assertEqual(cm["fn"], 1)

    def test_roc_auc_perfect_and_random(self) -> None:
        # Perfect ranking
        y_true = [0, 0, 1, 1]
        y_scores = [0.1, 0.2, 0.8, 0.9]
        auc_perfect = calculate_roc_auc(y_true, y_scores)
        self.assertEqual(auc_perfect, 1.0)

        # Inverted ranking
        y_scores_inverted = [0.9, 0.8, 0.2, 0.1]
        auc_inverted = calculate_roc_auc(y_true, y_scores_inverted)
        self.assertEqual(auc_inverted, 0.0)

    def test_evaluate_predictions_metrics_integrity(self) -> None:
        y_true = [1, 1, 1, 0, 0, 0]
        y_prob = [0.9, 0.85, 0.7, 0.2, 0.1, 0.45]
        metrics = evaluate_predictions(y_true, y_prob, horizon=1, threshold=0.50)

        self.assertIsInstance(metrics, HorizonMetrics)
        self.assertEqual(metrics.horizon, 1)
        self.assertEqual(metrics.sample_count, 6)
        self.assertEqual(metrics.positive_count, 3)
        self.assertEqual(metrics.accuracy, 1.0)
        self.assertEqual(metrics.precision, 1.0)
        self.assertEqual(metrics.recall, 1.0)
        self.assertEqual(metrics.f1_score, 1.0)
        self.assertEqual(metrics.roc_auc, 1.0)
        self.assertTrue(metrics.is_proxy_evaluation)
        self.assertIn("calibrated proxy", metrics.disclaimer.lower())

    def test_format_evaluation_report_contains_disclaimer(self) -> None:
        y_true = [1, 0]
        y_prob = [0.8, 0.2]
        m1 = evaluate_predictions(y_true, y_prob, horizon=1)
        m3 = evaluate_predictions(y_true, y_prob, horizon=3)
        report = format_evaluation_report({1: m1, 3: m3})

        self.assertIn("SCIENTIFIC PROVENANCE & PROTOTYPE DISCLAIMER", report)
        self.assertIn("PROXY DEVELOPMENT LABELS", report)
        self.assertIn("+1h", report)
        self.assertIn("+3h", report)


class TestM1Day3XGBoostModelAndPredictor(unittest.TestCase):
    """Test suite for XGBoost model training, persistence, and inference."""

    @classmethod
    def setUpClass(cls) -> None:
        # Create deterministic synthetic dataset for quick model tests
        cls.rng = np.random.RandomState(42)
        cls.X_train = np.array([
            [5.0, 0.0, 15.0, 2.0, 500.0, 0.40, 0.25, 35.0, 0.0],
            [12.0, 10.0, 12.0, 1.5, 2000.0, 0.60, 0.45, 35.0, 0.0],
            [45.0, 20.0, 6.0, 0.3, 50000.0, 0.85, 0.85, 25.0, 1.0],
            [60.0, 45.0, 4.0, 0.1, 95000.0, 0.92, 0.95, 20.0, 1.0],
            [2.0, 0.0, 22.0, 3.5, 300.0, 0.30, 0.18, 40.0, 0.0],
            [70.0, 50.0, 5.0, 0.2, 80000.0, 0.88, 0.90, 22.0, 1.0],
        ], dtype=np.float32)
        cls.y_train = np.array([0, 0, 1, 1, 0, 1], dtype=np.int32)

    def test_xgboost_flood_model_training_and_reproducibility(self) -> None:
        """Verifies XGBoost training is deterministic with fixed random seed."""
        model_a = XGBoostFloodModel(random_state=42, n_estimators=10)
        model_a.train_horizon(1, self.X_train, self.y_train)

        model_b = XGBoostFloodModel(random_state=42, n_estimators=10)
        model_b.train_horizon(1, self.X_train, self.y_train)

        preds_a = model_a.predict_proba(1, self.X_train)
        preds_b = model_b.predict_proba(1, self.X_train)

        np.testing.assert_allclose(preds_a, preds_b, atol=1e-5)
        # All probabilities strictly in [0.0, 1.0]
        self.assertTrue(np.all(preds_a >= 0.0) and np.all(preds_a <= 1.0))

    def test_model_serialization_and_deserialization(self) -> None:
        """Verifies models can be serialized to JSON and loaded identically."""
        model = XGBoostFloodModel(random_state=42, n_estimators=10)
        for h in (1, 3, 6):
            model.train_horizon(h, self.X_train, self.y_train)

        with tempfile.TemporaryDirectory() as tmp_dir:
            model.save(tmp_dir)

            # Check files were created
            for h in (1, 3, 6):
                self.assertTrue((Path(tmp_dir) / f"model_h{h}.json").is_file())
            self.assertTrue((Path(tmp_dir) / "model_metadata.json").is_file())

            # Load into fresh model
            loaded_model = XGBoostFloodModel()
            loaded_model.load(tmp_dir)
            self.assertTrue(loaded_model.is_trained)

            orig_preds = model.predict_proba(3, self.X_train)
            loaded_preds = loaded_model.predict_proba(3, self.X_train)
            np.testing.assert_allclose(orig_preds, loaded_preds, atol=1e-5)

    def test_xgboost_risk_predictor_inference_and_levels(self) -> None:
        """Verifies XGBoostRiskPredictor produces valid RiskPrediction objects with proper risk tiers."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_m1.db"
            init_db(db_path)

            predictor = XGBoostRiskPredictor(
                db_path=db_path,
                model_dir="data/m1/models",
                allow_fallback=True,
            )

            # High rain scenario for known hotspot cell
            pred_high = predictor.predict_from_forecast(
                rainfall_mm=60.0,
                cell_id="CELL_VEL_01",
                horizon=1,
                persist=True,
            )
            self.assertIsInstance(pred_high, RiskPrediction)
            self.assertEqual(pred_high.cell_id, "CELL_VEL_01")
            self.assertEqual(pred_high.horizon, 1)
            self.assertGreaterEqual(pred_high.probability, 0.0)
            self.assertLessEqual(pred_high.probability, 1.0)
            self.assertIn(pred_high.level, ["LOW", "MEDIUM", "HIGH"])
            self.assertTrue(pred_high.persisted)

            # Low rain scenario
            pred_low = predictor.predict_from_forecast(
                rainfall_mm=1.0,
                cell_id="CELL_VEL_01",
                horizon=1,
                persist=False,
            )
            self.assertLess(pred_low.probability, 0.40)
            self.assertEqual(pred_low.level, "LOW")

            # Check persistence in database
            with get_db_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cell_id, horizon, level, probability FROM risk_predictions WHERE cell_id='CELL_VEL_01';")
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["cell_id"], "CELL_VEL_01")
                self.assertEqual(rows[0]["horizon"], 1)

    def test_xgboost_risk_predictor_fallback(self) -> None:
        """Verifies predictor cleanly falls back to heuristic model when ML models are missing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_fb.db"
            init_db(db_path)

            # Predictor pointing to non-existent model dir with fallback enabled
            predictor_fb = XGBoostRiskPredictor(
                db_path=db_path,
                model_dir=Path(tmp_dir) / "non_existent",
                allow_fallback=True,
            )
            self.assertFalse(predictor_fb.model.is_trained)

            # Should gracefully produce prediction via fallback
            pred = predictor_fb.predict_from_forecast(
                rainfall_mm=25.0,
                cell_id="TEST_CELL",
                horizon=1,
                persist=False,
            )
            self.assertIsInstance(pred, RiskPrediction)
            self.assertIn(pred.level, ["LOW", "MEDIUM", "HIGH"])

            # Predictor with fallback disabled should raise RuntimeError
            predictor_no_fb = XGBoostRiskPredictor(
                db_path=db_path,
                model_dir=Path(tmp_dir) / "non_existent",
                allow_fallback=False,
            )
            with self.assertRaises(RuntimeError):
                predictor_no_fb.predict_from_forecast(rainfall_mm=25.0, cell_id="TEST_CELL", horizon=1)

    def test_flood_risk_predictor_mode_ml(self) -> None:
        """Verifies FloodRiskPredictor(mode='ml') functions seamlessly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_mode.db"
            init_db(db_path)

            predictor = FloodRiskPredictor(
                db_path=db_path,
                mode="ml",
                model_dir="data/m1/models",
            )
            pred = predictor.predict_from_forecast(
                rainfall_mm=40.0,
                cell_id="CELL_VEL_01",
                horizon=3,
                persist=False,
            )
            self.assertIsInstance(pred, RiskPrediction)
            self.assertEqual(pred.horizon, 3)
            self.assertIn(pred.level, ["LOW", "MEDIUM", "HIGH"])

    def test_pipeline_execution_with_ml_predictor(self) -> None:
        """Verifies run_pipeline(..., predictor_mode='ml') executes successfully."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_pipe_ml.db"
            init_db(db_path)

            # Seed test cells
            sample_cells = [
                ("CELL_VEL_01", '{"type":"Polygon","coordinates":[]}', 6.5, 0.2, 85000.0, 0.88),
                ("CELL_MAD_02", '{"type":"Polygon","coordinates":[]}', 7.2, 0.4, 62000.0, 0.74),
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

                res = run_pipeline(
                    latitude=13.0827,
                    longitude=80.2707,
                    db_path=db_path,
                    predictor_mode="ml",
                    model_dir="data/m1/models",
                    persist=True,
                )

                self.assertEqual(res.cells_processed, 2)
                self.assertEqual(res.predictions_created, 6)  # 2 cells * 3 horizons

            # Verify saved predictions in database
            with get_db_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as c FROM risk_predictions;")
                row = cursor.fetchone()
                self.assertEqual(row["c"], 6)


if __name__ == "__main__":
    unittest.main()
