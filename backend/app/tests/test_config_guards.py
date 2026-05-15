from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import ValidationError


def test_local_noauth_requires_local_or_test_env() -> None:
    with pytest.raises(ValidationError, match="APP_ENV=local or APP_ENV=test"):
        Settings(APP_ENV="dev", AUTH_MODE="local_noauth")


def test_debug_is_forbidden_in_staging() -> None:
    with pytest.raises(ValidationError, match="DEBUG must be false"):
        Settings(APP_ENV="staging", DEBUG=True, AUTH_MODE="trusted_headers")


def test_localhost_cors_is_forbidden_in_staging() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_CORS_ORIGINS"):
        Settings(
            APP_ENV="staging",
            AUTH_MODE="trusted_headers",
            ALLOWED_CORS_ORIGINS="http://localhost:3000",
        )


def test_placeholder_secret_is_forbidden_in_staging() -> None:
    with pytest.raises(ValidationError, match="LLM_API_KEY"):
        Settings(APP_ENV="staging", AUTH_MODE="trusted_headers", LLM_API_KEY="changeme")


def test_safe_staging_configuration_is_allowed() -> None:
    settings = Settings(
        APP_ENV="staging",
        AUTH_MODE="trusted_headers",
        ALLOWED_CORS_ORIGINS="https://staging.arch.example.internal",
        LLM_API_KEY="real-key",
        EMBEDDING_API_KEY="real-embedding-key",
    )

    assert settings.is_strict_runtime_env() is True
    assert settings.is_local_noauth() is False
