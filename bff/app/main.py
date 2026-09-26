"""FastAPI application factory for the BFF (architecture.svg, the :8000 box)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import ping
from .routes_api import router as api_router
from .routes_auth import router as auth_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="OAuth lab BFF", version="0.1.0")

    # The browser sends the session cookie cross-origin, so credentials are on,
    # and that means the origin must be exact. Browsers reject "*" with credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.include_router(auth_router)
    app.include_router(api_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health/db")
    async def health_db():
        try:
            ping()
        except Exception as exc:  # noqa: BLE001 - report any driver error as 503
            return JSONResponse(status_code=503, content={"status": "down", "error": str(exc)})
        return {"status": "ok"}

    return app


app = create_app()
