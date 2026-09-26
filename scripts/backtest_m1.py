"""M1 Day 5: Command-Line Interface for Rigorous Backtesting and Baseline Comparison.

Executes comparative backtesting across historical heavy-rainfall events:
- M1 XGBoost Model
- Heuristic Baseline Model
- Simple Rainfall-Threshold Baseline

Usage:
    python scripts/backtest_m1.py
    python scripts/backtest_m1.py --output-dir data/m1/backtest
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model.ml_backtest import (
    DEFAULT_RAINFALL_THRESHOLDS,
    BacktestResult,
    run_backtest,
)

logger = logging.getLogger("backtest_m1")


def print_backtest_summary(result: BacktestResult) -> None:
    """Prints a structured, neutral comparison table without declaring winners or marketing hype."""
    print("\n" + "=" * 105)
    print("CHETNA M1 DAY 5: HISTORICAL BACKTESTING & BASELINE COMPARISON REPORT")
    print("=" * 105)
    print("\n>>> SCIENTIFIC PROVENANCE & PROTOTYPE DISCLAIMER <<<")
    print("NOTE: Metrics are computed strictly against DETERMINISTIC PROXY DEVELOPMENT LABELS")
    print("calibrated to GCC chronic hotspot trigger thresholds and M1 Day 2 static terrain vulnerability.")
    print("They do NOT represent physical ground-truth sensor measurements.")
    print("Evaluations show comparative prototype response across available historical events.\n")

    # Event-Level Results Table
    print(f"{'Event':<24}{'Horizon':<9}{'Method':<20}{'Samples':<9}{'Positives':<11}{'Precision':<11}{'Recall':<10}{'F1':<8}{'ROC-AUC':<9}{'Brier':<8}")
    print("-" * 105)

    current_event = None
    for r in result.event_results:
        if r.event_id != current_event:
            current_event = r.event_id
            event_short = current_event.replace("EVT_", "")
        else:
            event_short = ""

        prec_str = f"{r.precision:.4f}" if r.precision is not None else "N/A"
        rec_str = f"{r.recall:.4f}" if r.recall is not None else "N/A"
        f1_str = f"{r.f1:.4f}" if r.f1 is not None else "N/A"
        auc_str = f"{r.roc_auc:.4f}" if r.roc_auc is not None else "N/A"
        brier_str = f"{r.brier:.4f}" if r.brier is not None else "N/A"

        print(
            f"{event_short:<24}+{r.horizon}h{'':<6}{r.method:<20}{r.n_samples:<9}{r.n_positive:<11}"
            f"{prec_str:<11}{rec_str:<10}{f1_str:<8}{auc_str:<9}{brier_str:<8}"
        )

    # Aggregate Results Table
    print("\n" + "=" * 105)
    print("AGGREGATE COMPARISON ACROSS ALL EVENTS COMBINED")
    print("=" * 105)
    print(f"{'Horizon':<9}{'Method':<22}{'Samples':<9}{'Positives':<11}{'Precision':<11}{'Recall':<10}{'F1':<8}{'ROC-AUC':<9}{'Brier':<8}")
    print("-" * 105)

    for r in result.aggregate_results:
        prec_str = f"{r.precision:.4f}" if r.precision is not None else "N/A"
        rec_str = f"{r.recall:.4f}" if r.recall is not None else "N/A"
        f1_str = f"{r.f1:.4f}" if r.f1 is not None else "N/A"
        auc_str = f"{r.roc_auc:.4f}" if r.roc_auc is not None else "N/A"
        brier_str = f"{r.brier:.4f}" if r.brier is not None else "N/A"

        print(
            f"+{r.horizon}h{'':<6}{r.method:<22}{r.n_samples:<9}{r.n_positive:<11}"
            f"{prec_str:<11}{rec_str:<10}{f1_str:<8}{auc_str:<9}{brier_str:<8}"
        )

    print("-" * 105)
    print("\nConfusion Matrix Counts (Aggregate):")
    for r in result.aggregate_results:
        print(f"  +{r.horizon}h {r.method:<20}: TP={r.tp:<4} TN={r.tn:<4} FP={r.fp:<4} FN={r.fn:<4}")
    print("=" * 105 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chetna M1 Day 5 Backtesting & Baseline Comparison")
    parser.add_argument("--data-dir", type=str, default="data/m1", help="Path to M1 data directory")
    parser.add_argument("--model-dir", type=str, default="data/m1/models", help="Path to trained models directory")
    parser.add_argument("--output-dir", type=str, default="data/m1/backtest", help="Target output directory")
    parser.add_argument("--h1-thresh", type=float, default=35.0, help="Rainfall threshold for +1h baseline (mm)")
    parser.add_argument("--h3-thresh", type=float, default=55.0, help="Rainfall threshold for +3h baseline (mm)")
    parser.add_argument("--h6-thresh", type=float, default=80.0, help="Rainfall threshold for +6h baseline (mm)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    thresholds = {
        1: args.h1_thresh,
        3: args.h3_thresh,
        6: args.h6_thresh,
    }

    try:
        result = run_backtest(
            data_dir=args.data_dir,
            model_dir=args.model_dir,
            output_dir=args.output_dir,
            rainfall_thresholds=thresholds,
        )
        print_backtest_summary(result)
        print(f"Backtest successfully finished. Results saved to '{args.output_dir}'")
    except Exception as exc:
        logger.error("Backtest execution failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
