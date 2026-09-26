#!/usr/bin/env python3
"""CLI script for computing Chetna M1 Day 2 static flood vulnerability."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.static_risk.vulnerability import compute_static_vulnerability

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("compute_static_risk")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute explainable static flood vulnerability scores for Chennai grid cells."
    )
    parser.add_argument(
        "--source",
        type=str,
        default="data/m1/synthetic_grid_features.json",
        help="Path to grid file (JSON/CSV) or SQLite database (default: data/m1/synthetic_grid_features.json)",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="data/m1/static_risk_scores.json",
        help="Output JSON file path (default: data/m1/static_risk_scores.json)",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="data/m1/static_risk_scores.csv",
        help="Output CSV file path (default: data/m1/static_risk_scores.csv)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/chetna.db",
        help="Path to SQLite database to store 'cells' table (default: data/chetna.db)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip storing to SQLite database",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify and print score distribution across risk levels",
    )
    args = parser.parse_args()

    db_path = None if args.no_db else args.db_path

    logger.info("Computing static flood vulnerability scores...")
    logger.info("  Source:      %s", args.source)
    logger.info("  JSON output: %s", args.output_json)
    logger.info("  CSV output:  %s", args.output_csv)
    logger.info("  DB output:   %s", db_path or "SKIPPED")

    result = compute_static_vulnerability(
        source=args.source,
        save_json_path=args.output_json,
        save_csv_path=args.output_csv,
        save_db_path=db_path,
    )

    logger.info("Processed %d cells successfully.", len(result.cells))

    low_count = len(result.filter_by_risk("low"))
    med_count = len(result.filter_by_risk("medium"))
    high_count = len(result.filter_by_risk("high"))
    total = len(result.cells) or 1
    logger.info(
        "Risk distribution: Low=%d (%.1f%%), Medium=%d (%.1f%%), High=%d (%.1f%%)",
        low_count,
        (low_count / total) * 100,
        med_count,
        (med_count / total) * 100,
        high_count,
        (high_count / total) * 100,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
