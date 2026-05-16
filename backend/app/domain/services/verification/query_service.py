from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    CheckResultStatus,
    Severity,
    VerificationRunStatus,
)
from app.db.models.generation import SolutionVersion
from app.db.models.verification import (
    CheckResult,
    VerificationProtocol,
    VerificationRun,
)
from app.db.repositories.verification import (
    VerificationRunRepository,
)
from app.domain.services.mvp_access import has_mvp_global_scope
from app.domain.services.principal_keys import principal_owner_key
from app.domain.services.publication import PublicationArtifactService

logger = logging.getLogger(__name__)

TERMINAL_VERIFICATION_STATUSES = {
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELED,
}


SEVERITY_PRIORITY = {
    Severity.INFO.value: 1,
    Severity.MINOR.value: 2,
    Severity.MAJOR.value: 3,
    Severity.CRITICAL.value: 4,
}


def _highest_non_pass_severity(check_results: list[CheckResult]) -> str | None:
    severities: list[str] = []
    for item in check_results:
        if item.status == CheckResultStatus.PASSED:
            continue
        severity = getattr(item.severity, "value", item.severity)
        normalized = str(severity or "").strip().lower()
        if normalized:
            severities.append(normalized)
    if not severities:
        return None
    return max(severities, key=lambda value: SEVERITY_PRIORITY.get(value, 0))


class VerificationQueryService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.runs = VerificationRunRepository(session)
        self.publication_artifacts = PublicationArtifactService(session)

    def _has_global_scope(self, principal: AuthPrincipal) -> bool:
        return has_mvp_global_scope(self.settings, principal)

    def _ensure_solution_access(self, solution: SolutionVersion, principal: AuthPrincipal) -> None:
        if self._has_global_scope(principal):
            return
        owner_key = principal_owner_key(principal)
        if owner_key and str(solution.business_task.created_by_user_id) == owner_key:
            return
        raise AuthorizationError("Нет доступа к запрошенному объекту проверки")

    def list_solution_runs(
        self, solution_version_id: str, principal: AuthPrincipal
    ) -> list[VerificationRun]:
        items = self.runs.list_for_solution(solution_version_id)
        if not items:
            return []
        self._ensure_solution_access(items[0].solution_version, principal)
        return items

    def list_protocols(
        self,
        *,
        principal: AuthPrincipal,
        summary_status: str | None = None,
        severity: str | None = None,
        solution_version_id: str | None = None,
        knowledge_version_id: str | None = None,
        has_errors: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        batch_size = max(limit, 100)
        offset = 0
        rows: list[dict[str, Any]] = []
        while len(rows) < limit:
            statement = (
                select(VerificationProtocol)
                .join(VerificationProtocol.verification_run)
                .options(
                    selectinload(VerificationProtocol.check_results),
                    selectinload(VerificationProtocol.verification_run)
                    .selectinload(VerificationRun.solution_version)
                    .selectinload(SolutionVersion.business_task),
                )
                .order_by(VerificationProtocol.issued_at.desc())
                .offset(offset)
                .limit(batch_size)
            )
            items = list(self.session.scalars(statement))
            if not items:
                break
            for protocol in items:
                run = protocol.verification_run
                try:
                    self._ensure_solution_access(run.solution_version, principal)
                except AuthorizationError:
                    continue
                scope_snapshot = run.scope_snapshot or {}
                protocol_has_errors = any(
                    item.status in {CheckResultStatus.FAILED, CheckResultStatus.NOT_DETERMINED}
                    for item in protocol.check_results
                )
                max_severity = _highest_non_pass_severity(protocol.check_results)
                row = {
                    "verification_protocol_id": str(protocol.verification_protocol_id),
                    "verification_run_id": str(protocol.verification_run_id),
                    "solution_version_id": str(run.solution_version_id),
                    "knowledge_version_id": str(run.knowledge_version_id),
                    "protocol_no": protocol.protocol_no,
                    "summary_status": protocol.summary_status,
                    "status": protocol.status,
                    "created_at": protocol.issued_at,
                    "validation_scope": scope_snapshot.get("validation_scope", "full"),
                    "rulebook_version": scope_snapshot.get("rulebook_version"),
                    "has_errors": protocol_has_errors,
                    "highest_non_pass_severity": max_severity,
                }
                if (
                    summary_status is not None
                    and getattr(row["summary_status"], "value", row["summary_status"])
                    != summary_status
                ):
                    continue
                if severity is not None and row["highest_non_pass_severity"] != severity:
                    continue
                if (
                    solution_version_id is not None
                    and row["solution_version_id"] != solution_version_id
                ):
                    continue
                if (
                    knowledge_version_id is not None
                    and row["knowledge_version_id"] != knowledge_version_id
                ):
                    continue
                if has_errors is not None and row["has_errors"] is not has_errors:
                    continue
                row.pop("highest_non_pass_severity", None)
                rows.append(row)
                if len(rows) >= limit:
                    break
            offset += len(items)
            if len(items) < batch_size:
                break
        return rows

    def get_protocol(
        self, verification_protocol_id: str, principal: AuthPrincipal | None = None
    ) -> VerificationProtocol:
        statement = (
            select(VerificationProtocol)
            .where(VerificationProtocol.verification_protocol_id == verification_protocol_id)
            .options(
                selectinload(VerificationProtocol.check_results),
                selectinload(VerificationProtocol.basis_documents),
                selectinload(VerificationProtocol.verification_run),
            )
        )
        protocol = self.session.scalar(statement)
        if protocol is None:
            raise NotFoundError("VerificationProtocol", verification_protocol_id)
        if principal is not None:
            self._ensure_solution_access(protocol.verification_run.solution_version, principal)
        return protocol

    def get_protocol_view(
        self, verification_protocol_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        protocol = self.get_protocol(verification_protocol_id, principal)
        artifact = self.publication_artifacts.get_current(
            target_type="verification_protocol", target_id=str(protocol.verification_protocol_id)
        )
        if artifact is None:
            raise ValidationError(
                "Протокол проверки ещё не опубликован",
                error_code="VERIFICATION_PROTOCOL_NOT_PUBLISHED",
            )
        return {
            "verification_protocol_id": str(protocol.verification_protocol_id),
            "protocol_no": protocol.protocol_no,
            "summary_status": protocol.summary_status,
            "protocol_status": protocol.status,
            "rendered_html": artifact.rendered_html,
            "issued_at": artifact.published_at,
            "publication_artifact_id": str(artifact.published_artifact_id),
            "publication_revision_no": artifact.revision_no,
            "artifact_state": artifact.state,
            "version_hash": artifact.version_hash,
        }
