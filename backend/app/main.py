from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.middleware import request_context_middleware
from app.core.request_context import request_id_ctx_var
from app.schemas.errors import ApiErrorResponse

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.middleware("http")(request_context_middleware)

    if settings.allowed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        payload = ApiErrorResponse(
            code=exc.error_code,
            user_message=exc.message,
            technical_message=exc.technical_message or exc.message,
            operation_id=(exc.details or {}).get("operation_id")
            if isinstance(exc.details, dict)
            else None,
            request_id=request_id_ctx_var.get() or None,
            details=exc.details,
            error_code=exc.error_code,
            message=exc.message,
            recoverable=exc.recoverable,
        )
        return JSONResponse(status_code=exc.http_status, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        payload = ApiErrorResponse(
            code="REQUEST_VALIDATION_ERROR",
            user_message="Request validation failed",
            technical_message="Request validation failed",
            request_id=request_id_ctx_var.get() or None,
            details={"errors": exc.errors()},
            error_code="REQUEST_VALIDATION_ERROR",
            message="Request validation failed",
            recoverable=True,
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name, "version": settings.app_version}

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
