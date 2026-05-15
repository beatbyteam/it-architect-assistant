from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.db.enums import (
    GenerationRunStatus,
    SolutionVersionStatus,
)
from app.db.models.generation import (
    SolutionVersion,
)
from app.domain.services.publication import PublicationArtifactService
from app.integrations.generation import (
    SolutionRenderer,
)
from app.integrations.generation.contracts import REQUIRED_SECTION_CODES, GenerationSolutionPayload

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


class SolutionPublicationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.renderer = SolutionRenderer()
        self.publication_artifacts = PublicationArtifactService(session)

    def publish(
        self,
        *,
        solution: SolutionVersion,
        payload: GenerationSolutionPayload,
        created_by_user_id: str | None = None,
    ) -> tuple[SolutionVersion, Any]:
        self._validate_persisted_solution(solution)
        rendered_markdown = self.renderer.render_markdown(payload)
        rendered_html = self.renderer.render_html(payload)
        published_at = datetime.now(UTC)
        artifact = self.publication_artifacts.publish(
            artifact_type="solution_view",
            target_type="solution_version",
            target_id=str(solution.solution_version_id),
            rendered_markdown=rendered_markdown,
            rendered_html=rendered_html,
            created_by_user_id=created_by_user_id,
            published_at=published_at,
            metadata={
                "solution_version_id": str(solution.solution_version_id),
                "generation_run_id": str(solution.generation_run_id),
                "solution_title": solution.solution_title,
                "status": SolutionVersionStatus.PUBLISHED.value,
            },
        )
        solution.rendered_markdown = rendered_markdown
        solution.rendered_html = rendered_html
        solution.status = SolutionVersionStatus.PUBLISHED
        solution.published_at = published_at
        self.session.add(solution)
        self.session.flush()
        self.session.refresh(solution)
        return solution, artifact

    def _validate_persisted_solution(self, solution: SolutionVersion) -> None:
        section_codes = {section.section_code for section in solution.sections}
        missing = [code for code in REQUIRED_SECTION_CODES if code not in section_codes]
        if missing:
            raise ValidationError(
                f"Cannot publish solution without required sections: {', '.join(missing)}",
                error_code="SOLUTION_PUBLICATION_BLOCKED",
            )
