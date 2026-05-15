from __future__ import annotations

from app.core.security import AuthPrincipal


def principal_actor_id(principal: AuthPrincipal | None) -> str | None:
    if principal is None:
        return None
    actor_id = principal.user_id or principal.login
    return str(actor_id) if actor_id else None


def principal_owner_key(principal: AuthPrincipal | None) -> str | None:
    return principal_actor_id(principal)


def principal_requested_by(
    principal: AuthPrincipal | None, *, fallback: str = "system.user"
) -> str:
    if principal is None:
        return fallback
    for value in (principal.login, principal.display_name, principal_actor_id(principal)):
        if value:
            return str(value)
    return fallback
