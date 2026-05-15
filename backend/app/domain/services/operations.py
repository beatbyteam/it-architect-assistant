from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import AuthPrincipal
from app.db.models.generation import BusinessTask, SolutionVersion
from app.db.models.knowledge import (
    KnowledgeBaseSelection,
    KnowledgeSource,
    KnowledgeVersion,
    SourceDocument,
)
from app.db.models.verification import VerificationProtocol, VerificationRun
from app.db.repositories.audit import AuditEventRepository
from app.db.repositories.generation import GenerationRunRepository
from app.db.repositories.knowledge import KnowledgeUpdateRunRepository
from app.db.repositories.operations import OperationStepRepository
from app.db.repositories.verification import VerificationRunRepository
from app.domain.services.knowledge_bases import KnowledgeBaseService


class OperationsQueryService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.knowledge_runs = KnowledgeUpdateRunRepository(session)
        self.generation_runs = GenerationRunRepository(session)
        self.verification_runs = VerificationRunRepository(session)
        self.audit = AuditEventRepository(session)
        self.operation_steps = OperationStepRepository(session)

    @staticmethod
    def _safe_started_at(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        return None

    @classmethod
    def _sort_started_at(cls, row: dict[str, Any]) -> datetime:
        started_at = cls._safe_started_at(row.get("started_at"))
        finished_at = cls._safe_started_at(row.get("finished_at"))
        return started_at or finished_at or datetime.min.replace(tzinfo=UTC)

    @staticmethod
    def _row_started_at(*values: Any) -> datetime | None:
        for value in values:
            if isinstance(value, datetime):
                return value
        return None

    @staticmethod
    def _operation_window(limit: int) -> int:
        normalized_limit = max(int(limit or 0), 1)
        return max(normalized_limit * 3, 200)

    @staticmethod
    def _metrics_window() -> int:
        return 500

    @staticmethod
    def _principal_user_id(principal: AuthPrincipal | None) -> str | None:
        if principal is None:
            return None
        user_id = principal.user_id or principal.login
        return str(user_id) if user_id else None

    def _session_get(self, model: type[Any], entity_id: str | None) -> Any | None:
        if not entity_id:
            return None
        getter = getattr(self.session, "get", None)
        if not callable(getter):
            return None
        try:
            return getter(model, entity_id)
        except Exception:
            return None

    def _is_visible_business_task(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        user_id = self._principal_user_id(principal)
        created_by = getattr(item, "created_by_user_id", None)
        return bool(user_id and created_by and str(created_by) == user_id)

    def _is_visible_solution_version(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        business_task = getattr(item, "business_task", None)
        if business_task is None:
            business_task_id = getattr(item, "business_task_id", None)
            business_task = self._session_get(
                BusinessTask, str(business_task_id) if business_task_id else None
            )
        return bool(business_task and self._is_visible_business_task(business_task, principal))

    def _is_visible_knowledge_source(self, item: Any, principal: AuthPrincipal | None) -> bool:
        knowledge_base_id = str(getattr(item, "knowledge_base_id", "") or "")
        return self._can_access_knowledge_base(knowledge_base_id, principal)

    def _is_visible_source_document(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        source = getattr(item, "source", None)
        if source is None:
            source_id = getattr(item, "source_id", None)
            source = self._session_get(KnowledgeSource, str(source_id) if source_id else None)
        return bool(source and self._is_visible_knowledge_source(source, principal))

    def _is_visible_knowledge_version(self, item: Any, principal: AuthPrincipal | None) -> bool:
        knowledge_base_id = str(getattr(item, "knowledge_base_id", "") or "")
        return self._can_access_knowledge_base(knowledge_base_id, principal)

    def _can_access_knowledge_base(
        self, knowledge_base_id: str | None, principal: AuthPrincipal | None
    ) -> bool:
        if principal is None or not knowledge_base_id:
            return True
        try:
            KnowledgeBaseService(self.session).get_base(str(knowledge_base_id), principal)
            return True
        except Exception:
            return False

    def _is_visible_knowledge_run(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        user_id = self._principal_user_id(principal)
        initiator = getattr(item, "initiator_user_id", None)
        if user_id and initiator and str(initiator) == user_id:
            return True
        knowledge_base_id = str(getattr(item, "knowledge_base_id", "") or "")
        if not knowledge_base_id:
            return False
        try:
            KnowledgeBaseService(self.session).get_base(knowledge_base_id, principal)
        except Exception:
            return False
        return True

    def _is_visible_generation_run(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        user_id = self._principal_user_id(principal)
        started_by = getattr(item, "started_by_user_id", None)
        if user_id and started_by and str(started_by) == user_id:
            return True
        business_task = getattr(item, "business_task", None)
        if business_task is None:
            business_task_id = getattr(item, "business_task_id", None)
            business_task = self._session_get(
                BusinessTask, str(business_task_id) if business_task_id else None
            )
        return bool(business_task and self._is_visible_business_task(business_task, principal))

    def _is_visible_verification_run(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        user_id = self._principal_user_id(principal)
        started_by = getattr(item, "started_by_user_id", None)
        if user_id and started_by and str(started_by) == user_id:
            return True
        solution_version = getattr(item, "solution_version", None)
        if solution_version is None:
            solution_version_id = getattr(item, "solution_version_id", None)
            solution_version = self._session_get(
                SolutionVersion, str(solution_version_id) if solution_version_id else None
            )
        return bool(
            solution_version and self._is_visible_solution_version(solution_version, principal)
        )

    def _audit_event_visible(self, item: Any, principal: AuthPrincipal | None) -> bool:
        if principal is None:
            return True
        user_id = self._principal_user_id(principal)
        actor_user_id = getattr(item, "actor_user_id", None)
        if user_id and actor_user_id and str(actor_user_id) == user_id:
            return True

        target_type = str(getattr(item, "target_type", "") or "")
        target_id = str(getattr(item, "target_id", "") or "")
        if target_type == "knowledge_update_run":
            knowledge_run = self.knowledge_runs.get(target_id)
            return bool(knowledge_run and self._is_visible_knowledge_run(knowledge_run, principal))
        if target_type == "generation_run":
            generation_run = self.generation_runs.get(target_id)
            return bool(
                generation_run and self._is_visible_generation_run(generation_run, principal)
            )
        if target_type == "verification_run":
            verification_run = self.verification_runs.get(target_id)
            return bool(
                verification_run and self._is_visible_verification_run(verification_run, principal)
            )
        if target_type == "knowledge_base":
            return self._can_access_knowledge_base(target_id, principal)
        if target_type == "knowledge_source":
            source = self._session_get(KnowledgeSource, target_id)
            return bool(source and self._is_visible_knowledge_source(source, principal))
        if target_type == "source_document":
            document = self._session_get(SourceDocument, target_id)
            return bool(document and self._is_visible_source_document(document, principal))
        if target_type == "knowledge_version":
            version = self._session_get(KnowledgeVersion, target_id)
            return bool(version and self._is_visible_knowledge_version(version, principal))
        if target_type == "business_task":
            task = self._session_get(BusinessTask, target_id)
            return bool(task and self._is_visible_business_task(task, principal))
        if target_type == "solution_version":
            solution = self._session_get(SolutionVersion, target_id)
            return bool(solution and self._is_visible_solution_version(solution, principal))
        if target_type == "verification_protocol":
            protocol = self._session_get(VerificationProtocol, target_id)
            if protocol is None:
                return False
            protocol_run = getattr(protocol, "verification_run", None)
            if protocol_run is None:
                run_id = getattr(protocol, "verification_run_id", None)
                protocol_run = self.verification_runs.get(str(run_id)) if run_id else None
                if protocol_run is None:
                    protocol_run = self._session_get(
                        VerificationRun, str(run_id) if run_id else None
                    )
            return bool(protocol_run and self._is_visible_verification_run(protocol_run, principal))
        if target_type == "knowledge_base_selection":
            selection = self._session_get(KnowledgeBaseSelection, target_id)
            if selection is None:
                return False
            selected_base_id = getattr(selection, "selected_knowledge_base_id", None)
            return self._can_access_knowledge_base(
                str(selected_base_id) if selected_base_id else None, principal
            )
        return False

    def _filter_visible_audit_events(
        self, items: list[Any], principal: AuthPrincipal | None
    ) -> list[Any]:
        return [item for item in items if self._audit_event_visible(item, principal)]

    @staticmethod
    def _fetch_recent_page(repo: Any, *, batch: int, offset: int, **kwargs) -> list[Any]:
        try:
            return repo.list_recent(limit=batch, offset=offset, **kwargs)
        except TypeError:
            if offset:
                return []
            return repo.list_recent(limit=batch, **kwargs)

    @staticmethod
    def _fetch_audit_page(repo: Any, *, batch: int, offset: int, **kwargs) -> list[Any]:
        filtered_kwargs = {key: value for key, value in kwargs.items() if value is not None}
        try:
            return repo.list_filtered(limit=batch, offset=offset, **filtered_kwargs)
        except TypeError:
            if offset:
                return []
            try:
                return repo.list_filtered(limit=batch, **filtered_kwargs)
            except TypeError:
                return repo.list_filtered(limit=batch)

    def _collect_visible_items(self, *, limit: int, fetch_page, is_visible) -> list[Any]:
        batch_size = max(limit, 100)
        offset = 0
        rows: list[Any] = []
        while len(rows) < limit:
            page = fetch_page(batch_size, offset)
            if not page:
                break
            for item in page:
                if is_visible(item):
                    rows.append(item)
                    if len(rows) >= limit:
                        break
            offset += len(page)
            if len(page) < batch_size:
                break
        return rows

    def _collect_visible_audit_events(
        self,
        *,
        limit: int,
        principal: AuthPrincipal | None,
        target_type: str | None = None,
        target_id: str | None = None,
        correlation_id: str | None = None,
        severity: str | None = None,
    ) -> list[Any]:
        actor_user_id = None if target_id or correlation_id else self._principal_user_id(principal)
        return self._collect_visible_items(
            limit=limit,
            fetch_page=lambda batch, offset: self._fetch_audit_page(
                self.audit,
                batch=batch,
                offset=offset,
                target_type=target_type,
                target_id=target_id,
                correlation_id=correlation_id,
                severity=severity,
                actor_user_id=actor_user_id,
            ),
            is_visible=lambda item: self._audit_event_visible(item, principal),
        )

    def list_operations(
        self,
        *,
        operation_kind: str | None = None,
        status: str | None = None,
        correlation_id: str | None = None,
        solution_version_id: str | None = None,
        verification_protocol_id: str | None = None,
        knowledge_version_id: str | None = None,
        limit: int = 100,
        principal: AuthPrincipal | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        window = self._operation_window(limit)
        if operation_kind in (None, "knowledge_update_run"):
            for item in self._collect_visible_items(
                limit=window,
                fetch_page=lambda batch, offset: self._fetch_recent_page(
                    self.knowledge_runs, batch=batch, offset=offset, knowledge_base_id=None
                ),
                is_visible=lambda item: self._is_visible_knowledge_run(item, principal),
            ):
                summary = item.summary or {}
                rows.append(
                    {
                        "operation_kind": "knowledge_update_run",
                        "operation_id": str(item.update_run_id),
                        "status": item.status.value,
                        "current_stage": item.current_stage,
                        "correlation_id": item.correlation_id,
                        "started_at": self._row_started_at(item.started_at, item.finished_at),
                        "finished_at": item.finished_at,
                        "initiator_user_id": str(item.initiator_user_id)
                        if item.initiator_user_id
                        else None,
                        "entity_refs": {
                            "knowledge_base_id": str(item.knowledge_base_id),
                            "candidate_version_id": summary.get("candidate_knowledge_version_id"),
                            "activated_version_id": summary.get("activated_knowledge_version_id"),
                            "knowledge_version_id": summary.get("activated_knowledge_version_id")
                            or summary.get("candidate_knowledge_version_id"),
                        },
                        "diagnostics": summary,
                    }
                )
        if operation_kind in (None, "generation_run"):
            for item in self._collect_visible_items(
                limit=window,
                fetch_page=lambda batch, offset: self._fetch_recent_page(
                    self.generation_runs,
                    batch=batch,
                    offset=offset,
                    correlation_id=correlation_id,
                    eager=True,
                ),
                is_visible=lambda item: self._is_visible_generation_run(item, principal),
            ):
                rows.append(
                    {
                        "operation_kind": "generation_run",
                        "operation_id": str(item.generation_run_id),
                        "status": item.status.value,
                        "current_stage": item.current_stage,
                        "correlation_id": item.correlation_id,
                        "started_at": self._row_started_at(item.started_at, item.finished_at),
                        "finished_at": item.finished_at,
                        "initiator_user_id": str(item.started_by_user_id),
                        "entity_refs": {
                            "business_task_id": str(item.business_task_id),
                            "knowledge_version_id": str(item.knowledge_version_id),
                            "solution_version_id": str(item.solution_version.solution_version_id)
                            if item.solution_version
                            else None,
                        },
                        "diagnostics": item.diagnostics,
                    }
                )
        if operation_kind in (None, "verification_run"):
            for item in self._collect_visible_items(
                limit=window,
                fetch_page=lambda batch, offset: self._fetch_recent_page(
                    self.verification_runs,
                    batch=batch,
                    offset=offset,
                    correlation_id=correlation_id,
                    eager=True,
                ),
                is_visible=lambda item: self._is_visible_verification_run(item, principal),
            ):
                rows.append(
                    {
                        "operation_kind": "verification_run",
                        "operation_id": str(item.verification_run_id),
                        "status": item.status.value,
                        "current_stage": item.current_stage,
                        "correlation_id": item.correlation_id,
                        "started_at": self._row_started_at(item.started_at, item.finished_at),
                        "finished_at": item.finished_at,
                        "initiator_user_id": str(item.started_by_user_id),
                        "entity_refs": {
                            "solution_version_id": str(item.solution_version_id),
                            "knowledge_version_id": str(item.knowledge_version_id),
                            "verification_protocol_id": str(item.protocol.verification_protocol_id)
                            if item.protocol
                            else None,
                        },
                        "diagnostics": item.diagnostics,
                    }
                )

        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if correlation_id is not None and operation_kind in (None, "knowledge_update_run"):
            rows = [row for row in rows if row["correlation_id"] == correlation_id]
        if solution_version_id is not None:
            rows = [
                row
                for row in rows
                if (row.get("entity_refs") or {}).get("solution_version_id") == solution_version_id
            ]
        if verification_protocol_id is not None:
            rows = [
                row
                for row in rows
                if (row.get("entity_refs") or {}).get("verification_protocol_id")
                == verification_protocol_id
            ]
        if knowledge_version_id is not None:

            def _row_has_knowledge_id(row):
                refs = row.get("entity_refs") or {}
                return (
                    refs.get("knowledge_version_id") == knowledge_version_id
                    or (row.get("diagnostics") or {}).get("knowledge_version_id")
                    == knowledge_version_id
                )

            rows = [row for row in rows if _row_has_knowledge_id(row)]
        rows.sort(key=self._sort_started_at, reverse=True)
        rows = rows[:limit]
        return [self._enrich_operation_row(row) for row in rows]

    @staticmethod
    def _derive_duration_sec(row: dict[str, Any]) -> int | None:
        started_at = row.get("started_at")
        finished_at = row.get("finished_at")
        if not started_at or not finished_at:
            return None
        try:
            return max(0, int((finished_at - started_at).total_seconds()))
        except Exception:
            return None

    @staticmethod
    def _derive_error_code(row: dict[str, Any]) -> str | None:
        diagnostics = row.get("diagnostics") or {}
        if isinstance(diagnostics, dict):
            for key in ("error_code", "last_error_code", "code"):
                value = diagnostics.get(key)
                if isinstance(value, str) and value:
                    return value
            error = diagnostics.get("error")
            if isinstance(error, dict):
                for key in ("error_code", "code"):
                    value = error.get(key)
                    if isinstance(value, str) and value:
                        return value
        return None

    @staticmethod
    def _derive_actor_label(row: dict[str, Any]) -> str | None:
        diagnostics = row.get("diagnostics") or {}
        if isinstance(diagnostics, dict):
            requested_by = diagnostics.get("requested_by")
            if isinstance(requested_by, str) and requested_by:
                return requested_by
        initiator = row.get("initiator_user_id")
        if initiator:
            return str(initiator)
        return "system"

    def _enrich_operation_row(self, row: dict[str, Any]) -> dict[str, Any]:
        row["duration_sec"] = self._derive_duration_sec(row)
        row["error_code"] = self._derive_error_code(row)
        row["actor_label"] = self._derive_actor_label(row)
        step_repo = getattr(self, "operation_steps", None)
        steps = []
        if step_repo is not None:
            steps = step_repo.list_for_operation(
                operation_kind=str(row.get("operation_kind")),
                operation_id=str(row.get("operation_id")),
            )
        row["last_problem_step"] = self._derive_last_problem_step(
            row.get("status"), steps, row.get("current_stage"), row.get("diagnostics")
        )
        return row

    @staticmethod
    def _derive_last_problem_step(
        status: str | None,
        steps: list[Any],
        current_stage: str | None,
        diagnostics: dict[str, Any] | None = None,
    ) -> str | None:
        if status not in {"failed", "completed_with_warnings", "degraded", "incomplete"}:
            return None
        for item in reversed(steps or []):
            if getattr(item, "status", None) in {
                "failed",
                "warning",
                "incomplete",
                "not_determined",
            }:
                payload = getattr(item, "payload", None)
                failed_stage = payload.get("failed_stage") if isinstance(payload, dict) else None
                if getattr(item, "step_code", None) == "failed" and failed_stage:
                    return str(failed_stage)
                return getattr(item, "step_code", None)
        stage_history = (
            ((diagnostics or {}).get("stage_history") or [])
            if isinstance(diagnostics, dict)
            else []
        )
        for item in reversed(stage_history or []):
            if item.get("status") in {"failed", "warning", "incomplete"}:
                return item.get("stage")
        return current_stage

    def list_audit_events(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        correlation_id: str | None = None,
        severity: str | None = None,
        limit: int = 100,
        principal: AuthPrincipal | None = None,
    ):
        return self._collect_visible_audit_events(
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
            severity=severity,
            limit=limit,
            principal=principal,
        )

    def get_audit_event(self, audit_event_id: str, *, principal: AuthPrincipal | None = None):
        item = self.audit.get(audit_event_id)
        if item is None or not self._audit_event_visible(item, principal):
            raise NotFoundError("AuditEvent", audit_event_id)
        return item

    def get_metrics_snapshot(self, *, principal: AuthPrincipal | None = None) -> dict[str, Any]:
        window = self._metrics_window()
        knowledge_items = self._collect_visible_items(
            limit=window,
            fetch_page=lambda batch, offset: self._fetch_recent_page(
                self.knowledge_runs, batch=batch, offset=offset
            ),
            is_visible=lambda item: self._is_visible_knowledge_run(item, principal),
        )
        generation_items = self._collect_visible_items(
            limit=window,
            fetch_page=lambda batch, offset: self._fetch_recent_page(
                self.generation_runs, batch=batch, offset=offset, eager=True
            ),
            is_visible=lambda item: self._is_visible_generation_run(item, principal),
        )
        verification_items = self._collect_visible_items(
            limit=window,
            fetch_page=lambda batch, offset: self._fetch_recent_page(
                self.verification_runs, batch=batch, offset=offset, eager=True
            ),
            is_visible=lambda item: self._is_visible_verification_run(item, principal),
        )
        audit_items = self._collect_visible_audit_events(limit=window, principal=principal)
        return {
            "generated_at": datetime.now(UTC),
            "knowledge_updates": self._counter_payload(
                knowledge_items, lambda item: item.status.value
            ),
            "generation_runs": self._counter_payload(
                generation_items, lambda item: item.status.value
            ),
            "verification_runs": self._counter_payload(
                verification_items, lambda item: item.status.value
            ),
            "audit_events": self._counter_payload(audit_items, lambda item: item.severity.value),
            "data_llm_dashboard": {
                "generation_quality": self._generation_quality_payload(generation_items),
                "verification_quality": self._verification_quality_payload(verification_items),
                "retrieval_policy_versions": self._distribution_payload(
                    [
                        ((item.diagnostics or {}).get("policy_stack") or {}).get(
                            "retrieval_policy_version"
                        )
                        for item in generation_items + verification_items
                    ]
                ),
                "embedding_model_versions": self._distribution_payload(
                    [
                        ((item.diagnostics or {}).get("policy_stack") or {}).get(
                            "embedding_model_version"
                        )
                        for item in generation_items + verification_items
                    ]
                    + [
                        (
                            ((item.summary or {}).get("quality_summary") or {}).get("policy_stack")
                            or {}
                        ).get("embedding_model_version")
                        for item in knowledge_items
                    ]
                ),
                "chunking_policy_versions": self._distribution_payload(
                    [
                        (
                            ((item.summary or {}).get("quality_summary") or {}).get("policy_stack")
                            or {}
                        ).get("chunking_policy_version")
                        for item in knowledge_items
                    ]
                ),
                "pipeline_observability": {
                    "knowledge_updates": self._pipeline_observability_payload(
                        [
                            ((item.summary or {}).get("quality_summary") or {}).get(
                                "pipeline_telemetry"
                            )
                            or ((item.summary or {}).get("quality_summary") or {}).get("telemetry")
                            for item in knowledge_items
                        ]
                    ),
                    "generation_runs": self._pipeline_observability_payload(
                        [
                            (item.diagnostics or {}).get("pipeline_telemetry")
                            for item in generation_items
                        ]
                    ),
                    "verification_runs": self._pipeline_observability_payload(
                        [
                            (item.diagnostics or {}).get("pipeline_telemetry")
                            for item in verification_items
                        ]
                    ),
                },
            },
        }

    @staticmethod
    def _distribution_payload(values: list[Any]) -> dict[str, Any]:
        normalized = [str(value) for value in values if value]
        counter = Counter(normalized)
        return {"count": len(normalized), "by_value": dict(sorted(counter.items()))}

    @staticmethod
    def _average(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 3)

    def _pipeline_observability_payload(self, telemetry_items: list[Any]) -> dict[str, Any]:
        normalized = [
            dict(item or {}) for item in telemetry_items if isinstance(item, dict) and item
        ]
        total_stage_duration = [
            float(item.get("total_stage_duration_sec") or 0.0)
            for item in normalized
            if item.get("total_stage_duration_sec") is not None
        ]
        runtime_sec = [
            float(item.get("total_runtime_sec") or 0.0)
            for item in normalized
            if item.get("total_runtime_sec") is not None
        ]
        stage_count = [
            float(item.get("stage_count") or 0.0)
            for item in normalized
            if item.get("stage_count") is not None
        ]
        failed_stage_count = [
            float(item.get("failed_stage_count") or 0.0)
            for item in normalized
            if item.get("failed_stage_count") is not None
        ]
        longest_stage_counter = Counter(
            str(item.get("longest_stage")) for item in normalized if item.get("longest_stage")
        )
        return {
            "count": len(normalized),
            "average_total_stage_duration_sec": self._average(total_stage_duration),
            "average_runtime_sec": self._average(runtime_sec),
            "average_stage_count": self._average(stage_count),
            "average_failed_stage_count": self._average(failed_stage_count),
            "longest_stage_distribution": dict(sorted(longest_stage_counter.items())),
        }

    def _generation_quality_payload(self, items: list[Any]) -> dict[str, Any]:
        quality_items = [item.diagnostics or {} for item in items]
        groundedness = [
            float(q.get("quality_outcomes", {}).get("groundedness_score"))
            for q in quality_items
            if q.get("quality_outcomes", {}).get("groundedness_score") is not None
        ]
        citation = [
            float(q.get("quality_outcomes", {}).get("citation_coverage"))
            for q in quality_items
            if q.get("quality_outcomes", {}).get("citation_coverage") is not None
        ]
        fallback_count = sum(
            1 for q in quality_items if q.get("quality_outcomes", {}).get("fallback_used")
        )
        empty_retrieval = sum(
            1 for q in quality_items if q.get("retrieval", {}).get("empty_result")
        )
        count = len(items)
        return {
            "count": count,
            "average_groundedness_score": self._average(groundedness),
            "average_citation_coverage": self._average(citation),
            "fallback_rate": round(fallback_count / count, 3) if count else None,
            "retrieval_empty_rate": round(empty_retrieval / count, 3) if count else None,
            "average_check_count": None,
        }

    def _verification_quality_payload(self, items: list[Any]) -> dict[str, Any]:
        quality_items = [item.diagnostics or {} for item in items]
        check_counts = [
            float(q.get("quality_outcomes", {}).get("check_count"))
            for q in quality_items
            if q.get("quality_outcomes", {}).get("check_count") is not None
        ]
        empty_retrieval = sum(
            1 for q in quality_items if q.get("knowledge_query", {}).get("empty_result")
        )
        count = len(items)
        return {
            "count": count,
            "average_groundedness_score": None,
            "average_citation_coverage": None,
            "fallback_rate": None,
            "retrieval_empty_rate": round(empty_retrieval / count, 3) if count else None,
            "average_check_count": self._average(check_counts),
        }

    @staticmethod
    def _counter_payload(items: list[Any], getter) -> dict[str, Any]:
        counter = Counter(str(getter(item)) for item in items if getter(item) is not None)
        return {"count": len(items), "by_status": dict(sorted(counter.items()))}

    def get_operation_detail(
        self, operation_id: str, *, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        knowledge_item = self.knowledge_runs.get(operation_id)
        if knowledge_item is not None:
            if not self._is_visible_knowledge_run(knowledge_item, principal):
                raise NotFoundError("Operation", operation_id)
            summary = knowledge_item.summary or {}
            return self._decorate_operation_detail(
                {
                    "operation_kind": "knowledge_update_run",
                    "operation_id": str(knowledge_item.update_run_id),
                    "status": knowledge_item.status.value,
                    "current_stage": knowledge_item.current_stage,
                    "correlation_id": knowledge_item.correlation_id,
                    "started_at": self._row_started_at(
                        knowledge_item.started_at, knowledge_item.finished_at
                    ),
                    "finished_at": knowledge_item.finished_at,
                    "initiator_user_id": str(knowledge_item.initiator_user_id)
                    if knowledge_item.initiator_user_id
                    else None,
                    "entity_refs": {
                        "knowledge_base_id": str(knowledge_item.knowledge_base_id),
                        "candidate_version_id": summary.get("candidate_knowledge_version_id"),
                        "activated_version_id": summary.get("activated_knowledge_version_id"),
                        "knowledge_version_id": summary.get("activated_knowledge_version_id")
                        or summary.get("candidate_knowledge_version_id"),
                    },
                    "diagnostics": summary,
                },
                principal=principal,
            )
        generation_item = self.generation_runs.get(operation_id)
        if generation_item is not None:
            if not self._is_visible_generation_run(generation_item, principal):
                raise NotFoundError("Operation", operation_id)
            return self._decorate_operation_detail(
                {
                    "operation_kind": "generation_run",
                    "operation_id": str(generation_item.generation_run_id),
                    "status": generation_item.status.value,
                    "current_stage": generation_item.current_stage,
                    "correlation_id": generation_item.correlation_id,
                    "started_at": self._row_started_at(
                        generation_item.started_at, generation_item.finished_at
                    ),
                    "finished_at": generation_item.finished_at,
                    "initiator_user_id": str(generation_item.started_by_user_id),
                    "entity_refs": {
                        "business_task_id": str(generation_item.business_task_id),
                        "knowledge_version_id": str(generation_item.knowledge_version_id),
                        "solution_version_id": str(
                            generation_item.solution_version.solution_version_id
                        )
                        if generation_item.solution_version
                        else None,
                    },
                    "diagnostics": generation_item.diagnostics,
                },
                principal=principal,
            )
        verification_item = self.verification_runs.get(operation_id)
        if verification_item is not None:
            if not self._is_visible_verification_run(verification_item, principal):
                raise NotFoundError("Operation", operation_id)
            return self._decorate_operation_detail(
                {
                    "operation_kind": "verification_run",
                    "operation_id": str(verification_item.verification_run_id),
                    "status": verification_item.status.value,
                    "current_stage": verification_item.current_stage,
                    "correlation_id": verification_item.correlation_id,
                    "started_at": self._row_started_at(
                        verification_item.started_at, verification_item.finished_at
                    ),
                    "finished_at": verification_item.finished_at,
                    "initiator_user_id": str(verification_item.started_by_user_id),
                    "entity_refs": {
                        "solution_version_id": str(verification_item.solution_version_id),
                        "knowledge_version_id": str(verification_item.knowledge_version_id),
                        "verification_protocol_id": str(
                            verification_item.protocol.verification_protocol_id
                        )
                        if verification_item.protocol
                        else None,
                    },
                    "diagnostics": verification_item.diagnostics,
                },
                principal=principal,
            )
        raise NotFoundError("Operation", operation_id)

    def _decorate_operation_detail(
        self, row: dict[str, Any], *, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        correlation_id = row.get("correlation_id")
        operation_kind = row.get("operation_kind")
        operation_id = row.get("operation_id")
        audit_events = self._collect_visible_audit_events(
            correlation_id=correlation_id, limit=50, principal=principal
        )
        if not audit_events:
            target_type = {
                "knowledge_update_run": "knowledge_update_run",
                "generation_run": "generation_run",
                "verification_run": "verification_run",
            }.get(str(operation_kind))
            if target_type:
                audit_events = self._collect_visible_audit_events(
                    target_type=target_type, target_id=operation_id, limit=50, principal=principal
                )
        audit_events = self._filter_visible_audit_events(audit_events, principal)
        row = self._enrich_operation_row(row)
        row["summary_text"] = self._build_operation_summary(row)
        persisted_steps = self.operation_steps.list_for_operation(
            operation_kind=str(operation_kind), operation_id=str(operation_id)
        )
        persisted_step_payloads = [
            {
                "code": item.step_code,
                "title": item.title,
                "status": item.status,
                "started_at": self._row_started_at(item.started_at, item.finished_at),
                "finished_at": item.finished_at,
                "detail": item.detail,
                "error_code": item.error_code,
                "payload": item.payload,
            }
            for item in persisted_steps
        ]
        row["steps"] = self._merge_operation_steps(row, persisted_step_payloads)
        row["audit_events"] = [
            {
                "audit_event_id": str(item.audit_event_id),
                "event_time": item.event_time,
                "event_type": item.event_type,
                "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None,
                "target_type": item.target_type,
                "target_id": str(item.target_id),
                "severity": item.severity,
                "message": item.message,
                "payload": item.payload,
                "correlation_id": item.correlation_id,
            }
            for item in audit_events
        ]
        return row

    @staticmethod
    def _parse_stage_timestamp(value: Any):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except Exception:
                return None
        return None

    @staticmethod
    def _build_operation_summary(row: dict[str, Any]) -> str:
        refs = row.get("entity_refs") or {}
        kind = row.get("operation_kind")
        if kind == "knowledge_update_run":
            diagnostics = row.get("diagnostics") or {}
            candidate = refs.get("candidate_version_id") or diagnostics.get(
                "candidate_knowledge_version_id"
            )
            activated = refs.get("activated_version_id") or diagnostics.get(
                "activated_knowledge_version_id"
            )
            quality = diagnostics.get("quality_summary") or {}
            processed_documents = quality.get("processed_documents")
            if activated:
                return f"Обновление знаний завершилось активацией версии {activated}. Обработано документов: {processed_documents or 0}."
            if candidate:
                return f"Обновление знаний подготовило кандидатную версию {candidate}. Обработано документов: {processed_documents or 0}."
            return (
                "Обновление знаний обрабатывает подключённые источники и проверяет их пригодность."
            )
        if kind == "generation_run":
            solution_id = refs.get("solution_version_id")
            if solution_id:
                return f"Генерация завершилась публикацией решения {solution_id}."
            return "Генерация собирает решение по зафиксированной версии знаний."
        if kind == "verification_run":
            protocol_id = refs.get("verification_protocol_id")
            if protocol_id:
                return f"Проверка завершилась выпуском протокола {protocol_id}."
            return "Проверка оценивает опубликованное решение и формирует протокол."
        return "Операция выполняется."

    @staticmethod
    def _build_operation_steps(row: dict[str, Any]) -> list[dict[str, Any]]:
        started_at = row.get("started_at")
        finished_at = row.get("finished_at")
        current_stage = row.get("current_stage")
        status = row.get("status")
        diagnostics = row.get("diagnostics") or {}
        operation_kind = row.get("operation_kind")
        stage_history = diagnostics.get("stage_history") or []
        stage_map = {
            item.get("stage"): item
            for item in stage_history
            if isinstance(item, dict) and item.get("stage")
        }

        stage_order: dict[str, int] = {}

        def step(
            code: str, title: str, done_when: set[str], detail: str | None = None
        ) -> dict[str, Any]:
            event = stage_map.get(code)
            event_status = (event or {}).get("status")
            current_order = stage_order.get(str(current_stage), -1)
            step_order = stage_order.get(code, -1)
            if event_status in {"failed", "canceled", "warning", "incomplete"}:
                step_status = event_status
            elif status in {"failed", "canceled"} and current_stage == code:
                step_status = status
            elif current_stage == code or status == code:
                step_status = (
                    "running"
                    if status not in {"completed", "completed_with_warnings", "failed", "canceled"}
                    else "completed"
                )
            elif (
                code in stage_map
                or status in {"completed", "completed_with_warnings"}
                or status in done_when
                or (current_order >= 0 and step_order >= 0 and step_order < current_order)
            ):
                step_status = "completed"
            else:
                step_status = "pending"
            return {
                "code": code,
                "title": title,
                "status": step_status,
                "started_at": OperationsQueryService._parse_stage_timestamp(event.get("timestamp"))
                if event
                else (started_at if step_status != "pending" else None),
                "finished_at": finished_at
                if step_status == "completed" and code == "completed"
                else None,
                "detail": event.get("detail") if event and event.get("detail") else detail,
            }

        if operation_kind == "knowledge_update_run":
            quality = diagnostics.get("quality_summary") or {}
            activated_version = diagnostics.get("activated_knowledge_version_id")
            stage_order = {
                "queued": 0,
                "loading": 1,
                "parsing": 2,
                "extracting": 3,
                "indexing": 4,
                "validating": 5,
                "active": 6,
                "completed": 7,
            }
            return [
                step(
                    "queued",
                    "Поставлено в очередь",
                    {"queued"},
                    "Система приняла запрос на обновление знаний.",
                ),
                step(
                    "loading",
                    "Обнаружение и загрузка источников",
                    {"loading"},
                    "Система находит документы, скачивает и подготавливает их к обработке.",
                ),
                step(
                    "parsing",
                    "Разбор документов",
                    {"parsing"},
                    "Документы приводятся к нормализованному внутреннему представлению.",
                ),
                step(
                    "extracting",
                    "Извлечение знаний",
                    {"extracting"},
                    "Из документа извлекаются правила, сущности, ограничения и термины.",
                ),
                step(
                    "indexing",
                    "Индексация и память базы",
                    {"indexing"},
                    "Готовятся фрагменты, embeddings и прозрачная память документа.",
                ),
                step(
                    "validating",
                    "Проверка кандидатной версии",
                    {"validating"},
                    f"Результат проверки: {quality.get('validation') or diagnostics.get('validation') or 'ожидается'}",
                ),
                step(
                    "active",
                    "Активация новой версии",
                    {"active"},
                    "Новая версия базы активируется автоматически."
                    if activated_version
                    else "Активация не выполнялась.",
                ),
                step(
                    "completed",
                    "Синхронизация завершена",
                    {"completed", "completed_with_warnings", "requires_operator_decision"},
                    "Операция завершена, журнал и метрики доступны для анализа.",
                ),
            ]
        if operation_kind == "generation_run":
            stage_order = {
                "queued": 0,
                "retrieving": 1,
                "prompting": 2,
                "model_generation": 3,
                "validating": 4,
                "persisting": 5,
                "publishing": 6,
                "completed": 7,
            }
            return [
                step(
                    "queued",
                    "Поставлено в очередь",
                    {"queued"},
                    "Запрос на подготовку решения принят.",
                ),
                step(
                    "retrieving",
                    "Подбор знаний",
                    {"retrieving"},
                    "Система подбирает материалы из активной версии знаний.",
                ),
                step(
                    "prompting",
                    "Подготовка промпта",
                    {"prompting"},
                    "Формируется grounded prompt artifact.",
                ),
                step(
                    "model_generation",
                    "Ожидание ответа модели",
                    {"model_generation"},
                    "Запрос отправлен во внешнюю модель. На этом шаге нормальны паузы в несколько минут.",
                ),
                step(
                    "validating",
                    "Проверка результата",
                    {"validating"},
                    "Проверяется качество и groundedness ответа.",
                ),
                step(
                    "persisting",
                    "Сохранение решения",
                    {"persisting"},
                    "Проверенный результат сохраняется как версия решения.",
                ),
                step(
                    "publishing",
                    "Публикация решения",
                    {"publishing"},
                    "Готовится страница решения для просмотра.",
                ),
                step(
                    "completed",
                    "Решение опубликовано",
                    {"completed"},
                    "Результат сохранён как отдельный артефакт.",
                ),
            ]
        if operation_kind == "verification_run":
            stage_order = {
                "queued": 0,
                "preparing": 1,
                "verification": 2,
                "publishing": 3,
                "completed": 4,
            }
            return [
                step("queued", "Поставлено в очередь", {"queued"}, "Запрос на проверку принят."),
                step(
                    "preparing",
                    "Подготовка контекста",
                    {"preparing"},
                    "Загружается решение и зафиксированная версия знаний.",
                ),
                step(
                    "verification",
                    "Проверка решения",
                    {"verification"},
                    "Выполняются обязательные проверки по профилю full.",
                ),
                step(
                    "publishing",
                    "Сборка протокола",
                    {"publishing"},
                    "Формируется отдельный протокол проверки.",
                ),
                step(
                    "completed", "Проверка завершена", {"completed"}, "Протокол готов к просмотру."
                ),
            ]

        return [step("running", "Операция выполняется", {str(current_stage)})]

    @staticmethod
    def _merge_operation_steps(
        row: dict[str, Any], persisted_steps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        planned_steps = OperationsQueryService._build_operation_steps(row)
        if not persisted_steps:
            return planned_steps

        persisted_by_code = {str(item.get("code")): item for item in persisted_steps}
        merged: list[dict[str, Any]] = []
        terminal_problem_statuses = {
            "failed",
            "canceled",
            "warning",
            "incomplete",
            "not_determined",
        }

        for planned in planned_steps:
            code = str(planned.get("code"))
            persisted = persisted_by_code.pop(code, None)
            if persisted is None:
                merged.append(planned)
                continue

            persisted_status = str(persisted.get("status") or "")
            planned_status = str(planned.get("status") or "")
            if persisted_status in terminal_problem_statuses:
                status = persisted_status
            elif planned_status == "completed" and persisted_status not in terminal_problem_statuses:
                status = "completed"
            elif planned_status == "running" and persisted_status in {"pending", "queued", ""}:
                status = "running"
            else:
                status = persisted_status or planned_status

            merged.append(
                {
                    **planned,
                    "title": persisted.get("title") or planned.get("title"),
                    "status": status,
                    "started_at": persisted.get("started_at") or planned.get("started_at"),
                    "finished_at": persisted.get("finished_at") or planned.get("finished_at"),
                    "detail": persisted.get("detail") or planned.get("detail"),
                    "error_code": persisted.get("error_code") or planned.get("error_code"),
                    "payload": persisted.get("payload") if "payload" in persisted else planned.get("payload"),
                }
            )

        merged.extend(persisted_by_code.values())
        return merged
