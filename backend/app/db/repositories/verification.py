from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.enums import VerificationRunStatus
from app.db.models.verification import CheckResult, VerificationProtocol, VerificationRun
from app.db.repositories.base import Repository

TERMINAL_VERIFICATION_RUN_STATUSES = {
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELED,
}


class VerificationRunRepository(Repository[VerificationRun]):
    model = VerificationRun

    def list_recent(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        correlation_id: str | None = None,
        eager: bool = False,
    ) -> list[VerificationRun]:
        statement = select(VerificationRun)
        if correlation_id is not None:
            statement = statement.where(VerificationRun.correlation_id == correlation_id)
        if eager:
            statement = statement.options(selectinload(VerificationRun.protocol))
        statement = (
            statement.order_by(VerificationRun.started_at.desc()).offset(offset).limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_for_solution(self, solution_version_id) -> list[VerificationRun]:
        statement = (
            select(VerificationRun)
            .where(VerificationRun.solution_version_id == solution_version_id)
            .order_by(VerificationRun.started_at.desc())
            .options(selectinload(VerificationRun.protocol))
        )
        return list(self.session.scalars(statement))

    def get_running_for_solution(self, solution_version_id) -> VerificationRun | None:
        statement = select(VerificationRun).where(
            VerificationRun.solution_version_id == solution_version_id,
            VerificationRun.status.not_in(tuple(TERMINAL_VERIFICATION_RUN_STATUSES)),
        )
        return self.session.scalar(statement)

    def get_by_correlation_id(self, correlation_id: str) -> VerificationRun | None:
        statement = (
            select(VerificationRun)
            .where(VerificationRun.correlation_id == correlation_id)
            .order_by(VerificationRun.started_at.desc())
            .options(selectinload(VerificationRun.protocol))
        )
        return self.session.scalar(statement)


class VerificationProtocolRepository(Repository[VerificationProtocol]):
    model = VerificationProtocol


class CheckResultRepository(Repository[CheckResult]):
    model = CheckResult
