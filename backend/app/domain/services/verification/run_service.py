from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AuditSeverity,
    SolutionVersionStatus,
    VerificationRunStatus,
)
from app.db.models.generation import SolutionComponent, SolutionSection, SolutionVersion
from app.db.models.knowledge import (
    KnowledgeFragment,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    NormativeRule,
    SourceDocument,
)
from app.db.models.verification import (
    VerificationRun,
)
from app.db.repositories.knowledge import KnowledgeVersionRepository
from app.db.repositories.verification import (
    VerificationProtocolRepository,
    VerificationRunRepository,
)
from app.domain.services.audit import AuditService
from app.domain.services.idempotency import IdempotencyService
from app.domain.services.immutable_snapshot import freeze_snapshot
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.domain.services.knowledge_snapshot import (
    build_knowledge_scope_snapshot,
)
from app.domain.services.operation_tracking import OperationTrackingService
from app.domain.services.presenters import retention_policy_payload
from app.domain.services.principal_keys import principal_owner_key
from app.domain.services.publication import PublicationArtifactService
from app.domain.services.workflow_runtime import (
    append_stage_history,
    dispatch_run,
    record_operation_step,
)
from app.integrations.knowledge.policy_stack import build_policy_stack
from app.integrations.verification import (
    VerificationRuleDefinition,
    VerificationRuleRegistry,
)
from app.schemas.verification import InternalVerificationRunStartRequest

from .document_scope import (
    build_document_scope_snapshot,
    filter_version_documents,
    normalize_document_ids,
)
from .persistence_service import VerificationProtocolPersistenceService
from .post_validation import VerificationPostValidator
from .query_service import VerificationQueryService
from .rule_engine import VerificationRuleEngine
from .runtime import execute_verification_run

logger = logging.getLogger(__name__)

TERMINAL_VERIFICATION_STATUSES = {
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELED,
}

SELECTED_DOCUMENT_TECHNICAL_RULE_CODES = {"VR-TEC-01", "VR-TEC-02", "VR-TEC-04"}
DOCUMENT_ROLE_RULE_CODES = {
    "ig1242_oda_component_inventory": {"VR-NRM-01"},
    "oda": {"VR-NRM-01"},
    "archimate_3_2": {"VR-NRM-02", "VR-NRM-05", "VR-NRM-06"},
    "technology_standard": {"VR-NRM-03"},
    "template_or_principles": {"VR-NRM-04"},
}
DOCUMENT_TITLE_RULE_CODES = (
    ("archimate", {"VR-NRM-02", "VR-NRM-05", "VR-NRM-06"}),
    (
        "togaf",
        {
            "VR-STR-01",
            "VR-STR-02",
            "VR-STR-03",
            "VR-STR-04",
            "VR-STR-05",
            "VR-STR-06",
            "VR-STR-07",
        },
    ),
    ("integration", {"VR-STR-04", "VR-CNS-01", "VR-CNS-05"}),
    ("интеграц", {"VR-STR-04", "VR-CNS-01", "VR-CNS-05"}),
    ("traceability", {"VR-CNS-02", "VR-CNS-06"}),
    ("principle", {"VR-NRM-04"}),
    ("template", {"VR-NRM-04"}),
)


class VerificationRunService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.runs = VerificationRunRepository(session)
        self.protocols = VerificationProtocolRepository(session)
        self.audit = AuditService(session)
        self.operations = OperationTrackingService(session)
        self.idempotency = IdempotencyService(session)
        self.registry = VerificationRuleRegistry()
        self.engine = VerificationRuleEngine()
        self.validator = VerificationPostValidator()
        self.persistence = VerificationProtocolPersistenceService(session)
        self.publication_artifacts = PublicationArtifactService(session)
        self.knowledge_query = KnowledgeQueryService(session, settings)
        self.knowledge_versions = KnowledgeVersionRepository(session)

    @staticmethod
    def _build_verification_idempotency_request_payload(
        *,
        solution: SolutionVersion,
        validation_scope: str,
        knowledge_version_id: str,
        scope_snapshot: dict[str, Any],
        publication_artifact: Any | None,
        rulebook_version: str | None,
    ) -> dict[str, Any]:
        publication_snapshot = (
            (scope_snapshot.get("publication_snapshot") or {})
            if isinstance(scope_snapshot, dict)
            else {}
        )
        return {
            "solution_version_id": str(solution.solution_version_id),
            "validation_scope": validation_scope,
            "knowledge_version_id": knowledge_version_id,
            "knowledge_version_ids": list(scope_snapshot.get("knowledge_version_ids") or []),
            "document_scope": dict(scope_snapshot.get("document_scope") or {}),
            "knowledge_scope_hash": (
                (scope_snapshot.get("knowledge_snapshot") or {}).get("snapshot_hash")
            ),
            "scope_snapshot_hash": ((scope_snapshot.get("_snapshot") or {}).get("payload_hash")),
            "rulebook_version": rulebook_version,
            "rule_codes": list(scope_snapshot.get("rule_codes") or []),
            "publication_revision_no": publication_snapshot.get("revision_no"),
            "publication_version_hash": publication_snapshot.get("version_hash"),
            "published_artifact_id": str(publication_artifact.published_artifact_id)
            if publication_artifact
            else None,
        }

    def start_run(
        self, payload: InternalVerificationRunStartRequest, principal: AuthPrincipal
    ) -> VerificationRun:
        solution = self._get_solution(payload.solution_version_id)
        scope_service = KnowledgeBaseService(self.session)
        try:
            knowledge_scope = scope_service.get_effective_scope(principal)
        except TypeError:  # compatibility with simplified test doubles
            knowledge_scope = scope_service.get_effective_scope()
        active_version = knowledge_scope.selected_generation_version()
        if active_version is None:
            raise ValidationError(
                "Active knowledge version is required for verification",
                error_code="ACTIVE_KNOWLEDGE_VERSION_MISSING",
            )
        knowledge_version_id = active_version.knowledge_version_id
        knowledge_snapshot = build_knowledge_scope_snapshot(
            mandatory_version=knowledge_scope.mandatory_version,
            selected_user_version=knowledge_scope.selected_user_version,
        )
        selected_document_ids = normalize_document_ids(payload.knowledge_document_ids)
        document_scope = build_document_scope_snapshot(
            knowledge_versions=[
                version
                for version in [
                    knowledge_scope.mandatory_version,
                    knowledge_scope.selected_user_version,
                ]
                if version is not None
            ],
            selected_document_ids=selected_document_ids,
        )
        rules = self._select_rules(payload.validation_scope, document_scope=document_scope)
        rulebook_version = getattr(self.registry, "version", None)
        publication_artifact = self.publication_artifacts.get_current(
            target_type="solution_version", target_id=str(solution.solution_version_id)
        )
        scope_snapshot = freeze_snapshot(
            {
                "solution_version_id": str(solution.solution_version_id),
                "generation_run_id": str(solution.generation_run_id),
                "knowledge_version_id": str(knowledge_version_id),
                "knowledge_version_ids": list(
                    knowledge_snapshot.get("effective_version_ids") or []
                ),
                "validation_scope": payload.validation_scope,
                "document_scope": document_scope,
                "rule_codes": [rule.code for rule in rules],
                "rulebook_version": rulebook_version,
                "knowledge_snapshot": knowledge_snapshot,
                "solution_snapshot": {
                    "solution_title": solution.solution_title,
                    "solution_status": getattr(solution.status, "value", solution.status),
                    "section_count": len(solution.sections),
                    "component_count": len(solution.components),
                    "integration_count": len(solution.integrations),
                    "risk_count": len(solution.risks),
                },
                "publication_snapshot": {
                    "published_artifact_id": str(publication_artifact.published_artifact_id)
                    if publication_artifact
                    else None,
                    "revision_no": publication_artifact.revision_no
                    if publication_artifact
                    else None,
                    "version_hash": publication_artifact.version_hash
                    if publication_artifact
                    else None,
                    "published_at": publication_artifact.published_at
                    if publication_artifact
                    else None,
                },
                "retention_policy": retention_policy_payload(target_type="verification_protocol"),
                "policy_stack": build_policy_stack(
                    use_case="verification", embeddings=self.knowledge_query.embeddings
                ).as_dict(),
            },
            snapshot_type="verification_scope",
        )
        request_payload = self._build_verification_idempotency_request_payload(
            solution=solution,
            validation_scope=payload.validation_scope,
            knowledge_version_id=str(knowledge_version_id),
            scope_snapshot=scope_snapshot,
            publication_artifact=publication_artifact,
            rulebook_version=rulebook_version,
        )
        owner_key = principal_owner_key(principal)
        existing = self.idempotency.resolve_existing(
            actor_user_id=owner_key,
            operation_name="verification.run.start",
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
        )
        if existing is not None:
            return self.get_run(existing.target_id, principal)
        if solution.status != SolutionVersionStatus.PUBLISHED:
            raise ValidationError(
                "Only published solution versions can be verified",
                error_code="SOLUTION_NOT_PUBLISHED",
            )
        running = self.runs.get_running_for_solution(solution.solution_version_id)
        if running is not None:
            raise ConflictError(
                "Verification run already active for solution",
                error_code="VERIFICATION_ALREADY_RUNNING",
            )
        run = VerificationRun(
            solution_version_id=solution.solution_version_id,
            knowledge_version_id=knowledge_version_id,
            started_by_user_id=owner_key,
            status=VerificationRunStatus.QUEUED,
            current_stage="queued",
            correlation_id=payload.correlation_id,
            scope_snapshot=scope_snapshot,
            diagnostics={
                "status": "queued",
                "quality_outcomes": {"rule_execution_completed": False},
                "policy_stack": build_policy_stack(
                    use_case="verification", embeddings=self.knowledge_query.embeddings
                ).as_dict(),
                "knowledge_snapshot": knowledge_snapshot,
                "document_scope": document_scope,
                "knowledge_version_ids": list(
                    knowledge_snapshot.get("effective_version_ids") or []
                ),
                "stage_history": [
                    {
                        "stage": "queued",
                        "status": "queued",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "detail": "Verification run created",
                    }
                ],
            },
        )
        self.session.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            self.session.expire_all()
            running = self.runs.get_running_for_solution(solution.solution_version_id)
            if running is not None:
                raise ConflictError(
                    "Verification run already active for solution",
                    error_code="VERIFICATION_ALREADY_RUNNING",
                ) from exc
            raise
        run.diagnostics = {
            **(run.diagnostics or {}),
            "operation_kind": "verification_run",
            "operation_id": str(run.verification_run_id),
        }
        self._record_operation_step(
            run,
            stage="queued",
            status="queued",
            detail="Verification run created",
            payload={
                "solution_version_id": str(solution.solution_version_id),
                "knowledge_version_id": str(knowledge_version_id),
                "document_scope": document_scope,
            },
        )
        self.idempotency.register(
            actor_user_id=owner_key,
            operation_name="verification.run.start",
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            target_type="verification_run",
            target_id=str(run.verification_run_id),
            correlation_id=payload.correlation_id,
        )
        self.audit.record(
            event_type="verification.run.created",
            target_type="verification_run",
            target_id=run.verification_run_id,
            message="Verification run created",
            actor_user_id=owner_key,
            correlation_id=payload.correlation_id,
            payload=scope_snapshot,
        )
        self.session.commit()

        def _run_inline() -> VerificationRun:
            try:
                return self.execute_run(str(run.verification_run_id))
            except Exception:
                self.session.expire_all()
                return self.get_run(str(run.verification_run_id), principal)

        def _queue_run() -> VerificationRun:
            from app.tasks.jobs.verification import run_verification_job

            run_verification_job.delay(str(run.verification_run_id))
            return run

        def _handle_queue_failure(exc: Exception) -> VerificationRun:
            self.session.rollback()
            failed_run = self.get_run(str(run.verification_run_id))
            failed_run.status = VerificationRunStatus.FAILED
            failed_run.current_stage = "failed"
            failed_run.finished_at = datetime.now(UTC)
            failed_run.diagnostics = self._with_stage_history(
                {
                    **(failed_run.diagnostics or {}),
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "VERIFICATION_QUEUE_DISPATCH_ERROR"),
                },
                "failed",
                detail=str(exc),
                status="failed",
            )
            self._record_operation_step(
                failed_run,
                stage="failed",
                status="failed",
                detail=str(exc),
                error_code=getattr(exc, "error_code", "VERIFICATION_QUEUE_DISPATCH_ERROR"),
                payload={"dispatch": "queue"},
            )
            self.session.add(failed_run)
            self.audit.record(
                event_type="verification.run.failed",
                target_type="verification_run",
                target_id=failed_run.verification_run_id,
                message="Verification run queue dispatch failed",
                actor_user_id=failed_run.started_by_user_id,
                correlation_id=failed_run.correlation_id,
                payload={"error": str(exc), "stage": "queue_dispatch"},
                severity=AuditSeverity.ERROR,
            )
            self.session.commit()
            self.session.refresh(failed_run)
            return failed_run

        return dispatch_run(
            settings=self.settings,
            requested_inline=self.settings.verification_execute_inline,
            inline_executor=_run_inline,
            queue_dispatcher=_queue_run,
            queue_failure_handler=_handle_queue_failure,
        )

    def get_run(
        self, verification_run_id: str, principal: AuthPrincipal | None = None
    ) -> VerificationRun:
        run = self.runs.get(verification_run_id)
        if run is None:
            raise NotFoundError("VerificationRun", verification_run_id)
        if principal is not None:
            VerificationQueryService(self.session)._ensure_solution_access(
                run.solution_version, principal
            )
        return run

    def get_run_status_payload(
        self, verification_run_id: str, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        run = self.get_run(verification_run_id, principal)
        protocol_id = (
            str(run.protocol.verification_protocol_id) if run.protocol is not None else None
        )
        diagnostics = {
            **(run.diagnostics or {}),
            "operation_kind": "verification_run",
            "operation_id": str(run.verification_run_id),
        }
        return {
            "verification_run_id": str(run.verification_run_id),
            "solution_version_id": str(run.solution_version_id),
            "knowledge_version_id": str(run.knowledge_version_id),
            "started_by_user_id": str(run.started_by_user_id),
            "status": run.status,
            "current_stage": run.current_stage,
            "correlation_id": run.correlation_id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "scope_snapshot": run.scope_snapshot,
            "diagnostics": diagnostics,
            "verification_protocol_id": protocol_id,
        }

    def execute_run(self, verification_run_id: str) -> VerificationRun:
        return execute_verification_run(self, verification_run_id)

    @staticmethod
    def _stage_title(stage: str) -> str:
        return {
            "queued": "Поставлено в очередь",
            "preparing": "Подготовка контекста",
            "verification": "Проверка решения",
            "publishing": "Сборка протокола",
            "completed": "Проверка завершена",
            "failed": "Проверка завершилась ошибкой",
        }.get(stage, stage.replace("_", " ").strip().title())

    def _record_operation_step(
        self,
        run: VerificationRun,
        *,
        stage: str,
        status: str,
        detail: str | None = None,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record_operation_step(
            self.operations,
            operation_kind="verification_run",
            operation_id=str(run.verification_run_id),
            step_code=stage,
            title=self._stage_title(stage),
            status=status,
            correlation_id=run.correlation_id,
            actor_user_id=str(run.started_by_user_id),
            detail=detail,
            error_code=error_code,
            payload=payload,
        )

    @staticmethod
    def _with_stage_history(
        diagnostics: dict[str, Any],
        stage: str,
        *,
        detail: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        return append_stage_history(diagnostics, stage, detail=detail, status=status)

    def _select_rules(
        self,
        validation_scope: str,
        *,
        document_scope: dict[str, Any] | None = None,
    ) -> list[VerificationRuleDefinition]:
        if validation_scope != "full":
            raise ValidationError(
                "Only full validation scope is supported in MVP",
                error_code="INVALID_VALIDATION_SCOPE",
            )
        rules = self.registry.list_rules()
        if not document_scope or document_scope.get("mode") != "selected":
            return rules
        allowed_rule_codes = self._selected_document_rule_codes(document_scope)
        return [rule for rule in rules if rule.code in allowed_rule_codes]

    @staticmethod
    def _selected_document_rule_codes(document_scope: dict[str, Any]) -> set[str]:
        selected_documents = list(document_scope.get("selected_documents") or [])
        rule_codes: set[str] = set(SELECTED_DOCUMENT_TECHNICAL_RULE_CODES)
        for document in selected_documents:
            if not isinstance(document, dict):
                continue
            role_code = str(document.get("role_code") or "").strip()
            rule_codes.update(DOCUMENT_ROLE_RULE_CODES.get(role_code, set()))
            title = str(document.get("title") or "").lower()
            document_type = str(document.get("document_type") or "").lower()
            title_haystack = f"{title} {document_type}"
            for marker, marker_rule_codes in DOCUMENT_TITLE_RULE_CODES:
                if marker in title_haystack:
                    rule_codes.update(marker_rule_codes)
        return rule_codes

    def _get_solution(self, solution_version_id: str, *, eager: bool = True) -> SolutionVersion:
        if eager:
            statement = (
                select(SolutionVersion)
                .where(SolutionVersion.solution_version_id == solution_version_id)
                .options(
                    selectinload(SolutionVersion.business_task),
                    selectinload(SolutionVersion.generation_run),
                    selectinload(SolutionVersion.sections).selectinload(
                        SolutionSection.source_refs
                    ),
                    selectinload(SolutionVersion.components).selectinload(
                        SolutionComponent.interfaces
                    ),
                    selectinload(SolutionVersion.integrations),
                    selectinload(SolutionVersion.list_items),
                    selectinload(SolutionVersion.risks),
                    selectinload(SolutionVersion.verification_runs).selectinload(
                        VerificationRun.protocol
                    ),
                )
            )
            solution = self.session.scalar(statement)
        else:
            solution = self.session.get(SolutionVersion, solution_version_id)
        if solution is None:
            raise NotFoundError("SolutionVersion", solution_version_id)
        if solution.generation_run is None:
            raise ValidationError(
                "Solution version is not linked to generation run",
                error_code="SOLUTION_GENERATION_LINK_MISSING",
            )
        return solution

    def _get_rule_lookup(self, knowledge_version_ids: list[str] | str) -> dict[str, NormativeRule]:
        version_ids = (
            [knowledge_version_ids]
            if isinstance(knowledge_version_ids, str)
            else list(knowledge_version_ids)
        )
        statement = select(NormativeRule).where(NormativeRule.knowledge_version_id.in_(version_ids))
        rules = list(self.session.scalars(statement))
        return {rule.rule_code: rule for rule in rules}

    def _get_knowledge_version(self, knowledge_version_id: str) -> KnowledgeVersion:
        statement = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.knowledge_version_id == knowledge_version_id)
            .options(
                selectinload(KnowledgeVersion.version_documents)
                .selectinload(KnowledgeVersionDocument.document)
                .selectinload(SourceDocument.source)
            )
        )
        version = self.session.scalar(statement)
        if version is None:
            raise NotFoundError("KnowledgeVersion", knowledge_version_id)
        return version

    def _build_rule_support_context(
        self,
        *,
        solution: SolutionVersion,
        knowledge_versions: list[KnowledgeVersion],
        selected_document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        version_documents = [
            doc
            for version in knowledge_versions
            for doc in filter_version_documents(
                getattr(version, "version_documents", []) or [],
                selected_document_ids,
            )
        ]
        required_documents = [
            item for item in version_documents if bool(getattr(item, "required_flag", False))
        ]
        role_by_document_id = {
            str(item.document_id): str(item.role_code) for item in required_documents
        }
        required_fragments: list[KnowledgeFragment] = []
        if role_by_document_id:
            statement = (
                select(KnowledgeFragment)
                .where(
                    KnowledgeFragment.knowledge_version_id.in_(
                        [version.knowledge_version_id for version in knowledge_versions]
                    ),
                    KnowledgeFragment.document_id.in_(list(role_by_document_id.keys())),
                )
                .options(selectinload(KnowledgeFragment.document))
            )
            required_fragments = list(self.session.scalars(statement))
        required_fragments_by_role: dict[str, list[KnowledgeFragment]] = {}
        for fragment in required_fragments:
            role_code = role_by_document_id.get(str(fragment.document_id))
            if role_code is None:
                continue
            required_fragments_by_role.setdefault(role_code, []).append(fragment)
        return {
            "required_fragments_by_role": required_fragments_by_role,
            "support_summary": {
                "required_document_count": len(required_documents),
                "required_fragment_count": len(required_fragments),
                "required_roles_with_fragments": sorted(required_fragments_by_role),
                "document_scope": "selected" if selected_document_ids else "full",
                "selected_document_count": len(normalize_document_ids(selected_document_ids)),
            },
        }
