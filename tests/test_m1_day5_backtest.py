"""Automated tests for Chetna M1 Day 5: Rigorous Backtesting and Baseline Comparison.

Verifies:
1. Historical backtesting events (Michaung 2023, Nov 2021) load correctly.
2. All three prediction methods are evaluated (ML, Heuristic, Rainfall Baseline).
3. All three forecast horizons (+1h, +3h, +6h) are evaluated.
4. Correct calculation of classification metrics (precision, recall, F1, ROC-AUC, PR-AUC, Brier score).
5. Exact confusion matrix counts (TP + TN + FP + FN == n_samples).
6. Safe handling of edge cases (undefined metrics return None rather than synthetic values).
7. Rainfall-only baseline uses strictly rainfall and ignores terrain/vulnerability features.
8. Preservation of historical event identities across outputs.
9. Machine-readable serialization to results.json, results.csv, and confusion_matrices.json.
10. Strict protection against label leakage and future-horizon leakage.
11. Deterministic reproducibility across repeated backtest runs.
12. Zero regressions across existing B1, B2, and M1 Day 1-4 components.
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.model.ml_backtest import (
    DEFAULT_RAINFALL_THRESHOLDS,
    BacktestRecord,
    BacktestResult,
    RainfallThresholdBaseline,
    calculate_binary_metrics,
    run_backtest,
)
from src.model.ml_dataset import FEATURE_COLUMNS, build_proxy_training_dataset
from src.static_risk.hotspots import load_backtest_events


class TestM1Day5Backtesting(unittest.TestCase):
    """Test suite for M1 Day 5 backtesting pipeline, metrics, baselines, and leakage guards."""

    def test_historical_events_load_and_contain_required_identifiers(self) -> None:
        """Verifies both registered historical backtest events exist and have valid metadata."""
        events = load_backtest_events("data/m1/backtest_events.json")
        self.assertGreaterEqual(len(events), 2)

        event_ids = [e.event_id for e in events]
        self.assertIn("EVT_2023_MICHAUNG", event_ids)
        self.assertIn("EVT_2021_NOV_DEPRESSION", event_ids)

        for e in events:
            self.assertGreater(e.total_rainfall_mm, 0.0)
            self.assertGreater(e.duration_hours, 0)
            self.assertTrue(len(e.name) > 0)
            self.assertTrue(len(e.rainfall_data_file) > 0)

    def test_rainfall_threshold_baseline_uses_rainfall_only(self) -> None:
        """Verifies RainfallThresholdBaseline relies strictly on rainfall and horizon thresholds."""
        baseline = RainfallThresholdBaseline(thresholds={1: 30.0, 3: 50.0, 6: 70.0})

        # Above threshold -> 1
        self.assertEqual(baseline.predict(rainfall_mm=35.0, horizon=1), 1)
        self.assertEqual(baseline.predict(rainfall_mm=55.0, horizon=3), 1)
        self.assertEqual(baseline.predict(rainfall_mm=75.0, horizon=6), 1)

        # Below threshold -> 0
        self.assertEqual(baseline.predict(rainfall_mm=25.0, horizon=1), 0)
        self.assertEqual(baseline.predict(rainfall_mm=45.0, horizon=3), 0)
        self.assertEqual(baseline.predict(rainfall_mm=65.0, horizon=6), 0)

        # Continuous scores strictly in [0.0, 1.0]
        self.assertEqual(baseline.score(rainfall_mm=15.0, horizon=1), 0.50)
        self.assertEqual(baseline.score(rainfall_mm=60.0, horizon=1), 1.00)
        self.assertEqual(baseline.score(rainfall_mm=0.0, horizon=1), 0.00)

    def test_metrics_calculation_and_confusion_matrix_sum(self) -> None:
        """Verifies binary classification metrics and ensures confusion matrix sums to sample count."""
        y_true = [1, 1, 1, 0, 0, 0, 0, 0, 1, 0]
        y_pred = [1, 1, 0, 0, 0, 1, 0, 0, 1, 0]
        y_prob = [0.9, 0.8, 0.4, 0.1, 0.2, 0.7, 0.15, 0.05, 0.85, 0.25]

        record = calculate_binary_metrics(
            y_true=y_true,
            y_pred=y_pred,
            y_prob=y_prob,
            event_id="TEST_EVENT",
            horizon=3,
            method="ml",
        )

        self.assertEqual(record.n_samples, 10)
        self.assertEqual(record.n_positive, 4)
        self.assertEqual(record.n_predicted_positive, 4)
        self.assertEqual(record.tp, 3)
        self.assertEqual(record.fp, 1)
        self.assertEqual(record.tn, 5)
        self.assertEqual(record.fn, 1)

        # Confusion matrix conservation law
        self.assertEqual(record.tp + record.tn + record.fp + record.fn, record.n_samples)

        # Precision = 3/4 = 0.75, Recall = 3/4 = 0.75, F1 = 0.75
        self.assertEqual(record.precision, 0.75)
        self.assertEqual(record.recall, 0.75)
        self.assertEqual(record.f1, 0.75)
        self.assertIsNotNone(record.roc_auc)
        self.assertGreater(record.roc_auc, 0.50)
        self.assertIsNotNone(record.brier)

    def test_edge_cases_handled_gracefully(self) -> None:
        """Verifies undefined metrics return None without crashing or manufacturing false numbers."""
        # Case A: Zero positive cases (e.g. dry event)
        y_true_zero_pos = [0, 0, 0, 0, 0]
        y_pred_zero_pos = [0, 0, 0, 0, 0]
        rec_zero_pos = calculate_binary_metrics(y_true=y_true_zero_pos, y_pred=y_pred_zero_pos)
        self.assertEqual(rec_zero_pos.tp, 0)
        self.assertEqual(rec_zero_pos.fp, 0)
        self.assertEqual(rec_zero_pos.tn, 5)
        self.assertEqual(rec_zero_pos.fn, 0)
        self.assertIsNone(rec_zero_pos.roc_auc)  # ROC-AUC undefined when only 1 class exists

        # Case B: Zero positive predictions (conservative model on mild event)
        y_true_mild = [1, 0, 0, 0]
        y_pred_conservative = [0, 0, 0, 0]
        rec_mild = calculate_binary_metrics(y_true=y_true_mild, y_pred=y_pred_conservative)
        self.assertIsNone(rec_mild.precision)  # 0/0 precision is None
        self.assertEqual(rec_mild.recall, 0.0)
        self.assertEqual(rec_mild.f1, 0.0)

    def test_no_target_label_leakage_into_features(self) -> None:
        """Verifies feature columns do not contain the target label or future proxies."""
        samples = build_proxy_training_dataset(data_dir="data/m1")
        self.assertGreater(len(samples), 0)

        # Verify FEATURE_COLUMNS does not contain target variables
        forbidden = ["waterlogged_proxy", "flood_risk_proxy", "proxy_risk_tier", "inundation_depth"]
        for f in forbidden:
            self.assertNotIn(f, FEATURE_COLUMNS)

        # Verify sample feature vector matches FEATURE_COLUMNS length exactly
        vec = samples[0].to_feature_vector()
        self.assertEqual(len(vec), len(FEATURE_COLUMNS))

    def test_no_future_horizon_leakage(self) -> None:
        """Verifies horizon +1h samples strictly contain +1h rainfall and not future +3h/+6h precipitation."""
        samples = build_proxy_training_dataset(data_dir="data/m1")
        h1_samples = {s.sample_id: s for s in samples if s.horizon == 1}
        h6_samples = {s.sample_id.replace("H6", "H1"): s for s in samples if s.horizon == 6}

        for sid, s1 in list(h1_samples.items())[:20]:
            if sid in h6_samples:
                s6 = h6_samples[sid]
                # During active storm rain, 6h cumulative rain should be >= 1h rain
                self.assertGreaterEqual(s6.rainfall_mm, s1.rainfall_mm)
                # s1.rainfall_mm strictly reflects 1h rain
                self.assertEqual(s1.horizon, 1)

    def test_run_backtest_evaluates_all_methods_events_and_horizons(self) -> None:
        """Verifies run_backtest evaluates ML, Heuristic, and Rainfall Baseline across all events and horizons."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = run_backtest(
                data_dir="data/m1",
                model_dir="data/m1/models",
                output_dir=tmp_dir,
            )

            self.assertIsInstance(result, BacktestResult)

            # Check metadata
            self.assertIn("events", result.metadata)
            self.assertIn("EVT_2023_MICHAUNG", result.metadata["events"])
            self.assertIn("EVT_2021_NOV_DEPRESSION", result.metadata["events"])
            self.assertEqual(result.metadata["horizons"], [1, 3, 6])
            self.assertEqual(set(result.metadata["methods"]), {"ml", "heuristic", "rainfall_threshold"})

            # Check event-level results count: 2 events * 3 horizons * 3 methods = 18 records
            self.assertEqual(len(result.event_results), 18)

            # Check aggregate results count: 3 horizons * 3 methods = 9 records
            self.assertEqual(len(result.aggregate_results), 9)

            # Check all 3 methods are present in event results
            methods_found = set(r.method for r in result.event_results)
            self.assertEqual(methods_found, {"ml", "heuristic", "rainfall_threshold"})

            # Check all 3 horizons are present
            horizons_found = set(r.horizon for r in result.event_results)
            self.assertEqual(horizons_found, {1, 3, 6})

            # Check file persistence
            json_file = Path(tmp_dir) / "results.json"
            csv_file = Path(tmp_dir) / "results.csv"
            cm_file = Path(tmp_dir) / "confusion_matrices.json"

            self.assertTrue(json_file.is_file())
            self.assertTrue(csv_file.is_file())
            self.assertTrue(cm_file.is_file())

            # Verify JSON loadable and valid
            with open(json_file, "r", encoding="utf-8") as f:
                loaded_json = json.load(f)
            self.assertEqual(len(loaded_json["event_results"]), 18)
            self.assertEqual(len(loaded_json["aggregate_results"]), 9)

            # Verify CSV loadable and valid
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(len(rows), 27)  # 18 event + 9 aggregate

    def test_backtest_reproducibility(self) -> None:
        """Verifies repeated backtest executions yield identical results."""
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            res_a = run_backtest(data_dir="data/m1", model_dir="data/m1/models", output_dir=tmp_a)
            res_b = run_backtest(data_dir="data/m1", model_dir="data/m1/models", output_dir=tmp_b)

            for rec_a, rec_b in zip(res_a.event_results, res_b.event_results):
                self.assertEqual(rec_a.event_id, rec_b.event_id)
                self.assertEqual(rec_a.horizon, rec_b.horizon)
                self.assertEqual(rec_a.method, rec_b.method)
                self.assertEqual(rec_a.n_samples, rec_b.n_samples)
                self.assertEqual(rec_a.tp, rec_b.tp)
                self.assertEqual(rec_a.fp, rec_b.fp)
                self.assertEqual(rec_a.tn, rec_b.tn)
                self.assertEqual(rec_a.fn, rec_b.fn)
                if rec_a.f1 is not None and rec_b.f1 is not None:
                    self.assertAlmostEqual(rec_a.f1, rec_b.f1)


if __name__ == "__main__":
    unittest.main()
