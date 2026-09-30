"""M1 Day 3: Model Training Script for Prototype XGBoost Flood-Risk Engine.

Generates calibrated proxy development labels, trains multi-horizon (+1h, +3h, +6h)
XGBoost classifiers, evaluates validation metrics, and serializes model artifacts.

Usage:
    python scripts/train_m1_model.py
    python scripts/train_m1_model.py --output-model-dir data/m1/models
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sklearn.model_selection import train_test_split

from src.model.ml_dataset import (
    build_proxy_training_dataset,
    prepare_matrices_by_horizon,
)
from src.model.ml_evaluator import (
    HorizonMetrics,
    evaluate_predictions,
    format_evaluation_report,
)
from src.model.ml_predictor import XGBoostFloodModel

logger = logging.getLogger("train_m1_model")


def run_training_pipeline(
    data_dir: str = "data/m1",
    model_dir: str = "data/m1/models",
    test_size: float = 0.20,
    random_state: int = 42,
    output_dataset_dir: str = "data/m1",
    held_out_event: str = "EVT_PATNA_2024_09_HEAVY_RAIN",
) -> Dict[int, HorizonMetrics]:
    """Executes the complete M1 Day 3 training and evaluation pipeline."""
    print("=" * 72)
    print("CHETNA M1 DAY 3: TRAINING PROTOTYPE MULTI-HORIZON XGBOOST FLOOD-RISK MODEL")
    print("=" * 72)

    # 1. Generate / Load Proxy Development Dataset
    print(f"\n[1/5] Generating calibrated proxy training dataset from '{data_dir}'...")
    samples = build_proxy_training_dataset(
        data_dir=data_dir,
        output_dir=output_dataset_dir,
    )
    print(f"      Total generated multi-horizon proxy samples: {len(samples)}")

    # Strict isolation: exclude held-out evaluation event
    training_samples = [s for s in samples if s.event_id != held_out_event]
    print(f"      Training samples after excluding held-out event '{held_out_event}': {len(training_samples)}")

    # 2. Prepare feature and target matrices
    print("\n[2/5] Structuring feature matrices for horizons (+1h, +3h, +6h)...")
    matrices = prepare_matrices_by_horizon(training_samples)
    for h, (X, y) in matrices.items():
        pos = int(y.sum())
        print(f"      Horizon +{h}h: {X.shape[0]} samples, {pos} positive proxy waterlogging events ({pos / len(y):.1%})")

    # 3. Train multi-horizon XGBoost models
    print(f"\n[3/5] Training horizon-specific XGBoost models (seed={random_state})...")
    flood_model = XGBoostFloodModel(random_state=random_state)
    metrics_by_horizon: Dict[int, HorizonMetrics] = {}

    for h in (1, 3, 6):
        if h not in matrices:
            continue
        X, y = matrices[h]
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

        flood_model.train_horizon(
            horizon=h,
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
        )

        # 4. Evaluate on validation split
        probs_val = flood_model.predict_proba(horizon=h, X=X_val)
        m = evaluate_predictions(y_true=y_val, y_prob=probs_val, horizon=h)
        metrics_by_horizon[h] = m
        flood_model.metadata["horizon_metrics"][str(h)] = m.to_dict()

    # Record metadata regarding clean feature policy and event provenance
    training_event_ids = sorted(list(set(s.event_id for s in training_samples)))
    assert held_out_event not in training_event_ids, f"Contamination: {held_out_event} in training events!"
    flood_model.metadata["clean_feature_policy"] = (
        "Target-derived variables (trigger_rain_threshold, flood_risk_proxy, waterlogged_proxy) "
        "are strictly excluded from feature inputs."
    )
    flood_model.metadata["training_events"] = training_event_ids
    flood_model.metadata["held_out_event_excluded"] = held_out_event
    flood_model.metadata["validation_mode"] = "DEVELOPMENT_STRATIFIED_SPLIT"
    flood_model.metadata["patna_status"] = (
        f"Model trained with strict event isolation. Held-out test event '{held_out_event}' strictly excluded."
    )

    # 5. Serialize model artifacts
    print(f"\n[4/5] Serializing model artifacts and metadata to '{model_dir}'...")
    flood_model.save(model_dir)

    # Also save to secondary default location data/models if different
    sec_dir = Path("data/models")
    if Path(model_dir).resolve() != sec_dir.resolve():
        try:
            flood_model.save(sec_dir)
            print(f"      Also mirrored models to '{sec_dir}'")
        except Exception as exc:
            logger.warning("Could not mirror to %s: %s", sec_dir, exc)

    # 6. Display evaluation report
    print("\n[5/5] Finalizing Evaluation Report:")
    report_text = format_evaluation_report(metrics_by_horizon)
    print("\n" + report_text)

    # Display Top Feature Importances
    print("\nTop Feature Importances by Horizon:")
    for h in (1, 3, 6):
        importances = flood_model.get_feature_importances(h)
        sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:4]
        imp_str = ", ".join([f"{k}: {v:.3f}" for k, v in sorted_imp])
        print(f"  Horizon +{h}h: {imp_str}")

    print("\nTraining completed successfully.\n")
    return metrics_by_horizon


def main() -> None:
    parser = argparse.ArgumentParser(description="Chetna M1 Day 3 Model Training Pipeline")
    parser.add_argument("--data-dir", type=str, default="data/m1", help="Path to M1 data directory")
    parser.add_argument("--output-model-dir", type=str, default="data/m1/models", help="Target model directory")
    parser.add_argument("--output-dataset-dir", type=str, default="data/m1", help="Directory to save proxy dataset")
    parser.add_argument("--test-size", type=float, default=0.20, help="Validation set split ratio (default: 0.20)")
    parser.add_argument("--seed", type=int, default=42, help="Random state seed (default: 42)")
    parser.add_argument("--held-out-event", type=str, default="EVT_PATNA_2024_09_HEAVY_RAIN",
                        help="Unseen held-out event to strictly exclude from training (default: EVT_PATNA_2024_09_HEAVY_RAIN)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        run_training_pipeline(
            data_dir=args.data_dir,
            model_dir=args.output_model_dir,
            test_size=args.test_size,
            random_state=args.seed,
            output_dataset_dir=args.output_dataset_dir,
            held_out_event=args.held_out_event,
        )
    except Exception as exc:
        logger.error("Training pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
