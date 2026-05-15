from __future__ import annotations

from app.core.exceptions import DependencyUnavailableError


def resolve_openai_compatible_endpoint(
    *, base_url: str | None, endpoint_path: str, dependency_name: str, missing_message: str
) -> str:
    if not base_url:
        raise DependencyUnavailableError(dependency_name, missing_message)
    normalized = base_url.rstrip("/")
    endpoint_suffix = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
    if normalized.endswith(endpoint_suffix):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}{endpoint_suffix}"
    return f"{normalized}/v1{endpoint_suffix}"
