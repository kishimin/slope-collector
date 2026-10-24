"""FastAPI application entry point."""

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.control import create_control_router
from app.api.health import router as health_router
from app.api.records import create_records_router
from app.config import Settings, load_settings
from app.db.session import create_session_factory
from app.models.control import ControlStorageError
from app.repositories.control import SqlAlchemyControlRepository

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
    database_sessions = sessions or create_session_factory(settings)
    application.include_router(
        create_control_router(SqlAlchemyControlRepository(database_sessions))
    )

    @application.exception_handler(ControlStorageError)
    async def control_storage_error_handler(
        _request: Request, _exc: ControlStorageError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": "CONTROL_STORAGE_UNAVAILABLE",
                "message": "Collection control storage is unavailable.",
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for error in exc.errors():
            location = error.get("loc", ())
            field = next(
                (item for item in reversed(location) if isinstance(item, str)), None
            )
            errors.append(
                {"field": field, "message": error.get("msg", "Invalid value.")}
            )
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "errors": errors,
            },
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        content = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {
                "code": (
                    "NOT_FOUND"
                    if exc.status_code == status.HTTP_404_NOT_FOUND
                    else "BAD_REQUEST"
                ),
                "message": str(exc.detail),
            }
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    if settings.environment == "development":
        application.include_router(create_records_router(database_sessions))
    return application


app = create_app(load_settings())
