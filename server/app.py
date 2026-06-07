"""FastAPI application factory."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import server.models  # noqa: F401
from server.api.v1.router import router as v1_router
from server.middleware.auth import AuthMiddleware
from server.core.config import settings
from server.core.installation import is_application_installed
from server.db import engine
from server.db import Base
from sqlalchemy import inspect, text


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.project_name,
        description=settings.project_description,
        version=settings.version,
    )

    # Add middleware
    app.add_middleware(AuthMiddleware)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(v1_router, prefix="/api/v1")

    @app.on_event("startup")
    async def on_startup():
        """Create database tables when the application is already installed."""

        if not is_application_installed():
            logger.info("Application is not installed yet; skipping database bootstrap.")
            return

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await _ensure_agent_config_columns(conn)
        except Exception as exc:  # pragma: no cover - startup safety
            logger.warning("Database bootstrap failed during startup: %s", exc)

    return app


async def _ensure_agent_config_columns(conn) -> None:
    """Add lightweight JSON columns for existing installations."""

    for table_name in ("agent_sessions", "agent_session_templates"):
        columns = await conn.run_sync(
            lambda sync_conn, table=table_name: {
                column["name"] for column in inspect(sync_conn).get_columns(table)
            }
        )
        if "agent_configs" not in columns:
            await conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN agent_configs JSON")
            )
