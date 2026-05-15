from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.enums import GenerationRunStatus
from app.db.models.generation import BusinessTask, GenerationRun, SolutionVersion
from app.db.repositories.base import Repository

TERMINAL_GENERATION_RUN_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


class BusinessTaskRepository(Repository[BusinessTask]):
    model = BusinessTask

    def list_visible(
        self, *, created_by_user_id: str | None = None, include_all: bool = False
    ) -> list[BusinessTask]:
        statement = select(BusinessTask)
        if not include_all and created_by_user_id is not None:
            statement = statement.where(BusinessTask.created_by_user_id == created_by_user_id)
        statement = statement.order_by(BusinessTask.created_at.desc())
        return list(self.session.scalars(statement))


class GenerationRunRepository(Repository[GenerationRun]):
    model = GenerationRun

    def list_recent(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        correlation_id: str | None = None,
        eager: bool = False,
    ) -> list[GenerationRun]:
        statement = select(GenerationRun)
        if correlation_id is not None:
            statement = statement.where(GenerationRun.correlation_id == correlation_id)
        if eager:
            statement = statement.options(selectinload(GenerationRun.solution_version))
        statement = statement.order_by(GenerationRun.started_at.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def list_for_task(self, business_task_id) -> list[GenerationRun]:
        statement = (
            select(GenerationRun)
            .where(GenerationRun.business_task_id == business_task_id)
            .order_by(GenerationRun.started_at.desc())
        )
        return list(self.session.scalars(statement))

    def get_running_for_task(self, business_task_id) -> GenerationRun | None:
        statement = select(GenerationRun).where(
            GenerationRun.business_task_id == business_task_id,
            GenerationRun.status.not_in(tuple(TERMINAL_GENERATION_RUN_STATUSES)),
        )
        return self.session.scalar(statement)

    def get_running_for_owner(self, created_by_user_id: str | None = None) -> GenerationRun | None:
        statement = select(GenerationRun).join(GenerationRun.business_task).where(
            GenerationRun.status.not_in(tuple(TERMINAL_GENERATION_RUN_STATUSES))
        )
        if created_by_user_id is not None:
            statement = statement.where(BusinessTask.created_by_user_id == created_by_user_id)
        statement = statement.order_by(GenerationRun.started_at.desc()).limit(1)
        return self.session.scalar(statement)

    def get_by_correlation_id(self, correlation_id: str) -> GenerationRun | None:
        statement = (
            select(GenerationRun)
            .where(GenerationRun.correlation_id == correlation_id)
            .order_by(GenerationRun.started_at.desc())
        )
        return self.session.scalar(statement)


class SolutionVersionRepository(Repository[SolutionVersion]):
    model = SolutionVersion

    def list_for_task(self, business_task_id) -> list[SolutionVersion]:
        statement = (
            select(SolutionVersion)
            .where(SolutionVersion.business_task_id == business_task_id)
            .order_by(SolutionVersion.version_no.desc())
        )
        return list(self.session.scalars(statement))

    def get_next_version_no(self, business_task_id) -> int:
        statement = select(func.coalesce(func.max(SolutionVersion.version_no), 0)).where(
            SolutionVersion.business_task_id == business_task_id
        )
        value = self.session.scalar(statement) or 0
        return int(value) + 1
