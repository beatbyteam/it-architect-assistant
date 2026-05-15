from __future__ import annotations

from app.core.exceptions import ValidationError
from app.db.enums import SourceType

SUPPORTED_SOURCE_TYPES = {
    SourceType.REPOSITORY,
    SourceType.URL_LIST,
    SourceType.MANUAL_UPLOAD,
    SourceType.URL,
    SourceType.LOCAL_FOLDER,
}
AUTO_SYNC_REFRESH_POLICIES = {"monthly", "weekly", "scheduled", "auto"}
MANUAL_REFRESH_POLICIES = {"manual", "off", "disabled", "never"}
REFRESH_POLICY_ALIASES = {
    "": None,
    "monthly": "monthly",
    "auto_monthly": "monthly",
    "scheduled": "monthly",
    "auto": "monthly",
    "weekly": "weekly",
    "manual": "manual",
    "off": "manual",
    "disabled": "manual",
    "never": "manual",
}
ALLOWED_SOURCE_TRANSITIONS = {
    "draft": {"active", "disabled"},
    "active": {"disabled", "archived"},
    "disabled": {"active", "archived"},
    "archived": set(),
}
GENERATION_SELECTABLE_VERSION_STATUS_VALUES = {"active", "validated"}


def normalize_source_type(source_type: SourceType):
    if source_type == SourceType.URL:
        return SourceType.URL_LIST
    if source_type == SourceType.LOCAL_FOLDER:
        return SourceType.REPOSITORY
    return source_type


def public_source_type(source_type):
    raw = getattr(source_type, "value", source_type)
    if raw == SourceType.REPOSITORY.value:
        return SourceType.LOCAL_FOLDER
    if raw == SourceType.URL_LIST.value:
        return SourceType.URL
    return source_type


def default_refresh_policy_for_source(source_type: SourceType) -> str:
    normalized = normalize_source_type(source_type)
    if normalized == SourceType.MANUAL_UPLOAD:
        return "manual"
    return "monthly"


def normalize_refresh_policy(value: str | None) -> str | None:
    if value is None:
        return None
    return REFRESH_POLICY_ALIASES.get(value.strip().lower(), value.strip().lower())


def uses_auto_sync(refresh_policy: str | None) -> bool:
    policy = normalize_refresh_policy(refresh_policy)
    if not policy:
        return True
    if policy in MANUAL_REFRESH_POLICIES:
        return False
    return policy in AUTO_SYNC_REFRESH_POLICIES


def schedule_interval_days(refresh_policy: str | None, default_days: int) -> int:
    return 7 if normalize_refresh_policy(refresh_policy) == "weekly" else default_days


def validate_source_transition(current_status, next_status) -> None:
    current_value = getattr(current_status, "value", current_status)
    next_value = getattr(next_status, "value", next_status)
    if next_value == current_value:
        return
    allowed = ALLOWED_SOURCE_TRANSITIONS.get(str(current_value), set())
    if next_value not in allowed:
        raise ValidationError(
            "Unsupported knowledge source lifecycle transition",
            error_code="KNOWLEDGE_SOURCE_TRANSITION_INVALID",
            details={"current_status": current_value, "next_status": next_value},
        )


def is_generation_selectable_version(version) -> bool:
    return (
        getattr(getattr(version, "status", None), "value", getattr(version, "status", None))
        in GENERATION_SELECTABLE_VERSION_STATUS_VALUES
    )
