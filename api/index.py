import sys
import traceback
from pathlib import Path

# Add project root and packages/audit-engine to sys.path for Vercel Serverless Function execution
BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "packages" / "audit-engine"), str(BASE_DIR / "apps"), str(BASE_DIR / "packages")]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from apps.api.server import app
except Exception as e:
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="RateGuard AI Diagnostic")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
    async def vercel_startup_error_handler(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Serverless Startup Failure",
                "detail": str(e),
                "traceback": err_tb,
                "path": full_path,
            }
        )

__all__ = ["app"]
