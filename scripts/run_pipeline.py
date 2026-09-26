"""Script to execute Chetna B1 Day 3 forecast-to-risk prediction pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is on Python sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.pipeline import main

if __name__ == "__main__":
    main()
