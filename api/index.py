import sys
from pathlib import Path

# Add project root and packages/audit-engine to sys.path for Vercel Serverless Function execution
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
ENGINE_DIR = BASE_DIR / "packages" / "audit-engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from apps.api.server import app

__all__ = ["app"]
