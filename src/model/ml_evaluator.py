"""M1 Day 3: Machine Learning Evaluation Metrics for Flood-Risk Predictions.

Provides deterministic calculation of binary classification metrics, calibration scores,
and formatted evaluation reports for multi-horizon prototype flood-risk models.

IMPORTANT PROVENANCE & LIMITATION NOTICE:
All evaluation metrics produced by this module reflect performance against CALIBRATED PROXY
DEVELOPMENT LABELS derived from historical reanalysis and municipal hotspot thresholds.
They do NOT represent empirical validation against physical ground-truth flood sensor networks.
Reports must explicitly state this prototype limitation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np


@dataclass
class HorizonMetrics:
    """Evaluation metrics for a specific forecast horizon."""
    horizon: int
    sample_count: int
    positive_count: int
    negative_count: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    roc_auc: float
    brier_score: float
    tp: int
    fp: int
    tn: int
    fn: int
    is_proxy_evaluation: bool = True
    disclaimer: str = (
        "Evaluated on calibrated proxy development dataset (GCC hotspot triggers + M1 Day 2 vulnerability). "
        "Not physical ground-truth sensor measurements."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_confusion_matrix(
    y_true: Sequence[Union[int, float]],
    y_pred: Sequence[Union[int, float]],
) -> Dict[str, int]:
    """Calculates true positive, false positive, true negative, false negative counts."""
    tp = fp = tn = fn = 0
    for yt, yp in zip(y_true, y_pred):
        yt_bin = 1 if yt >= 0.5 else 0
        yp_bin = 1 if yp >= 0.5 else 0
        if yt_bin == 1 and yp_bin == 1:
            tp += 1
        elif yt_bin == 0 and yp_bin == 1:
            fp += 1
        elif yt_bin == 0 and yp_bin == 0:
            tn += 1
        elif yt_bin == 1 and yp_bin == 0:
            fn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def calculate_roc_auc(
    y_true: Sequence[Union[int, float]],
    y_scores: Sequence[float],
) -> float:
    """Calculates Area Under ROC Curve (ROC-AUC) using the Mann-Whitney U rank-sum method.

    Deterministic and requires no external libraries.
    """
    y_t = [1 if y >= 0.5 else 0 for y in y_true]
    n_pos = sum(y_t)
    n_neg = len(y_t) - n_pos

    if n_pos == 0 or n_neg == 0:
        return 0.50  # Undefined when single class; return random baseline

    # Pair scores with labels and sort by score ascending
    paired = sorted(zip(y_scores, y_t), key=lambda x: x[0])

    # Assign ranks with fractional tie resolution
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


def evaluate_predictions(
    y_true: Sequence[Union[int, float]],
    y_prob: Sequence[float],
    horizon: int,
    threshold: float = 0.50,
) -> HorizonMetrics:
    """Computes comprehensive evaluation metrics for a specific horizon's predictions.

    Args:
        y_true: Binary ground-truth or proxy labels (0 or 1).
        y_prob: Predicted probabilities in [0.0, 1.0].
        horizon: Forecast horizon (e.g. 1, 3, or 6).
        threshold: Classification decision threshold (default: 0.50).

    Returns:
        HorizonMetrics instance.
    """
    y_t = [1 if y >= 0.5 else 0 for y in y_true]
    y_p = [float(p) for p in y_prob]
    y_pred = [1 if p >= threshold else 0 for p in y_p]

    n = len(y_t)
    if n == 0:
        return HorizonMetrics(
            horizon=horizon,
            sample_count=0,
            positive_count=0,
            negative_count=0,
            accuracy=0.0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            roc_auc=0.50,
            brier_score=0.0,
            tp=0,
            fp=0,
            tn=0,
            fn=0,
        )

    cm = calculate_confusion_matrix(y_t, y_pred)
    tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]

    accuracy = round((tp + tn) / n, 4)
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round((2 * precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    roc_auc = calculate_roc_auc(y_t, y_p)
    brier = round(sum((p - t) ** 2 for p, t in zip(y_p, y_t)) / n, 4)

    return HorizonMetrics(
        horizon=horizon,
        sample_count=n,
        positive_count=sum(y_t),
        negative_count=n - sum(y_t),
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1_score=f1,
        roc_auc=roc_auc,
        brier_score=brier,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
    )


def format_evaluation_report(metrics_by_horizon: Dict[int, HorizonMetrics]) -> str:
    """Formats a human-readable text report of evaluation metrics across horizons."""
    lines = [
        "=" * 72,
        "CHETNA M1 DAY 3: MULTI-HORIZON PROTOTYPE ML EVALUATION REPORT",
        "=" * 72,
        "",
        ">>> SCIENTIFIC PROVENANCE & PROTOTYPE DISCLAIMER <<<",
        "NOTE: Metrics are computed strictly against DETERMINISTIC PROXY DEVELOPMENT LABELS",
        "calibrated to GCC chronic hotspot trigger thresholds and M1 Day 2 terrain vulnerability.",
        "They do NOT represent physical ground-truth sensor measurements.",
        "",
        f"{'Horizon':<10}{'Samples':<10}{'Positives':<12}{'Precision':<12}{'Recall':<10}{'F1-Score':<10}{'ROC-AUC':<10}",
        "-" * 72,
    ]

    for h in sorted(metrics_by_horizon.keys()):
        m = metrics_by_horizon[h]
        lines.append(
            f"+{h}h{'':<7}{m.sample_count:<10}{m.positive_count:<12}{m.precision:<12.4f}{m.recall:<10.4f}{m.f1_score:<10.4f}{m.roc_auc:<10.4f}"
        )

    lines.append("-" * 72)
    lines.append("")
    lines.append("Confusion Matrices:")
    for h in sorted(metrics_by_horizon.keys()):
        m = metrics_by_horizon[h]
        lines.append(f"  Horizon +{h}h: TP={m.tp}, FP={m.fp}, TN={m.tn}, FN={m.fn}, Brier Score={m.brier_score:.4f}")

    lines.append("=" * 72)
    return "\n".join(lines)
