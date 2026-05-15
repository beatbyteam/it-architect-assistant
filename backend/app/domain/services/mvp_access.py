from __future__ import annotations

from app.core.config import Settings
from app.core.security import AuthPrincipal
from app.db.enums import AccountType

DEFAULT_MVP_GLOBAL_ROLE_CODES = frozenset({"ADMIN", "MVP_ADMIN"})


def has_mvp_global_scope(settings: Settings, principal: AuthPrincipal) -> bool:
    if principal.account_type == AccountType.SERVICE:
        return True
    if settings.allows_mvp_permissive_local_access():
        return True
    required_roles = settings.normalized_mvp_global_role_codes() or set(
        DEFAULT_MVP_GLOBAL_ROLE_CODES
    )
    return principal.has_any_role(required_roles)
