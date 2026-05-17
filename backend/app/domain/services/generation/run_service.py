from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AuditSeverity,
    BusinessTaskStatus,
    GenerationRunStatus,
)
from app.db.models.generation import (
    BusinessTask,
    GenerationRun,
)
from app.db.repositories.generation import (
    BusinessTaskRepository,
    GenerationRunRepository,
)
from app.db.repositories.knowledge import KnowledgeVersionRepository
from app.domain.services.audit import AuditService
from app.domain.services.idempotency import IdempotencyService
from app.domain.services.immutable_snapshot import freeze_snapshot
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_snapshot import (
    build_knowledge_scope_snapshot,
)
from app.domain.services.operation_tracking import OperationTrackingService
from app.domain.services.presenters import retention_policy_payload
from app.domain.services.workflow_runtime import (
    append_stage_history,
    dispatch_run,
    record_operation_step,
)
from app.integrations.generation import (
    GenerationPromptBuilder,
    LLMGateway,
    PromptRegistry,
    TokenBudgetManager,
)
from app.integrations.knowledge.policy_stack import build_policy_stack
from app.schemas.generation import InternalGenerationRunStartRequest

from ..mvp_access import has_mvp_global_scope
from ..principal_keys import principal_owner_key
from .common import _context_notes, _json_safe
from .persistence_service import SolutionPersistenceService
from .post_validation import GenerationPostValidator
from .publication_service import SolutionPublicationService
from .retrieval_service import RetrievalService
from .runtime import execute_generation_run

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}

GENERATION_RETRYABLE_TASK_STATUSES = {
    BusinessTaskStatus.READY_FOR_GENERATION,
    BusinessTaskStatus.FAILED,
}


class GenerationRunService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tasks = BusinessTaskRepository(session)
        self.runs = GenerationRunRepository(session)
        self.versions = KnowledgeVersionRepository(session)
        self.audit = AuditService(session)
        self.operations = OperationTrackingService(session)
        self.idempotency = IdempotencyService(session)
        self.prompt_registry = PromptRegistry()
        self.retrieval = RetrievalService(session, settings)
        self.validator = GenerationPostValidator()
        self.prompt_builder = GenerationPromptBuilder(
            TokenBudgetManager(
                max_input_tokens=settings.generation_prompt_max_input_tokens,
                reserved_output_tokens=settings.generation_prompt_reserved_output_tokens,
            ),
            fragment_char_limit=settings.generation_prompt_fragment_char_limit,
        )
        self.llm_gateway = LLMGateway(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout_sec=settings.llm_timeout_sec,
            model_id=settings.llm_model_id,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            max_tokens=settings.llm_max_tokens,
            fallback_provider=settings.llm_fallback_provider,
            fallback_base_url=settings.llm_fallback_base_url,
            fallback_api_key=settings.llm_fallback_api_key,
            fallback_model_id=settings.llm_fallback_model_id,
        )
        self.persistence = SolutionPersistenceService(session)
        self.publication = SolutionPublicationService(session)

    def _make_base_service(self):
        factory = getattr(self, "knowledge_base_service_factory", None)
        if callable(factory):
            try:
                return factory(self.session)
            except TypeError:
                return factory()
        from app.domain.services import generation_core as generation_core_module

        service_cls = getattr(generation_core_module, "KnowledgeBaseService", KnowledgeBaseService)
        return service_cls(self.session)

    def _has_global_scope(self, principal: AuthPrincipal) -> bool:
        return has_mvp_global_scope(self.settings, principal)

    def _ensure_task_access(self, task: BusinessTask, principal: AuthPrincipal) -> None:
        if self._has_global_scope(principal):
            return
        owner_key = principal_owner_key(principal)
        if owner_key and str(task.created_by_user_id) == owner_key:
            return
        raise AuthorizationError("Access denied to the requested business task")

    def get_run(
        self, generation_run_id: str, principal: AuthPrincipal | None = None
    ) -> GenerationRun:
        run = self.runs.get(generation_run_id)
        if run is None:
            raise NotFoundError("GenerationRun", generation_run_id)
        if principal is not None:
            self._ensure_task_access(run.business_task, principal)
        return run

    def _build_generation_input_snapshot(
        self,
        *,
        task: BusinessTask,
        knowledge_snapshot: dict[str, Any],
        policy_stack: dict[str, Any],
        prompt_version: str,
        template_name: str,
        output_contract_name: str,
    ) -> dict[str, Any]:
        return freeze_snapshot(
            {
                "business_task_id": str(task.business_task_id),
                "title": task.title,
                "task_text": task.task_text,
                "metadata": task.task_metadata,
                "context_notes": _context_notes(task),
                "clarification_answers": (task.task_metadata or {}).get("clarification_answers", {})
                if isinstance(task.task_metadata, dict)
                else {},
                "clarification_requests": [
                    {
                        "clarification_id": str(item.clarification_id),
                        "state": getattr(item.state, "value", item.state),
                        "question_items": list(item.question_items or []),
                        "answers": [
                            {
                                "question_code": answer.question_code,
                                "question_text": answer.question_text,
                                "answer_text": answer.answer_text,
                                "sort_order": answer.sort_order,
                            }
                            for answer in sorted(item.answers, key=lambda row: row.sort_order)
                        ],
                    }
                    for item in sorted(task.clarification_requests, key=lambda row: row.created_at)
                ],
                "readiness_assessment": (
                    (task.task_metadata or {}).get("clarification_assessment")
                    if isinstance(task.task_metadata, dict)
                    else {}
                )
                or {},
                "knowledge_snapshot": knowledge_snapshot,
                "prompt_contract": {
                    "prompt_version": prompt_version,
                    "template_name": template_name,
                    "output_contract_name": output_contract_name,
                    "llm_model_id": self.settings.llm_model_id,
                },
                "policy_stack": policy_stack,
                "retention_policy": retention_policy_payload(target_type="solution_version"),
            },
            snapshot_type="generation_input",
        )

    @staticmethod
    def _build_generation_idempotency_request_payload(
        *,
        task: BusinessTask,
        active_version_id: str,
        knowledge_snapshot: dict[str, Any],
        input_snapshot: dict[str, Any],
        prompt_version: str,
    ) -> dict[str, Any]:
        return {
            "business_task_id": str(task.business_task_id),
            "knowledge_version_id": active_version_id,
            "knowledge_version_ids": list(knowledge_snapshot.get("effective_version_ids") or []),
            "knowledge_scope_hash": knowledge_snapshot.get("snapshot_hash"),
            "prompt_version": prompt_version,
            "task_input_hash": ((input_snapshot.get("_snapshot") or {}).get("payload_hash")),
        }

    def start_run(
        self, payload: InternalGenerationRunStartRequest, principal: AuthPrincipal
    ) -> GenerationRun:
        task = self._get_task(payload.business_task_id)
        scope_service = self._make_base_service()
        try:
            knowledge_scope = scope_service.get_effective_scope(principal)
        except TypeError:  # compatibility with simplified test doubles
            knowledge_scope = scope_service.get_effective_scope()
        active_version = knowledge_scope.selected_generation_version()
        if active_version is None:
            raise ValidationError(
                "At least one active knowledge version is required before generation",
                error_code="ACTIVE_KNOWLEDGE_VERSION_REQUIRED",
            )
        prompt = self.prompt_registry.get_generation_template()
        knowledge_snapshot = build_knowledge_scope_snapshot(
            mandatory_version=knowledge_scope.mandatory_version,
            selected_user_version=knowledge_scope.selected_user_version,
        )
        policy_stack = build_policy_stack(
            use_case="generation", embeddings=self.retrieval.knowledge_query.embeddings
        ).as_dict()
        input_snapshot = self._build_generation_input_snapshot(
            task=task,
            knowledge_snapshot=knowledge_snapshot,
            policy_stack=policy_stack,
            prompt_version=prompt.version_id,
            template_name=prompt.template_name,
            output_contract_name=prompt.output_contract_name,
        )
        request_payload = self._build_generation_idempotency_request_payload(
            task=task,
            active_version_id=str(active_version.knowledge_version_id),
            knowledge_snapshot=knowledge_snapshot,
            input_snapshot=input_snapshot,
            prompt_version=prompt.version_id,
        )
        owner_key = principal_owner_key(principal)
        existing = self.idempotency.resolve_existing(
            actor_user_id=owner_key,
            operation_name="generation.run.start",
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
        )
        if existing is not None:
            return self.get_run(existing.target_id, principal)
        if task.status not in GENERATION_RETRYABLE_TASK_STATUSES:
            raise ValidationError(
                "Business task is not ready for generation",
                error_code="BUSINESS_TASK_NOT_READY",
            )
        running = self.runs.get_running_for_task(task.business_task_id)
        if running is not None:
            raise ConflictError(
                "Generation run already active for business task",
                error_code="GENERATION_ALREADY_RUNNING",
            )
        run = GenerationRun(
            business_task_id=task.business_task_id,
            knowledge_version_id=active_version.knowledge_version_id,
            started_by_user_id=owner_key,
            status=GenerationRunStatus.QUEUED,
            current_stage="queued",
            correlation_id=payload.correlation_id,
            prompt_version=prompt.version_id,
            input_snapshot=input_snapshot,
            diagnostics=_json_safe(
                {
                    "status": "queued",
                    "quality_outcomes": {"schema_valid": False, "semantic_valid": False},
                    "policy_stack": policy_stack,
                    "knowledge_snapshot": knowledge_snapshot,
                    "knowledge_version_id": str(active_version.knowledge_version_id),
                    "knowledge_version_ids": list(
                        knowledge_snapshot.get("effective_version_ids") or []
                    ),
                    "stage_history": [
                        {
                            "stage": "queued",
                            "status": "queued",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "detail": "Generation run created",
                        }
                    ],
                }
            ),
        )
        self.session.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            self.session.expire_all()
            running = self.runs.get_running_for_task(task.business_task_id)
            if running is not None:
                raise ConflictError(
                    "Generation run already active for business task",
                    error_code="GENERATION_ALREADY_RUNNING",
                ) from exc
            raise
        run.diagnostics = _json_safe(
            {
                **(run.diagnostics or {}),
                "operation_kind": "generation_run",
                "operation_id": str(run.generation_run_id),
            }
        )
        self._record_operation_step(
            run,
            stage="queued",
            status="queued",
            detail="Generation run created",
            payload={
                "business_task_id": str(task.business_task_id),
                "knowledge_version_id": str(active_version.knowledge_version_id),
            },
        )
        self.idempotency.register(
            actor_user_id=owner_key,
            operation_name="generation.run.start",
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            target_type="generation_run",
            target_id=str(run.generation_run_id),
            correlation_id=payload.correlation_id,
        )
        self.audit.record(
            event_type="generation.run.created",
            target_type="generation_run",
            target_id=run.generation_run_id,
            message="Generation run created",
            actor_user_id=owner_key,
            correlation_id=payload.correlation_id,
            payload={
                "knowledge_version_id": str(active_version.knowledge_version_id),
                "knowledge_version_ids": list(
                    knowledge_snapshot.get("effective_version_ids") or []
                ),
                "knowledge_scope": knowledge_snapshot,
                "prompt_version": prompt.version_id,
            },
        )
        self.session.commit()

        def _run_inline() -> GenerationRun:
            try:
                return self.execute_run(str(run.generation_run_id))
            except Exception:
                self.session.expire_all()
                return self.get_run(str(run.generation_run_id), principal)

        def _queue_run() -> GenerationRun:
            from app.tasks.jobs.generation import run_generation_job

            task_id = f"generation-run:{run.generation_run_id}"
            run_generation_job.apply_async(args=[str(run.generation_run_id)], task_id=task_id)
            run.diagnostics = _json_safe({**(run.diagnostics or {}), "celery_task_id": task_id})
            self.session.add(run)
            self.session.commit()
            return run

        def _handle_queue_failure(exc: Exception) -> GenerationRun:
            self.session.rollback()
            failed_run = self.get_run(str(run.generation_run_id))
            diagnostics = _json_safe(
                {
                    **(failed_run.diagnostics or {}),
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "GENERATION_QUEUE_DISPATCH_ERROR"),
                }
            )
            failed_run.status = GenerationRunStatus.FAILED
            failed_run.current_stage = "failed"
            failed_run.finished_at = datetime.now(UTC)
            failed_run.diagnostics = self._with_stage_history(
                diagnostics, "failed", detail=str(exc), status="failed"
            )
            self._record_operation_step(
                failed_run,
                stage="failed",
                status="failed",
                detail=str(exc),
                error_code=getattr(exc, "error_code", "GENERATION_QUEUE_DISPATCH_ERROR"),
                payload={"dispatch": "queue"},
            )
            self.session.add(failed_run)
            self.audit.record(
                event_type="generation.run.failed",
                target_type="generation_run",
                target_id=failed_run.generation_run_id,
                message="Generation run queue dispatch failed",
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
            requested_inline=(
                payload.execute_inline
                if payload.execute_inline is not None
                else self.settings.generation_execute_inline
            ),
            inline_executor=_run_inline,
            queue_dispatcher=_queue_run,
            queue_failure_handler=_handle_queue_failure,
        )

    def get_run_status_payload(
        self, generation_run_id: str, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        run = self.get_run(generation_run_id, principal)
        solution_version_id = None
        if run.solution_version is not None:
            solution_version_id = str(run.solution_version.solution_version_id)
        diagnostics = _json_safe(
            {
                **(run.diagnostics or {}),
                "operation_kind": "generation_run",
                "operation_id": str(run.generation_run_id),
            }
        )
        return {
            "generation_run_id": str(run.generation_run_id),
            "business_task_id": str(run.business_task_id),
            "knowledge_version_id": str(run.knowledge_version_id),
            "started_by_user_id": str(run.started_by_user_id),
            "status": run.status,
            "current_stage": run.current_stage,
            "correlation_id": run.correlation_id,
            "prompt_version": run.prompt_version,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "input_snapshot": run.input_snapshot,
            "diagnostics": diagnostics,
            "solution_version_id": solution_version_id,
        }

    def cancel_run(
        self, generation_run_id: str, principal: AuthPrincipal | None = None
    ) -> GenerationRun:
        run = self.get_run(generation_run_id, principal)
        if run.status in TERMINAL_GENERATION_STATUSES:
            if run.status == GenerationRunStatus.CANCELED:
                return run
            raise ConflictError(
                "Generation run is already finished",
                error_code="GENERATION_RUN_ALREADY_FINISHED",
            )

        previous_stage = run.current_stage or "queued"
        finished_at = datetime.now(UTC)
        diagnostics = _json_safe(
            {
                **(run.diagnostics or {}),
                "status": GenerationRunStatus.CANCELED.value,
                "current_stage": "canceled",
                "error_code": "CANCELED_BY_USER",
                "canceled_at": finished_at.isoformat(),
                "active_stage": {
                    "stage": "canceled",
                    "operation": "user_cancel",
                    "message": "Подготовка решения остановлена пользователем.",
                    "updated_at": finished_at.isoformat(),
                },
            }
        )
        if previous_stage != "canceled":
            self._record_operation_step(
                run,
                stage=previous_stage,
                status="canceled",
                detail="Generation run canceled by user",
                error_code="CANCELED_BY_USER",
            )
        run.status = GenerationRunStatus.CANCELED
        run.current_stage = "canceled"
        run.finished_at = finished_at
        run.diagnostics = self._with_stage_history(
            diagnostics,
            "canceled",
            detail="Generation run canceled by user",
            status="canceled",
        )
        self._record_operation_step(
            run,
            stage="canceled",
            status="canceled",
            detail="Generation run canceled by user",
            error_code="CANCELED_BY_USER",
        )
        self.session.add(run)
        self.audit.record(
            event_type="generation.run.canceled",
            target_type="generation_run",
            target_id=run.generation_run_id,
            message="Generation run canceled by user",
            actor_user_id=run.started_by_user_id,
            correlation_id=run.correlation_id,
            payload={
                "previous_stage": previous_stage,
                "error_code": "CANCELED_BY_USER",
            },
            severity=AuditSeverity.WARNING,
        )
        self.session.commit()
        self._revoke_generation_task(run)
        try:
            self.session.refresh(run)
        except Exception:
            logger.warning(
                "generation_run_refresh_after_cancel_failed",
                extra={
                    "stage": "canceled",
                    "stage_status": "canceled",
                    "run_id": str(run.generation_run_id),
                    "entity_id": str(run.business_task_id),
                },
            )
        return run

    def _revoke_generation_task(self, run: GenerationRun) -> None:
        task_ids = {
            f"generation-run:{run.generation_run_id}",
            str((run.diagnostics or {}).get("celery_task_id") or "").strip(),
        }
        self._revoke_celery_tasks(
            {item for item in task_ids if item},
            task_name="app.tasks.jobs.generation.run_generation_job",
            run_id=str(run.generation_run_id),
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
                "generation_run_celery_revoke_failed",
                extra={
                    "stage": "canceled",
                    "stage_status": "revoke_failed",
                    "run_id": run_id,
                    "error": str(exc),
                },
            )

    def execute_run(self, generation_run_id: str) -> GenerationRun:
        return execute_generation_run(self, generation_run_id)

    @staticmethod
    def _stage_title(stage: str) -> str:
        return {
            "queued": "Поставлено в очередь",
            "retrieving": "Подбор знаний",
            "prompting": "Подготовка промпта",
            "model_generation": "Ожидание ответа модели",
            "validating": "Проверка результата",
            "persisting": "Сохранение решения",
            "publishing": "Публикация решения",
            "completed": "Решение опубликовано",
            "failed": "Генерация завершилась ошибкой",
            "canceled": "Подготовка решения остановлена",
        }.get(stage, stage.replace("_", " ").strip().title())

    def _record_operation_step(
        self,
        run: GenerationRun,
        *,
        stage: str,
        status: str,
        detail: str | None = None,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record_operation_step(
            self.operations,
            operation_kind="generation_run",
            operation_id=str(run.generation_run_id),
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

    def _get_task(self, business_task_id: str, *, eager: bool = False) -> BusinessTask:
        if eager:
            statement = select(BusinessTask).where(
                BusinessTask.business_task_id == business_task_id
            )
            task = self.session.scalar(statement)
        else:
            task = self.tasks.get(business_task_id)
        if task is None:
            raise NotFoundError("BusinessTask", business_task_id)
        return task
