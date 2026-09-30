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
    PATNA_HELD_OUT_STATUS_MESSAGE,
    BacktestResult,
    run_backtest,
    run_held_out_event_backtest,
)

logger = logging.getLogger("backtest_m1")


def print_backtest_summary(result: BacktestResult) -> None:
    """Prints a structured, neutral comparison table with strict scientific provenance."""
    print("\n" + "=" * 115)
    print("CHETNA M1: HISTORICAL BACKTESTING & BASELINE COMPARISON REPORT")
    print(f"EVALUATION MODE: {result.evaluation_mode}")
    print("=" * 115)
    print("\n>>> SCIENTIFIC PROVENANCE & METHODOLOGY NOTICE <<<")
    print(f"PATNA STATUS: {result.patna_held_out_status}")
    print("NOTE: Prior reported >99% metrics were invalidated due to target formula feature leakage")
    print("(trigger_rain_threshold feature) and training/test event overlap. The evaluation below")
    print("uses the corrected clean 8-feature policy strictly without target-derived leakage.")
    print("Evaluations show comparative prototype response across available historical events.\n")

    # Event-Level Results Table
    print(
        f"{'Event':<24}{'Horizon':<9}{'Method':<20}{'Samples':<8}{'Positives':<10}"
        f"{'Prev%':<7}{'Acc':<8}{'Prec':<8}{'Recall':<8}{'F1':<8}{'TP':<5}{'TN':<6}{'FP':<5}{'FN':<5}"
    )
    print("-" * 115)

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
        acc = (r.tp + r.tn) / max(1, r.n_samples)
        acc_str = f"{acc:.4f}"
        prev_str = f"{r.positive_prevalence * 100:.1f}%"

        print(
            f"{event_short:<24}+{r.horizon}h{'':<6}{r.method:<20}{r.n_samples:<8}{r.n_positive:<10}"
            f"{prev_str:<7}{acc_str:<8}{prec_str:<8}{rec_str:<8}{f1_str:<8}"
            f"{r.tp:<5}{r.tn:<6}{r.fp:<5}{r.fn:<5}"
        )

    # Aggregate Results Table
    if len(result.aggregate_results) > 0 and result.evaluation_mode != "HELD_OUT_EVENT_TEST":
        print("\n" + "=" * 115)
        print("AGGREGATE COMPARISON ACROSS ALL EVENTS COMBINED")
        print("=" * 115)
        print(
            f"{'Horizon':<9}{'Method':<22}{'Samples':<8}{'Positives':<10}"
            f"{'Prev%':<7}{'Acc':<8}{'Prec':<8}{'Recall':<8}{'F1':<8}{'TP':<5}{'TN':<6}{'FP':<5}{'FN':<5}"
        )
        print("-" * 115)

        for r in result.aggregate_results:
            prec_str = f"{r.precision:.4f}" if r.precision is not None else "N/A"
            rec_str = f"{r.recall:.4f}" if r.recall is not None else "N/A"
            f1_str = f"{r.f1:.4f}" if r.f1 is not None else "N/A"
            acc = (r.tp + r.tn) / max(1, r.n_samples)
            acc_str = f"{acc:.4f}"
            prev_str = f"{r.positive_prevalence * 100:.1f}%"

            print(
                f"+{r.horizon}h{'':<6}{r.method:<22}{r.n_samples:<8}{r.n_positive:<10}"
                f"{prev_str:<7}{acc_str:<8}{prec_str:<8}{rec_str:<8}{f1_str:<8}"
                f"{r.tp:<5}{r.tn:<6}{r.fp:<5}{r.fn:<5}"
            )

    print("-" * 115)
    print("\nConfusion Matrix Counts (Aggregate/Selected):")
    for r in result.aggregate_results:
        print(f"  +{r.horizon}h {r.method:<20}: TP={r.tp:<4} TN={r.tn:<4} FP={r.fp:<4} FN={r.fn:<4}")
    print("=" * 115 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chetna M1 Backtesting & Baseline Comparison")
    parser.add_argument("--mode", type=str, default="held_out", choices=["audit", "held_out"],
                        help="Evaluation mode: 'held_out' (strictly event-isolated) or 'audit' (evaluates existing dataset with disclaimer)")
    parser.add_argument("--city", type=str, default="patna", choices=["patna", "chennai"],
                        help="Pilot city domain for evaluation (default: patna)")
    parser.add_argument("--train-event", type=str, default=None,
                        help="Training event ID for held-out evaluation (default: EVT_PATNA_2019_FLOOD for patna, EVT_2023_MICHAUNG for chennai)")
    parser.add_argument("--test-event", type=str, default=None,
                        help="Unseen held-out event ID for evaluation (default: EVT_PATNA_2024_09_HEAVY_RAIN for patna, EVT_2021_NOV_DEPRESSION for chennai)")
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

    train_evt = args.train_event
    test_evt = args.test_event
    if train_evt is None:
        train_evt = "EVT_PATNA_2019_FLOOD" if args.city == "patna" else "EVT_2023_MICHAUNG"
    if test_evt is None:
        test_evt = "EVT_PATNA_2024_09_HEAVY_RAIN" if args.city == "patna" else "EVT_2021_NOV_DEPRESSION"

    try:
        if args.mode == "held_out":
            print(f"Running event-isolated held-out evaluation (train={train_evt}, test={test_evt})...")
            result = run_held_out_event_backtest(
                train_event_id=train_evt,
                test_event_id=test_evt,
                data_dir=args.data_dir,
                rainfall_thresholds=thresholds,
                output_dir=args.output_dir,
            )
        else:
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
