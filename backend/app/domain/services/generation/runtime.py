from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.core.exceptions import ValidationError
from app.core.request_context import bind_log_context
from app.core.security import AuthPrincipal
from app.db.enums import AccountType, AuditSeverity, BusinessTaskStatus, GenerationRunStatus
from app.db.models.generation import GenerationRun
from app.domain.services.knowledge_telemetry import build_retrieval_telemetry_summary
from app.domain.services.observability import (
    StageObservation,
    observe_stage,
    summarize_stage_metrics,
)

from .common import TERMINAL_GENERATION_STATUSES, _json_safe, _prompt_context_items, logger
from .post_validation_repair import GenerationValidationRepairer


class GenerationRunCanceled(Exception):
    """Internal signal used to stop a generation worker after an API cancellation."""


def execute_generation_run(service: Any, generation_run_id: str) -> GenerationRun:
    run = service.get_run(generation_run_id)
    if run.status in TERMINAL_GENERATION_STATUSES:
        return run
    task = service._get_task(str(run.business_task_id), eager=True)
    run_principal = _build_run_principal(run)

    input_snapshot = dict(run.input_snapshot or {}) if isinstance(run.input_snapshot, dict) else {}
    policy_stack = dict(input_snapshot.get("policy_stack") or {})
    if not policy_stack:
        policy_stack = service._build_policy_stack()

    if run.finished_at is not None:
        return run

    stage_metrics = dict((run.diagnostics or {}).get("stage_metrics") or {})
    pipeline_started = perf_counter()
    with bind_log_context(
        correlation_id=run.correlation_id,
        operation_kind="generation_run",
        operation_id=str(run.generation_run_id),
        business_task_id=str(run.business_task_id),
        generation_run_id=str(run.generation_run_id),
        knowledge_version_id=str(run.knowledge_version_id),
    ):
        logger.info(
            "generation_run_started",
            extra={
                "stage": "queued",
                "stage_status": "running",
                "run_id": str(run.generation_run_id),
                "entity_id": str(run.business_task_id),
                "event_type": "pipeline_started",
            },
        )
        try:
            _raise_if_generation_canceled(service, run)
            _mark_run_started(service, run, stage_metrics=stage_metrics)
            stage_obs: StageObservation
            _raise_if_generation_canceled(service, run)
            with observe_stage(
                stage_metrics, "retrieving", logger=logger, log_message="generation_stage"
            ) as stage_obs:
                retrieval, coverage_summary = _run_retrieval_stage(
                    service,
                    run=run,
                    task=task,
                    input_snapshot=input_snapshot,
                    principal=run_principal,
                )
                stage_obs.update(
                    {
                        "selected_fragment_count": len(retrieval.fragments),
                        "selected_document_count": len(
                            {
                                str(fragment.document_id)
                                for fragment in retrieval.fragments
                                if fragment.document_id
                            }
                        ),
                        "required_role_coverage": coverage_summary.get("required_role_coverage"),
                    }
                )
            _raise_if_generation_canceled(service, run)
            with observe_stage(
                stage_metrics, "prompting", logger=logger, log_message="generation_stage"
            ) as stage_obs:
                prompt_artifact = _run_prompt_stage(
                    service,
                    run=run,
                    task=task,
                    retrieval=retrieval,
                    coverage_summary=coverage_summary,
                    stage_metrics=stage_metrics,
                )
                stage_obs.update(
                    {
                        "included_fragment_count": len(prompt_artifact.included_fragment_ids),
                        "dropped_fragment_count": len(prompt_artifact.dropped_fragment_ids),
                    }
                )
            _raise_if_generation_canceled(service, run)
            with observe_stage(
                stage_metrics, "model_generation", logger=logger, log_message="generation_stage"
            ) as stage_obs:
                payload = _run_model_generation_stage(
                    service,
                    run=run,
                    task=task,
                    retrieval=retrieval,
                    prompt_artifact=prompt_artifact,
                    stage_metrics=stage_metrics,
                )
                stage_obs.update(
                    {
                        "fallback_used": bool(
                            service.llm_gateway.last_call_diagnostics.get("fallback_used")
                        ),
                        "model_id": service.llm_gateway.last_call_diagnostics.get("model_id"),
                    }
                )
            _raise_if_generation_canceled(service, run)
            with observe_stage(
                stage_metrics, "validating", logger=logger, log_message="generation_stage"
            ) as stage_obs:
                validation_summary, quality_outcomes, explainability, payload = _run_validation_stage(
                    service,
                    run=run,
                    task=task,
                    retrieval=retrieval,
                    coverage_summary=coverage_summary,
                    payload=payload,
                    stage_metrics=stage_metrics,
                )
                stage_obs.update(
                    {
                        "groundedness_score": validation_summary.get("groundedness_score"),
                        "citation_coverage": validation_summary.get("citation_coverage"),
                        "validation_repair_applied": quality_outcomes.get(
                            "validation_repair_applied"
                        ),
                    }
                )
            _raise_if_generation_canceled(service, run)
            with observe_stage(
                stage_metrics, "persisting", logger=logger, log_message="generation_stage"
            ) as stage_obs:
                solution = _run_persistence_stage(
                    service,
                    run=run,
                    task=task,
                    payload=payload,
                    validation_summary=validation_summary,
                    quality_outcomes=quality_outcomes,
                    explainability=explainability,
                    coverage_summary=coverage_summary,
                    policy_stack=policy_stack,
                    stage_metrics=stage_metrics,
                )
                stage_obs.update({"solution_version_id": str(solution.solution_version_id)})
            _raise_if_generation_canceled(service, run)
            with observe_stage(
                stage_metrics, "publishing", logger=logger, log_message="generation_stage"
            ) as stage_obs:
                completed_run = _run_publication_stage(
                    service,
                    run=run,
                    task=task,
                    solution=solution,
                    payload=payload,
                    quality_outcomes=quality_outcomes,
                    coverage_summary=coverage_summary,
                    stage_metrics=stage_metrics,
                    total_duration_sec=max(0.0, perf_counter() - pipeline_started),
                )
                completed_solution = getattr(completed_run, "solution_version", None)
                if completed_solution is not None:
                    stage_obs["solution_version_id"] = str(completed_solution.solution_version_id)
            total_duration_sec = max(0.0, perf_counter() - pipeline_started)
            completed_run.diagnostics = _attach_pipeline_observability(
                _json_safe(completed_run.diagnostics or {}),
                stage_metrics=stage_metrics,
                total_duration_sec=total_duration_sec,
                status=completed_run.status.value,
                current_stage=completed_run.current_stage,
            )
            service.session.add(completed_run)
            service.session.commit()
            logger.info(
                "generation_run_completed",
                extra={
                    "stage": "completed",
                    "stage_status": "completed",
                    "run_id": str(completed_run.generation_run_id),
                    "entity_id": str(task.business_task_id),
                    "duration_ms": round(total_duration_sec * 1000.0, 3),
                    "outcome": "completed",
                    "event_type": "pipeline_finished",
                },
            )
            return completed_run
        except GenerationRunCanceled:
            service.session.rollback()
            canceled_run = service.get_run(generation_run_id)
            logger.info(
                "generation_run_canceled",
                extra={
                    "stage": canceled_run.current_stage,
                    "stage_status": "canceled",
                    "run_id": str(canceled_run.generation_run_id),
                    "entity_id": str(canceled_run.business_task_id),
                    "outcome": "canceled",
                    "event_type": "pipeline_finished",
                },
            )
            return canceled_run
        except Exception as exc:
            _fail_generation_run(
                service,
                generation_run_id,
                exc,
                failed_stage=getattr(run, "current_stage", None),
                stage_metrics=stage_metrics,
                total_duration_sec=max(0.0, perf_counter() - pipeline_started),
            )
            raise


def _attach_pipeline_observability(
    diagnostics: dict[str, Any],
    *,
    stage_metrics: dict[str, dict[str, Any]],
    total_duration_sec: float | None,
    status: str | None,
    current_stage: str | None,
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    payload["stage_metrics"] = _json_safe(stage_metrics)
    payload["pipeline_telemetry"] = {
        **summarize_stage_metrics(stage_metrics),
        "status": status,
        "current_stage": current_stage,
        "total_runtime_sec": round(float(total_duration_sec), 6)
        if total_duration_sec is not None
        else None,
    }
    return payload


def _raise_if_generation_canceled(service: Any, run: GenerationRun) -> None:
    with suppress(Exception):
        service.session.refresh(run)
    if run.status == GenerationRunStatus.CANCELED:
        raise GenerationRunCanceled()


def _active_stage(stage: str, message: str, **values: Any) -> dict[str, Any]:
    return _json_safe(
        {
            "stage": stage,
            "message": message,
            "updated_at": datetime.now(UTC).isoformat(),
            **values,
        }
    )


def _mark_run_started(
    service: Any, run: GenerationRun, *, stage_metrics: dict[str, dict[str, Any]]
) -> None:
    input_snapshot = dict(run.input_snapshot or {}) if isinstance(run.input_snapshot, dict) else {}
    scope_snapshot = dict(input_snapshot.get("knowledge_snapshot") or {})
    run.status = GenerationRunStatus.RUNNING
    run.current_stage = "retrieving"
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "started": True,
                    "active_stage": _active_stage(
                        "retrieving",
                        "Подбираем релевантные фрагменты из зафиксированной версии знаний.",
                        operation="knowledge_retrieval",
                        knowledge_version_ids=list(
                            scope_snapshot.get("effective_version_ids")
                            or [str(run.knowledge_version_id)]
                        ),
                    ),
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "retrieving",
        detail="Knowledge retrieval started",
    )
    service._record_operation_step(
        run,
        stage="retrieving",
        status="running",
        detail="Knowledge retrieval started",
    )
    service.session.add(run)
    service.session.commit()


def _run_retrieval_stage(
    service: Any,
    *,
    run: GenerationRun,
    task: Any,
    input_snapshot: dict[str, Any],
    principal: AuthPrincipal | None = None,
) -> tuple[Any, dict[str, Any]]:
    scope_snapshot = dict(input_snapshot.get("knowledge_snapshot") or {})
    retrieval = service.retrieval.retrieve_for_task(
        task=task,
        knowledge_version_ids=list(
            scope_snapshot.get("effective_version_ids") or [str(run.knowledge_version_id)]
        ),
        principal=principal,
        limit=service.settings.generation_retrieval_limit,
    )
    coverage_summary = dict(retrieval.diagnostics.get("coverage_summary") or {})
    if not service.retrieval.is_coverage_sufficient(coverage_summary):
        raise ValidationError(
            service.retrieval._coverage_warning_message(coverage_summary),
            error_code="GENERATION_RETRIEVAL_COVERAGE_LOW",
        )
    service._record_operation_step(
        run,
        stage="retrieving",
        status="completed",
        detail="Knowledge fragments selected",
        payload={
            "selected_fragment_count": len(retrieval.fragments),
            "selected_document_count": len(
                {str(fragment.document_id) for fragment in retrieval.fragments if fragment.document_id}
            ),
            "coverage_summary": coverage_summary,
            "empty_result_versions": list(
                retrieval.diagnostics.get("empty_result_versions") or []
            ),
        },
    )
    return retrieval, coverage_summary


def _build_run_principal(run: GenerationRun) -> AuthPrincipal | None:
    actor_id = str(getattr(run, "started_by_user_id", "") or "").strip()
    if not actor_id:
        return None
    return AuthPrincipal(
        user_id=actor_id,
        login=actor_id,
        display_name=actor_id,
        account_type=AccountType.HUMAN,
        role_codes=[],
    )


def _run_prompt_stage(
    service: Any,
    *,
    run: GenerationRun,
    task: Any,
    retrieval: Any,
    coverage_summary: dict[str, Any],
    stage_metrics: dict[str, dict[str, Any]],
) -> Any:
    prompt = service.prompt_registry.get_generation_template()
    prompt_artifact = service.prompt_builder.build(
        template=prompt,
        task_title=task.title or "Проект решения",
        task_text=task.task_text,
        context_items=_prompt_context_items(task),
        retrieved_fragments=retrieval.fragments,
    )
    run.current_stage = "prompting"
    service._record_operation_step(
        run,
        stage="prompting",
        status="completed",
        detail="Prompt artifact prepared",
        payload={
            "coverage_summary": coverage_summary,
            "retrieved_fragment_count": len(retrieval.fragments),
            "included_fragment_count": len(prompt_artifact.included_fragment_ids),
            "dropped_fragment_count": len(prompt_artifact.dropped_fragment_ids),
            "token_budget": prompt_artifact.token_budget,
            "prompt_version": prompt_artifact.prompt_version,
            "retrieval_contract_version": prompt_artifact.retrieval_contract_version,
        },
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "active_stage": _active_stage(
                        "prompting",
                        "Grounded prompt собран: выбраны фрагменты, рассчитан token budget и подготовлен запрос к модели.",
                        operation="prompt_build",
                        retrieved_fragment_count=len(retrieval.fragments),
                        included_fragment_count=len(prompt_artifact.included_fragment_ids),
                        dropped_fragment_count=len(prompt_artifact.dropped_fragment_ids),
                        token_budget=prompt_artifact.token_budget,
                        prompt_version=prompt_artifact.prompt_version,
                    ),
                    "retrieval": retrieval.diagnostics,
                    "retrieval_telemetry": retrieval.diagnostics.get("telemetry_summary")
                    or build_retrieval_telemetry_summary(retrieval.diagnostics),
                    "coverage_summary": coverage_summary,
                    "prompt": {
                        "prompt_version": prompt_artifact.prompt_version,
                        "included_fragment_ids": prompt_artifact.included_fragment_ids,
                        "dropped_fragment_ids": prompt_artifact.dropped_fragment_ids,
                        "token_budget": prompt_artifact.token_budget,
                        "retrieval_trace": prompt_artifact.retrieval_trace,
                        "section_generation_plan": prompt_artifact.section_generation_plan,
                        "section_readiness_precheck": prompt_artifact.section_readiness,
                    },
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "prompting",
        detail="Prompt artifact prepared",
    )
    service.session.add(run)
    service.session.commit()
    return prompt_artifact


def _run_model_generation_stage(
    service: Any,
    *,
    run: GenerationRun,
    task: Any,
    retrieval: Any,
    prompt_artifact: Any,
    stage_metrics: dict[str, dict[str, Any]],
) -> Any:
    run.current_stage = "model_generation"
    llm_payload = {
        "provider_name": service.settings.llm_provider,
        "model_id": service.settings.llm_model_id,
        "timeout_sec": service.settings.llm_timeout_sec,
        "retrieved_fragment_count": len(retrieval.fragments),
        "included_fragment_count": len(prompt_artifact.included_fragment_ids),
        "dropped_fragment_count": len(prompt_artifact.dropped_fragment_ids),
        "token_budget": prompt_artifact.token_budget,
        "prompt_version": prompt_artifact.prompt_version,
    }
    service._record_operation_step(
        run,
        stage="model_generation",
        status="running",
        detail="LLM request sent; waiting for model response",
        payload=llm_payload,
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "active_stage": _active_stage(
                        "model_generation",
                        "Запрос отправлен в LLM; ждём ответ модели.",
                        operation="llm_request",
                        **llm_payload,
                    ),
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "model_generation",
        detail="LLM request sent; waiting for model response",
    )
    service.session.add(run)
    service.session.commit()

    payload = service.llm_gateway.generate_solution(
        task_title=task.title or "Проект решения",
        task_text=task.task_text,
        context_items=_prompt_context_items(task),
        retrieved_fragments=retrieval.fragments,
        prompt_artifact=prompt_artifact.as_payload(),
    )
    _raise_if_generation_canceled(service, run)
    service._record_operation_step(
        run,
        stage="model_generation",
        status="completed",
        detail="LLM response received",
        payload={
            "provider_name": service.llm_gateway.last_call_diagnostics.get("provider_name"),
            "model_id": service.llm_gateway.last_call_diagnostics.get("model_id"),
            "latency_ms": service.llm_gateway.last_call_diagnostics.get("latency_ms"),
            "fallback_used": bool(service.llm_gateway.last_call_diagnostics.get("fallback_used")),
        },
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(run.diagnostics or {}),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "model_generation",
        detail="LLM response received",
        status="completed",
    )
    service.session.add(run)
    service.session.commit()
    return payload


def _run_validation_stage(
    service: Any,
    *,
    run: GenerationRun,
    task: Any | None = None,
    retrieval: Any,
    coverage_summary: dict[str, Any],
    payload: Any,
    stage_metrics: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
    run.current_stage = "validating"
    service._record_operation_step(
        run,
        stage="validating",
        status="running",
        detail="LLM response received; validation started",
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "active_stage": _active_stage(
                        "validating",
                        "Ответ LLM получен; проверяем структуру, полноту разделов и привязку к источникам.",
                        operation="result_validation",
                        retrieved_fragment_count=len(retrieval.fragments),
                    ),
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "validating",
        detail="LLM response received; validation started",
    )
    service.session.add(run)
    service.session.commit()
    repair_diagnostics: dict[str, Any] | None = None
    try:
        validation_summary = service.validator.validate(
            payload, retrieved_fragments=retrieval.fragments
        )
    except ValidationError as exc:
        repaired_payload, repair_diagnostics = _repair_validation_payload(
            service,
            run=run,
            task=task,
            retrieval=retrieval,
            payload=payload,
            validation_error=exc,
            stage_metrics=stage_metrics,
        )
        if repaired_payload is None:
            raise
        payload = repaired_payload
        validation_summary = service.validator.validate(
            payload, retrieved_fragments=retrieval.fragments
        )
    service._record_operation_step(
        run,
        stage="validating",
        status="completed",
        detail="LLM response validated",
        payload={
            "groundedness_score": validation_summary.get("groundedness_score"),
            "citation_coverage": validation_summary.get("citation_coverage"),
            "section_readiness_status_counts": validation_summary.get(
                "section_readiness_status_counts"
            )
            or {},
            "validation_repair": repair_diagnostics,
        },
    )
    quality_outcomes = {
        "schema_valid": True,
        "semantic_valid": True,
        "groundedness_score": validation_summary.get("groundedness_score", 0.0),
        "citation_coverage": validation_summary.get("citation_coverage", 0.0),
        "fallback_used": bool(service.llm_gateway.last_call_diagnostics.get("fallback_used")),
        "validation_repair_applied": bool(repair_diagnostics),
        "retrieval_coverage_ok": True,
        "required_role_coverage": coverage_summary.get("required_role_coverage"),
        "section_readiness_status_counts": validation_summary.get("section_readiness_status_counts")
        or {},
        "structured_model_summary": validation_summary.get("structured_model_summary") or {},
    }
    explainability = {
        "basis_documents_used": [
            {
                "fragment_id": fragment.fragment_id,
                "document_id": fragment.document_id,
                "document_title": fragment.metadata.get("document_title"),
                "role_code": fragment.metadata.get("role_code"),
                "required_flag": bool(fragment.metadata.get("required_flag")),
                "selection_reason": fragment.metadata.get("selection_reason"),
            }
            for fragment in retrieval.fragments
        ],
        "assumptions": list(payload.assumptions),
        "next_steps": list(payload.next_steps),
        "coverage_summary": coverage_summary,
        "validation_summary": validation_summary,
        "validation_repair": repair_diagnostics,
        "section_readiness": [
            item.model_dump() for item in getattr(payload, "section_readiness", [])
        ],
        "structured_model": (
            structured_model.model_dump()
            if (structured_model := getattr(payload, "structured_model", None)) is not None
            else None
        ),
    }
    return validation_summary, quality_outcomes, explainability, payload


def _repair_validation_payload(
    service: Any,
    *,
    run: GenerationRun,
    task: Any | None,
    retrieval: Any,
    payload: Any,
    validation_error: ValidationError,
    stage_metrics: dict[str, dict[str, Any]],
) -> tuple[Any | None, dict[str, Any] | None]:
    repairer = getattr(service, "validation_repairer", None)
    if repairer is None:
        repairer = GenerationValidationRepairer(post_validator=service.validator)
    task_title = getattr(task, "title", None) if task is not None else None
    task_text = getattr(task, "task_text", "") if task is not None else ""
    context_items = _prompt_context_items(task) if task is not None else []
    repair_result = repairer.repair(
        payload,
        validation_error=validation_error,
        task_title=task_title,
        task_text=task_text,
        context_items=context_items,
        retrieved_fragments=list(getattr(retrieval, "fragments", []) or []),
    )
    if not repair_result.applied:
        return None, repair_result.diagnostics

    repair_diagnostics = _json_safe(repair_result.diagnostics)
    service._record_operation_step(
        run,
        stage="validating",
        status="running",
        detail="Validation repair applied; retrying validation",
        error_code=getattr(validation_error, "error_code", "SOLUTION_VALIDATION_REPAIR"),
        payload=repair_diagnostics,
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "active_stage": _active_stage(
                        "validating",
                        "Результат LLM автоматически исправлен после ValidationError; повторяем проверку.",
                        operation="result_validation_repair",
                        validation_repair=repair_diagnostics,
                    ),
                    "validation_repair": repair_diagnostics,
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "validating",
        detail="Validation repair applied; retrying validation",
        status="running",
    )
    service.session.add(run)
    service.session.commit()
    return repair_result.payload, repair_diagnostics


def _run_persistence_stage(
    service: Any,
    *,
    run: GenerationRun,
    task: Any,
    payload: Any,
    validation_summary: dict[str, Any],
    quality_outcomes: dict[str, Any],
    explainability: dict[str, Any],
    coverage_summary: dict[str, Any],
    policy_stack: dict[str, Any],
    stage_metrics: dict[str, dict[str, Any]],
) -> Any:
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "active_stage": _active_stage(
                        "persisting",
                        "Проверенный результат сохраняется как версия решения.",
                        operation="solution_persistence",
                        groundedness_score=quality_outcomes.get("groundedness_score"),
                        citation_coverage=quality_outcomes.get("citation_coverage"),
                    ),
                    "validation": validation_summary,
                    "llm": service.llm_gateway.last_call_diagnostics,
                    "llm_telemetry": {
                        "provider_name": service.llm_gateway.last_call_diagnostics.get(
                            "provider_name"
                        ),
                        "model_id": service.llm_gateway.last_call_diagnostics.get("model_id"),
                        "latency_ms": service.llm_gateway.last_call_diagnostics.get("latency_ms"),
                        "fallback_used": bool(
                            service.llm_gateway.last_call_diagnostics.get("fallback_used")
                        ),
                        "retrieval_context_contract": service.llm_gateway.last_call_diagnostics.get(
                            "retrieval_context_contract"
                        ),
                        "retrieved_fragment_count": service.llm_gateway.last_call_diagnostics.get(
                            "retrieved_fragment_count"
                        ),
                    },
                    "quality_outcomes": quality_outcomes,
                    "explainability": explainability,
                    "policy_stack": policy_stack,
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage="persisting",
        ),
        "persisting",
        detail="Validation passed; persisting solution",
    )
    service.session.add(run)
    service.session.commit()

    logger.info(
        "generation_quality_outcomes",
        extra={
            "stage": "generation_quality",
            "stage_status": "validated",
            "run_id": str(run.generation_run_id),
            "entity_id": str(task.business_task_id),
            "event_type": "quality_summary",
        },
    )

    run.current_stage = "persisting"
    service._record_operation_step(
        run,
        stage="persisting",
        status="running",
        detail="Validation passed; persisting solution",
        payload={"quality_outcomes": quality_outcomes},
    )
    solution = service.persistence.persist(business_task=task, run=run, payload=payload)
    service.session.commit()
    return solution


def _run_publication_stage(
    service: Any,
    *,
    run: GenerationRun,
    task: Any,
    solution: Any,
    payload: Any,
    quality_outcomes: dict[str, Any],
    coverage_summary: dict[str, Any],
    stage_metrics: dict[str, dict[str, Any]],
    total_duration_sec: float | None,
) -> GenerationRun:
    run.current_stage = "publishing"
    service._record_operation_step(
        run,
        stage="publishing",
        status="running",
        detail="Solution persisted; publishing rendered artifact",
        payload={
            "solution_version_id": str(solution.solution_version_id),
            "groundedness_score": quality_outcomes.get("groundedness_score"),
            "citation_coverage": quality_outcomes.get("citation_coverage"),
        },
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "active_stage": _active_stage(
                        "publishing",
                        "Решение сохранено; готовим опубликованную страницу для просмотра.",
                        operation="solution_publication",
                        solution_version_id=str(solution.solution_version_id),
                    ),
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=total_duration_sec,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "publishing",
        detail="Solution persisted; publishing rendered artifact",
    )
    solution, published_artifact = service.publication.publish(
        solution=solution,
        payload=payload,
        created_by_user_id=run.started_by_user_id,
    )
    _raise_if_generation_canceled(service, run)
    task.status = BusinessTaskStatus.COMPLETED
    task.updated_at = datetime.now(UTC)
    service.session.add(task)
    run.status = GenerationRunStatus.COMPLETED
    run.current_stage = "completed"
    run.finished_at = datetime.now(UTC)
    service._record_operation_step(
        run,
        stage="completed",
        status="completed",
        detail="Solution published",
        payload={
            "solution_version_id": str(solution.solution_version_id),
            "published_artifact_id": str(published_artifact.published_artifact_id),
        },
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **(run.diagnostics or {}),
                    "solution_version_id": str(solution.solution_version_id),
                    "published_artifact_id": str(published_artifact.published_artifact_id),
                    "publication_revision_no": published_artifact.revision_no,
                    "published_at": solution.published_at.isoformat()
                    if solution.published_at
                    else None,
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=total_duration_sec,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "completed",
        detail="Solution published",
        status="completed",
    )
    service.session.add(run)
    service.audit.record(
        event_type="generation.run.completed",
        target_type="generation_run",
        target_id=run.generation_run_id,
        message="Generation run completed and solution published",
        actor_user_id=run.started_by_user_id,
        correlation_id=run.correlation_id,
        payload={
            "solution_version_id": str(solution.solution_version_id),
            "published_artifact_id": str(published_artifact.published_artifact_id),
            "publication_revision_no": published_artifact.revision_no,
            "quality_outcomes": quality_outcomes,
            "coverage_summary": coverage_summary,
            "pipeline_telemetry": summarize_stage_metrics(stage_metrics),
        },
    )
    service.session.commit()
    try:
        service.session.refresh(run)
    except Exception:
        logger.warning(
            "generation_run_refresh_after_commit_failed",
            extra={
                "stage": "completed",
                "stage_status": "completed_with_refresh_warning",
                "run_id": str(run.generation_run_id),
                "entity_id": str(task.business_task_id),
            },
        )
    return run


def _fail_generation_run(
    service: Any,
    generation_run_id: str,
    exc: Exception,
    *,
    failed_stage: str | None = None,
    stage_metrics: dict[str, dict[str, Any]],
    total_duration_sec: float | None,
) -> None:
    service.session.rollback()

    failed_run = service.get_run(generation_run_id)
    failed_task = service._get_task(str(failed_run.business_task_id), eager=False)
    existing_diagnostics = _json_safe(failed_run.diagnostics or {})

    failed_run.status = GenerationRunStatus.FAILED
    failed_run.current_stage = "failed"
    failed_run.finished_at = datetime.now(UTC)
    if failed_stage and failed_stage != "failed":
        service._record_operation_step(
            failed_run,
            stage=failed_stage,
            status="failed",
            detail=str(exc),
            error_code=getattr(exc, "error_code", "GENERATION_RUNTIME_ERROR"),
        )
    service._record_operation_step(
        failed_run,
        stage="failed",
        status="failed",
        detail=str(exc),
        error_code=getattr(exc, "error_code", "GENERATION_RUNTIME_ERROR"),
        payload={"failed_stage": failed_stage or "failed"},
    )
    failed_run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            _json_safe(
                {
                    **existing_diagnostics,
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "GENERATION_RUNTIME_ERROR"),
                    "quality_outcomes": {
                        **(existing_diagnostics.get("quality_outcomes") or {}),
                        "schema_valid": False,
                        "semantic_valid": False,
                    },
                }
            ),
            stage_metrics=stage_metrics,
            total_duration_sec=total_duration_sec,
            status=failed_run.status.value,
            current_stage=failed_run.current_stage,
        ),
        failed_stage or "failed",
        detail=str(exc),
        status="failed",
    )
    service.session.add(failed_run)

    failed_task.status = BusinessTaskStatus.FAILED
    failed_task.updated_at = datetime.now(UTC)
    service.session.add(failed_task)

    logger.error(
        "generation_run_failed",
        extra={
            "stage": failed_run.current_stage,
            "stage_status": "failed",
            "run_id": str(failed_run.generation_run_id),
            "entity_id": str(failed_run.business_task_id),
            "error_code": getattr(exc, "error_code", "GENERATION_RUNTIME_ERROR"),
            "duration_ms": round(float(total_duration_sec or 0.0) * 1000.0, 3),
            "outcome": "failed",
            "event_type": "pipeline_finished",
        },
    )
    service.audit.record(
        event_type="generation.run.failed",
        target_type="generation_run",
        target_id=failed_run.generation_run_id,
        message="Generation run failed",
        actor_user_id=failed_run.started_by_user_id,
        correlation_id=failed_run.correlation_id,
        payload=_json_safe(
            {
                "error": str(exc),
                "error_code": getattr(exc, "error_code", "GENERATION_RUNTIME_ERROR"),
                "pipeline_telemetry": summarize_stage_metrics(stage_metrics),
            }
        ),
        severity=AuditSeverity.ERROR,
    )
    service.session.commit()
