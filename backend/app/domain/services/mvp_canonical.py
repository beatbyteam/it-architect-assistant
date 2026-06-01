from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import AuthPrincipal
from app.db.models.generation import BusinessTask, ClarificationRequest, GenerationRun, SolutionVersion
from app.db.models.verification import VerificationRun
from app.db.repositories.generation import BusinessTaskRepository, GenerationRunRepository
from app.db.repositories.knowledge import KnowledgeVersionRepository
from app.domain.services.audit import AuditService
from app.domain.services.canonical_read_helpers import (
    build_architecture_model_payload,
    build_protocol_explainability,
    build_section_assessments_payload,
    build_snapshot_summary,
    build_solution_explainability,
    extract_knowledge_scope,
    group_verification_findings,
    rule_group_for_result,
    safe_dict,
    serialize_solution_source_ref,
)
from app.domain.services.generation_core import GenerationRunService, SolutionQueryService
from app.domain.services.idempotency import IdempotencyService
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.mvp_access import has_mvp_global_scope
from app.domain.services.mvp_protocol_read_service import (
    _materialize_basis_documents as _materialize_basis_documents_impl,
)
from app.domain.services.mvp_protocol_read_service import (
    get_verification_protocol_payload as get_verification_protocol_payload_impl,
)
from app.domain.services.mvp_protocol_read_service import (
    get_verification_protocol_rendered_payload as get_verification_protocol_rendered_payload_impl,
)
from app.domain.services.mvp_protocol_read_service import (
    get_verification_protocol_violations_payload as get_verification_protocol_violations_payload_impl,
)
from app.domain.services.mvp_protocol_read_service import (
    get_verification_run_payload as get_verification_run_payload_impl,
)
from app.domain.services.mvp_protocol_read_service import (
    start_verification as start_verification_impl,
)
from app.domain.services.mvp_registry_presenters import (
    list_protocols as list_protocols_impl,
)
from app.domain.services.mvp_registry_presenters import (
    list_solutions as list_solutions_impl,
)
from app.domain.services.mvp_registry_presenters import (
    map_generation_state as map_generation_state_impl,
)
from app.domain.services.mvp_registry_presenters import (
    map_protocol_state as map_protocol_state_impl,
)
from app.domain.services.mvp_registry_presenters import (
    map_solution_state as map_solution_state_impl,
)
from app.domain.services.mvp_registry_presenters import (
    map_verification_run_state as map_verification_run_state_impl,
)
from app.domain.services.mvp_solution_read_service import (
    get_solution_model_payload as get_solution_model_payload_impl,
)
from app.domain.services.mvp_solution_read_service import (
    get_solution_payload as get_solution_payload_impl,
)
from app.domain.services.mvp_solution_read_service import (
    get_solution_rendered_payload as get_solution_rendered_payload_impl,
)
from app.domain.services.mvp_solution_read_service import (
    get_solution_section_assessments_payload as get_solution_section_assessments_payload_impl,
)
from app.domain.services.mvp_task_read_service import (
    build_task_snapshot as build_task_snapshot_impl,
)
from app.domain.services.mvp_task_read_service import (
    get_active_knowledge_version_payload as get_active_knowledge_version_payload_impl,
)
from app.domain.services.mvp_task_read_service import (
    get_generation_run_payload as get_generation_run_payload_impl,
)
from app.domain.services.mvp_task_write_service import (
    _assess_task_readiness as _assess_task_readiness_impl,
)
from app.domain.services.mvp_task_write_service import (
    _cancel_open_clarifications as _cancel_open_clarifications_impl,
)
from app.domain.services.mvp_task_write_service import (
    _canonical_task_state as _canonical_task_state_impl,
)
from app.domain.services.mvp_task_write_service import (
    _detect_missing_inputs as _detect_missing_inputs_impl,
)
from app.domain.services.mvp_task_write_service import (
    _is_substantive_answer as _is_substantive_answer_impl,
)
from app.domain.services.mvp_task_write_service import (
    _latest_open_clarification as _latest_open_clarification_impl,
)
from app.domain.services.mvp_task_write_service import (
    _reassess_task as _reassess_task_impl,
)
from app.domain.services.mvp_task_write_service import (
    answer_clarification as answer_clarification_impl,
)
from app.domain.services.mvp_task_write_service import (
    create_task as create_task_impl,
)
from app.domain.services.mvp_task_write_service import (
    get_task as get_task_impl,
)
from app.domain.services.mvp_task_write_service import (
    list_tasks as list_tasks_impl,
)
from app.domain.services.mvp_task_write_service import (
    start_generation as start_generation_impl,
)
from app.domain.services.mvp_task_write_service import (
    update_task as update_task_impl,
)
from app.domain.services.presenters import publication_revision_payload
from app.domain.services.principal_keys import principal_owner_key
from app.domain.services.publication import PublicationArtifactService
from app.domain.services.task_readiness import TaskReadinessPolicy
from app.domain.services.verification_core import VerificationQueryService, VerificationRunService


class CanonicalTaskService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tasks = BusinessTaskRepository(session)
        self.runs = GenerationRunRepository(session)
        self.versions = KnowledgeVersionRepository(session)
        self.audit = AuditService(session)
        self.idempotency = IdempotencyService(session)
        self.readiness_policy = TaskReadinessPolicy()

    def _has_global_scope(self, principal: AuthPrincipal) -> bool:
        return has_mvp_global_scope(self.settings, principal)

    def _ensure_task_access(self, task: BusinessTask, principal: AuthPrincipal) -> None:
        if self._has_global_scope(principal):
            return
        owner_key = principal_owner_key(principal)
        if owner_key and str(task.created_by_user_id) == owner_key:
            return
        raise AuthorizationError("Access denied to the requested business task")

    def _get_task(self, task_id: str, principal: AuthPrincipal | None = None) -> BusinessTask:
        statement = (
            select(BusinessTask)
            .where(BusinessTask.business_task_id == task_id)
            .options(
                selectinload(BusinessTask.clarification_requests).selectinload(
                    ClarificationRequest.answers
                ),
                selectinload(BusinessTask.generation_runs).selectinload(
                    GenerationRun.solution_version
                ),
                selectinload(BusinessTask.generation_runs)
                .selectinload(GenerationRun.solution_version)
                .selectinload(SolutionVersion.verification_runs)
                .selectinload(VerificationRun.protocol),
            )
        )
        task = self.session.scalar(statement)
        if task is None:
            raise NotFoundError("BusinessTask", task_id)
        if principal is not None:
            self._ensure_task_access(task, principal)
        return task

    def list_tasks(self, principal: AuthPrincipal):
        return list_tasks_impl(self, principal)

    def get_task(self, task_id: str, principal: AuthPrincipal):
        return get_task_impl(self, task_id, principal)

    def create_task(self, **kwargs):
        return create_task_impl(self, **kwargs)

    def update_task(self, task_id: str, **kwargs):
        return update_task_impl(self, task_id, **kwargs)

    def answer_clarification(
        self,
        task_id: str,
        clarification_id: str,
        answers: list[dict[str, str]],
        principal: AuthPrincipal,
    ):
        return answer_clarification_impl(self, task_id, clarification_id, answers, principal)

    def start_generation(
        self,
        task_id: str,
        *,
        correlation_id: str | None,
        principal: AuthPrincipal,
        idempotency_key: str | None = None,
        execute_inline: bool | None = None,
    ):
        return start_generation_impl(
            self,
            task_id,
            correlation_id=correlation_id,
            principal=principal,
            idempotency_key=idempotency_key,
            execute_inline=execute_inline,
            generation_run_service_factory=GenerationRunService,
            read_service_factory=CanonicalReadService,
        )

    def _latest_open_clarification(self, task: BusinessTask):
        return _latest_open_clarification_impl(self, task)

    def _cancel_open_clarifications(self, task: BusinessTask) -> None:
        return _cancel_open_clarifications_impl(self, task)

    def _reassess_task(self, task: BusinessTask, principal: AuthPrincipal, *, reopen: bool) -> None:
        return _reassess_task_impl(self, task, principal, reopen=reopen)

    def _detect_missing_inputs(self, task: BusinessTask) -> list[str]:
        return _detect_missing_inputs_impl(self, task)

    def _assess_task_readiness(self, task: BusinessTask) -> dict[str, Any]:
        return _assess_task_readiness_impl(self, task)

    def _is_substantive_answer(self, answer_text: str | None) -> bool:
        return _is_substantive_answer_impl(self, answer_text)

    def _canonical_task_state(self, task: BusinessTask) -> str:
        return _canonical_task_state_impl(task)


class CanonicalReadService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tasks = CanonicalTaskService(session, settings)
        self.publication_artifacts = PublicationArtifactService(session)

    @staticmethod
    def map_generation_state(status: Any) -> str:
        return map_generation_state_impl(status)

    @staticmethod
    def map_solution_state(status: Any) -> str:
        return map_solution_state_impl(status)

    @staticmethod
    def map_verification_run_state(status: Any) -> str:
        return map_verification_run_state_impl(status)

    @staticmethod
    def map_protocol_state(status: Any, summary_status: Any) -> str:
        return map_protocol_state_impl(status, summary_status)

    def build_task_snapshot(self, task: BusinessTask) -> dict[str, Any]:
        return build_task_snapshot_impl(self, task)

    def get_generation_run_payload(self, run_id: str, principal: AuthPrincipal) -> dict[str, Any]:
        return get_generation_run_payload_impl(
            self, run_id, principal, generation_run_service_factory=GenerationRunService
        )

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return safe_dict(value)

    def _extract_knowledge_scope(
        self, snapshot: Any, *, fallback_version_id: str | None = None
    ) -> dict[str, Any] | None:
        return extract_knowledge_scope(snapshot, fallback_version_id=fallback_version_id)

    def _serialize_solution_source_ref(self, ref) -> dict[str, Any]:
        return serialize_solution_source_ref(ref)

    def _build_solution_explainability(self, solution) -> dict[str, Any]:
        return build_solution_explainability(solution)

    def _build_architecture_model_payload(self, solution) -> dict[str, Any]:
        return build_architecture_model_payload(solution)

    def _build_section_assessments_payload(self, solution) -> list[dict[str, Any]]:
        return build_section_assessments_payload(solution)

    @staticmethod
    def _rule_group_for_result(*, rule_name: str | None, check_name: str | None) -> str | None:
        return rule_group_for_result(rule_name=rule_name, check_name=check_name)

    def _group_verification_findings(
        self, findings: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        return group_verification_findings(findings)

    def _build_protocol_explainability(
        self, protocol, basis_documents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return build_protocol_explainability(protocol, basis_documents)

    def _list_publication_revisions(
        self, *, target_type: str, target_id: str
    ) -> list[dict[str, Any]]:
        return [
            publication_revision_payload(item)
            for item in self.publication_artifacts.list_revisions(
                target_type=target_type, target_id=target_id
            )
        ]

    def _build_snapshot_summary(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        return build_snapshot_summary(snapshot)

    def get_solution_model_payload(
        self, solution_version_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_solution_model_payload_impl(
            self,
            solution_version_id,
            principal,
            solution_query_service_factory=SolutionQueryService,
        )

    def get_solution_section_assessments_payload(
        self, solution_version_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_solution_section_assessments_payload_impl(
            self,
            solution_version_id,
            principal,
            solution_query_service_factory=SolutionQueryService,
        )

    def get_solution_rendered_payload(
        self, solution_version_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_solution_rendered_payload_impl(
            self,
            solution_version_id,
            principal,
            solution_query_service_factory=SolutionQueryService,
        )

    def get_solution_payload(
        self, solution_version_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_solution_payload_impl(
            self,
            solution_version_id,
            principal,
            solution_query_service_factory=SolutionQueryService,
        )

    def list_solutions(
        self,
        principal: AuthPrincipal,
        *,
        task_id: str | None = None,
        state: str | None = None,
        knowledge_version_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return list_solutions_impl(
            self,
            principal,
            verification_query_service_factory=VerificationQueryService,
            task_id=task_id,
            state=state,
            knowledge_version_id=knowledge_version_id,
            limit=limit,
        )

    def list_protocols(
        self,
        principal: AuthPrincipal,
        *,
        solution_version_id: str | None = None,
        summary_status: str | None = None,
        knowledge_version_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return list_protocols_impl(
            self,
            principal,
            verification_query_service_factory=VerificationQueryService,
            solution_version_id=solution_version_id,
            summary_status=summary_status,
            knowledge_version_id=knowledge_version_id,
            limit=limit,
        )

    def start_verification(
        self,
        solution_version_id: str,
        *,
        correlation_id: str | None,
        principal: AuthPrincipal,
        idempotency_key: str | None = None,
        knowledge_document_ids: list[str] | None = None,
    ):
        return start_verification_impl(
            self,
            solution_version_id,
            correlation_id=correlation_id,
            principal=principal,
            idempotency_key=idempotency_key,
            knowledge_document_ids=knowledge_document_ids,
            verification_run_service_factory=VerificationRunService,
        )

    def get_verification_run_payload(self, run_id: str, principal: AuthPrincipal) -> dict[str, Any]:
        return get_verification_run_payload_impl(
            self, run_id, principal, verification_run_service_factory=VerificationRunService
        )

    def get_verification_protocol_payload(
        self, protocol_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_verification_protocol_payload_impl(
            self,
            protocol_id,
            principal,
            verification_query_service_factory=VerificationQueryService,
        )

    def get_verification_protocol_violations_payload(
        self, protocol_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_verification_protocol_violations_payload_impl(
            self,
            protocol_id,
            principal,
            verification_query_service_factory=VerificationQueryService,
        )

    def get_verification_protocol_rendered_payload(
        self, protocol_id: str, principal: AuthPrincipal
    ) -> dict[str, Any]:
        return get_verification_protocol_rendered_payload_impl(
            self,
            protocol_id,
            principal,
            verification_query_service_factory=VerificationQueryService,
        )

    def _materialize_basis_documents(self, protocol) -> list[Any]:
        return _materialize_basis_documents_impl(self, protocol)

    def get_active_knowledge_version_payload(
        self, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        return get_active_knowledge_version_payload_impl(
            self, principal, knowledge_base_service_factory=KnowledgeBaseService
        )
