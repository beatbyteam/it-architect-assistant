from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthorizationError
from app.core.security import AuthHeaders, AuthPrincipal, parse_account_type
from app.db.enums import normalize_role_code
from app.db.session import get_session
from app.domain.services import AuthLiteService

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_auth_headers(request: Request, settings: SettingsDep) -> AuthHeaders:
    if settings.is_local_noauth():
        return AuthHeaders(
            login=settings.local_user_login,
            display_name=settings.local_user_display_name,
            roles=[normalize_role_code(item) for item in settings.local_user_roles if item],
            account_type=parse_account_type(settings.local_user_account_type),
        )

    login = request.headers.get(settings.auth_header_login)
    display_name = request.headers.get(settings.auth_header_display_name)
    roles = request.headers.get(settings.auth_header_roles)
    account_type = request.headers.get(settings.auth_header_account_type)

    parsed_roles = [normalize_role_code(item) for item in roles.split(",")] if roles else []
    return AuthHeaders(
        login=login,
        display_name=display_name,
        roles=[role for role in parsed_roles if role],
        account_type=parse_account_type(account_type),
    )


def get_current_principal(
    session: SessionDep,
    settings: SettingsDep,
    headers: Annotated[AuthHeaders, Depends(get_auth_headers)],
) -> AuthPrincipal:
    return AuthLiteService(session=session, settings=settings).resolve_principal(headers)


PrincipalDep = Annotated[AuthPrincipal, Depends(get_current_principal)]


def require_roles(*required_roles: str) -> Callable[..., AuthPrincipal]:
    def dependency(principal: PrincipalDep, settings: SettingsDep) -> AuthPrincipal:
        if settings.is_local_noauth():
            return principal
        if not principal.has_any_role(set(required_roles)):
            raise AuthorizationError()
        return principal

    return dependency


def require_write_access(principal: PrincipalDep, settings: SettingsDep) -> AuthPrincipal:
    if settings.is_local_noauth():
        return principal
    if not principal.is_authenticated:
        raise AuthorizationError("Authenticated principal is required for write operations")
    return principal


WriteGuardDep = Depends(require_write_access)
