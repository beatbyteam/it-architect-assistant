from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import AuthPrincipal
from app.db.enums import (
    BusinessTaskStatus,
    GenerationRunStatus,
)
from app.db.models.generation import (
    BusinessTask,
)
from app.db.repositories.generation import (
    BusinessTaskRepository,
)
from app.domain.services.audit import AuditService
from app.schemas.generation import BusinessTaskCreateRequest

from ..mvp_access import has_mvp_global_scope
from ..principal_keys import principal_owner_key

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


class BusinessTaskService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.tasks = BusinessTaskRepository(session)
        self.audit = AuditService(session)

    def list_tasks(self, principal: AuthPrincipal) -> list[BusinessTask]:
        return self.tasks.list_visible(
            created_by_user_id=principal_owner_key(principal),
            include_all=self._has_global_scope(principal),
        )

    def get_task(
        self, business_task_id: str, principal: AuthPrincipal | None = None
    ) -> BusinessTask:
        task = self.tasks.get(business_task_id)
        if task is None:
            raise NotFoundError("BusinessTask", business_task_id)
        if principal is not None:
            self._ensure_task_access(task, principal)
        return task

    def create_task(
        self, payload: BusinessTaskCreateRequest, principal: AuthPrincipal
    ) -> BusinessTask:
        task = BusinessTask(
            created_by_user_id=principal_owner_key(principal),
            title=payload.title,
            task_text=payload.task_text,
            task_metadata=payload.metadata,
            status=BusinessTaskStatus.DRAFT,
        )
        self.tasks.add(task)
        self.session.flush()
        self.audit.record(
            event_type="generation.business_task.created",
            target_type="business_task",
            target_id=task.business_task_id,
            message="Business task created",
            actor_user_id=principal_owner_key(principal),
            payload={"title": payload.title, "has_metadata": bool(payload.metadata)},
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def _has_global_scope(self, principal: AuthPrincipal) -> bool:
        return has_mvp_global_scope(self.settings, principal)

    def _ensure_task_access(self, task: BusinessTask, principal: AuthPrincipal) -> None:
        if self._has_global_scope(principal):
            return
        owner_key = principal_owner_key(principal)
        if owner_key and str(task.created_by_user_id) == owner_key:
            return
        raise AuthorizationError("Access denied to the requested business task")
