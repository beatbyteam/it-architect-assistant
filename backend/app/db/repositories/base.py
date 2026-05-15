from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def get(self, primary_key) -> ModelT | None:
        return self.session.get(self.model, primary_key)

    def list_all(self) -> list[ModelT]:
        return list(self.session.scalars(select(self.model)))

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)

    def execute(self, statement: Select[tuple[ModelT]]) -> list[ModelT]:
        return list(self.session.scalars(statement))
