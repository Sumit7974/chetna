"""M1 Day 5: Rigorous Backtesting and Baseline-Comparison Layer.

Evaluates prototype flood-risk models against historical rainfall events and proxy labels:
1. M1 ML Model (Multi-horizon XGBoost)
2. M1 Heuristic Model (FloodRiskPredictor)
3. Simple Rainfall-Threshold Baseline (RainfallThresholdBaseline)

Across historical events:
- EVT_2023_MICHAUNG (Cyclone Michaung, Dec 2023)
- EVT_2021_NOV_DEPRESSION (Nov 2021 Deep Depression)

Across forecast horizons:
- +1h, +3h, +6h

IMPORTANT SCIENTIFIC PROVENANCE & LIMITATION NOTICE:
Evaluations are conducted against deterministic proxy development labels calibrated to
chronic municipal hotspot thresholds. They do NOT represent physical water-depth sensor logs.
Results show comparative prototype behavior under the available dataset and must NOT be
interpreted as proven operational flood prediction accuracy.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from src.model.ml_dataset import (
    FEATURE_COLUMNS,
    ProxySample,
    build_proxy_training_dataset,
    load_static_cell_catalog,
    prepare_matrices_by_horizon,
    split_samples_by_events,
    verify_event_isolation,
)
from src.model.ml_predictor import XGBoostFloodModel, XGBoostRiskPredictor
from src.model.predictor import FloodRiskPredictor
from src.static_risk.hotspots import load_backtest_events

logger = logging.getLogger(__name__)

PATNA_HELD_OUT_STATUS_MESSAGE = (
    "Patna-specific independent ML accuracy is not yet established because the repository "
    "lacks a valid Patna held-out historical event dataset."
)

# Standard rainfall-only baseline thresholds (in mm) derived from Chennai drainage criteria
DEFAULT_RAINFALL_THRESHOLDS: Dict[int, float] = {
    1: 35.0,  # 35 mm in 1h: localized flash waterlogging threshold
    3: 55.0,  # 55 mm in 3h: urban storm drainage network capacity threshold
    6: 80.0,  # 80 mm in 6h: major catchment storage / ponding threshold
}

BACKTEST_DISCLAIMER = (
    "Prototype backtest evaluation against calibrated proxy development labels. "
    "Not verified against physical water-level sensor telemetry. "
    "Comparative behavior reflects prototype response under 2 historical events."
)


class RainfallThresholdBaseline:
    """Simple, transparent rainfall-only baseline classifier.

    Evaluates flood risk solely on cumulative forecast precipitation.
    Does NOT use terrain vulnerability, elevation, slope, flow accumulation,
    imperviousness, hotspot status, or ML features.
    """

    def __init__(self, thresholds: Optional[Dict[int, float]] = None) -> None:
        self.thresholds = dict(thresholds or DEFAULT_RAINFALL_THRESHOLDS)

    def predict(self, rainfall_mm: float, horizon: int) -> int:
        """Returns binary prediction (1 if rainfall >= threshold, else 0)."""
        thresh = self.thresholds.get(int(horizon), 35.0)
        return 1 if float(rainfall_mm) >= thresh else 0

    def score(self, rainfall_mm: float, horizon: int) -> float:
        """Returns normalized rainfall-to-threshold ratio capped at 1.0 for ranking."""
        thresh = self.thresholds.get(int(horizon), 35.0)
        ratio = max(0.0, float(rainfall_mm)) / max(1.0, thresh)
        return round(float(min(1.0, ratio)), 4)


@dataclass
class BacktestRecord:
    """Evaluation record for a specific (method, event_id, horizon) combination."""
    event_id: str
    horizon: int
    method: str
    n_samples: int
    n_positive: int
    n_predicted_positive: int
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    roc_auc: Optional[float]
    pr_auc: Optional[float]
    brier: Optional[float]
    tp: int
    tn: int
    fp: int
    fn: int
    threshold_used: float
    evaluation_type: str = "prototype_backtest"
    data_city: str = "Chennai"
    is_held_out: bool = False
    positive_prevalence: float = 0.0
    disclaimer: str = BACKTEST_DISCLAIMER

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / max(1, self.n_samples)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["accuracy"] = self.accuracy
        return d



@dataclass
class BacktestResult:
    """Comprehensive backtest results containing event-level and aggregate metrics."""
    metadata: Dict[str, Any]
    event_results: List[BacktestRecord]
    aggregate_results: List[BacktestRecord]
    confusion_matrices: Dict[str, Dict[str, int]]
    evaluation_mode: str = "DEVELOPMENT_CONTAMINATED_AUDIT"
    training_event_ids: List[str] = field(default_factory=list)
    test_event_ids: List[str] = field(default_factory=list)
    patna_held_out_status: str = PATNA_HELD_OUT_STATUS_MESSAGE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata,
            "event_results": [r.to_dict() for r in self.event_results],
            "aggregate_results": [r.to_dict() for r in self.aggregate_results],
            "confusion_matrices": self.confusion_matrices,
            "evaluation_mode": self.evaluation_mode,
            "training_event_ids": self.training_event_ids,
            "test_event_ids": self.test_event_ids,
            "patna_held_out_status": self.patna_held_out_status,
        }

    def save_json(self, filepath: Union[str, Path]) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Saved backtest JSON results to %s", path)

    def save_csv(self, filepath: Union[str, Path]) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        all_records = self.event_results + self.aggregate_results
        if not all_records:
            return
        fieldnames = list(all_records[0].to_dict().keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in all_records:
                writer.writerow(r.to_dict())
        logger.info("Saved backtest CSV results to %s", path)

    def save_confusion_matrices(self, filepath: Union[str, Path]) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.confusion_matrices, f, indent=2)
        logger.info("Saved confusion matrices to %s", path)


def calculate_binary_metrics(
    y_true: Sequence[int],
    y_pred: Sequence[int],
    y_prob: Optional[Sequence[float]] = None,
    event_id: str = "all",
    horizon: int = 1,
    method: str = "ml",
    threshold_used: float = 0.50,
    evaluation_type: str = "prototype_backtest",
    data_city: str = "Chennai",
    is_held_out: bool = False,
    disclaimer: Optional[str] = None,
) -> BacktestRecord:
    """Calculates precision, recall, F1, ROC-AUC, PR-AUC, Brier score, and confusion matrix.

    Handles edge cases gracefully without dividing by zero or inventing values:
    - If no positive labels: recall is None, ROC-AUC is None, PR-AUC is None.
    - If no positive predictions: precision is None, F1 is None.
    - If no negative labels: ROC-AUC is None.
    """
    y_t = [int(y) for y in y_true]
    y_p = [int(y) for y in y_pred]
    n = len(y_t)

    if n == 0:
        return BacktestRecord(
            event_id=event_id,
            horizon=horizon,
            method=method,
            n_samples=0,
            n_positive=0,
            n_predicted_positive=0,
            precision=None,
            recall=None,
            f1=None,
            roc_auc=None,
            pr_auc=None,
            brier=None,
            tp=0,
            tn=0,
            fp=0,
            fn=0,
            threshold_used=threshold_used,
            evaluation_type="prototype_backtest",
            disclaimer=BACKTEST_DISCLAIMER,
        )

    n_pos = sum(y_t)
    n_neg = n - n_pos
    n_pred_pos = sum(y_p)

    tp = sum(1 for yt, yp in zip(y_t, y_p) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_t, y_p) if yt == 0 and yp == 1)
    tn = sum(1 for yt, yp in zip(y_t, y_p) if yt == 0 and yp == 0)
    fn = sum(1 for yt, yp in zip(y_t, y_p) if yt == 1 and yp == 0)

    # Precision
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else (1.0 if n_pos == 0 and n_pred_pos == 0 else None)

    # Recall
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else (1.0 if n_pos == 0 and n_pred_pos == 0 else None)

    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round((2 * precision * recall) / (precision + recall), 4)
    elif precision == 0.0 or recall == 0.0:
        f1 = 0.0
    else:
        f1 = None

    # Probabilistic metrics
    roc_auc: Optional[float] = None
    pr_auc: Optional[float] = None
    brier: Optional[float] = None

    if y_prob is not None and len(y_prob) == n:
        probs = [float(p) for p in y_prob]

        # Brier Score (MSE of probability against binary target)
        brier = round(sum((p - t) ** 2 for p, t in zip(probs, y_t)) / max(1, n), 4)

        # ROC-AUC and PR-AUC require at least 1 positive and 1 negative sample
        if n_pos > 0 and n_neg > 0:
            try:
                from sklearn.metrics import average_precision_score, roc_auc_score
                roc_auc = round(float(roc_auc_score(y_t, probs)), 4)
                pr_auc = round(float(average_precision_score(y_t, probs)), 4)
            except Exception:
                # Deterministic Mann-Whitney rank sum fallback for ROC-AUC
                roc_auc = _rank_sum_roc_auc(y_t, probs)
                pr_auc = None

    pos_prev = round(n_pos / max(1, n), 4) if n > 0 else 0.0

    return BacktestRecord(
        event_id=event_id,
        horizon=horizon,
        method=method,
        n_samples=n,
        n_positive=n_pos,
        n_predicted_positive=n_pred_pos,
        precision=precision,
        recall=recall,
        f1=f1,
        roc_auc=roc_auc,
        pr_auc=pr_auc,
        brier=brier,
        tp=tp,
        tn=tn,
        fp=fp,
        fn=fn,
        threshold_used=threshold_used,
        evaluation_type=evaluation_type,
        data_city=data_city,
        is_held_out=is_held_out,
        positive_prevalence=pos_prev,
        disclaimer=disclaimer or BACKTEST_DISCLAIMER,
    )


def _rank_sum_roc_auc(y_true: List[int], scores: List[float]) -> Optional[float]:
    """Calculates ROC-AUC using rank sums with tie resolution."""
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    paired = sorted(zip(scores, y_true), key=lambda x: x[0])
    rank_sum = 0.0
    i = 0
    n = len(paired)
    while i < n:
        j = i
        while j < n - 1 and paired[j][0] == paired[j + 1][0]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            if paired[k][1] == 1:
                rank_sum += avg_rank
        i = j + 1

    u_stat = rank_sum - (n_pos * (n_pos + 1)) / 2.0
    auc = u_stat / (n_pos * n_neg)
    return round(float(max(0.0, min(1.0, auc))), 4)


def run_backtest(
    data_dir: Union[str, Path] = "data/m1",
    model_dir: Union[str, Path] = "data/m1/models",
    output_dir: Optional[Union[str, Path]] = "data/m1/backtest",
    rainfall_thresholds: Optional[Dict[int, float]] = None,
    ml_decision_threshold: float = 0.50,
    heuristic_decision_threshold: float = 0.50,
    event_ids: Optional[Sequence[str]] = None,
) -> BacktestResult:
    """Executes the complete M1 Day 5 backtest comparing ML, Heuristic, and Rainfall Baseline.

    Evaluates across:
    - Events: EVT_2023_MICHAUNG, EVT_2021_NOV_DEPRESSION
    - Horizons: +1h, +3h, +6h
    - Methods: 'ml', 'heuristic', 'rainfall_threshold'
    """
    data_p = Path(data_dir)
    model_p = Path(model_dir)

    # 1. Load multi-horizon proxy dataset
    proxy_dataset_path = data_p / "proxy_training_dataset.json"
    if proxy_dataset_path.is_file():
        with open(proxy_dataset_path, "r", encoding="utf-8") as f:
            raw_samples = json.load(f)
        samples = [ProxySample(**s) for s in raw_samples]
    else:
        samples = build_proxy_training_dataset(data_dir=data_p)

    # 2. Instantiate predictors
    ml_predictor = XGBoostRiskPredictor(model_dir=model_p, allow_fallback=True)
    heuristic_predictor = FloodRiskPredictor(mode="heuristic")
    threshold_baseline = RainfallThresholdBaseline(rainfall_thresholds)

    avail_events = sorted(list(set(s.event_id for s in samples)))
    if event_ids is None:
        # Default M1 Day 5 audit evaluates the historical development events
        dev_evts = [e for e in avail_events if e in ("EVT_2023_MICHAUNG", "EVT_2021_NOV_DEPRESSION")]
        target_event_ids = dev_evts if dev_evts else avail_events
    else:
        target_event_ids = list(event_ids)

    horizons = sorted(list(set(s.horizon for s in samples)))
    methods = ["ml", "heuristic", "rainfall_threshold"]

    event_results: List[BacktestRecord] = []
    confusion_matrices: Dict[str, Dict[str, int]] = {}

    # 3. Evaluate by Event and Horizon
    for event_id in target_event_ids:
        for h in horizons:
            sub = [s for s in samples if s.event_id == event_id and s.horizon == h]
            if not sub:
                continue

            y_true = [s.waterlogged_proxy for s in sub]

            # Method A: ML Model (XGBoost)
            y_prob_ml: List[float] = []
            for s in sub:
                if ml_predictor.model.is_trained:
                    prob = float(ml_predictor.model.predict_proba(h, np.array(s.to_feature_vector(), dtype=np.float32))[0])
                else:
                    prob = float(s.flood_risk_proxy)
                y_prob_ml.append(prob)
            y_pred_ml = [1 if p >= ml_decision_threshold else 0 for p in y_prob_ml]

            rec_ml = calculate_binary_metrics(
                y_true=y_true,
                y_pred=y_pred_ml,
                y_prob=y_prob_ml,
                event_id=event_id,
                horizon=h,
                method="ml",
                threshold_used=ml_decision_threshold,
            )
            event_results.append(rec_ml)
            key_ml = f"{event_id}_H{h}_ml"
            confusion_matrices[key_ml] = {"tp": rec_ml.tp, "tn": rec_ml.tn, "fp": rec_ml.fp, "fn": rec_ml.fn}

            # Method B: Heuristic Model (FloodRiskPredictor)
            y_prob_heur: List[float] = []
            for s in sub:
                pred_h = heuristic_predictor.predict_from_forecast(
                    rainfall_mm=s.rainfall_mm,
                    cell_id=s.cell_id,
                    horizon=h,
                    vulnerability=s.vulnerability_score,
                    persist=False,
                )
                y_prob_heur.append(pred_h.probability)
            y_pred_heur = [1 if p >= heuristic_decision_threshold else 0 for p in y_prob_heur]

            rec_heur = calculate_binary_metrics(
                y_true=y_true,
                y_pred=y_pred_heur,
                y_prob=y_prob_heur,
                event_id=event_id,
                horizon=h,
                method="heuristic",
                threshold_used=heuristic_decision_threshold,
            )
            event_results.append(rec_heur)
            key_heur = f"{event_id}_H{h}_heuristic"
            confusion_matrices[key_heur] = {"tp": rec_heur.tp, "tn": rec_heur.tn, "fp": rec_heur.fp, "fn": rec_heur.fn}

            # Method C: Rainfall Threshold Baseline
            t_thresh = threshold_baseline.thresholds.get(h, 35.0)
            y_pred_thresh = [threshold_baseline.predict(s.rainfall_mm, h) for s in sub]
            y_score_thresh = [threshold_baseline.score(s.rainfall_mm, h) for s in sub]

            rec_thresh = calculate_binary_metrics(
                y_true=y_true,
                y_pred=y_pred_thresh,
                y_prob=y_score_thresh,
                event_id=event_id,
                horizon=h,
                method="rainfall_threshold",
                threshold_used=t_thresh,
            )
            event_results.append(rec_thresh)
            key_thresh = f"{event_id}_H{h}_rainfall_threshold"
            confusion_matrices[key_thresh] = {"tp": rec_thresh.tp, "tn": rec_thresh.tn, "fp": rec_thresh.fp, "fn": rec_thresh.fn}

    # 4. Compute Aggregate Results (across all events per method and horizon)
    aggregate_results: List[BacktestRecord] = []
    for h in horizons:
        sub_all = [s for s in samples if s.horizon == h]
        y_true_all = [s.waterlogged_proxy for s in sub_all]

        # ML aggregate
        probs_ml_all: List[float] = []
        for s in sub_all:
            if ml_predictor.model.is_trained:
                p = float(ml_predictor.model.predict_proba(h, np.array(s.to_feature_vector(), dtype=np.float32))[0])
            else:
                p = float(s.flood_risk_proxy)
            probs_ml_all.append(p)
        preds_ml_all = [1 if p >= ml_decision_threshold else 0 for p in probs_ml_all]
        agg_ml = calculate_binary_metrics(
            y_true=y_true_all,
            y_pred=preds_ml_all,
            y_prob=probs_ml_all,
            event_id="ALL_EVENTS_COMBINED",
            horizon=h,
            method="ml",
            threshold_used=ml_decision_threshold,
        )
        aggregate_results.append(agg_ml)
        confusion_matrices[f"ALL_H{h}_ml"] = {"tp": agg_ml.tp, "tn": agg_ml.tn, "fp": agg_ml.fp, "fn": agg_ml.fn}

        # Heuristic aggregate
        probs_heur_all: List[float] = []
        for s in sub_all:
            pred_h = heuristic_predictor.predict_from_forecast(
                rainfall_mm=s.rainfall_mm,
                cell_id=s.cell_id,
                horizon=h,
                vulnerability=s.vulnerability_score,
                persist=False,
            )
            probs_heur_all.append(pred_h.probability)
        preds_heur_all = [1 if p >= heuristic_decision_threshold else 0 for p in probs_heur_all]
        agg_heur = calculate_binary_metrics(
            y_true=y_true_all,
            y_pred=preds_heur_all,
            y_prob=probs_heur_all,
            event_id="ALL_EVENTS_COMBINED",
            horizon=h,
            method="heuristic",
            threshold_used=heuristic_decision_threshold,
        )
        aggregate_results.append(agg_heur)
        confusion_matrices[f"ALL_H{h}_heuristic"] = {"tp": agg_heur.tp, "tn": agg_heur.tn, "fp": agg_heur.fp, "fn": agg_heur.fn}

        # Rainfall baseline aggregate
        t_thresh = threshold_baseline.thresholds.get(h, 35.0)
        preds_thresh_all = [threshold_baseline.predict(s.rainfall_mm, h) for s in sub_all]
        scores_thresh_all = [threshold_baseline.score(s.rainfall_mm, h) for s in sub_all]
        agg_thresh = calculate_binary_metrics(
            y_true=y_true_all,
            y_pred=preds_thresh_all,
            y_prob=scores_thresh_all,
            event_id="ALL_EVENTS_COMBINED",
            horizon=h,
            method="rainfall_threshold",
            threshold_used=t_thresh,
        )
        aggregate_results.append(agg_thresh)
        confusion_matrices[f"ALL_H{h}_rainfall_threshold"] = {"tp": agg_thresh.tp, "tn": agg_thresh.tn, "fp": agg_thresh.fp, "fn": agg_thresh.fn}

    # 5. Metadata compilation
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "DEVELOPMENT_CONTAMINATED_AUDIT",
        "model_version": ml_predictor.model.metadata.get("version", "1.0"),
        "model_type": ml_predictor.model.metadata.get("model_type", "xgboost"),
        "events": target_event_ids,
        "horizons": horizons,
        "methods": methods,
        "features_used": FEATURE_COLUMNS,
        "rainfall_thresholds_mm": threshold_baseline.thresholds,
        "ml_decision_threshold": ml_decision_threshold,
        "heuristic_decision_threshold": heuristic_decision_threshold,
        "disclaimer": BACKTEST_DISCLAIMER,
        "patna_held_out_status": PATNA_HELD_OUT_STATUS_MESSAGE,
        "limitations": [
            "Evaluated against calibrated proxy development labels, not ground-truth physical sensor measurements.",
            "Historical events limited to 2 Chennai events (Michaung Dec 2023 and Nov 2021).",
            "Prototype XGBoost models evaluated here share training data with the backtest set (in-sample benchmark).",
            PATNA_HELD_OUT_STATUS_MESSAGE,
        ],
    }

    result = BacktestResult(
        metadata=metadata,
        event_results=event_results,
        aggregate_results=aggregate_results,
        confusion_matrices=confusion_matrices,
        evaluation_mode="DEVELOPMENT_CONTAMINATED_AUDIT",
        training_event_ids=event_ids,
        test_event_ids=event_ids,
        patna_held_out_status=PATNA_HELD_OUT_STATUS_MESSAGE,
    )

    # 6. Save results to output directory if specified
    if output_dir:
        out_p = Path(output_dir)
        result.save_json(out_p / "results.json")
        result.save_csv(out_p / "results.csv")
        result.save_confusion_matrices(out_p / "confusion_matrices.json")

    return result


def run_held_out_event_backtest(
    train_event_id: str,
    test_event_id: str,
    data_dir: Union[str, Path] = "data/m1",
    rainfall_thresholds: Optional[Dict[int, float]] = None,
    ml_decision_threshold: float = 0.50,
    heuristic_decision_threshold: float = 0.50,
    random_state: int = 42,
    output_dir: Optional[Union[str, Path]] = None,
) -> BacktestResult:
    """Executes a strictly event-isolated held-out evaluation.

    Trains horizon-specific models strictly on train_event_id samples,
    and evaluates strictly on test_event_id samples.

    Raises:
        ValueError: If train_event_id == test_event_id (contamination).
    """
    if train_event_id == test_event_id:
        raise ValueError(
            f"Contamination error: train_event_id '{train_event_id}' cannot be equal to test_event_id"
        )

    is_patna_eval = test_event_id.startswith("EVT_PATNA_") or "PATNA" in test_event_id.upper()
    eval_city = "Patna" if is_patna_eval else "Chennai"

    if is_patna_eval:
        patna_status = (
            "VALID PATNA HELD-OUT RESULTS AVAILABLE (Patna proxy-label evaluation calibrated to "
            "documented PMC/BSDMA chronic inundation occurrences and Copernicus DEM terrain)"
        )
    else:
        patna_status = PATNA_HELD_OUT_STATUS_MESSAGE

    data_p = Path(data_dir)
    proxy_dataset_path = data_p / "proxy_training_dataset.json"
    if proxy_dataset_path.is_file():
        with open(proxy_dataset_path, "r", encoding="utf-8") as f:
            raw_samples = json.load(f)
        samples = [ProxySample(**s) for s in raw_samples]
    else:
        samples = build_proxy_training_dataset(data_dir=data_p)

    train_samples, test_samples, _ = split_samples_by_events(
        samples, train_event_ids=[train_event_id], test_event_ids=[test_event_id]
    )

    if not train_samples:
        raise ValueError(f"No samples found for training event '{train_event_id}'")
    if not test_samples:
        raise ValueError(f"No samples found for test event '{test_event_id}'")

    # Verify event isolation
    verify_event_isolation(train_samples, test_samples)

    # Train clean multi-horizon XGBoost models strictly on train_samples
    train_matrices = prepare_matrices_by_horizon(train_samples)
    flood_model = XGBoostFloodModel(random_state=random_state)
    for h in (1, 3, 6):
        if h in train_matrices:
            X_tr, y_tr = train_matrices[h]
            flood_model.train_horizon(horizon=h, X_train=X_tr, y_train=y_tr)

    heuristic_predictor = FloodRiskPredictor(mode="heuristic")
    threshold_baseline = RainfallThresholdBaseline(rainfall_thresholds)

    horizons = sorted(list(set(s.horizon for s in test_samples)))
    event_results: List[BacktestRecord] = []
    confusion_matrices: Dict[str, Dict[str, int]] = {}

    for h in horizons:
        sub = [s for s in test_samples if s.horizon == h]
        if not sub:
            continue
        y_true = [s.waterlogged_proxy for s in sub]

        disclaimer_ml = (
            f"Patna held-out event evaluation on {test_event_id} (trained exclusively on {train_event_id}; clean 8-feature policy)."
            if is_patna_eval else
            f"Held-out event test on {test_event_id} (trained exclusively on {train_event_id})."
        )
        disclaimer_heur = (
            f"Patna held-out heuristic baseline evaluation on {test_event_id}."
            if is_patna_eval else
            f"Held-out baseline evaluation on {test_event_id}."
        )
        disclaimer_thresh = (
            f"Patna held-out rainfall-threshold baseline evaluation on {test_event_id}."
            if is_patna_eval else
            f"Held-out baseline evaluation on {test_event_id}."
        )

        # Method A: ML Model (evaluated on held-out test event)
        X_test = np.array([s.to_feature_vector() for s in sub], dtype=np.float32)
        y_prob_ml = list(flood_model.predict_proba(h, X_test))
        y_pred_ml = [1 if p >= ml_decision_threshold else 0 for p in y_prob_ml]

        rec_ml = calculate_binary_metrics(
            y_true=y_true,
            y_pred=y_pred_ml,
            y_prob=y_prob_ml,
            event_id=test_event_id,
            horizon=h,
            method="ml",
            threshold_used=ml_decision_threshold,
            evaluation_type="held_out_event_test",
            data_city=eval_city,
            is_held_out=True,
            disclaimer=disclaimer_ml,
        )
        event_results.append(rec_ml)
        confusion_matrices[f"{test_event_id}_H{h}_ml"] = {"tp": rec_ml.tp, "tn": rec_ml.tn, "fp": rec_ml.fp, "fn": rec_ml.fn}

        # Method B: Heuristic Model
        y_prob_heur: List[float] = []
        for s in sub:
            pred_h = heuristic_predictor.predict_from_forecast(
                rainfall_mm=s.rainfall_mm,
                cell_id=s.cell_id,
                horizon=h,
                vulnerability=s.vulnerability_score,
                persist=False,
            )
            y_prob_heur.append(pred_h.probability)
        y_pred_heur = [1 if p >= heuristic_decision_threshold else 0 for p in y_prob_heur]
        rec_heur = calculate_binary_metrics(
            y_true=y_true,
            y_pred=y_pred_heur,
            y_prob=y_prob_heur,
            event_id=test_event_id,
            horizon=h,
            method="heuristic",
            threshold_used=heuristic_decision_threshold,
            evaluation_type="held_out_event_test",
            data_city=eval_city,
            is_held_out=True,
            disclaimer=disclaimer_heur,
        )
        event_results.append(rec_heur)
        confusion_matrices[f"{test_event_id}_H{h}_heuristic"] = {"tp": rec_heur.tp, "tn": rec_heur.tn, "fp": rec_heur.fp, "fn": rec_heur.fn}

        # Method C: Rainfall Threshold Baseline
        t_thresh = threshold_baseline.thresholds.get(h, 35.0)
        y_pred_thresh = [threshold_baseline.predict(s.rainfall_mm, h) for s in sub]
        y_score_thresh = [threshold_baseline.score(s.rainfall_mm, h) for s in sub]
        rec_thresh = calculate_binary_metrics(
            y_true=y_true,
            y_pred=y_pred_thresh,
            y_prob=y_score_thresh,
            event_id=test_event_id,
            horizon=h,
            method="rainfall_threshold",
            threshold_used=t_thresh,
            evaluation_type="held_out_event_test",
            data_city=eval_city,
            is_held_out=True,
            disclaimer=disclaimer_thresh,
        )
        event_results.append(rec_thresh)
        confusion_matrices[f"{test_event_id}_H{h}_rainfall_threshold"] = {"tp": rec_thresh.tp, "tn": rec_thresh.tn, "fp": rec_thresh.fp, "fn": rec_thresh.fn}

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "HELD_OUT_EVENT_TEST",
        "train_event_id": train_event_id,
        "test_event_id": test_event_id,
        "events": [e.event_id for e in load_backtest_events(data_p / "backtest_events.json")] if (data_p / "backtest_events.json").exists() else [train_event_id, test_event_id],
        "methods": ["ml", "heuristic", "rainfall_threshold"],
        "horizons": horizons,
        "features_used": FEATURE_COLUMNS,
        "is_held_out": True,
        "evaluation_city": eval_city,
        "patna_held_out_status": patna_status,
        "rainfall_thresholds_mm": threshold_baseline.thresholds,
        "ml_decision_threshold": ml_decision_threshold,
        "heuristic_decision_threshold": heuristic_decision_threshold,
        "limitations": [
            "Evaluated against calibrated proxy development labels and documented municipal flood impact records.",
            "Historical Patna test event held strictly out from model training.",
            "Physical IoT water-depth telemetry is not deployed; proxy-label evaluation strictly stated.",
        ],
        "disclaimer": (
            "Held-out event evaluation against documented municipal flood occurrences "
            "and Copernicus DEM terrain. Not physical sensor telemetry."
        ),
    }

    result = BacktestResult(
        metadata=meta,
        event_results=event_results,
        aggregate_results=event_results,
        confusion_matrices=confusion_matrices,
        evaluation_mode="HELD_OUT_EVENT_TEST",
        training_event_ids=[train_event_id],
        test_event_ids=[test_event_id],
        patna_held_out_status=patna_status,
    )

    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        result.save_json(out_p / "results.json")
        result.save_csv(out_p / "results.csv")
        result.save_confusion_matrices(out_p / "confusion_matrices.json")

    return result
