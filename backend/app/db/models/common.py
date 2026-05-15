from __future__ import annotations

from enum import StrEnum
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import Enum as SAEnum
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column

EnumType = TypeVar("EnumType", bound=StrEnum)


def enum_column(enum_cls: type[EnumType], *, nullable: bool = False, **kwargs):
    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            validate_strings=True,
            values_callable=lambda enum_items: [item.value for item in enum_items],
        ),
        nullable=nullable,
        **kwargs,
    )


def uuid_primary_key(column_name: str):
    return mapped_column(
        column_name,
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
