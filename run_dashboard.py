"""Chetna: Project-root Streamlit Entrypoint.

Launches the Chetna Flood Early Warning System dashboard with proper
package imports from the repository root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.dashboard import main

if __name__ == "__main__":
    main()
