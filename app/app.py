import sys
from pathlib import Path

# Ensure repository root is on sys.path and app/ directory does not shadow the 'app' package
_APP_DIR = str(Path(__file__).resolve().parent)
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

while _APP_DIR in sys.path:
    sys.path.remove(_APP_DIR)

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if "app" in sys.modules and not hasattr(sys.modules["app"], "__path__"):
    del sys.modules["app"]

try:
    from app.dashboard import main
except (ImportError, ModuleNotFoundError):
    from dashboard import main  # type: ignore

if __name__ == "__main__":
    main()
