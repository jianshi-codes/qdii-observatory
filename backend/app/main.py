"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import portfolio_router, router
from backend.app.config import get_settings
from backend.app.database import engine
from backend.app.database_preflight import database_readiness


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="QDII Observatory API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(router)
    if settings.portfolio_enabled:
        application.include_router(portfolio_router)

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", tags=["operations"])
    def ready(response: Response) -> dict[str, object]:
        readiness = database_readiness(engine)
        if not readiness.ready:
            response.status_code = 503
        return {
            "status": "ready" if readiness.ready else "not_ready",
            "database": readiness.database,
            "migration": readiness.migration,
        }

    return application


app = create_app()
