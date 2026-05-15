from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.db.enums import (
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
)

from .policies import (
    AUTO_SYNC_REFRESH_POLICIES,
    MANUAL_REFRESH_POLICIES,
    SUPPORTED_SOURCE_TYPES,
    default_refresh_policy_for_source,
    is_generation_selectable_version,
    normalize_refresh_policy,
    normalize_source_type,
    public_source_type,
    schedule_interval_days,
    uses_auto_sync,
    validate_source_transition,
)

TERMINAL_UPDATE_STATUSES = {
    KnowledgeUpdateStatus.COMPLETED,
    KnowledgeUpdateStatus.COMPLETED_WITH_WARNINGS,
    KnowledgeUpdateStatus.FAILED,
    KnowledgeUpdateStatus.CANCELED,
}


_normalize_source_type = normalize_source_type
_public_source_type = public_source_type
_default_refresh_policy_for_source = default_refresh_policy_for_source
_normalize_refresh_policy = normalize_refresh_policy
_uses_auto_sync = uses_auto_sync
_schedule_interval_days = schedule_interval_days
_validate_source_transition = validate_source_transition
_is_generation_selectable_version = is_generation_selectable_version


def _build_allowed_local_source_roots(settings: Settings | None) -> list[str]:
    resolved_settings = settings or get_settings()
    roots: list[str] = []

    def add_root(candidate: str | None) -> None:
        if not candidate:
            return
        normalized = str(candidate).strip()
        if normalized and normalized not in roots:
            roots.append(normalized)

    for candidate in getattr(resolved_settings, "knowledge_allowed_local_source_roots", []) or []:
        add_root(candidate)

    add_root(getattr(resolved_settings, "knowledge_upload_dir", None))

    for candidate in (
        "./data/knowledge_sources",
        "./app/bootstrap/knowledge_bundle",
    ):
        add_root(candidate)
    return roots


@dataclass(slots=True)
class ValidationSummary:
    run_status: KnowledgeUpdateStatus
    version_status: KnowledgeVersionStatus
    details: dict[str, Any]


__all__ = [
    "AUTO_SYNC_REFRESH_POLICIES",
    "MANUAL_REFRESH_POLICIES",
    "SUPPORTED_SOURCE_TYPES",
    "TERMINAL_UPDATE_STATUSES",
    "ValidationSummary",
    "_build_allowed_local_source_roots",
    "_default_refresh_policy_for_source",
    "_is_generation_selectable_version",
    "_normalize_refresh_policy",
    "_normalize_source_type",
    "_public_source_type",
    "_schedule_interval_days",
    "_uses_auto_sync",
    "_validate_source_transition",
]
