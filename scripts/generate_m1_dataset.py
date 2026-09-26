#!/usr/bin/env python3
"""Deterministic Generator Script for Chetna M1 Day 1 Dataset.

Generates and validates:
- Documented Chennai urban flood hotspots (GCC/TNSDMA registry)
- Historical heavy-rain backtest events (Cyclone Michaung, Nov 2021)
- Hourly observation series with rainfall horizons and proxy inundation flags
- Grid cell associations (~200 m resolution)
- SQLite database persistence into 'hotspots', 'backtest_events', and 'hotspot_observations'
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.static_risk.hotspots import (
    DEFAULT_M1_DATA_DIR,
    generate_m1_development_dataset,
    load_m1_development_dataset,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("generate_m1_dataset")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic M1 Day 1 flood hotspots and backtest dataset."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_M1_DATA_DIR),
        help="Target directory for M1 data files (default: data/m1)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/chetna.db",
        help="Target SQLite database file path (default: data/chetna.db)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip SQLite database persistence",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the dataset by reloading it after generation",
    )
    args = parser.parse_args()

    db_path = None if args.no_db else args.db_path
    logger.info("Generating M1 Day 1 development dataset...")
    logger.info("Output directory: %s", args.output_dir)
    logger.info("Database target: %s", db_path or "SKIPPED")

    dataset = generate_m1_development_dataset(output_dir=args.output_dir, db_path=db_path)

    logger.info("Generation successful:")
    logger.info("  Hotspots:     %d", len(dataset.hotspots))
    logger.info("  Events:       %d", len(dataset.events))
    logger.info("  Observations: %d", len(dataset.observations))
    logger.info("  Files saved in %s", args.output_dir)

    if args.verify:
        logger.info("Verifying generated dataset...")
        reloaded = load_m1_development_dataset(data_dir=args.output_dir)
        assert len(reloaded.hotspots) == len(dataset.hotspots), "Hotspot count mismatch!"
        assert len(reloaded.events) == len(dataset.events), "Event count mismatch!"
        assert len(reloaded.observations) == len(dataset.observations), "Observation count mismatch!"
        logger.info("Verification PASSED: %d records matched exactly.", len(reloaded.observations))

    return 0


if __name__ == "__main__":
    sys.exit(main())
