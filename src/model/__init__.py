"""Flood-risk prediction package for Chetna.

Exports heuristic and machine-learning predictors, evaluation metrics,
and calibrated dataset builders.
"""

from src.model.ml_backtest import (
    DEFAULT_RAINFALL_THRESHOLDS,
    BacktestRecord,
    BacktestResult,
    RainfallThresholdBaseline,
    calculate_binary_metrics,
    run_backtest,
)
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
from src.model.ml_explainability import (
    FactorContribution,
    PredictionExplanation,
    explain_prediction,
    generate_human_readable_summary,
)
from src.model.failure_isolation import (
    CellFailureRecord,
    validate_risk_prediction_contract,
    validate_sensor_reading_contract,
)
from src.model.ml_predictor import (
    XGBoostFloodModel,
    XGBoostRiskPredictor,
)
from src.model.predictor import FloodRiskPredictor, RiskPrediction

__all__ = [
    "FloodRiskPredictor",
    "RiskPrediction",
    "XGBoostFloodModel",
    "XGBoostRiskPredictor",
    "RainfallThresholdBaseline",
    "BacktestRecord",
    "BacktestResult",
    "calculate_binary_metrics",
    "run_backtest",
    "DEFAULT_RAINFALL_THRESHOLDS",
    "FactorContribution",
    "PredictionExplanation",
    "explain_prediction",
    "generate_human_readable_summary",
    "HorizonMetrics",
    "calculate_confusion_matrix",
    "calculate_roc_auc",
    "evaluate_predictions",
    "format_evaluation_report",
    "FEATURE_COLUMNS",
    "ProxySample",
    "calibrate_hotspot_threshold",
    "compute_proxy_target",
    "load_static_cell_catalog",
    "build_proxy_training_dataset",
    "prepare_matrices_by_horizon",
    "CellFailureRecord",
    "validate_risk_prediction_contract",
    "validate_sensor_reading_contract",
]
