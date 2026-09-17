"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, load_settings


def create_app(settings: Settings) -> FastAPI:
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
    return application


app = create_app(load_settings())
