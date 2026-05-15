from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    GenerationRunStatus,
)
from app.db.models.generation import (
    SolutionComponent,
    SolutionSection,
    SolutionSectionSourceRef,
    SolutionVersion,
)
from app.db.models.knowledge import KnowledgeFragment, SourceDocument
from app.db.models.verification import VerificationRun
from app.db.repositories.generation import (
    SolutionVersionRepository,
)
from app.domain.services.generation.task_service import BusinessTaskService
from app.domain.services.publication import PublicationArtifactService

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


class SolutionQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.solutions = SolutionVersionRepository(session)
        self.tasks = BusinessTaskService(session, settings=get_settings())
        self.publication_artifacts = PublicationArtifactService(session)

    def get_solution(
        self, solution_version_id: str, principal: AuthPrincipal | None = None
    ) -> SolutionVersion:
        statement = (
            select(SolutionVersion)
            .where(SolutionVersion.solution_version_id == solution_version_id)
            .options(
                selectinload(SolutionVersion.generation_run),
                selectinload(SolutionVersion.sections)
                .selectinload(SolutionSection.source_refs)
                .selectinload(SolutionSectionSourceRef.document)
                .selectinload(SourceDocument.source),
                selectinload(SolutionVersion.sections)
                .selectinload(SolutionSection.source_refs)
                .selectinload(SolutionSectionSourceRef.fragment)
                .selectinload(KnowledgeFragment.document)
                .selectinload(SourceDocument.source),
                selectinload(SolutionVersion.section_assessments),
                selectinload(SolutionVersion.architecture_entities),
                selectinload(SolutionVersion.architecture_relations),
                selectinload(SolutionVersion.components).selectinload(SolutionComponent.interfaces),
                selectinload(SolutionVersion.integrations),
                selectinload(SolutionVersion.list_items),
                selectinload(SolutionVersion.risks),
                selectinload(SolutionVersion.verification_runs).selectinload(
                    VerificationRun.protocol
                ),
            )
        )
        item = self.session.scalar(statement)
        if item is None:
            raise NotFoundError("SolutionVersion", solution_version_id)
        if principal is not None:
            self.tasks._ensure_task_access(item.business_task, principal)
        return item

    def list_task_solutions(
        self, business_task_id: str, principal: AuthPrincipal
    ) -> list[SolutionVersion]:
        statement = (
            select(SolutionVersion)
            .order_by(SolutionVersion.version_no.desc())
            .options(
                selectinload(SolutionVersion.generation_run),
                selectinload(SolutionVersion.sections)
                .selectinload(SolutionSection.source_refs)
                .selectinload(SolutionSectionSourceRef.document)
                .selectinload(SourceDocument.source),
                selectinload(SolutionVersion.sections)
                .selectinload(SolutionSection.source_refs)
                .selectinload(SolutionSectionSourceRef.fragment)
                .selectinload(KnowledgeFragment.document)
                .selectinload(SourceDocument.source),
                selectinload(SolutionVersion.section_assessments),
                selectinload(SolutionVersion.architecture_entities),
                selectinload(SolutionVersion.architecture_relations),
                selectinload(SolutionVersion.components).selectinload(SolutionComponent.interfaces),
                selectinload(SolutionVersion.integrations),
                selectinload(SolutionVersion.list_items),
                selectinload(SolutionVersion.risks),
            )
        )
        task = self.tasks.get_task(business_task_id, principal)
        return list(
            self.session.scalars(
                statement.where(SolutionVersion.business_task_id == task.business_task_id)
            )
        )

    def get_solution_view(
        self, solution_version_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        solution = self.get_solution(solution_version_id, principal)
        artifact = self.publication_artifacts.get_current(
            target_type="solution_version", target_id=str(solution.solution_version_id)
        )
        if artifact is None:
            raise ValidationError(
                "Solution has not been published yet", error_code="SOLUTION_NOT_PUBLISHED"
            )
        return {
            "solution_version_id": str(solution.solution_version_id),
            "solution_title": solution.solution_title,
            "rendered_html": artifact.rendered_html,
            "status": solution.status,
            "published_at": artifact.published_at,
            "publication_artifact_id": str(artifact.published_artifact_id),
            "publication_revision_no": artifact.revision_no,
            "artifact_state": artifact.state,
            "version_hash": artifact.version_hash,
        }
