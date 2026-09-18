import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
for p in [str(BASE_DIR), str(BASE_DIR / "packages" / "audit-engine"), str(BASE_DIR / "apps"), str(BASE_DIR / "packages")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from apps.api.server import app

__all__ = ["app"]
