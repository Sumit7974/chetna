# Chetna M1 Final Validation Report

**Validated**: 2026-09-27
**Validator**: M1 Day 7 automated rehearsal
**Repository**: `C:\Users\ABC\chetna`
**Status**: FINAL VALIDATION COMPLETE — No commits or pushes were made during this pass.

---

## 1. Scope

M1 is the machine-learning flood-risk prediction prototype for Chetna.
It spans M1 Days 1–7 and produces neighbourhood-scale, horizon-specific
(`+1h / +3h / +6h`) flood-risk predictions for the Chennai pilot area.

M1 builds on top of the existing B1/B2 data pipeline:

```
Open-Meteo Forecast  →  Forecast Ingestion (B1 Day 2)
                     →  Spatial Grid / DEM (B1 Day 1)
                     →  Static Vulnerability (M1 Day 2)
                     →  ML / Heuristic Predictor (M1 Day 3)
                     →  Risk Tier + Explanation (M1 Day 4)
                     →  Backtest Evaluation (M1 Day 5)
                     →  Failure Isolation (M1 Day 6)
                     →  Final Validation (M1 Day 7)
```

**M1 is a software prototype** using proxy labels, simulated sensors, and
calibrated synthetic grid data. It is **not** an operationally validated flood-
warning system.

---

## 2. Day-by-Day Status

| Day | Focus | Files | Status |
|---|---|---|---|
| **M1 Day 1** | Hotspot / event dataset, historical events, proxy labeling, grid mapping | `src/static_risk/hotspots.py`, `scripts/generate_m1_dataset.py`, `data/m1/hotspots.*`, `data/m1/hotspot_event_observations.*` | ✅ COMPLETE |
| **M1 Day 2** | Elevation / slope / flow accumulation / imperviousness vulnerability score | `src/static_risk/vulnerability.py`, `scripts/compute_static_risk.py`, `data/m1/static_risk_scores.*` | ✅ COMPLETE |
| **M1 Day 3** | Proxy dataset, hotspot calibration, XGBoost H1/H3/H6, ML predictor, heuristic fallback | `src/model/ml_dataset.py`, `src/model/ml_predictor.py`, `scripts/train_m1_model.py`, `data/m1/proxy_training_dataset.*`, `data/models/model_h*.json` | ✅ COMPLETE |
| **M1 Day 4** | ML/static/dynamic explanation, persistence, human-readable summary, non-causal disclaimer | `src/model/ml_explainability.py`, `src/model/ml_evaluator.py` | ✅ COMPLETE |
| **M1 Day 5** | ML vs heuristic vs rainfall-baseline backtest, confusion matrices, proxy/in-sample limitations | `src/model/ml_backtest.py`, `scripts/backtest_m1.py`, `data/m1/backtest/` | ✅ COMPLETE |
| **M1 Day 6** | Input/model/pipeline failure isolation, boundary & contract validation, structured failures | `src/model/failure_isolation.py`, hardened `predictor.py`, `ml_predictor.py`, `pipeline.py`, `tests/test_m1_day6_robustness.py` | ✅ COMPLETE |
| **M1 Day 7** | Read-only end-to-end final validation rehearsal, report generation | `docs/M1_FINAL_VALIDATION.md`, README M1 Day 7 section | ✅ COMPLETE |

---

## 3. Test Results

### M1 Day 6 Robustness Tests (`test_m1_day6_robustness.py`)

| Metric | Result |
|---|---|
| **Collected** | 66 |
| **Passed** | **66** |
| **Failed** | 0 |
| **Duration** | ~6s |
| **Exit code** | 0 ✅ |

Test classes covered:

| Class | Tests | Coverage |
|---|---|---|
| `TestInputDataFailures` | 11 | Missing DEM, empty grid, NaN features, negative/NaN/extreme rainfall, malformed hotspots, incomplete sensors |
| `TestModelRobustness` | 9 | H1/H3/H6 rainfall spectrum, vulnerability boundaries (0.0, 1.0, None, -0.5, 2.5, "invalid") |
| `TestMLArtifactFailure` | 5 | Missing dir/file, corrupted model, fallback transparency, disabled-fallback RuntimeError |
| `TestPipelineFailureIsolation` | 3 | Empty DB, empty cells table, per-cell isolation with partial success |
| `TestExplainabilityRobustness` | 4 | LOW/MEDIUM/HIGH tiers, zero rain with empty importances |
| `TestBacktestRobustness` | 5 | Empty set, no positives, no negatives, zero predictions, constant probabilities |
| `TestBoundaryConditions` | 14 | Risk thresholds at 0.40/0.70, horizon validation 0/1/2/3/4/6/12/-1 |
| `TestDataContractValidation` | 12 | Valid/invalid risk payloads, valid/invalid sensor payloads |
| `TestStructuredFailureRepresentation` | 1 | `CellFailureRecord` serialization |

### Full Test Suite

| Metric | Result |
|---|---|
| **Collected** | 283 |
| **Passed** | **283** |
| **Failed** | 0 |
| **Duration** | ~104s |
| **Exit code** | 0 ✅ |

All 25 test files passing — B1, B2, M1 Days 1–6, integration, and database tests.

---

## 4. Data Artifacts

All artifacts validated as parseable and non-empty.

| Artifact | Type | Records | Status |
|---|---|---|---|
| `data/m1/hotspots.json` | JSON | 10 hotspots | ✅ Valid |
| `data/m1/hotspots.csv` | CSV | 10 rows | ✅ Valid |
| `data/m1/hotspot_event_observations.json` | JSON | 7 event groups | ✅ Valid |
| `data/m1/hotspot_event_observations.csv` | CSV | 1,008 observation rows | ✅ Valid |
| `data/m1/static_risk_scores.json` | JSON | 9 items | ✅ Valid |
| `data/m1/static_risk_scores.csv` | CSV | 38 rows | ✅ Valid |
| `data/m1/proxy_training_dataset.json` | JSON | 16,416 samples | ✅ Valid |
| `data/m1/proxy_training_dataset.csv` | CSV | 16,416 rows | ✅ Valid |
| `data/m1/models/model_h1.json` | XGBoost JSON | learner + version | ✅ Valid |
| `data/m1/models/model_h3.json` | XGBoost JSON | learner + version | ✅ Valid |
| `data/m1/models/model_h6.json` | XGBoost JSON | learner + version | ✅ Valid |
| `data/m1/models/model_metadata.json` | JSON | 7 keys | ✅ Valid |
| `data/m1/backtest/results.json` | JSON | metadata + 18 event records + 9 agg + 27 CMs | ✅ Valid |
| `data/m1/backtest/results.csv` | CSV | 27 rows | ✅ Valid |
| `data/m1/backtest/confusion_matrices.json` | JSON | 27 matrices | ✅ Valid |
| `data/m1/backtest_events.json` | JSON | 2 historical events | ✅ Valid |
| `data/m1/michaung_2023_rainfall.json` | JSON | 13 items | ✅ Valid |
| `data/m1/nov_2021_rainfall.json` | JSON | 13 items | ✅ Valid |

Model artifacts also mirrored at `data/models/model_h*.json` for pipeline access.

---

## 5. Model Validation

### Model Metadata (from `model_metadata.json`)

- **Type**: XGBoost (`xgboost`)
- **Version**: 1.0
- **Features**: `rainfall_mm`, `rain_past_24h`, `elevation`, `slope`, `flow_accumulation`, `imperviousness`, `vulnerability_score`, `trigger_rain_threshold`, `is_hotspot`
- **Horizons**: H1, H3, H6
- **Trained at**: 2026-09-26

### In-Sample Proxy Metrics (proxy labels — not ground truth)

| Horizon | Samples | Positives | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|---|---|
| H1 | 1,095 | 56 | 1.000 | 0.982 | 0.991 | 0.9999 |
| H3 | 1,095 | 123 | 0.959 | 0.959 | 0.959 | 0.9995 |
| H6 | 1,095 | 160 | 1.000 | 0.975 | 0.987 | 0.9998 |

> [!WARNING]
> These metrics reflect in-sample fitting on calibrated proxy labels, not operational accuracy.
> Every metric record carries `is_proxy_evaluation: true` and an explicit disclaimer.

### H1/H3/H6 Contract Verification (M1 Day 7)

Tested rainfall values: 0 mm, 25 mm, 60 mm, 120 mm.

| Mode | H1 | H3 | H6 |
|---|---|---|---|
| ML (`mode="ml"`) | ✅ prob ∈ [0,1], level valid | ✅ | ✅ |
| Heuristic (`mode="heuristic"`) | ✅ | ✅ | ✅ |
| Graceful fallback (`mode="heuristic_fallback"`) | ✅ | ✅ | ✅ |
| Explanation (ML, `explain=True`) | ✅ `top_factors` + `summary` present | ✅ | ✅ |

**Default predictor mode**: `"heuristic"` — unchanged throughout M1.

---

## 6. Pipeline Validation

End-to-end pipeline test using in-memory SQLite with 3 seeded cells and 1 seeded forecast record:

```
Forecast → SQLite read → 3 cells × 3 horizons → 9 predictions → 0 failures
```

| Metric | Result |
|---|---|
| `cells_processed` | 3 |
| `predictions_created` | 9 |
| `horizons_processed` | [1, 3, 6] |
| `failed_cell_count` | 0 |
| All predictions level-valid | ✅ |
| All predictions prob ∈ [0,1] | ✅ |
| Explanations populated | ✅ |

Pipeline flow verified:

```
Forecast input (rain_1h / rain_3h / rain_6h)
     ↓
Feature generation (vulnerability from cells table)
     ↓
Static vulnerability (M1 Day 2 scores per cell)
     ↓
Heuristic / ML prediction (FloodRiskPredictor)
     ↓
Risk tier + probability [0, 1]
     ↓
Explanation (top_factors + human-readable summary)
     ↓
Database persistence (risk_predictions table)
     ↓
PipelineResult (cells_processed, predictions_created, failed_cells)
```

---

## 7. Backtest Validation

Backtest output inspected from `data/m1/backtest/results.json`.

| Attribute | Value |
|---|---|
| Generated at | 2026-09-26T20:02:46 |
| Model version | 1.0 |
| Events | EVT_2021_NOV_DEPRESSION, EVT_2023_MICHAUNG |
| Methods | `ml`, `heuristic`, `rainfall_threshold` |
| Horizons | H1, H3, H6 |
| Event records | 18 (2 events × 3 methods × 3 horizons) |
| Aggregate records | 9 (3 methods × 3 horizons) |
| Confusion matrices | 27 |
| All metrics ∈ [0,1] or None | ✅ |
| `is_proxy_evaluation` in records | ✅ |
| `limitations` in metadata | ✅ |

**Limitations recorded in backtest metadata**:

1. Evaluated against calibrated proxy development labels, not ground-truth physical sensor measurements.
2. Historical events limited to 2 events (Michaung Dec 2023 and Nov 2021).
3. Prototype XGBoost models evaluated here share training data with the backtest set (in-sample benchmark).
4. Rainfall baseline uses uniform rainfall thresholds without terrain vulnerability.

---

## 8. Robustness Validation (M1 Day 6 Summary)

All 66 robustness tests pass. Key behaviours confirmed:

| Failure Class | Behaviour | Verified |
|---|---|---|
| Missing ML model artifacts | Falls back to heuristic; sets `mode="heuristic_fallback"` | ✅ |
| NaN/Inf rainfall input | Raises `ValueError`; caught by per-cell isolation | ✅ |
| Negative rainfall | Silently clamped to 0.0 mm | ✅ |
| NaN vulnerability | Silently defaults to 0.50 | ✅ |
| NaN/Inf static features | Imputed with physical defaults; `was_imputed=True` | ✅ |
| Empty grid | Rejected with `ValueError` | ✅ |
| Empty database | Raises `EmptyCellsError` or `ForecastUnavailableError` | ✅ |
| Per-cell prediction error | Isolated to `failed_cells`; pipeline continues | ✅ |
| Invalid horizon (e.g. +2h) | Raises `ValueError` | ✅ |
| Corrupted model file | Raises explicit deserialization error | ✅ |
| Empty backtest set | Returns `None` metrics (no fabricated numbers) | ✅ |

**Per-cell failure isolation**: verified via `test_pipeline_isolates_corrupted_cell_and_reports_partial_success`.

---

## 9. Limitations

> [!CAUTION]
> The following limitations are preserved in all metric records, metadata, and documentation.

1. **Proxy Labels**: Target labels (`waterlogged_proxy` / `flood_risk_proxy`) are synthetic indicators derived from GCC municipal heuristics and historical flood reports — not calibrated gauge telemetry.

2. **In-Sample Benchmark**: The XGBoost models were trained and evaluated on overlapping data partitions from the same pilot events. High metric scores reflect in-sample fitting capacity, not out-of-sample operational generalization.

3. **Limited Historical Events**: Backtest uses only 2 events (Cyclone Michaung Dec 2023 and Nov 2021 Depression). Generalisation to other storm types is untested.

4. **Simulated Sensors**: All water-level readings in B2 are simulated. No real IoT sensor data was ingested during M1.

5. **Estimated Drainage Capacity**: Hotspot trigger rainfall thresholds are estimated from GCC documentation — not measured hydraulic capacity data.

6. **No Physical Validation**: The system has not been validated against streamflow gauges, ultrasonic depth sensors, or official GCC alert records.

7. **Rain-Driven Only**: Risk is driven entirely by forecast rainfall and static terrain vulnerability. Antecedent soil moisture, tidal backwater, and urban drainage dynamics are not modelled.

8. **Not Operational**: The default pipeline predictor mode remains `"heuristic"`. The ML model must not be used for evacuation decisions or operational warnings without physical gauge validation.

---

## 10. Demo-Readiness Checklist

- [x] Static vulnerability map (`data/m1/static_risk_scores.*`)
- [x] Forecast ingestion (Open-Meteo + JSON cache + SQLite `forecasts` table)
- [x] H1/H3/H6 predictions (XGBoost + heuristic fallback)
- [x] Risk tiers (LOW / MEDIUM / HIGH at prob <0.40 / <0.70 / ≥0.70)
- [x] Risk explanations with non-causal disclaimer
- [x] Backtest results (ML / heuristic / rainfall-threshold, 2 events × H1/H3/H6)
- [x] Failure handling & structured error isolation (per-cell `CellFailureRecord`)
- [x] Existing B1/B2 integration preserved (283/283 tests pass)
- [x] Dashboard integration stubs present (B2 Day 2–4, F1/F2)
- [x] No broken tests

---

## Final Verdict

**M1 Day 7 FINAL VALIDATION: COMPLETE**

All 283 tests pass. All M1 data artifacts validated. Model contract verified for H1/H3/H6 in both ML and heuristic modes. End-to-end pipeline produces 9 valid predictions from 3 cells with 0 failures. Backtest output contains all required methods, horizons, events, and prototype-limitation disclaimers. Failure-isolation layer confirmed. README updated with M1 Day 7 status.

No source code was modified. No commits or pushes were made.
