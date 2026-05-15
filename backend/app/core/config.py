from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, get_origin

from pydantic import Field, field_validator, model_validator
from pydantic.fields import FieldInfo, PydanticUndefined
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import (
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)

from app.core.exceptions import ValidationError
from app.db.constants import EMBEDDING_VECTOR_DIMENSIONS

LOCAL_APP_ENVS = {"local", "test"}
DEV_APP_ENVS = {"dev", "development"}
STAGING_APP_ENVS = {"staging", "stage", "preprod", "uat"}
PROD_APP_ENVS = {"prod", "production", "release"}
STRICT_RUNTIME_APP_ENVS = STAGING_APP_ENVS | PROD_APP_ENVS
PERMISSIVE_CORS_ORIGINS = {"*"}
INSECURE_SECRET_SENTINELS = {
    "",
    "changeme",
    "change-me",
    "dev-only",
    "development-only",
    "dummy",
    "example",
    "local-only",
    "placeholder",
    "test",
    "test-key",
    "test-token",
    "unsafe",
}
DEFAULT_KNOWLEDGE_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
DEFAULT_KNOWLEDGE_LARGE_DOCUMENT_THRESHOLD_BYTES = 1 * 1024 * 1024


def _parse_env_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return [str(value).strip()] if str(value).strip() else []
    raw = value.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


def _field_expects_list(field: FieldInfo) -> bool:
    origin = get_origin(getattr(field, "annotation", None))
    return origin in {list, tuple, set}


class _CsvFriendlySettingsMixin:
    def _delegate_prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        prepare = getattr(super(), "prepare_field_value", None)
        if callable(prepare):
            return prepare(field_name, field, value, value_is_complex)
        return value

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if _field_expects_list(field):
            try:
                return self._delegate_prepare_field_value(
                    field_name, field, value, value_is_complex
                )
            except Exception:
                return _parse_env_list(value)
        return self._delegate_prepare_field_value(field_name, field, value, value_is_complex)


class CsvFriendlyEnvSettingsSource(_CsvFriendlySettingsMixin, EnvSettingsSource):
    pass


class CsvFriendlyDotEnvSettingsSource(_CsvFriendlySettingsMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    def __init__(self, **values: Any) -> None:
        explicit_fields = {key for key in values if not key.startswith("_")}
        if explicit_fields:
            isolated_values = dict(values)
            for field_name, field in type(self).model_fields.items():
                keys = {field_name}
                if field.alias:
                    keys.add(str(field.alias))
                if explicit_fields.intersection(keys):
                    continue
                default_value = field.get_default(call_default_factory=True)
                if default_value is PydanticUndefined:
                    continue
                isolated_values[field.alias or field_name] = default_value
            isolated_values.setdefault("_env_file", None)
            values = isolated_values
        super().__init__(**values)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del env_settings, dotenv_settings
        return (
            init_settings,
            CsvFriendlyEnvSettingsSource(settings_cls),
            CsvFriendlyDotEnvSettingsSource(settings_cls),
            file_secret_settings,
        )

    app_name: str = Field(default="IT Architect Assistant Backend", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    app_env: str = Field(default="local", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    allowed_cors_origins: list[str] = Field(default_factory=list, alias="ALLOWED_CORS_ORIGINS")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/it_arch_assistant",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(
        default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND"
    )
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")

    health_check_worker: bool = Field(default=False, alias="HEALTH_CHECK_WORKER")
    health_check_redis: bool = Field(default=False, alias="HEALTH_CHECK_REDIS")
    health_check_db: bool = Field(default=True, alias="HEALTH_CHECK_DB")
    health_check_llm: bool = Field(default=False, alias="HEALTH_CHECK_LLM")
    health_check_embedding: bool = Field(default=False, alias="HEALTH_CHECK_EMBEDDING")
    health_check_active_knowledge_version: bool = Field(
        default=False, alias="HEALTH_CHECK_ACTIVE_KNOWLEDGE_VERSION"
    )
    request_id_header: str = Field(default="X-Request-ID", alias="REQUEST_ID_HEADER")

    auth_mode: str = Field(default="trusted_headers", alias="AUTH_MODE")
    auth_header_login: str = Field(default="X-Auth-Login", alias="AUTH_HEADER_LOGIN")
    auth_header_display_name: str = Field(
        default="X-Auth-Display-Name", alias="AUTH_HEADER_DISPLAY_NAME"
    )
    auth_header_roles: str = Field(default="X-Auth-Roles", alias="AUTH_HEADER_ROLES")
    auth_header_account_type: str = Field(
        default="X-Auth-Account-Type", alias="AUTH_HEADER_ACCOUNT_TYPE"
    )
    auth_default_display_name: str = Field(default="User", alias="AUTH_DEFAULT_DISPLAY_NAME")
    local_user_login: str = Field(default="local.user", alias="LOCAL_USER_LOGIN")
    local_user_display_name: str = Field(default="Local User", alias="LOCAL_USER_DISPLAY_NAME")
    local_user_roles: list[str] = Field(default_factory=lambda: ["USER"], alias="LOCAL_USER_ROLES")
    local_user_account_type: str = Field(default="human", alias="LOCAL_USER_ACCOUNT_TYPE")
    mvp_permissive_local_access: bool = Field(default=True, alias="MVP_PERMISSIVE_LOCAL_ACCESS")
    mvp_global_role_codes: list[str] = Field(
        default_factory=lambda: ["ADMIN", "MVP_ADMIN"], alias="MVP_GLOBAL_ROLE_CODES"
    )

    knowledge_fetch_timeout_sec: float = Field(default=30.0, alias="KNOWLEDGE_FETCH_TIMEOUT_SEC")
    knowledge_upload_dir: str = Field(
        default="./data/knowledge_uploads", alias="KNOWLEDGE_UPLOAD_DIR"
    )
    knowledge_allowed_local_source_roots: list[str] = Field(
        default_factory=list, alias="KNOWLEDGE_ALLOWED_LOCAL_SOURCE_ROOTS"
    )
    knowledge_allow_unrestricted_local_sources: bool = Field(
        default=False, alias="KNOWLEDGE_ALLOW_UNRESTRICTED_LOCAL_SOURCES"
    )
    knowledge_chunk_max_chars: int = Field(default=2200, alias="KNOWLEDGE_CHUNK_MAX_CHARS")
    knowledge_chunk_target_tokens: int = Field(default=420, alias="KNOWLEDGE_CHUNK_TARGET_TOKENS")
    knowledge_chunk_overlap_pct: int = Field(default=5, alias="KNOWLEDGE_CHUNK_OVERLAP_PCT")
    knowledge_large_document_threshold_bytes: int = Field(
        default=DEFAULT_KNOWLEDGE_LARGE_DOCUMENT_THRESHOLD_BYTES,
        alias="KNOWLEDGE_LARGE_DOCUMENT_THRESHOLD_BYTES",
    )
    knowledge_large_document_chunk_max_chars: int = Field(
        default=6000, alias="KNOWLEDGE_LARGE_DOCUMENT_CHUNK_MAX_CHARS"
    )
    knowledge_large_document_chunk_target_tokens: int = Field(
        default=900, alias="KNOWLEDGE_LARGE_DOCUMENT_CHUNK_TARGET_TOKENS"
    )
    knowledge_large_document_chunk_overlap_pct: int = Field(
        default=0, alias="KNOWLEDGE_LARGE_DOCUMENT_CHUNK_OVERLAP_PCT"
    )
    knowledge_large_document_max_chunks: int = Field(
        default=240, alias="KNOWLEDGE_LARGE_DOCUMENT_MAX_CHUNKS"
    )
    knowledge_llm_extraction_max_chunks: int = Field(
        default=12, alias="KNOWLEDGE_LLM_EXTRACTION_MAX_CHUNKS"
    )
    knowledge_auto_sync_interval_days: int = Field(
        default=30, alias="KNOWLEDGE_AUTO_SYNC_INTERVAL_DAYS"
    )
    knowledge_execute_inline: bool = Field(default=False, alias="KNOWLEDGE_EXECUTE_INLINE")
    knowledge_sync_sla_seconds: int = Field(default=3600, alias="KNOWLEDGE_SYNC_SLA_SECONDS")
    knowledge_max_document_size_bytes: int = Field(
        default=DEFAULT_KNOWLEDGE_MAX_FILE_SIZE_BYTES, alias="KNOWLEDGE_MAX_DOCUMENT_SIZE_BYTES"
    )
    knowledge_max_upload_size_bytes: int = Field(
        default=DEFAULT_KNOWLEDGE_MAX_FILE_SIZE_BYTES, alias="KNOWLEDGE_MAX_UPLOAD_SIZE_BYTES"
    )
    embedding_profile: str = Field(default="bge_m3_default", alias="EMBEDDING_PROFILE")
    embedding_provider: str = Field(default="local_openai_compatible", alias="EMBEDDING_PROVIDER")
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")
    embedding_base_url: str | None = Field(default=None, alias="EMBEDDING_BASE_URL")
    embedding_api_key: str | None = Field(default=None, alias="EMBEDDING_API_KEY")
    embedding_timeout_sec: float = Field(default=30.0, alias="EMBEDDING_TIMEOUT_SEC")
    embedding_batch_size: int = Field(default=64, alias="EMBEDDING_BATCH_SIZE")
    embedding_model_id: str | None = Field(default="bge-m3", alias="EMBEDDING_MODEL_ID")
    reranker_provider: str = Field(default="heuristic", alias="RERANKER_PROVIDER")
    reranker_base_url: str | None = Field(default=None, alias="RERANKER_BASE_URL")
    reranker_api_key: str | None = Field(default=None, alias="RERANKER_API_KEY")
    reranker_timeout_sec: float = Field(default=30.0, alias="RERANKER_TIMEOUT_SEC")
    reranker_model_id: str | None = Field(default=None, alias="RERANKER_MODEL_ID")

    generation_execute_inline: bool = Field(default=False, alias="GENERATION_EXECUTE_INLINE")
    generation_prompt_max_input_tokens: int = Field(
        default=3000, alias="GENERATION_PROMPT_MAX_INPUT_TOKENS"
    )
    generation_prompt_reserved_output_tokens: int = Field(
        default=1200, alias="GENERATION_PROMPT_RESERVED_OUTPUT_TOKENS"
    )
    llm_provider: str = Field(default="openai_compatible", alias="LLM_PROVIDER")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_timeout_sec: float = Field(default=60.0, alias="LLM_TIMEOUT_SEC")
    llm_model_id: str | None = Field(default=None, alias="LLM_MODEL_ID")
    llm_fallback_provider: str | None = Field(default=None, alias="LLM_FALLBACK_PROVIDER")
    llm_fallback_base_url: str | None = Field(default=None, alias="LLM_FALLBACK_BASE_URL")
    llm_fallback_api_key: str | None = Field(default=None, alias="LLM_FALLBACK_API_KEY")
    llm_fallback_model_id: str | None = Field(default=None, alias="LLM_FALLBACK_MODEL_ID")

    verification_execute_inline: bool = Field(default=False, alias="VERIFICATION_EXECUTE_INLINE")

    @field_validator(
        "allowed_cors_origins",
        "local_user_roles",
        "knowledge_allowed_local_source_roots",
        "mvp_global_role_codes",
        mode="before",
    )
    @classmethod
    def parse_list_values(cls, value: Any) -> list[str]:
        return _parse_env_list(value)

    def normalized_app_env(self) -> str:
        return (self.app_env or "").strip().lower()

    def normalized_auth_mode(self) -> str:
        return (self.auth_mode or "").strip().lower()

    def is_local_env(self) -> bool:
        return self.normalized_app_env() in LOCAL_APP_ENVS

    def is_dev_env(self) -> bool:
        return self.normalized_app_env() in DEV_APP_ENVS

    def is_staging_env(self) -> bool:
        return self.normalized_app_env() in STAGING_APP_ENVS

    def is_prod_like_env(self) -> bool:
        return self.normalized_app_env() in PROD_APP_ENVS

    def is_strict_runtime_env(self) -> bool:
        return self.normalized_app_env() in STRICT_RUNTIME_APP_ENVS

    def is_local_noauth(self) -> bool:
        return self.normalized_auth_mode() == "local_noauth"

    def is_trusted_headers_auth(self) -> bool:
        return self.normalized_auth_mode() == "trusted_headers"

    def normalized_mvp_global_role_codes(self) -> set[str]:
        values = self.mvp_global_role_codes or []
        return {str(item).strip().upper() for item in values if str(item).strip()}

    def allows_mvp_permissive_local_access(self) -> bool:
        return bool(
            self.mvp_permissive_local_access and (self.is_local_env() or self.is_local_noauth())
        )

    @staticmethod
    def _is_placeholder_secret(value: str | None) -> bool:
        if value is None:
            return False
        return value.strip().lower() in INSECURE_SECRET_SENTINELS

    @staticmethod
    def _is_local_origin(origin: str) -> bool:
        candidate = origin.strip().lower()
        return (
            candidate.startswith("http://localhost")
            or candidate.startswith("https://localhost")
            or "127.0.0.1" in candidate
        )

    def has_permissive_cors_configuration(self) -> bool:
        return any(
            origin.strip() in PERMISSIVE_CORS_ORIGINS or self._is_local_origin(origin)
            for origin in self.allowed_cors_origins
        )

    @model_validator(mode="after")
    def validate_runtime_providers(self) -> Settings:
        strict_runtime = self.is_strict_runtime_env()
        embedding_provider = (self.embedding_provider or "").strip().lower()
        llm_provider = (self.llm_provider or "").strip().lower()
        auth_mode = self.normalized_auth_mode()

        if self.knowledge_chunk_target_tokens < 120:
            raise ValidationError(
                "KNOWLEDGE_CHUNK_TARGET_TOKENS must be at least 120",
                error_code="KNOWLEDGE_CHUNK_TARGET_TOKENS_INVALID",
            )
        if not 0 <= int(self.knowledge_chunk_overlap_pct) <= 40:
            raise ValidationError(
                "KNOWLEDGE_CHUNK_OVERLAP_PCT must be between 0 and 40",
                error_code="KNOWLEDGE_CHUNK_OVERLAP_PCT_INVALID",
            )
        if self.knowledge_large_document_threshold_bytes < 0:
            raise ValidationError(
                "KNOWLEDGE_LARGE_DOCUMENT_THRESHOLD_BYTES must be non-negative",
                error_code="KNOWLEDGE_LARGE_DOCUMENT_THRESHOLD_INVALID",
            )
        if self.knowledge_large_document_chunk_target_tokens < 120:
            raise ValidationError(
                "KNOWLEDGE_LARGE_DOCUMENT_CHUNK_TARGET_TOKENS must be at least 120",
                error_code="KNOWLEDGE_LARGE_DOCUMENT_CHUNK_TARGET_TOKENS_INVALID",
            )
        if not 0 <= int(self.knowledge_large_document_chunk_overlap_pct) <= 40:
            raise ValidationError(
                "KNOWLEDGE_LARGE_DOCUMENT_CHUNK_OVERLAP_PCT must be between 0 and 40",
                error_code="KNOWLEDGE_LARGE_DOCUMENT_CHUNK_OVERLAP_PCT_INVALID",
            )
        if self.knowledge_large_document_chunk_max_chars <= 0:
            raise ValidationError(
                "KNOWLEDGE_LARGE_DOCUMENT_CHUNK_MAX_CHARS must be positive",
                error_code="KNOWLEDGE_LARGE_DOCUMENT_CHUNK_MAX_CHARS_INVALID",
            )
        if self.knowledge_large_document_max_chunks < 0:
            raise ValidationError(
                "KNOWLEDGE_LARGE_DOCUMENT_MAX_CHUNKS must be non-negative",
                error_code="KNOWLEDGE_LARGE_DOCUMENT_MAX_CHUNKS_INVALID",
            )
        if self.knowledge_llm_extraction_max_chunks < 0:
            raise ValidationError(
                "KNOWLEDGE_LLM_EXTRACTION_MAX_CHUNKS must be non-negative",
                error_code="KNOWLEDGE_LLM_EXTRACTION_MAX_CHUNKS_INVALID",
            )
        if self.knowledge_fetch_timeout_sec <= 0:
            raise ValidationError(
                "KNOWLEDGE_FETCH_TIMEOUT_SEC must be positive",
                error_code="KNOWLEDGE_FETCH_TIMEOUT_INVALID",
            )
        if self.knowledge_max_document_size_bytes <= 0:
            raise ValidationError(
                "KNOWLEDGE_MAX_DOCUMENT_SIZE_BYTES must be positive",
                error_code="KNOWLEDGE_MAX_DOCUMENT_SIZE_INVALID",
            )
        if self.knowledge_max_upload_size_bytes <= 0:
            raise ValidationError(
                "KNOWLEDGE_MAX_UPLOAD_SIZE_BYTES must be positive",
                error_code="KNOWLEDGE_MAX_UPLOAD_SIZE_INVALID",
            )

        if self.knowledge_auto_sync_interval_days < 1:
            raise ValidationError(
                "KNOWLEDGE_AUTO_SYNC_INTERVAL_DAYS must be at least 1",
                error_code="KNOWLEDGE_AUTO_SYNC_INTERVAL_INVALID",
            )

        if auth_mode not in {"local_noauth", "trusted_headers"}:
            raise ValidationError(
                "AUTH_MODE must be one of: local_noauth, trusted_headers",
                error_code="AUTH_MODE_UNSUPPORTED",
            )

        if self.is_local_noauth() and not self.local_user_login.strip():
            raise ValidationError(
                "LOCAL_USER_LOGIN must be configured when AUTH_MODE=local_noauth",
                error_code="LOCAL_USER_LOGIN_REQUIRED",
            )

        if self.is_local_noauth() and not self.is_local_env():
            raise ValidationError(
                "AUTH_MODE=local_noauth is allowed only when APP_ENV=local or APP_ENV=test",
                error_code="AUTH_MODE_ENV_RESTRICTED",
            )

        if strict_runtime and self.debug:
            raise ValidationError(
                "DEBUG must be false in staging and production-like environments",
                error_code="DEBUG_FORBIDDEN_IN_STRICT_RUNTIME",
            )

        if strict_runtime and self.has_permissive_cors_configuration():
            raise ValidationError(
                "ALLOWED_CORS_ORIGINS must not contain localhost, 127.0.0.1, or wildcard entries in staging and production-like environments",
                error_code="CORS_STRICT_RUNTIME_INVALID",
            )

        for field_name, env_name in (
            ("llm_api_key", "LLM_API_KEY"),
            ("embedding_api_key", "EMBEDDING_API_KEY"),
            ("reranker_api_key", "RERANKER_API_KEY"),
        ):
            if strict_runtime and self._is_placeholder_secret(getattr(self, field_name)):
                raise ValidationError(
                    f"{env_name} must not use a placeholder or test secret outside local/dev environments",
                    error_code="PLACEHOLDER_SECRET_FORBIDDEN",
                    details={"env_name": env_name},
                )

        if self.is_prod_like_env() and embedding_provider in {"", "statistical", "local"}:
            raise ValidationError(
                "Release runtime requires a real embedding provider; statistical embeddings are allowed only for local/dev flows",
                error_code="EMBEDDING_PROVIDER_RELEASE_REQUIRED",
            )

        if (
            self.is_prod_like_env()
            and embedding_provider
            in {
                "http_json",
                "openai_compatible",
                "local_inference",
                "ollama",
                "local_openai_compatible",
            }
            and not self.embedding_base_url
        ):
            raise ValidationError(
                "EMBEDDING_BASE_URL is required for the selected embedding provider",
                error_code="EMBEDDING_BASE_URL_REQUIRED",
            )

        if self.is_prod_like_env() and llm_provider in {"", "statistical"}:
            raise ValidationError(
                "Release runtime requires a real LLM provider",
                error_code="LLM_PROVIDER_RELEASE_REQUIRED",
            )

        if (
            self.is_prod_like_env()
            and llm_provider
            in {
                "http_json",
                "openai_compatible",
                "local_inference",
                "ollama",
                "local_openai_compatible",
            }
            and not self.llm_base_url
        ):
            raise ValidationError(
                "LLM_BASE_URL is required for the selected LLM provider",
                error_code="LLM_BASE_URL_REQUIRED",
            )

        reranker_provider = (self.reranker_provider or "").strip().lower()
        if reranker_provider not in {"", "heuristic", "openai_compatible"}:
            raise ValidationError(
                "RERANKER_PROVIDER must be one of: heuristic, openai_compatible",
                error_code="RERANKER_PROVIDER_UNSUPPORTED",
            )
        if reranker_provider == "openai_compatible" and not self.reranker_base_url:
            raise ValidationError(
                "RERANKER_BASE_URL is required when RERANKER_PROVIDER=openai_compatible",
                error_code="RERANKER_BASE_URL_REQUIRED",
            )

        if int(self.embedding_dimensions) <= 0:
            raise ValidationError(
                "EMBEDDING_DIMENSIONS must be positive",
                error_code="EMBEDDING_DIMENSIONS_INVALID",
            )
        if int(self.embedding_batch_size) <= 0:
            raise ValidationError(
                "EMBEDDING_BATCH_SIZE must be positive",
                error_code="EMBEDDING_BATCH_SIZE_INVALID",
            )
        if int(self.embedding_dimensions) != int(EMBEDDING_VECTOR_DIMENSIONS):
            raise ValidationError(
                "Configured embedding dimensions do not match the database vector column dimensions",
                error_code="EMBEDDING_DIMENSIONS_MISMATCH",
                details={
                    "configured_dimensions": int(self.embedding_dimensions),
                    "database_dimensions": int(EMBEDDING_VECTOR_DIMENSIONS),
                },
            )
        if not (self.embedding_profile or "").strip():
            raise ValidationError(
                "EMBEDDING_PROFILE must not be empty",
                error_code="EMBEDDING_PROFILE_REQUIRED",
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
