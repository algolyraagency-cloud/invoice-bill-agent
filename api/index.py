import os
import sys
import traceback
from pathlib import Path

# Add root directory and packages to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

for sub in ["apps", "packages", "packages/audit-engine"]:
    p = str(BASE_DIR / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from apps.api.server import app
except Exception as e:
    err_msg = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="RateGuard Diagnostic Fallback")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
    async def catch_all(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Serverless Startup Failure",
                "detail": str(e),
                "traceback": err_msg,
                "path": full_path
            }
        )

__all__ = ["app"]
