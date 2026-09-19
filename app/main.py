"""FastAPI application entry point."""

from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.records import create_records_router
from app.config import Settings, load_settings
from app.db.session import create_session_factory

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def create_app(
    settings: Settings,
    *,
    sessions: sessionmaker[Session] | None = None,
) -> FastAPI:
    """Create an application with environment-specific public surfaces."""
    publish_api_docs = settings.environment != "production"
    application = FastAPI(
        title="slope-collector",
        debug=settings.debug,
        docs_url="/docs" if publish_api_docs else None,
        redoc_url="/redoc" if publish_api_docs else None,
        openapi_url="/openapi.json" if publish_api_docs else None,
    )
    application.include_router(health_router)
    if settings.environment == "development":
        application.include_router(
            create_records_router(sessions or create_session_factory(settings))
        )
    return application


app = create_app(load_settings())
