"""M1 Day 6: Robustness, failure-testing, and edge-case validation suite for Chetna.

Validates system behavior across:
1. Input and Data Failures (missing DEM, empty grid, NaN features, missing/corrupted forecasts, negative rain, extreme rain, bad hotspots, database failures)
2. Model Robustness across Horizons (+1h, +3h, +6h) and boundaries (0mm, threshold +- eps, extreme rain, vulnerability bounds, probability thresholds 0.40/0.70)
3. ML Artifact Failures & Explicit Fallback Transparency (missing models, corrupted artifacts, fallback mode tagging)
4. Pipeline Failure Isolation (per-cell error isolation, partial success reporting, failed cell auditing)
5. Explainability Robustness (LOW/MEDIUM/HIGH tiers, missing context, zero/extreme rain, non-causal compliance)
6. Backtest Robustness (empty sets, zero positives, zero negatives, constant predictions, undefined ROC/PR-AUC)
7. Boundary Tests (exact threshold transitions, epsilon deltas, invalid horizons)
8. Data Contract Validation (Risk and Sensor payloads validated against canonical schema contracts)
9. Failure Reporting (Structured CellFailureRecord representations)
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from database.db import DEFAULT_DB_PATH, get_db_connection
from src.model import (
    DEFAULT_RAINFALL_THRESHOLDS,
    BacktestRecord,
    CellFailureRecord,
    FloodRiskPredictor,
    RainfallThresholdBaseline,
    RiskPrediction,
    XGBoostFloodModel,
    XGBoostRiskPredictor,
    calculate_binary_metrics,
    explain_prediction,
    generate_human_readable_summary,
    validate_risk_prediction_contract,
    validate_sensor_reading_contract,
)
from src.pipeline import (
    EmptyCellsError,
    ForecastUnavailableError,
    PipelineResult,
    run_pipeline,
)
from src.static_risk.hotspots import (
    Hotspot,
    load_backtest_events,
    load_hotspots,
)
from src.static_risk.vulnerability import (
    DEFAULT_FEATURE_FALLBACKS,
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    calculate_cell_vulnerability,
    classify_risk_score,
    clean_cell_record,
    normalize_elevation,
    normalize_flow_accumulation,
    normalize_imperviousness,
    normalize_slope,
    process_static_risk_grid,
)


# ===========================================================================
# 1. INPUT / DATA FAILURE TESTS
# ===========================================================================

class TestInputDataFailures:
    """Tests realistic bad or missing inputs and verifies safe, explicit behavior."""

    def test_missing_dem_or_grid_file(self, tmp_path: Path):
        """Verifies FileNotFoundError on nonexistent input files."""
        nonexistent = tmp_path / "nonexistent_dem.json"
        from src.static_risk.vulnerability import load_grid_from_file
        with pytest.raises(FileNotFoundError):
            load_grid_from_file(nonexistent)

    def test_empty_grid_processing_rejected(self):
        """Verifies that an empty grid cannot be processed silently."""
        with pytest.raises(ValueError, match="Cannot process empty grid_cells list"):
            process_static_risk_grid([])

    def test_missing_static_risk_record_imputes_safely(self):
        """Verifies that a record missing all terrain features falls back to physical defaults."""
        raw_cell = {"cell_id": "CELL_EMPTY_01"}
        clean_feats, was_imputed = clean_cell_record(raw_cell)
        assert was_imputed is True
        assert clean_feats["elevation"] == DEFAULT_FEATURE_FALLBACKS["elevation"]
        assert clean_feats["slope"] == DEFAULT_FEATURE_FALLBACKS["slope"]
        assert clean_feats["flow_accumulation"] == DEFAULT_FEATURE_FALLBACKS["flow_accumulation"]
        assert clean_feats["imperviousness"] == DEFAULT_FEATURE_FALLBACKS["imperviousness"]

    def test_nan_feature_values_in_static_risk(self):
        """Verifies that NaN elevation/slope/flow_acc/imperviousness are imputed without NaN score."""
        raw_cell = {
            "cell_id": "CELL_NAN_01",
            "elevation": float("nan"),
            "slope": float("nan"),
            "flow_accumulation": float("nan"),
            "imperviousness": float("nan"),
        }
        clean_feats, was_imputed = clean_cell_record(raw_cell)
        assert was_imputed is True
        for k in ["elevation", "slope", "flow_accumulation", "imperviousness"]:
            assert not math.isnan(clean_feats[k])
            assert not math.isinf(clean_feats[k])

        bounds = {
            "elevation": (0.0, 30.0),
            "slope": (0.0, 5.0),
            "flow_accumulation": (0.0, 100000.0),
            "imperviousness": (0.0, 1.0),
        }
        scored = calculate_cell_vulnerability(clean_feats, bounds=bounds, cell_id="CELL_NAN_01")
        assert not math.isnan(scored.vulnerability_score)
        assert 0.0 <= scored.vulnerability_score <= 1.0
        assert scored.risk_level in ("low", "medium", "high")

    def test_constant_feature_values_normalization(self):
        """Verifies that uniform/zero-variance features across grid return neutral 0.50 without ZeroDivision."""
        assert normalize_elevation(10.0, 10.0, 10.0) == 0.5
        assert normalize_slope(2.0, 2.0, 2.0) == 0.5
        assert normalize_flow_accumulation(100.0, 100.0, 100.0) == 0.5
        assert normalize_imperviousness(0.5, 0.5, 0.5) == 0.5

    def test_negative_rainfall_clamped(self):
        """Verifies that negative rainfall is safely clamped to 0.0."""
        predictor = FloodRiskPredictor(mode="heuristic")
        pred = predictor.predict_from_forecast(rainfall_mm=-25.0, cell_id="CELL_NEG", horizon=1, persist=False)
        assert pred.probability >= 0.0
        assert pred.level == "LOW"

    def test_nan_rainfall_rejected(self):
        """Verifies that NaN or Infinite rainfall is strictly rejected."""
        predictor = FloodRiskPredictor(mode="heuristic")
        with pytest.raises(ValueError, match="Rainfall must be a finite number"):
            predictor.predict_from_forecast(rainfall_mm=float("nan"), cell_id="CELL_NAN", horizon=1, persist=False)
        with pytest.raises(ValueError, match="Rainfall must be a finite number"):
            predictor.predict_from_forecast(rainfall_mm=float("inf"), cell_id="CELL_INF", horizon=1, persist=False)

    def test_extremely_large_rainfall_capped(self):
        """Verifies that extreme hurricane rainfall (e.g. 10,000 mm) caps probability <= 1.0."""
        predictor = FloodRiskPredictor(mode="heuristic")
        pred = predictor.predict_from_forecast(rainfall_mm=10000.0, cell_id="CELL_EXTREME", horizon=3, persist=False)
        assert pred.probability <= 1.0
        assert pred.level == "HIGH"
        assert not math.isnan(pred.probability)

    def test_missing_hotspot_data_file(self, tmp_path: Path):
        """Verifies FileNotFoundError when hotspot file is missing."""
        with pytest.raises(FileNotFoundError):
            load_hotspots(tmp_path / "missing_hotspots.json")

    def test_malformed_hotspot_data(self, tmp_path: Path):
        """Verifies validation errors on malformed hotspot coordinates or negative triggers."""
        # Non-list JSON
        bad_json = tmp_path / "bad.json"
        bad_json.write_text('{"not": "a list"}', encoding="utf-8")
        with pytest.raises(ValueError, match="Expected list"):
            load_hotspots(bad_json)

        # Invalid latitude in Hotspot dataclass
        with pytest.raises(ValueError, match="Invalid latitude"):
            Hotspot(
                hotspot_id="HS_BAD",
                name="Bad Lat",
                city="Chennai",
                state="Tamil Nadu",
                zone="Zone 1",
                ward=1,
                latitude=95.0,
                longitude=80.2,
                elevation_m=5.0,
                hotspot_type="Road",
                severity_tier="High",
                typical_trigger_rain_1h_mm=30.0,
                typical_trigger_rain_6h_mm=60.0,
                historical_inundation_depth_m=1.0,
                primary_vulnerability_cause="Drainage",
                source_reference="GCC",
            )

    def test_incomplete_sensor_data_handling(self):
        """Verifies that sensor predict handles None/NaN water level without crash."""
        predictor = FloodRiskPredictor(mode="heuristic")
        pred = predictor.predict(water_level_cm=None, rainfall_rate_mm_h=None, persist=False)
        assert pred.probability == 0.15
        assert pred.level == "LOW"

        pred_nan = predictor.predict(water_level_cm=float("nan"), rainfall_rate_mm_h=float("nan"), persist=False)
        assert pred_nan.probability == 0.15
        assert pred_nan.level == "LOW"


# ===========================================================================
# 2. MODEL ROBUSTNESS ACROSS HORIZONS & VULNERABILITY
# ===========================================================================

class TestModelRobustness:
    """Verifies H1, H3, H6 response across the complete rainfall and vulnerability spectrum."""

    @pytest.mark.parametrize("h, r_crit", [(1, 50.0), (3, 80.0), (6, 120.0)])
    def test_horizon_critical_rainfall_response(self, h: int, r_crit: float):
        """Verifies horizon-specific saturation behavior and probability bounds."""
        predictor = FloodRiskPredictor(mode="heuristic")

        # 0 mm rainfall
        p_zero = predictor.predict_from_forecast(rainfall_mm=0.0, cell_id="C0", horizon=h, vulnerability=0.5, persist=False)
        assert p_zero.probability == round(0.35 * 0.5, 4)
        assert p_zero.level == "LOW"

        # Just below critical threshold
        p_below = predictor.predict_from_forecast(rainfall_mm=r_crit - 0.1, cell_id="C0", horizon=h, vulnerability=0.5, persist=False)
        assert 0.0 <= p_below.probability <= 1.0

        # Exact critical threshold
        p_exact = predictor.predict_from_forecast(rainfall_mm=r_crit, cell_id="C0", horizon=h, vulnerability=0.5, persist=False)
        # 0.65 * 1.0 + 0.35 * 0.5 = 0.825 -> HIGH
        assert p_exact.probability == 0.825
        assert p_exact.level == "HIGH"

        # Extreme rainfall
        p_huge = predictor.predict_from_forecast(rainfall_mm=5000.0, cell_id="C0", horizon=h, vulnerability=1.0, persist=False)
        assert p_huge.probability == 1.0
        assert p_huge.level == "HIGH"

    @pytest.mark.parametrize("vuln", [0.0, 1.0, None, -0.5, 2.5, "invalid"])
    def test_vulnerability_boundary_and_invalid_values(self, vuln: Any):
        """Verifies vulnerability bounds clamping and graceful fallback to 0.50."""
        predictor = FloodRiskPredictor(mode="heuristic")
        pred = predictor.predict_from_forecast(rainfall_mm=25.0, cell_id="C_VULN", horizon=1, vulnerability=vuln, persist=False)
        assert not math.isnan(pred.probability)
        assert not math.isinf(pred.probability)
        assert 0.0 <= pred.probability <= 1.0
        assert pred.level in ("LOW", "MEDIUM", "HIGH")


# ===========================================================================
# 3. ML ARTIFACT FAILURE & FALLBACK TRANSPARENCY
# ===========================================================================

class TestMLArtifactFailure:
    """Verifies behavior when ML model files are missing, corrupted, or directories absent."""

    def test_missing_model_directory_raises_on_direct_load(self, tmp_path: Path):
        """XGBoostFloodModel.load raises FileNotFoundError if model directory does not exist."""
        model = XGBoostFloodModel()
        with pytest.raises(FileNotFoundError, match="Model directory not found"):
            model.load(tmp_path / "nonexistent_dir")

    def test_missing_horizon_model_file_raises_on_direct_load(self, tmp_path: Path):
        """XGBoostFloodModel.load raises FileNotFoundError if a required horizon model is missing."""
        import shutil
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        src_h1 = Path("data/m1/models/model_h1.json")
        if src_h1.is_file():
            shutil.copy2(src_h1, model_dir / "model_h1.json")
        else:
            pytest.skip("Base trained model not found")

        model = XGBoostFloodModel()
        with pytest.raises(FileNotFoundError, match="not found for horizon"):
            model.load(model_dir)

    def test_corrupted_model_file_fails_safely(self, tmp_path: Path):
        """Corrupted JSON/binary model files raise when loaded directly."""
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        for h in (1, 3, 6):
            (model_dir / f"model_h{h}.json").write_text("NOT_VALID_XGBOOST_JSON", encoding="utf-8")

        model = XGBoostFloodModel()
        with pytest.raises(Exception):
            model.load(model_dir)

    def test_predictor_fallback_transparency_when_models_missing(self, tmp_path: Path):
        """XGBoostRiskPredictor with allow_fallback=True uses heuristic and explicitly tags fallback."""
        empty_dir = tmp_path / "empty_models"
        empty_dir.mkdir()

        predictor = XGBoostRiskPredictor(model_dir=empty_dir, allow_fallback=True)
        assert not predictor.model.is_trained

        pred = predictor.predict_from_forecast(rainfall_mm=60.0, cell_id="CELL_FB", horizon=1, persist=False, explain=True)
        # Must clearly identify fallback mode
        assert pred.mode == "heuristic_fallback"
        assert pred.explanation is not None
        assert pred.explanation.get("prediction_mode") == "heuristic_fallback"
        assert pred.explanation.get("fallback_used") is True
        assert pred.level in ("LOW", "MEDIUM", "HIGH")

    def test_predictor_raises_when_models_missing_and_fallback_disabled(self, tmp_path: Path):
        """XGBoostRiskPredictor with allow_fallback=False raises RuntimeError instead of silent fallback."""
        empty_dir = tmp_path / "empty_models"
        empty_dir.mkdir()

        predictor = XGBoostRiskPredictor(model_dir=empty_dir, allow_fallback=False)
        with pytest.raises(RuntimeError, match="XGBoost models are not loaded and fallback is disabled"):
            predictor.predict_from_forecast(rainfall_mm=60.0, cell_id="CELL_FB", horizon=1, persist=False)


# ===========================================================================
# 4. PIPELINE FAILURE ISOLATION
# ===========================================================================

class TestPipelineFailureIsolation:
    """Verifies that pipeline isolates bad cells, reports partial successes, and exposes structured failures."""

    def test_pipeline_raises_on_empty_database(self, tmp_path: Path, monkeypatch):
        """Empty database raises ForecastUnavailableError when weather fetch cannot recover."""
        import src.pipeline
        def mock_fetch(*args, **kwargs):
            raise RuntimeError("Weather network offline")
        monkeypatch.setattr(src.pipeline, "fetch_and_store_forecast", mock_fetch)

        empty_db = tmp_path / "empty.db"
        with pytest.raises(ForecastUnavailableError):
            run_pipeline(db_path=empty_db, persist=False)

    def test_pipeline_raises_on_empty_cells_table(self, tmp_path: Path):
        """Database with forecast but empty cells table raises EmptyCellsError."""
        db_path = tmp_path / "no_cells.db"
        with get_db_connection(db_path) as conn:
            conn.execute("CREATE TABLE forecasts (id INTEGER PRIMARY KEY, timestamp TEXT, rain_1h REAL, rain_3h REAL, rain_6h REAL);")
            conn.execute("INSERT INTO forecasts (timestamp, rain_1h, rain_3h, rain_6h) VALUES ('2026-09-27T00:00:00Z', 10.0, 20.0, 30.0);")
            conn.execute("CREATE TABLE cells (id TEXT PRIMARY KEY, geometry TEXT, elevation REAL, slope REAL, flow_acc REAL, vulnerability REAL);")
            conn.commit()

        with pytest.raises(EmptyCellsError):
            run_pipeline(db_path=db_path, persist=False)

    def test_pipeline_isolates_corrupted_cell_and_reports_partial_success(self, tmp_path: Path, monkeypatch):
        """When 1 cell encounters an exception during prediction, pipeline succeeds for valid cells and records failure."""
        db_path = tmp_path / "partial.db"
        with get_db_connection(db_path) as conn:
            conn.execute("CREATE TABLE forecasts (id INTEGER PRIMARY KEY, timestamp TEXT, rain_1h REAL, rain_3h REAL, rain_6h REAL);")
            conn.execute("INSERT INTO forecasts (timestamp, rain_1h, rain_3h, rain_6h) VALUES ('2026-09-27T00:00:00Z', 15.0, 25.0, 35.0);")
            conn.execute("CREATE TABLE cells (id TEXT PRIMARY KEY, geometry TEXT, elevation REAL, slope REAL, flow_acc REAL, vulnerability REAL);")
            conn.execute("INSERT INTO cells (id, elevation, slope, flow_acc, vulnerability) VALUES ('CELL_GOOD_01', 10.0, 1.0, 1000.0, 0.50);")
            conn.execute("INSERT INTO cells (id, elevation, slope, flow_acc, vulnerability) VALUES ('CELL_BAD_01', 5.0, 0.2, 50000.0, 0.90);")
            conn.execute("INSERT INTO cells (id, elevation, slope, flow_acc, vulnerability) VALUES ('CELL_GOOD_02', 12.0, 1.5, 500.0, 0.40);")
            conn.commit()

        # Monkeypatch FloodRiskPredictor.predict_from_forecast to raise for CELL_BAD_01
        orig_predict = FloodRiskPredictor.predict_from_forecast

        def patched_predict(self, *args, **kwargs):
            cid = kwargs.get("cell_id", "")
            if cid == "CELL_BAD_01":
                raise RuntimeError("Corrupted cell telemetry / sensor divergence")
            return orig_predict(self, *args, **kwargs)

        monkeypatch.setattr(FloodRiskPredictor, "predict_from_forecast", patched_predict)

        res = run_pipeline(db_path=db_path, horizons=[1], persist=False)
        assert res.cells_processed == 3
        assert res.predictions_created == 2  # Good cells succeeded
        assert res.failed_cell_count == 1   # Bad cell isolated
        assert len(res.failed_cells) == 1

        failed = res.failed_cells[0]
        assert failed["cell_id"] == "CELL_BAD_01"
        assert failed["stage"] == "prediction"
        assert failed["error_type"] == "RuntimeError"
        assert "Corrupted cell telemetry" in failed["message"]
        assert failed["recoverable"] is True


# ===========================================================================
# 5. EXPLAINABILITY ROBUSTNESS
# ===========================================================================

class TestExplainabilityRobustness:
    """Verifies that M1 Day 4 explainability functions never crash and adhere to non-causal rules."""

    @pytest.mark.parametrize("risk_level, rain, prob", [
        ("LOW", 0.0, 0.05),
        ("MEDIUM", 25.0, 0.55),
        ("HIGH", 150.0, 0.95),
    ])
    def test_explain_prediction_across_risk_tiers(self, risk_level: str, rain: float, prob: float):
        """Verifies valid explanation structure and top factor normalization across tiers."""
        feature_dict = {
            "rainfall_mm": rain,
            "rain_past_24h": 10.0,
            "vulnerability_score": 0.65,
            "elevation": 8.0,
            "slope": 0.5,
            "flow_accumulation": 10000.0,
            "imperviousness": 0.70,
            "trigger_rain_threshold": 40.0,
            "is_hotspot": 1.0,
        }
        feature_importances = {"rainfall_mm": 0.40, "vulnerability_score": 0.25}

        expl = explain_prediction(
            feature_dict=feature_dict,
            feature_importances=feature_importances,
            risk_level=risk_level,
            probability=prob,
            horizon=3,
            cell_id="CELL_TEST",
        )

        assert expl.risk_level == risk_level
        assert expl.probability == prob
        assert len(expl.top_factors) > 0
        for f in expl.top_factors:
            assert not math.isnan(f.importance)
            assert f.importance >= 0.0
            assert f.direction in ("increases_risk", "decreases_risk", "neutral")
        assert "disclaimer" in expl.to_dict()
        assert "NOT proven physical causation" in expl.disclaimer
        assert len(expl.summary) > 0

    def test_explain_with_empty_feature_importances_and_zero_rain(self):
        """Explainability handles missing importances and zero rainfall without ZeroDivisionError."""
        feature_dict = {
            "rainfall_mm": 0.0,
            "rain_past_24h": 0.0,
            "vulnerability_score": 0.50,
            "elevation": 12.0,
            "slope": 1.0,
            "flow_accumulation": 1000.0,
            "imperviousness": 0.50,
        }
        expl = explain_prediction(
            feature_dict=feature_dict,
            feature_importances={},
            risk_level="LOW",
            probability=0.0,
            horizon=1,
            cell_id="CELL_ZERO",
        )
        assert expl.top_factors[0].importance > 0.0
        assert not math.isnan(expl.top_factors[0].importance)


# ===========================================================================
# 6. BACKTEST ROBUSTNESS
# ===========================================================================

class TestBacktestRobustness:
    """Verifies that calculate_binary_metrics handles mathematical edge cases cleanly without fabrication."""

    def test_empty_sample_set(self):
        """Empty inputs return None for metrics rather than crashing or inventing values."""
        rec = calculate_binary_metrics(y_true=[], y_pred=[], y_prob=[])
        assert rec.n_samples == 0
        assert rec.precision is None
        assert rec.recall is None
        assert rec.f1 is None
        assert rec.roc_auc is None
        assert rec.pr_auc is None
        assert rec.brier is None

    def test_no_positive_labels(self):
        """When y_true contains only 0s, ROC-AUC and PR-AUC are None; precision is 0.0 if false positives occur."""
        # Case A: 0 positives in truth, 0 positive predictions -> ROC/PR-AUC None
        y_true = [0, 0, 0, 0, 0]
        y_pred = [0, 0, 0, 0, 0]
        y_prob = [0.1, 0.2, 0.05, 0.15, 0.1]
        rec = calculate_binary_metrics(y_true=y_true, y_pred=y_pred, y_prob=y_prob)
        assert rec.n_positive == 0
        assert rec.roc_auc is None
        assert rec.pr_auc is None
        assert rec.brier is not None
        assert rec.brier < 0.1

        # Case B: 0 positives in truth, but model predicts positive -> precision is 0.0, recall is None
        rec_fp = calculate_binary_metrics(y_true=[0, 0, 0], y_pred=[1, 0, 0], y_prob=[0.8, 0.1, 0.2])
        assert rec_fp.precision == 0.0
        assert rec_fp.recall is None
        assert rec_fp.roc_auc is None

    def test_no_negative_labels(self):
        """When y_true contains only 1s, ROC-AUC is undefined (None)."""
        y_true = [1, 1, 1, 1]
        y_pred = [1, 1, 1, 1]
        y_prob = [0.9, 0.85, 0.95, 0.8]
        rec = calculate_binary_metrics(y_true=y_true, y_pred=y_pred, y_prob=y_prob)
        assert rec.roc_auc is None
        assert rec.recall == 1.0
        assert rec.precision == 1.0

    def test_zero_predicted_positives(self):
        """When no samples are predicted positive, precision is None."""
        y_true = [1, 0, 1, 0]
        y_pred = [0, 0, 0, 0]
        y_prob = [0.2, 0.1, 0.3, 0.1]
        rec = calculate_binary_metrics(y_true=y_true, y_pred=y_pred, y_prob=y_prob)
        assert rec.n_predicted_positive == 0
        assert rec.precision is None
        assert rec.recall == 0.0
        assert rec.f1 == 0.0

    def test_constant_probabilities_roc_auc(self):
        """Constant probabilities produce 0.50 ROC-AUC with tie resolution."""
        y_true = [1, 0, 1, 0]
        y_prob = [0.5, 0.5, 0.5, 0.5]
        y_pred = [1, 1, 1, 1]
        rec = calculate_binary_metrics(y_true=y_true, y_pred=y_pred, y_prob=y_prob)
        assert rec.roc_auc == 0.50


# ===========================================================================
# 7. BOUNDARY TESTS
# ===========================================================================

class TestBoundaryConditions:
    """Verifies exact risk probability thresholds and horizon boundaries."""

    @pytest.mark.parametrize("prob, expected_level", [
        (0.0, "LOW"),
        (0.3999, "LOW"),
        (0.4000, "MEDIUM"),
        (0.6999, "MEDIUM"),
        (0.7000, "HIGH"),
        (1.0000, "HIGH"),
    ])
    def test_risk_classification_boundaries(self, prob: float, expected_level: str):
        """Verifies deterministic classification cutoffs at 0.40 and 0.70."""
        assert classify_risk_score(prob, uppercase=True) == expected_level

    @pytest.mark.parametrize("horizon, valid", [
        (1, True),
        (3, True),
        (6, True),
        (0, False),
        (2, False),
        (4, False),
        (12, False),
        (-1, False),
    ])
    def test_horizon_validation_boundaries(self, horizon: int, valid: bool):
        """Verifies that only horizons 1, 3, and 6 are accepted; others raise ValueError."""
        predictor = FloodRiskPredictor(mode="heuristic")
        if valid:
            pred = predictor.predict_from_forecast(rainfall_mm=20.0, cell_id="C", horizon=horizon, persist=False)
            assert pred.horizon == horizon
        else:
            with pytest.raises(ValueError, match="Invalid horizon"):
                predictor.predict_from_forecast(rainfall_mm=20.0, cell_id="C", horizon=horizon, persist=False)


# ===========================================================================
# 8. DATA CONTRACT VALIDATION
# ===========================================================================

class TestDataContractValidation:
    """Verifies strict validation of risk predictions and sensor readings."""

    def test_valid_risk_prediction_contract(self):
        """Valid risk prediction contract passes."""
        valid_payload = {
            "cell_id": "CELL_R01_C01",
            "timestamp": "2026-09-27T01:00:00Z",
            "horizon": 3,
            "level": "MEDIUM",
            "probability": 0.55,
        }
        ok, msg = validate_risk_prediction_contract(valid_payload)
        assert ok is True
        assert msg is None

    @pytest.mark.parametrize("bad_field, bad_val", [
        ("cell_id", ""),
        ("timestamp", ""),
        ("horizon", 2),
        ("level", "CRITICAL"),
        ("probability", -0.1),
        ("probability", 1.5),
        ("probability", float("nan")),
    ])
    def test_invalid_risk_prediction_contract_rejected(self, bad_field: str, bad_val: Any):
        """Invalid fields in risk prediction contract are rejected with explanatory message."""
        payload = {
            "cell_id": "CELL_VALID",
            "timestamp": "2026-09-27T01:00:00Z",
            "horizon": 1,
            "level": "LOW",
            "probability": 0.20,
        }
        payload[bad_field] = bad_val
        ok, msg = validate_risk_prediction_contract(payload)
        assert ok is False
        assert msg is not None

    def test_valid_sensor_reading_contract(self):
        """Valid sensor reading contract passes."""
        valid_sensor = {
            "sensor_id": "NODE_VEL_01",
            "timestamp": "2026-09-27T01:00:00Z",
            "level_cm": 45.0,
            "status": "ACTIVE",
            "source": "simulated",
        }
        ok, msg = validate_sensor_reading_contract(valid_sensor)
        assert ok is True
        assert msg is None

    @pytest.mark.parametrize("bad_field, bad_val", [
        ("sensor_id", ""),
        ("timestamp", ""),
        ("level_cm", -10.0),
        ("level_cm", float("nan")),
        ("status", "BROKEN"),
    ])
    def test_invalid_sensor_reading_contract_rejected(self, bad_field: str, bad_val: Any):
        """Invalid sensor readings are rejected with explanatory message."""
        payload = {
            "sensor_id": "NODE_VEL_01",
            "timestamp": "2026-09-27T01:00:00Z",
            "level_cm": 50.0,
            "status": "ACTIVE",
            "source": "simulated",
        }
        payload[bad_field] = bad_val
        ok, msg = validate_sensor_reading_contract(payload)
        assert ok is False
        assert msg is not None


# ===========================================================================
# 9. STRUCTURED FAILURE REPRESENTATION
# ===========================================================================

class TestStructuredFailureRepresentation:
    """Verifies CellFailureRecord serialization."""

    def test_cell_failure_record_serialization(self):
        """Verifies structured failure dictionary format."""
        record = CellFailureRecord(
            cell_id="CELL_TEST_99",
            stage="prediction",
            error_type="ValueError",
            message="Invalid rainfall value: NaN",
            recoverable=True,
            horizon=3,
        )
        d = record.to_dict()
        assert d["cell_id"] == "CELL_TEST_99"
        assert d["stage"] == "prediction"
        assert d["error_type"] == "ValueError"
        assert d["message"] == "Invalid rainfall value: NaN"
        assert d["recoverable"] is True
        assert d["horizon"] == 3
