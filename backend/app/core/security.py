from __future__ import annotations

from dataclasses import dataclass, field

from app.core.exceptions import AuthenticationError
from app.db.enums import AccountType


def parse_account_type(raw_value: str | None) -> AccountType:
    candidate = (raw_value or AccountType.HUMAN.value).strip().lower()
    try:
        return AccountType(candidate)
    except ValueError as exc:
        raise AuthenticationError(
            message="Invalid authentication headers",
            technical_message=f"Unsupported account type: {raw_value!r}",
        ) from exc


@dataclass(slots=True)
class AuthHeaders:
    login: str | None
    display_name: str | None
    roles: list[str]
    account_type: AccountType


@dataclass(slots=True)
class AuthPrincipal:
    user_id: str | None
    login: str
    display_name: str
    account_type: AccountType
    role_codes: list[str] = field(default_factory=list)
    is_authenticated: bool = True

    def has_any_role(self, required_roles: set[str]) -> bool:
        return bool(required_roles.intersection(set(self.role_codes)))
