from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
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
from app.domain.services.knowledge_basis import (
    classify_basis_requirement,
    requires_catalog_basis_for_versions,
)
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
    (
        "technology",
        {"VR-NRM-03", "VR-NFR-01", "VR-NFR-02", "VR-NFR-03", "VR-NFR-04", "VR-NFR-05"},
    ),
    ("технолог", {"VR-NRM-03", "VR-NFR-01", "VR-NFR-02", "VR-NFR-03", "VR-NFR-04", "VR-NFR-05"}),
    ("радар", {"VR-NRM-03"}),
    ("стандарт", {"VR-NRM-03"}),
    ("операцион", {"VR-NRM-03"}),
    ("ubuntu", {"VR-NRM-03"}),
    ("linux", {"VR-NRM-03"}),
    (
        "well-architected",
        {"VR-NFR-01", "VR-NFR-02", "VR-NFR-03", "VR-NFR-04", "VR-NFR-05"},
    ),
    (
        "безопас",
        {"VR-NFR-01", "VR-NFR-02", "VR-NFR-03", "VR-NFR-04", "VR-NFR-05"},
    ),
    ("principle", {"VR-NRM-04"}),
    ("template", {"VR-NRM-04"}),
)
DOCUMENT_CONTENT_RULE_CODES = (
    *DOCUMENT_TITLE_RULE_CODES,
    ("ig1242", {"VR-NRM-01"}),
    ("oda component inventory", {"VR-NRM-01"}),
    ("open digital architecture", {"VR-NRM-01"}),
    ("tm forum", {"VR-NRM-01"}),
    ("tmf", {"VR-NRM-01"}),
    ("оператор деятельност", {"VR-NRM-01"}),
    ("archimate 3.2", {"VR-NRM-02", "VR-NRM-05", "VR-NRM-06"}),
    ("метамодел", {"VR-NRM-02", "VR-NRM-05", "VR-NRM-06"}),
    ("моделир", {"VR-NRM-02", "VR-NRM-05", "VR-NRM-06"}),
    ("технологический стандарт", {"VR-NRM-03"}),
    ("технологический радар", {"VR-NRM-03"}),
    ("операционные системы", {"VR-NRM-03"}),
    ("windows server", {"VR-NRM-03"}),
    ("postgres", {"VR-NRM-03"}),
    ("java", {"VR-NRM-03"}),
    ("kubernetes", {"VR-NRM-03"}),
    ("docker", {"VR-NRM-03"}),
    (
        "business architecture",
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
    (
        "архитектура данных",
        {"VR-STR-03", "VR-STR-04", "VR-CNS-02", "VR-CNS-05"},
    ),
    (
        "архитектура прилож",
        {"VR-STR-03", "VR-STR-04", "VR-CNS-01", "VR-CNS-03", "VR-CNS-04"},
    ),
    (
        "технологическая архитект",
        {
            "VR-STR-03",
            "VR-NRM-03",
            "VR-CNS-04",
            "VR-NFR-01",
            "VR-NFR-02",
            "VR-NFR-03",
            "VR-NFR-04",
            "VR-NFR-05",
        },
    ),
    ("security", {"VR-NFR-01"}),
    ("authentication", {"VR-NFR-01"}),
    ("authorization", {"VR-NFR-01"}),
    ("шифр", {"VR-NFR-01"}),
    ("observability", {"VR-NFR-04"}),
    ("monitoring", {"VR-NFR-04"}),
    ("availability", {"VR-NFR-02"}),
    ("failover", {"VR-NFR-02"}),
    ("доступност", {"VR-NFR-02"}),
    ("отказоуст", {"VR-NFR-02"}),
    ("performance", {"VR-NFR-03"}),
    ("scalability", {"VR-NFR-03"}),
    ("производ", {"VR-NFR-03"}),
    ("масштаб", {"VR-NFR-03"}),
    ("backup", {"VR-NFR-05"}),
    ("restore", {"VR-NFR-05"}),
    ("резервн", {"VR-NFR-05"}),
    ("восстанов", {"VR-NFR-05"}),
)
DOCUMENT_CONTENT_ROLE_HINTS = (
    ("ig1242", "ig1242_oda_component_inventory"),
    ("oda component inventory", "ig1242_oda_component_inventory"),
    ("open digital architecture", "oda"),
    ("tm forum", "oda"),
    ("tmf", "oda"),
    ("оператор деятельност", "oda"),
    ("archimate", "archimate_3_2"),
    ("метамодел", "archimate_3_2"),
    ("технологический стандарт", "technology_standard"),
    ("технологический радар", "technology_standard"),
    ("операционные системы", "technology_standard"),
    ("ubuntu", "technology_standard"),
    ("linux", "technology_standard"),
    ("windows server", "technology_standard"),
    ("технологический стандарт", "technology_standard"),
    ("технологический радар", "technology_standard"),
    ("операционные системы", "technology_standard"),
    ("postgres", "technology_standard"),
    ("java", "technology_standard"),
    ("kubernetes", "technology_standard"),
    ("docker", "technology_standard"),
    ("template", "template_or_principles"),
    ("principle", "template_or_principles"),
    ("шаблон", "template_or_principles"),
    ("принцип", "template_or_principles"),
)
DOCUMENT_CONTENT_MARKERS = tuple(
    sorted(
        {
            marker
            for marker, _ in DOCUMENT_CONTENT_RULE_CODES
        }
        | {
            marker
            for marker, _ in DOCUMENT_CONTENT_ROLE_HINTS
        },
        key=len,
        reverse=True,
    )
)
TECHNOLOGY_POLICY_FRAGMENT_MARKERS = (
    "запрещ",
    "нельзя",
    "не допуска",
    "не рекоменду",
    "forbidden",
    "must not",
    "shall not",
    "deprecated",
    "not recommended",
)


def _content_hint_text(fragment: Any) -> str:
    return " ".join(
        part
        for part in [
            str(getattr(fragment, "title", "") or ""),
            str(getattr(fragment, "content", "") or ""),
        ]
        if part
    ).lower()


def _append_unique_role_fragments(
    target: dict[str, list[KnowledgeFragment]],
    role_code: str,
    fragments: list[KnowledgeFragment],
) -> None:
    if not fragments:
        return
    role_fragments = target.setdefault(role_code, [])
    existing_ids = {
        str(getattr(fragment, "fragment_id", "") or "")
        for fragment in role_fragments
    }
    for fragment in fragments:
        fragment_id = str(getattr(fragment, "fragment_id", "") or "")
        if fragment_id and fragment_id in existing_ids:
            continue
        role_fragments.append(fragment)
        if fragment_id:
            existing_ids.add(fragment_id)


def _infer_selected_document_content_hints(
    fragments: list[KnowledgeFragment],
) -> tuple[set[str], dict[str, list[KnowledgeFragment]]]:
    content_rule_codes: set[str] = set()
    role_fragments_by_role: dict[str, list[KnowledgeFragment]] = {}
    for fragment in fragments:
        hint_text = _content_hint_text(fragment)
        if not hint_text:
            continue
        for marker, marker_rule_codes in DOCUMENT_CONTENT_RULE_CODES:
            if marker in hint_text:
                content_rule_codes.update(marker_rule_codes)
        for marker, role_code in DOCUMENT_CONTENT_ROLE_HINTS:
            if marker in hint_text:
                role_fragments_by_role.setdefault(role_code, []).append(fragment)
    return content_rule_codes, role_fragments_by_role


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
                "Для проверки решения нужна активная версия базы знаний",
                error_code="ACTIVE_KNOWLEDGE_VERSION_MISSING",
            )
        knowledge_version_id = active_version.knowledge_version_id
        knowledge_snapshot = build_knowledge_scope_snapshot(
            mandatory_version=knowledge_scope.mandatory_version,
            selected_user_version=knowledge_scope.selected_user_version,
        )
        selected_document_ids = normalize_document_ids(
            getattr(payload, "knowledge_document_ids", None)
        )
        document_scope = build_document_scope_snapshot(
            knowledge_versions=[active_version],
            selected_document_ids=selected_document_ids,
        )
        try:
            rules = self._select_rules(payload.validation_scope, document_scope=document_scope)
        except TypeError:  # compatibility with simplified test doubles
            rules = self._select_rules(payload.validation_scope)
        rulebook_version = getattr(self.registry, "version", None)
        publication_artifact = self.publication_artifacts.get_current(
            target_type="solution_version", target_id=str(solution.solution_version_id)
        )
        scope_snapshot = freeze_snapshot(
            {
                "solution_version_id": str(solution.solution_version_id),
                "generation_run_id": str(solution.generation_run_id)
                if solution.generation_run_id
                else None,
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
                "Проверять можно только опубликованные версии решений",
                error_code="SOLUTION_NOT_PUBLISHED",
            )
        running = self.runs.get_running_for_solution(solution.solution_version_id)
        if running is not None:
            raise ConflictError(
                "Для этого решения уже запущена проверка",
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
                        "detail": "Проверка решения создана",
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
                    "Для этого решения уже запущена проверка",
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
            detail="Проверка решения создана",
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
            message="Проверка решения создана",
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

            task_id = f"verification-run:{run.verification_run_id}"
            run_verification_job.apply_async(args=[str(run.verification_run_id)], task_id=task_id)
            run.diagnostics = {**(run.diagnostics or {}), "celery_task_id": task_id}
            self.session.add(run)
            self.session.commit()
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
                message="Не удалось поставить проверку решения в очередь",
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

    def cancel_run(
        self, verification_run_id: str, principal: AuthPrincipal | None = None
    ) -> VerificationRun:
        run = self.get_run(verification_run_id, principal)
        if run.status in TERMINAL_VERIFICATION_STATUSES:
            if run.status == VerificationRunStatus.CANCELED:
                return run
            raise ConflictError(
                "Verification run is already finished",
                error_code="VERIFICATION_RUN_ALREADY_FINISHED",
            )

        previous_stage = run.current_stage or "queued"
        finished_at = datetime.now(UTC)
        diagnostics = {
            **(run.diagnostics or {}),
            "status": VerificationRunStatus.CANCELED.value,
            "current_stage": "canceled",
            "error_code": "CANCELED_BY_USER",
            "canceled_at": finished_at.isoformat(),
            "active_stage": {
                "stage": "canceled",
                "operation": "user_cancel",
                "message": "Проверка архитектурного решения остановлена пользователем.",
                "updated_at": finished_at.isoformat(),
            },
        }
        if previous_stage != "canceled":
            self._record_operation_step(
                run,
                stage=previous_stage,
                status="canceled",
                detail="Verification run canceled by user",
                error_code="CANCELED_BY_USER",
            )
        run.status = VerificationRunStatus.CANCELED
        run.current_stage = "canceled"
        run.finished_at = finished_at
        run.diagnostics = self._with_stage_history(
            diagnostics,
            "canceled",
            detail="Verification run canceled by user",
            status="canceled",
        )
        self._record_operation_step(
            run,
            stage="canceled",
            status="canceled",
            detail="Verification run canceled by user",
            error_code="CANCELED_BY_USER",
        )
        self.session.add(run)
        self.audit.record(
            event_type="verification.run.canceled",
            target_type="verification_run",
            target_id=run.verification_run_id,
            message="Verification run canceled by user",
            actor_user_id=run.started_by_user_id,
            correlation_id=run.correlation_id,
            payload={
                "previous_stage": previous_stage,
                "error_code": "CANCELED_BY_USER",
            },
            severity=AuditSeverity.WARNING,
        )
        self.session.commit()
        self._revoke_verification_task(run)
        try:
            self.session.refresh(run)
        except Exception:
            logger.warning(
                "verification_run_refresh_after_cancel_failed",
                extra={
                    "stage": "canceled",
                    "stage_status": "canceled",
                    "run_id": str(run.verification_run_id),
                    "entity_id": str(run.solution_version_id),
                },
            )
        return run

    def _revoke_verification_task(self, run: VerificationRun) -> None:
        task_ids = {
            f"verification-run:{run.verification_run_id}",
            str((run.diagnostics or {}).get("celery_task_id") or "").strip(),
        }
        self._revoke_celery_tasks(
            {item for item in task_ids if item},
            task_name="app.tasks.jobs.verification.run_verification_job",
            run_id=str(run.verification_run_id),
        )

    def _revoke_celery_tasks(
        self, task_ids: set[str], *, task_name: str, run_id: str
    ) -> None:
        try:
            from app.tasks.workers.celery_app import celery_app

            control = getattr(celery_app, "control", None)
            revoke = getattr(control, "revoke", None)
            if not callable(revoke):
                return
            for task_id in task_ids:
                revoke(task_id, terminate=True, signal="SIGTERM")
            inspector = getattr(control, "inspect", lambda **_kwargs: None)(timeout=1.0)
            if inspector is None:
                return
            for method_name in ("active", "reserved", "scheduled"):
                method = getattr(inspector, method_name, None)
                if not callable(method):
                    continue
                for tasks in (method() or {}).values():
                    for task in tasks or []:
                        if task.get("name") != task_name:
                            continue
                        if run_id not in str(task.get("args", "")) and run_id not in str(
                            task.get("kwargs", "")
                        ):
                            continue
                        task_id = str(task.get("id") or "").strip()
                        if task_id:
                            revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception as exc:
            logger.warning(
                "verification_run_celery_revoke_failed",
                extra={
                    "stage": "canceled",
                    "stage_status": "revoke_failed",
                    "run_id": run_id,
                    "error": str(exc),
                },
            )

    @staticmethod
    def _stage_title(stage: str) -> str:
        return {
            "queued": "Поставлено в очередь",
            "preparing": "Подготовка контекста",
            "verification": "Проверка решения",
            "publishing": "Сборка протокола",
            "completed": "Проверка завершена",
            "failed": "Проверка завершилась ошибкой",
            "canceled": "Проверка остановлена",
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
                "В MVP поддерживается только полный объём проверки",
                error_code="INVALID_VALIDATION_SCOPE",
            )
        rules = self.registry.list_rules()
        if not document_scope:
            return rules
        if document_scope.get("mode") == "selected":
            allowed_rule_codes = self._selected_document_rule_codes(document_scope)
            return [rule for rule in rules if rule.code in allowed_rule_codes]
        if document_scope.get("mode") != "full" or not document_scope.get(
            "effective_documents"
        ):
            return rules
        allowed_rule_codes = self._document_scope_rule_codes(
            document_scope,
            document_key="effective_documents",
            technical_rule_codes=SELECTED_DOCUMENT_TECHNICAL_RULE_CODES,
        )
        return [rule for rule in rules if rule.code in allowed_rule_codes]

    @staticmethod
    def _selected_document_rule_codes(document_scope: dict[str, Any]) -> set[str]:
        return VerificationRunService._document_scope_rule_codes(
            document_scope,
            document_key="selected_documents",
            technical_rule_codes=SELECTED_DOCUMENT_TECHNICAL_RULE_CODES,
        )

    @staticmethod
    def _document_scope_rule_codes(
        document_scope: dict[str, Any],
        *,
        document_key: str,
        technical_rule_codes: set[str],
    ) -> set[str]:
        selected_documents = list(document_scope.get(document_key) or [])
        rule_codes: set[str] = set(technical_rule_codes)
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
                selectinload(KnowledgeVersion.knowledge_base),
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
        rules: list[VerificationRuleDefinition],
        selected_document_ids: list[str] | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        selected_document_ids = normalize_document_ids(selected_document_ids)
        version_documents = [
            doc
            for version in knowledge_versions
            for doc in filter_version_documents(
                getattr(version, "version_documents", []) or [],
                selected_document_ids,
            )
        ]
        required_documents = []
        role_by_document_id: dict[str, str] = {}
        for item in version_documents:
            role_code = str(getattr(item, "role_code", "") or "").strip()
            required_flag = bool(getattr(item, "required_flag", False))
            if not role_code or role_code == "reference_only":
                requirement = classify_basis_requirement(getattr(item, "document", None))
                if requirement is not None and requirement.required:
                    role_code = requirement.role_code
                    required_flag = True
            if role_code and role_code != "reference_only" and required_flag:
                required_documents.append(item)
                role_by_document_id[str(item.document_id)] = role_code
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
        policy_fragments = self._load_technology_policy_fragments(
            knowledge_versions=knowledge_versions,
            selected_document_ids=selected_document_ids,
        )
        _append_unique_role_fragments(
            required_fragments_by_role,
            "technology_standard",
            policy_fragments,
        )
        content_hint_fragments = self._load_selected_document_rule_hint_fragments(
            knowledge_versions=knowledge_versions,
            selected_document_ids=selected_document_ids,
        )
        content_rule_codes, content_role_fragments_by_role = (
            _infer_selected_document_content_hints(content_hint_fragments)
        )
        for role_code, role_fragments in content_role_fragments_by_role.items():
            _append_unique_role_fragments(
                required_fragments_by_role,
                role_code,
                role_fragments,
            )
        rule_evidence_by_code, rule_rag_summary = self._build_rule_rag_evidence(
            rules=rules,
            knowledge_versions=knowledge_versions,
            selected_document_ids=selected_document_ids,
            principal=principal,
        )
        require_catalog_packages = (
            requires_catalog_basis_for_versions(knowledge_versions)
            and not selected_document_ids
        )
        return {
            "required_fragments_by_role": required_fragments_by_role,
            "rule_evidence_by_code": rule_evidence_by_code,
            "content_rule_codes": sorted(content_rule_codes),
            "support_summary": {
                "required_document_count": len(required_documents),
                "required_fragment_count": len(required_fragments),
                "required_roles_with_fragments": sorted(required_fragments_by_role),
                "document_scope": "selected" if selected_document_ids else "full",
                "selected_document_count": len(normalize_document_ids(selected_document_ids)),
                "scoped_document_count": len(version_documents),
                "basis_requirement_mode": "catalog"
                if require_catalog_packages
                else "scoped_documents",
                "rule_rag": rule_rag_summary,
                "content_rule_hint_codes": sorted(content_rule_codes),
                "content_rule_hint_fragment_count": len(content_hint_fragments),
                "content_role_hints": sorted(content_role_fragments_by_role),
            },
        }

    def _load_selected_document_rule_hint_fragments(
        self,
        *,
        knowledge_versions: list[KnowledgeVersion],
        selected_document_ids: list[str] | None,
    ) -> list[KnowledgeFragment]:
        selected_ids = set(normalize_document_ids(selected_document_ids))
        if not selected_ids:
            return []
        version_ids = [
            str(version.knowledge_version_id)
            for version in knowledge_versions
            if getattr(version, "knowledge_version_id", None)
        ]
        if not version_ids:
            return []
        marker_conditions = []
        for marker in DOCUMENT_CONTENT_MARKERS:
            pattern = f"%{marker}%"
            marker_conditions.append(KnowledgeFragment.content.ilike(pattern))
            marker_conditions.append(KnowledgeFragment.title.ilike(pattern))
        limit = max(96, int(getattr(self.settings, "verification_rule_rag_limit", 2) or 0) * 48)
        statement = (
            select(KnowledgeFragment)
            .where(
                KnowledgeFragment.knowledge_version_id.in_(version_ids),
                KnowledgeFragment.document_id.in_(list(selected_ids)),
                or_(*marker_conditions),
            )
            .options(selectinload(KnowledgeFragment.document))
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def _load_technology_policy_fragments(
        self,
        *,
        knowledge_versions: list[KnowledgeVersion],
        selected_document_ids: list[str] | None,
    ) -> list[KnowledgeFragment]:
        version_ids = [
            str(version.knowledge_version_id)
            for version in knowledge_versions
            if getattr(version, "knowledge_version_id", None)
        ]
        if not version_ids:
            return []
        selected_ids = set(normalize_document_ids(selected_document_ids))
        marker_conditions = []
        for marker in TECHNOLOGY_POLICY_FRAGMENT_MARKERS:
            pattern = f"%{marker}%"
            marker_conditions.append(KnowledgeFragment.content.ilike(pattern))
            marker_conditions.append(KnowledgeFragment.title.ilike(pattern))
        limit = max(48, int(getattr(self.settings, "verification_rule_rag_limit", 2) or 0) * 24)
        statement = (
            select(KnowledgeFragment)
            .where(
                KnowledgeFragment.knowledge_version_id.in_(version_ids),
                or_(*marker_conditions),
            )
            .options(selectinload(KnowledgeFragment.document))
            .limit(limit)
        )
        if selected_ids:
            statement = statement.where(KnowledgeFragment.document_id.in_(selected_ids))
        return list(self.session.scalars(statement))

    def _build_rule_rag_evidence(
        self,
        *,
        rules: list[VerificationRuleDefinition],
        knowledge_versions: list[KnowledgeVersion],
        selected_document_ids: list[str] | None,
        principal: AuthPrincipal | None = None,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
        limit = max(0, int(self.settings.verification_rule_rag_limit or 0))
        if limit <= 0 or not rules:
            return {}, {"enabled": False, "limit_per_rule": limit}

        selected_ids = set(normalize_document_ids(selected_document_ids))
        version_ids = [
            str(version.knowledge_version_id)
            for version in knowledge_versions
            if getattr(version, "knowledge_version_id", None)
        ]
        evidence_by_code: dict[str, list[dict[str, Any]]] = {}
        failures: list[dict[str, str]] = []
        for rule in rules:
            query_text = self._verification_rule_query(rule)
            collected: list[dict[str, Any]] = []
            seen_fragment_ids: set[str] = set()
            for version_id in version_ids:
                try:
                    result = self.knowledge_query.search_text(
                        query_text=query_text,
                        knowledge_version_id=version_id,
                        limit=limit,
                        use_case="verification",
                        principal=principal,
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "rule_code": rule.code,
                            "knowledge_version_id": version_id,
                            "error": str(exc),
                        }
                    )
                    continue
                for fragment in result.fragments:
                    document_id = str(fragment.document_id or "")
                    if selected_ids and document_id not in selected_ids:
                        continue
                    fragment_id = str(fragment.fragment_id or "")
                    if fragment_id and fragment_id in seen_fragment_ids:
                        continue
                    if fragment_id:
                        seen_fragment_ids.add(fragment_id)
                    content_preview = " ".join((fragment.content or "").split())[:260]
                    collected.append(
                        {
                            "fragment_id": fragment_id or None,
                            "document_id": document_id or None,
                            "document_title": fragment.metadata.get("document_title")
                            or fragment.title,
                            "source_location": fragment.source_location,
                            "score": fragment.score,
                            "content_preview": content_preview,
                        }
                    )
                    if len(collected) >= limit:
                        break
                if len(collected) >= limit:
                    break
            evidence_by_code[rule.code] = collected

        return evidence_by_code, {
            "enabled": True,
            "limit_per_rule": limit,
            "rule_count": len(rules),
            "rules_with_evidence": sum(1 for items in evidence_by_code.values() if items),
            "failure_count": len(failures),
            "failures": failures[:8],
        }

    @staticmethod
    def _principal_for_run(run: VerificationRun) -> AuthPrincipal | None:
        actor = str(getattr(run, "started_by_user_id", "") or "").strip()
        if not actor:
            return None
        return AuthPrincipal(
            user_id=actor,
            login=actor,
            display_name=actor,
            account_type=AccountType.HUMAN,
            role_codes=[],
        )

    @staticmethod
    def _verification_rule_query(rule: VerificationRuleDefinition) -> str:
        if rule.code == "VR-NRM-03":
            return " ".join(
                item
                for item in [
                    rule.code,
                    rule.name,
                    "technology standard operating system OS Ubuntu Linux Windows Server forbidden prohibited deprecated запрещено не допускается",
                ]
                if item
            )
        group_terms = {
            "technical": "technical readiness knowledge version basis documents",
            "structure": "TOGAF sections architecture structure integrations risks constraints",
            "normative": "normative basis ArchiMate TOGAF ODA technology standard",
            "consistency": "architecture consistency traceability components integrations data objects",
            "nfr": "non-functional requirements security availability performance monitoring backup",
        }
        return " ".join(
            item
            for item in [
                rule.code,
                rule.name,
                group_terms.get(rule.group, rule.group),
            ]
            if item
        )
