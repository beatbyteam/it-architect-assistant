from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.core.request_context import bind_log_context
from app.db.enums import AuditSeverity, VerificationRunStatus
from app.db.models.verification import VerificationRun
from app.domain.services.observability import (
    StageObservation,
    observe_stage,
    summarize_stage_metrics,
)

from .common import TERMINAL_VERIFICATION_STATUSES, VerificationExecutionContext, logger
from .document_scope import selected_document_ids_from_scope
from .rule_executors import calculate_verification_score


class VerificationRunCanceled(Exception):
    """Internal signal used to stop a verification worker after an API cancellation."""


def execute_verification_run(service: Any, verification_run_id: str) -> VerificationRun:
    run = service.get_run(verification_run_id)
    if run.status in TERMINAL_VERIFICATION_STATUSES:
        return run
    solution = service._get_solution(str(run.solution_version_id), eager=True)
    stage_metrics = dict((run.diagnostics or {}).get("stage_metrics") or {})
    pipeline_started = perf_counter()
    with bind_log_context(
        correlation_id=run.correlation_id,
        operation_kind="verification_run",
        operation_id=str(run.verification_run_id),
        verification_run_id=str(run.verification_run_id),
        knowledge_version_id=str(run.knowledge_version_id),
        solution_version_id=str(run.solution_version_id),
        business_task_id=str(solution.business_task_id),
    ):
        logger.info(
            "verification_run_started",
            extra={
                "stage": "queued",
                "stage_status": "running",
                "run_id": str(run.verification_run_id),
                "entity_id": str(run.solution_version_id),
                "event_type": "pipeline_started",
            },
        )
        run.status = VerificationRunStatus.RUNNING
        run.current_stage = "preparing"
        service._record_operation_step(
            run, stage="preparing", status="running", detail="Начата загрузка контекста проверки"
        )
        run.diagnostics = service._with_stage_history(
            _attach_pipeline_observability(
                dict(run.diagnostics or {}),
                stage_metrics=stage_metrics,
                total_duration_sec=None,
                status=run.status.value,
                current_stage=run.current_stage,
            ),
            "preparing",
            detail="Начата загрузка контекста проверки",
        )
        service.session.add(run)
        service.session.commit()
        try:
            _raise_if_verification_canceled(service, run)
            stage_obs: StageObservation
            with observe_stage(
                stage_metrics, "preparing", logger=logger, log_message="verification_stage"
            ) as stage_obs:
                (
                    knowledge_versions,
                    knowledge_version,
                    rule_lookup,
                    rules,
                    rule_groups,
                    support_context,
                    selected_document_ids,
                ) = _prepare_verification_context(service, run=run, solution=solution)
                _raise_if_verification_canceled(service, run)
                stage_obs.update(
                    {
                        "knowledge_version_count": len(knowledge_versions),
                        "rule_count": len(rules),
                        "support_scope_count": len(support_context),
                    }
                )
            with observe_stage(
                stage_metrics, "verification", logger=logger, log_message="verification_stage"
            ) as stage_obs:
                payload, validation_summary = _run_verification_stage(
                    service,
                    run=run,
                    solution=solution,
                    knowledge_versions=knowledge_versions,
                    rules=rules,
                    rule_lookup=rule_lookup,
                    support_context=support_context,
                    selected_document_ids=selected_document_ids,
                    stage_metrics=stage_metrics,
                )
                _raise_if_verification_canceled(service, run)
                stage_obs.update(
                    {
                        "check_count": validation_summary.get("check_count"),
                        "failed_count": validation_summary.get("failed_count"),
                        "warning_count": validation_summary.get("warning_count"),
                    }
                )
            with observe_stage(
                stage_metrics, "publishing", logger=logger, log_message="verification_stage"
            ) as stage_obs:
                completed_run = _publish_verification_protocol(
                    service,
                    run=run,
                    payload=payload,
                    validation_summary=validation_summary,
                    rule_lookup=rule_lookup,
                    rules=rules,
                    rule_groups=rule_groups,
                    support_context=support_context,
                    stage_metrics=stage_metrics,
                    total_duration_sec=max(0.0, perf_counter() - pipeline_started),
                )
                _raise_if_verification_canceled(service, run)
                protocol = getattr(completed_run, "protocol", None)
                if protocol is not None:
                    stage_obs["verification_protocol_id"] = str(protocol.verification_protocol_id)
            total_duration_sec = max(0.0, perf_counter() - pipeline_started)
            completed_run.diagnostics = _attach_pipeline_observability(
                dict(completed_run.diagnostics or {}),
                stage_metrics=stage_metrics,
                total_duration_sec=total_duration_sec,
                status=completed_run.status.value,
                current_stage=completed_run.current_stage,
            )
            service.session.add(completed_run)
            service.session.commit()
            logger.info(
                "verification_run_completed",
                extra={
                    "stage": "completed",
                    "stage_status": "completed",
                    "run_id": str(completed_run.verification_run_id),
                    "entity_id": str(completed_run.solution_version_id),
                    "duration_ms": round(total_duration_sec * 1000.0, 3),
                    "outcome": "completed",
                    "event_type": "pipeline_finished",
                },
            )
            return completed_run
        except VerificationRunCanceled:
            canceled_run = service.get_run(verification_run_id)
            logger.info(
                "verification_run_canceled",
                extra={
                    "stage": canceled_run.current_stage,
                    "stage_status": "canceled",
                    "run_id": str(canceled_run.verification_run_id),
                    "entity_id": str(canceled_run.solution_version_id),
                    "outcome": "canceled",
                    "event_type": "pipeline_finished",
                },
            )
            return canceled_run
        except Exception as exc:
            _fail_verification_run(
                service,
                verification_run_id,
                exc,
                stage_metrics=stage_metrics,
                total_duration_sec=max(0.0, perf_counter() - pipeline_started),
            )
            raise


def _raise_if_verification_canceled(service: Any, run: VerificationRun) -> None:
    try:
        service.session.refresh(run)
    except Exception:
        logger.warning("verification_run_cancel_refresh_failed", exc_info=True)
    if run.status == VerificationRunStatus.CANCELED:
        raise VerificationRunCanceled()


def _attach_pipeline_observability(
    diagnostics: dict[str, Any],
    *,
    stage_metrics: dict[str, dict[str, Any]],
    total_duration_sec: float | None,
    status: str | None,
    current_stage: str | None,
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    payload["stage_metrics"] = stage_metrics
    payload["pipeline_telemetry"] = {
        **summarize_stage_metrics(stage_metrics),
        "status": status,
        "current_stage": current_stage,
        "total_runtime_sec": round(float(total_duration_sec), 6)
        if total_duration_sec is not None
        else None,
    }
    return payload


def _prepare_verification_context(
    service: Any, *, run: VerificationRun, solution: Any
) -> tuple[list[Any], Any, dict[str, Any], list[Any], list[str], dict[str, Any], list[str]]:
    scope = run.scope_snapshot or {}
    selected_document_ids = selected_document_ids_from_scope(scope)
    scope_version_ids = list(scope.get("knowledge_version_ids") or [str(run.knowledge_version_id)])
    knowledge_versions = [
        service._get_knowledge_version(version_id) for version_id in scope_version_ids
    ]
    knowledge_version = next(
        (
            item
            for item in knowledge_versions
            if str(item.knowledge_version_id) == str(run.knowledge_version_id)
        ),
        knowledge_versions[0],
    )
    run.knowledge_version = knowledge_version
    if getattr(solution, "generation_run", None) is not None:
        solution.generation_run.knowledge_version = knowledge_version
    rule_lookup = service._get_rule_lookup(scope_version_ids)
    document_scope = scope.get("document_scope")
    rules = service._select_rules(
        scope.get("validation_scope", "full"),
        document_scope=document_scope if isinstance(document_scope, dict) else None,
    )
    rule_groups = sorted({rule.group for rule in rules})
    support_context = service._build_rule_support_context(
        solution=solution,
        knowledge_versions=knowledge_versions,
        rules=rules,
        selected_document_ids=selected_document_ids,
        principal=service._principal_for_run(run),
    )
    return (
        knowledge_versions,
        knowledge_version,
        rule_lookup,
        rules,
        rule_groups,
        support_context,
        selected_document_ids,
    )


def _run_verification_stage(
    service: Any,
    *,
    run: VerificationRun,
    solution: Any,
    knowledge_versions: list[Any],
    rules: list[Any],
    rule_lookup: dict[str, Any],
    support_context: dict[str, Any],
    selected_document_ids: list[str],
    stage_metrics: dict[str, dict[str, Any]],
) -> tuple[Any, dict[str, Any]]:
    run.current_stage = "verification"
    service._record_operation_step(
        run,
        stage="verification",
        status="running",
        detail="Начато выполнение правил проверки",
        payload={"support_summary": support_context.get("support_summary")},
    )
    generation_retrieval = {}
    if getattr(solution, "generation_run", None) is not None:
        generation_retrieval = dict(
            (solution.generation_run.diagnostics or {}).get("retrieval_telemetry")
            or (solution.generation_run.diagnostics or {}).get("retrieval")
            or {}
        )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            {
                **(run.diagnostics or {}),
                "support_summary": support_context.get("support_summary"),
                "generation_grounding": generation_retrieval,
                "verification_telemetry": {
                    "rule_count": len(rules),
                    "support_scope_count": len(support_context),
                    "support_summary": support_context.get("support_summary"),
                },
            },
            stage_metrics=stage_metrics,
            total_duration_sec=None,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "verification",
        detail="Начато выполнение правил проверки",
    )
    context = VerificationExecutionContext(
        solution=solution,
        run=run,
        rules=rules,
        rule_lookup=rule_lookup,
        support_context_by_scope=support_context,
        knowledge_versions=knowledge_versions,
        selected_document_ids=selected_document_ids,
    )
    payload = service.engine.execute(context)
    validation_summary = service.validator.validate(
        payload, expected_rule_codes=[rule.code for rule in rules]
    )
    return payload, validation_summary


def _publish_verification_protocol(
    service: Any,
    *,
    run: VerificationRun,
    payload: Any,
    validation_summary: dict[str, Any],
    rule_lookup: dict[str, Any],
    rules: list[Any],
    rule_groups: list[str],
    support_context: dict[str, Any],
    stage_metrics: dict[str, dict[str, Any]],
    total_duration_sec: float | None,
) -> VerificationRun:
    run.current_stage = "publishing"
    service._record_operation_step(
        run,
        stage="publishing",
        status="running",
        detail="Начата сборка и сохранение протокола",
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            dict(run.diagnostics or {}),
            stage_metrics=stage_metrics,
            total_duration_sec=total_duration_sec,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "publishing",
        detail="Начата сборка и сохранение протокола",
    )
    protocol, published_artifact = service.persistence.persist(
        run=run, payload=payload, rule_lookup=rule_lookup
    )
    verification_score = calculate_verification_score(payload.check_results)
    run.status = VerificationRunStatus.COMPLETED
    run.current_stage = "completed"
    run.finished_at = datetime.now(UTC)
    service._record_operation_step(
        run,
        stage="completed",
        status="completed",
        detail="Протокол проверки выпущен",
        payload={
            "verification_protocol_id": str(protocol.verification_protocol_id),
            "published_artifact_id": str(published_artifact.published_artifact_id),
            "summary_status": payload.final_status.value,
        },
    )
    run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            {
                **(run.diagnostics or {}),
                "verification_protocol_id": str(protocol.verification_protocol_id),
                "published_artifact_id": str(published_artifact.published_artifact_id),
                "publication_revision_no": published_artifact.revision_no,
                "summary_status": payload.final_status.value,
                "verification_score": verification_score,
                "check_count": len(payload.check_results),
                "validation": validation_summary,
                "current_rule_group": rule_groups[-1] if rule_groups else None,
                "executed_rule_groups": rule_groups,
                "quality_outcomes": {
                    "rule_execution_completed": True,
                    "check_count": validation_summary.get("check_count", 0),
                    "failed_count": validation_summary.get("failed_count", 0),
                    "warning_count": validation_summary.get("warning_count", 0),
                    "incomplete_count": validation_summary.get("incomplete_count", 0),
                    "score": verification_score,
                },
                "verification_telemetry": {
                    "rule_group_count": len(rule_groups),
                    "rule_count": len(rules),
                    "check_count": len(payload.check_results),
                    "final_status": payload.final_status.value,
                    "score": verification_score,
                    "support_summary": support_context.get("support_summary"),
                },
            },
            stage_metrics=stage_metrics,
            total_duration_sec=total_duration_sec,
            status=run.status.value,
            current_stage=run.current_stage,
        ),
        "completed",
        detail="Протокол проверки выпущен",
        status="completed",
    )
    service.session.add(run)
    service.audit.record(
        event_type="verification.run.completed",
        target_type="verification_run",
        target_id=run.verification_run_id,
        message="Проверка решения завершена, протокол выпущен",
        actor_user_id=run.started_by_user_id,
        correlation_id=run.correlation_id,
        payload={
            "verification_protocol_id": str(protocol.verification_protocol_id),
            "published_artifact_id": str(published_artifact.published_artifact_id),
            "publication_revision_no": published_artifact.revision_no,
            "summary_status": payload.final_status.value,
            "support_summary": support_context.get("support_summary"),
            "pipeline_telemetry": summarize_stage_metrics(stage_metrics),
        },
    )
    service.session.commit()
    try:
        service.session.refresh(run)
    except Exception:
        logger.warning(
            "verification_run_refresh_after_commit_failed",
            extra={
                "stage": "completed",
                "stage_status": "completed_with_refresh_warning",
                "run_id": str(run.verification_run_id),
                "entity_id": str(run.solution_version_id),
            },
        )
    return run


def _fail_verification_run(
    service: Any,
    verification_run_id: str,
    exc: Exception,
    *,
    stage_metrics: dict[str, dict[str, Any]],
    total_duration_sec: float | None,
) -> None:
    service.session.rollback()

    failed_run = service.get_run(verification_run_id)
    failed_run.status = VerificationRunStatus.FAILED
    failed_run.current_stage = "failed"
    failed_run.finished_at = datetime.now(UTC)
    service._record_operation_step(
        failed_run,
        stage="failed",
        status="failed",
        detail=str(exc),
        error_code=getattr(exc, "error_code", "VERIFICATION_RUNTIME_ERROR"),
    )
    failed_run.diagnostics = service._with_stage_history(
        _attach_pipeline_observability(
            {
                **(failed_run.diagnostics or {}),
                "error": str(exc),
                "error_code": getattr(exc, "error_code", "VERIFICATION_RUNTIME_ERROR"),
            },
            stage_metrics=stage_metrics,
            total_duration_sec=total_duration_sec,
            status=failed_run.status.value,
            current_stage=failed_run.current_stage,
        ),
        "failed",
        detail=str(exc),
        status="failed",
    )
    service.session.add(failed_run)
    logger.error(
        "verification_run_failed",
        extra={
            "stage": failed_run.current_stage,
            "stage_status": "failed",
            "run_id": str(failed_run.verification_run_id),
            "entity_id": str(failed_run.solution_version_id),
            "error_code": getattr(exc, "error_code", "VERIFICATION_RUNTIME_ERROR"),
            "duration_ms": round(float(total_duration_sec or 0.0) * 1000.0, 3),
            "outcome": "failed",
            "event_type": "pipeline_finished",
        },
    )
    service.audit.record(
        event_type="verification.run.failed",
        target_type="verification_run",
        target_id=failed_run.verification_run_id,
        message="Проверка решения завершилась ошибкой",
        actor_user_id=failed_run.started_by_user_id,
        correlation_id=failed_run.correlation_id,
        payload={
            "error": str(exc),
            "pipeline_telemetry": summarize_stage_metrics(stage_metrics),
        },
        severity=AuditSeverity.ERROR,
    )
    service.session.commit()
