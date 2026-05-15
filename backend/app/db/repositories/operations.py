from __future__ import annotations

from sqlalchemy import select

from app.db.models.operations import OperationStep
from app.db.repositories.base import Repository


class OperationStepRepository(Repository[OperationStep]):
    model = OperationStep

    def get_by_scope(
        self, *, operation_kind: str, operation_id: str, step_code: str
    ) -> OperationStep | None:
        statement = select(OperationStep).where(
            OperationStep.operation_kind == operation_kind,
            OperationStep.operation_id == str(operation_id),
            OperationStep.step_code == step_code,
        )
        return self.session.scalar(statement)

    def list_for_operation(self, *, operation_kind: str, operation_id: str) -> list[OperationStep]:
        statement = (
            select(OperationStep)
            .where(
                OperationStep.operation_kind == operation_kind,
                OperationStep.operation_id == str(operation_id),
            )
            .order_by(OperationStep.started_at.asc(), OperationStep.step_code.asc())
        )
        return list(self.session.scalars(statement))
