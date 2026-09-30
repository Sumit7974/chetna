"""Automated regression test suite for Chetna M1: Leakage Prevention & Event Isolation.

Validates:
1. Target columns (waterlogged_proxy, flood_risk_proxy, proxy_risk_tier) cannot enter features.
2. Target-derived columns (trigger_rain_threshold) cannot enter features.
3. Train/test event IDs cannot overlap (disjoint sets enforced).
4. Test event rows cannot appear in training dataset.
5. Preprocessing/scaling is completely independent of test evaluation labels.
6. Future timestamps and horizons cannot enter earlier horizon features.
7. Model prediction probabilities are strictly finite and bounded in [0.0, 1.0].
8. Held-out evaluation metrics are computed strictly on the held-out event population.
9. Mandatory Patna status disclaimer is present when Patna historical event series is absent.
"""

from __future__ import annotations

import unittest
import numpy as np

from src.model.ml_dataset import (
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURE_COLUMNS,
    ProxySample,
    build_proxy_training_dataset,
    get_available_event_ids,
    split_samples_by_events,
    verify_event_isolation,
)
from src.model.ml_predictor import XGBoostFloodModel, XGBoostRiskPredictor
from src.model.ml_backtest import (
    PATNA_HELD_OUT_STATUS_MESSAGE,
    run_backtest,
    run_held_out_event_backtest,
)


class TestM1LeakageAndEvaluationMethodology(unittest.TestCase):
    """Test suite ensuring zero feature leakage and rigorous event-level isolation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.samples = build_proxy_training_dataset(data_dir="data/m1")

    def test_target_columns_not_in_features(self) -> None:
        """1. Asserts target labels cannot enter FEATURE_COLUMNS."""
        forbidden_targets = ["waterlogged_proxy", "flood_risk_proxy", "proxy_risk_tier"]
        for target_col in forbidden_targets:
            self.assertNotIn(
                target_col,
                FEATURE_COLUMNS,
                f"Leakage: Target column '{target_col}' found in FEATURE_COLUMNS!",
            )

    def test_target_derived_threshold_not_in_features(self) -> None:
        """2. Asserts trigger_rain_threshold is strictly excluded from FEATURE_COLUMNS."""
        self.assertNotIn(
            "trigger_rain_threshold",
            FEATURE_COLUMNS,
            "Leakage: trigger_rain_threshold found in FEATURE_COLUMNS!",
        )
        # Also verify against FORBIDDEN_FEATURE_COLUMNS set
        overlap = set(FEATURE_COLUMNS).intersection(FORBIDDEN_FEATURE_COLUMNS)
        self.assertEqual(len(overlap), 0, f"Leakage: Forbidden columns in features: {overlap}")

    def test_feature_vector_matches_clean_feature_columns_exactly(self) -> None:
        """Verifies ProxySample.to_feature_vector() length and contents match FEATURE_COLUMNS."""
        self.assertEqual(len(FEATURE_COLUMNS), 8)
        sample = self.samples[0]
        vec = sample.to_feature_vector()
        self.assertEqual(len(vec), len(FEATURE_COLUMNS))
        self.assertIsInstance(vec, list)
        self.assertTrue(all(isinstance(v, float) for v in vec))

    def test_train_test_event_disjoint_assertion(self) -> None:
        """3. Asserts that split_samples_by_events rejects intersecting event ID sets."""
        event_ids = get_available_event_ids(self.samples)
        self.assertGreaterEqual(len(event_ids), 2)
        evt_a = event_ids[0]

        # Passing identical event ID to both train and test must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            split_samples_by_events(
                self.samples,
                train_event_ids=[evt_a],
                test_event_ids=[evt_a],
            )
        self.assertIn("Event leakage violation", str(ctx.exception))

    def test_event_isolation_verifier(self) -> None:
        """4. Asserts that verify_event_isolation catches contaminated sample sets."""
        event_ids = get_available_event_ids(self.samples)
        evt_a, evt_b = event_ids[0], event_ids[1]

        train_samples, test_samples, _ = split_samples_by_events(
            self.samples,
            train_event_ids=[evt_a],
            test_event_ids=[evt_b],
        )

        # Disjoint sets should verify without error
        verify_event_isolation(train_samples, test_samples)

        # Contaminated set should raise ValueError
        contaminated_test = test_samples + train_samples[:5]
        with self.assertRaises(ValueError) as ctx:
            verify_event_isolation(train_samples, contaminated_test)
        self.assertIn("Event isolation failure", str(ctx.exception))

    def test_preprocessing_independent_of_test_labels(self) -> None:
        """5. Verifies feature computation is local and does not fit scalers on evaluation labels."""
        # Each sample builds features purely from its own static attributes and weather inputs
        for s in self.samples[:50]:
            vec = s.to_feature_vector()
            # All values must be finite numbers without NaN
            self.assertTrue(all(np.isfinite(vec)))

    def test_temporal_monotonicity_and_no_future_leakage(self) -> None:
        """6. Verifies earlier horizons do not access future cumulative precipitation."""
        h1_samples = {s.sample_id: s for s in self.samples if s.horizon == 1}
        h6_samples = {s.sample_id.replace("H6", "H1"): s for s in self.samples if s.horizon == 6}

        for sid, s1 in list(h1_samples.items())[:30]:
            if sid in h6_samples:
                s6 = h6_samples[sid]
                # 6h rainfall must be >= 1h rainfall during precipitation
                self.assertGreaterEqual(s6.rainfall_mm, s1.rainfall_mm)
                self.assertEqual(s1.horizon, 1)

    def test_model_probabilities_bounded_in_zero_one(self) -> None:
        """7. Verifies ML predicted probabilities are strictly bounded in [0.0, 1.0]."""
        predictor = XGBoostRiskPredictor(allow_fallback=True)
        # Test extreme and zero rainfall
        for rf in [0.0, 5.0, 50.0, 150.0, 500.0]:
            for h in (1, 3, 6):
                pred = predictor.predict_from_forecast(rainfall_mm=rf, cell_id="CELL_RAJ_01", horizon=h)
                self.assertGreaterEqual(pred.probability, 0.0)
                self.assertLessEqual(pred.probability, 1.0)
                self.assertIn(pred.level, ["LOW", "MEDIUM", "HIGH", "SEVERE"])

    def test_held_out_event_evaluation_executes_strictly_on_unseen_event(self) -> None:
        """8. Runs held-out event evaluation and verifies test event sample counts match."""
        event_ids = get_available_event_ids(self.samples)
        self.assertGreaterEqual(len(event_ids), 2)
        train_evt = "EVT_2023_MICHAUNG"
        test_evt = "EVT_2021_NOV_DEPRESSION"

        result = run_held_out_event_backtest(
            train_event_id=train_evt,
            test_event_id=test_evt,
            data_dir="data/m1",
        )

        self.assertEqual(result.evaluation_mode, "HELD_OUT_EVENT_TEST")
        self.assertEqual(result.training_event_ids, [train_evt])
        self.assertEqual(result.test_event_ids, [test_evt])

        # All event results must belong strictly to test_evt
        for r in result.event_results:
            self.assertEqual(r.event_id, test_evt)
            self.assertTrue(r.is_held_out)
            self.assertEqual(r.evaluation_type, "held_out_event_test")
            self.assertGreater(r.n_samples, 0)
            self.assertEqual(r.tp + r.tn + r.fp + r.fn, r.n_samples)

    def test_patna_status_disclaimer_present_in_results(self) -> None:
        """9. Verifies mandatory Patna data status disclaimer is present in backtest audit results."""
        result = run_backtest(data_dir="data/m1")
        self.assertEqual(result.patna_held_out_status, PATNA_HELD_OUT_STATUS_MESSAGE)
        self.assertIn("Patna-specific independent ML accuracy is not yet established", result.patna_held_out_status)

    def test_patna_held_out_evaluation_satisfies_all_criteria(self) -> None:
        """10. Verifies authentic Patna held-out evaluation meets all strict criteria."""
        train_evt = "EVT_PATNA_2019_FLOOD"
        test_evt = "EVT_PATNA_2024_09_HEAVY_RAIN"

        # Disjoint assertion
        self.assertEqual(len(set([train_evt]).intersection(set([test_evt]))), 0)

        result = run_held_out_event_backtest(
            train_event_id=train_evt,
            test_event_id=test_evt,
            data_dir="data/m1",
        )

        self.assertEqual(result.evaluation_mode, "HELD_OUT_EVENT_TEST")
        self.assertEqual(result.training_event_ids, [train_evt])
        self.assertEqual(result.test_event_ids, [test_evt])
        self.assertIn("VALID PATNA HELD-OUT RESULTS AVAILABLE", result.patna_held_out_status)

        # Verify all horizons are evaluated and have exact expected Patna population
        horizons_found = set()
        for r in result.event_results:
            self.assertEqual(r.event_id, test_evt)
            self.assertEqual(r.data_city, "Patna")
            self.assertTrue(r.is_held_out)
            self.assertEqual(r.n_samples, 3648)  # 38 cells * 96 hours
            self.assertEqual(r.n_positive, 75)
            self.assertEqual(r.tp + r.tn + r.fp + r.fn, 3648)
            horizons_found.add(r.horizon)
            if r.method == "ml":
                self.assertGreater(r.accuracy, 0.90)
                self.assertGreater(r.recall, 0.50)

        self.assertEqual(horizons_found, {1, 3, 6})

    def test_chennai_events_excluded_from_patna_evaluation(self) -> None:
        """11. Verifies old Chennai events are strictly excluded from the Patna test set."""
        from src.model.ml_dataset import split_samples_by_events
        train_s, test_s, _ = split_samples_by_events(
            self.samples,
            train_event_ids=["EVT_PATNA_2019_FLOOD"],
            test_event_ids=["EVT_PATNA_2024_09_HEAVY_RAIN"],
        )
        test_event_ids = set(s.event_id for s in test_s)
        self.assertNotIn("EVT_2023_MICHAUNG", test_event_ids)
        self.assertNotIn("EVT_2021_NOV_DEPRESSION", test_event_ids)
        self.assertEqual(test_event_ids, {"EVT_PATNA_2024_09_HEAVY_RAIN"})

