from __future__ import annotations

from app.core.exceptions import AuthenticationError
from app.core.security import AuthHeaders, AuthPrincipal
from app.db.enums import normalize_role_code


class AuthLiteService:
    def __init__(self, session, settings) -> None:
        self.session = session
        self.settings = settings

    def resolve_principal(self, headers: AuthHeaders) -> AuthPrincipal:
        if self.settings.is_local_noauth():
            role_codes = sorted(
                {normalize_role_code(code) for code in self.settings.local_user_roles if code}
            )
            return AuthPrincipal(
                user_id=self.settings.local_user_login,
                login=self.settings.local_user_login,
                display_name=self.settings.local_user_display_name
                or self.settings.auth_default_display_name,
                account_type=headers.account_type,
                role_codes=role_codes,
                is_authenticated=True,
            )

        if not headers.login:
            raise AuthenticationError()

        role_codes = sorted({normalize_role_code(code) for code in headers.roles if code})
        return AuthPrincipal(
            user_id=headers.login,
            login=headers.login,
            display_name=headers.display_name or self.settings.auth_default_display_name,
            account_type=headers.account_type,
            role_codes=role_codes,
            is_authenticated=True,
        )
