from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    message: str
    error_code: str
    http_status: int
    recoverable: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    technical_message: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        if self.technical_message is None:
            self.technical_message = self.message


class AuthenticationError(AppError):
    def __init__(
        self, message: str = "Authentication required", *, technical_message: str | None = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_REQUIRED",
            http_status=401,
            recoverable=True,
            technical_message=technical_message,
        )


class AuthorizationError(AppError):
    def __init__(
        self, message: str = "Access denied", *, technical_message: str | None = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="ACCESS_DENIED",
            http_status=403,
            recoverable=False,
            technical_message=technical_message,
        )


class NotFoundError(AppError):
    def __init__(
        self,
        entity_name: str,
        entity_id: str,
        *,
        details: dict[str, Any] | None = None,
        technical_message: str | None = None,
    ) -> None:
        merged_details = {"entity_name": entity_name, "entity_id": entity_id, **(details or {})}
        super().__init__(
            message=f"{entity_name} not found: {entity_id}",
            error_code="ENTITY_NOT_FOUND",
            http_status=404,
            recoverable=False,
            details=merged_details,
            technical_message=technical_message,
        )


class ConflictError(AppError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "CONFLICT",
        details: dict[str, Any] | None = None,
        technical_message: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            http_status=409,
            recoverable=True,
            details=details or {},
            technical_message=technical_message,
        )


class ValidationError(AppError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
        technical_message: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            http_status=422,
            recoverable=True,
            details=details or {},
            technical_message=technical_message,
        )


class DependencyUnavailableError(AppError):
    def __init__(
        self,
        dependency_name: str,
        details: str,
        *,
        error_code: str = "DEPENDENCY_UNAVAILABLE",
        message: str | None = None,
        extra_details: dict[str, Any] | None = None,
        technical_message: str | None = None,
    ) -> None:
        merged_details = {
            "dependency": dependency_name,
            "details": details,
            **(extra_details or {}),
        }
        super().__init__(
            message=message or f"Dependency unavailable: {dependency_name}",
            error_code=error_code,
            http_status=503,
            recoverable=True,
            details=merged_details,
            technical_message=technical_message or details,
        )
