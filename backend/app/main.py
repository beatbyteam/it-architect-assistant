from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api.v1.routes import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.middleware import request_context_middleware
from app.core.request_context import request_id_ctx_var
from app.schemas.errors import ApiErrorResponse

logger = logging.getLogger(__name__)

OPENAPI_TAGS = [
    {
        "name": "Обучение базы знаний",
        "description": "Загрузка, разбор, обновление и выбор материалов базы знаний.",
    },
    {
        "name": "Генерация решения",
        "description": "Задачи, уточнения, запуск генерации и чтение подготовленных архитектурных решений.",
    },
    {
        "name": "Проверка существующего решения",
        "description": "Запуск проверки, протоколы, нарушения и проверка внешней архитектуры.",
    },
    {"name": "Операции", "description": "Журнал операций, аудит и технические метрики."},
    {"name": "Health", "description": "Проверки доступности API и зависимостей."},
]

OPENAPI_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _openapi_tag_for_path(path: str) -> str:
    normalized = path.removeprefix("/api/v1")
    if normalized.startswith("/health"):
        return "Health"
    if normalized.startswith("/knowledge"):
        return "Обучение базы знаний"
    if normalized.startswith("/external-architectures") or normalized.startswith(
        "/verification-runs"
    ) or normalized.startswith("/verification-protocols"):
        return "Проверка существующего решения"
    if normalized.startswith("/solutions/") and "/verification-runs" in normalized:
        return "Проверка существующего решения"
    if (
        normalized.startswith("/tasks")
        or normalized.startswith("/task-inputs")
        or normalized.startswith("/generation-runs")
        or normalized.startswith("/solutions")
    ):
        return "Генерация решения"
    if normalized.startswith("/operations") or normalized.startswith("/audit-events"):
        return "Операции"
    return "Операции"


def _install_custom_openapi(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            description=app.description,
            tags=OPENAPI_TAGS,
        )
        for path, path_item in (schema.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            tag = _openapi_tag_for_path(str(path))
            for method, operation in path_item.items():
                if method not in OPENAPI_METHODS or not isinstance(operation, dict):
                    continue
                operation["tags"] = [tag]
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


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

    @app.middleware("http")
    async def json_utf8_charset_middleware(request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json") and "charset=" not in content_type:
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response

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
    _install_custom_openapi(app)
    return app


app = create_app()
