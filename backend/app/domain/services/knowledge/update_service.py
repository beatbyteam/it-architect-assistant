from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    AuditSeverity,
    Criticality,
    DocumentDeltaKind,
    KnowledgeBaseKind,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceProcessingStatus,
    SourceScope,
    SourceStatus,
    SourceType,
    UpdateRunType,
)
from app.db.models.knowledge import (
    DocumentChunk,
    DocumentDelta,
    DocumentExtractedItem,
    DocumentSnapshot,
    EmbeddingSpace,
    KnowledgeBase,
    KnowledgeBaseSelection,
    KnowledgeFragment,
    KnowledgeFragmentEmbedding,
    KnowledgeSource,
    KnowledgeUpdateRun,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    NormativeRule,
    SourceDocument,
    SourceProcessingResult,
)
from app.db.repositories.knowledge import (
    DocumentChunkRepository,
    DocumentDeltaRepository,
    DocumentExtractedItemRepository,
    DocumentSnapshotRepository,
    EmbeddingSpaceRepository,
    KnowledgeBaseRepository,
    KnowledgeBaseSelectionRepository,
    KnowledgeFragmentEmbeddingRepository,
    KnowledgeSourceRepository,
    KnowledgeUpdateRunRepository,
    KnowledgeVersionRepository,
    SourceDocumentRepository,
    SourceProcessingResultRepository,
)
from app.domain.services.audit import AuditService
from app.domain.services.idempotency import IdempotencyService
from app.domain.services.knowledge.policies import is_generation_selectable_version
from app.domain.services.knowledge.update_diffing import (
    build_version_diff_summary,
    build_version_document_signature,
    classify_document_error_code,
)
from app.domain.services.knowledge.version_service import KnowledgeVersionService
from app.domain.services.knowledge_bases import KnowledgeBaseService, _selection_scope_for_principal
from app.domain.services.knowledge_basis import (
    build_basis_inventory_for_version_documents,
    resolve_basis_assignment,
)
from app.domain.services.knowledge_telemetry import build_update_run_telemetry_summary
from app.domain.services.operation_tracking import OperationTrackingService
from app.domain.services.principal_keys import principal_actor_id, principal_requested_by
from app.domain.services.workflow_runtime import (
    build_stage_event,
    dispatch_run,
    record_operation_step,
)
from app.integrations.knowledge.embedding import EmbeddingProfileRegistry, EmbeddingService
from app.integrations.knowledge.knowledge_extraction import (
    DocumentMemoryLlmConfig,
    extract_document_memory,
)
from app.integrations.knowledge.policy_stack import build_policy_stack
from app.integrations.knowledge.source_readers import (
    RepositoryReader,
    UrlListReader,
)
from app.integrations.knowledge.source_security import (
    SourceAvailabilityError,
    probe_source_availability,
    validate_document_uri,
    validate_source_base_uri,
)
from app.integrations.knowledge.text_processing import (
    detect_rule_conflicts,
)
from app.schemas.knowledge import (
    InternalKnowledgeUpdateRunStartRequest,
    KnowledgeUpdateRunStartRequest,
)

from .common import (
    SUPPORTED_SOURCE_TYPES,
    TERMINAL_UPDATE_STATUSES,
    ValidationSummary,
    _build_allowed_local_source_roots,
    _normalize_source_type,
    _public_source_type,
    _schedule_interval_days,
    _uses_auto_sync,
)
from .update_runtime import execute_knowledge_update_run


_MAX_SOURCE_LOCATION_CHARS = 200


def _fit_source_location(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= _MAX_SOURCE_LOCATION_CHARS:
        return text
    return text[: _MAX_SOURCE_LOCATION_CHARS - 3].rstrip() + "..."


def _is_delete_run_type(value: Any) -> bool:
    return getattr(value, "value", value) == UpdateRunType.DELETE.value


class RunStartResult(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class KnowledgeUpdateService:
    _QUEUE_RECOVERY_GRACE_SEC = 15

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.bases = KnowledgeBaseRepository(session)
        self.sources = KnowledgeSourceRepository(session)
        self.documents = SourceDocumentRepository(session)
        self.update_runs = KnowledgeUpdateRunRepository(session)
        self.processing_results = SourceProcessingResultRepository(session)
        self.document_snapshots = DocumentSnapshotRepository(session)
        self.document_chunks = DocumentChunkRepository(session)
        self.embedding_spaces = EmbeddingSpaceRepository(session)
        self.fragment_embeddings = KnowledgeFragmentEmbeddingRepository(session)
        self.extracted_items = DocumentExtractedItemRepository(session)
        self.document_deltas = DocumentDeltaRepository(session)
        self.versions = KnowledgeVersionRepository(session)
        self.selections = KnowledgeBaseSelectionRepository(session)
        self.update_runs = KnowledgeUpdateRunRepository(session)
        self.audit = AuditService(session)
        self.operations = OperationTrackingService(session)
        self.idempotency = IdempotencyService(session)
        self.repository_reader = RepositoryReader()
        self.url_list_reader = UrlListReader(
            timeout_sec=float(getattr(settings, "knowledge_fetch_timeout_sec", 30.0) or 30.0)
        )
        self.embeddings = EmbeddingService(
            profile_code=getattr(settings, "embedding_profile", None) or "statistical_default",
            provider_name=getattr(settings, "embedding_provider", None),
            dimensions=getattr(settings, "embedding_dimensions", None),
            base_url=getattr(settings, "embedding_base_url", None),
            api_key=getattr(settings, "embedding_api_key", None),
            timeout_sec=float(getattr(settings, "embedding_timeout_sec", 30.0) or 30.0),
            model_id=getattr(settings, "embedding_model_id", None),
            batch_size=int(getattr(settings, "embedding_batch_size", 32) or 32),
        )

    def _make_base_service(self):
        factory = getattr(self, "knowledge_base_service_factory", None)
        if callable(factory):
            try:
                return factory(self.session)
            except TypeError:
                return factory()
        from app.domain.services import knowledge_core as knowledge_core_module

        service_cls: Any = getattr(
            knowledge_core_module,
            "KnowledgeBaseService",
            KnowledgeBaseService,
        )
        try:
            return service_cls(self.session)
        except TypeError:
            return service_cls()

    def _get_base(
        self, knowledge_base_id: str, principal: AuthPrincipal | None = None
    ) -> KnowledgeBase:
        base_service = self._make_base_service()
        get_base = base_service.get_base
        try:
            return get_base(knowledge_base_id, principal)
        except TypeError:
            return get_base(knowledge_base_id)

    def _ensure_system_bases(self, principal: AuthPrincipal | None = None) -> None:
        base_service = self._make_base_service()
        ensure = base_service.ensure_system_bases
        try:
            ensure(principal)
        except TypeError:
            ensure()

    def _get_default_user_base(self, principal: AuthPrincipal | None = None) -> KnowledgeBase:
        base_service = self._make_base_service()
        getter = base_service.get_default_user_base
        try:
            return getter(principal)
        except TypeError:
            return getter()

    def _list_visible_bases(self, principal: AuthPrincipal | None = None) -> list[Any]:
        base_service = self._make_base_service()
        bases_repo = getattr(base_service, "bases", None)
        if bases_repo is None or not hasattr(bases_repo, "list_visible"):
            return []
        owner_user_id = (
            str(getattr(principal, "user_id", None) or getattr(principal, "login", None) or "")
            or None
        )
        try:
            return list(bases_repo.list_visible(owner_user_id=owner_user_id))
        except TypeError:
            return list(bases_repo.list_visible())

    @staticmethod
    def _run_identifier(run: Any, *, field: str) -> str | None:
        value = run.get(field) if isinstance(run, dict) else getattr(run, field, None)
        return str(value) if value is not None else None

    def _result_from_run(self, run: KnowledgeUpdateRun | dict[str, Any] | Any) -> RunStartResult:
        if isinstance(run, dict):
            return RunStartResult(run)
        if hasattr(run, "summary") or hasattr(run, "scope") or hasattr(run, "status"):
            return RunStartResult(self._serialize_run(run))
        payload: dict[str, Any] = {}
        for field in (
            "update_run_id",
            "knowledge_base_id",
            "run_type",
            "status",
            "current_stage",
            "started_at",
            "finished_at",
            "duration_sec",
            "correlation_id",
        ):
            if hasattr(run, field):
                payload[field] = getattr(run, field)
        return RunStartResult(payload)

    def _settings_value(self, field_name: str, default: Any = None) -> Any:
        return getattr(getattr(self, "settings", None), field_name, default)

    def _is_prod_like_env(self) -> bool:
        probe = getattr(getattr(self, "settings", None), "is_prod_like_env", None)
        if callable(probe):
            return bool(probe())
        return str(getattr(self.settings, "app_env", "") or "").strip().lower() in {
            "prod",
            "production",
            "release",
        }

    def _has_live_worker(self) -> bool:
        cached = getattr(self, "_cached_worker_health", None)
        if cached is not None:
            return bool(cached)
        try:
            from app.tasks.workers.celery_app import celery_app, redis_client

            redis_client.ping()
            reply = celery_app.control.inspect(timeout=1.0).ping() or {}
            healthy = bool(reply)
        except Exception:
            healthy = False
        self._cached_worker_health = healthy
        return healthy

    def _should_force_inline_without_worker(self) -> bool:
        if self._is_prod_like_env():
            return False
        if bool(getattr(self.settings, "celery_task_always_eager", False)):
            return True
        return not self._has_live_worker()

    def _maybe_resume_queued_run_inline(self, run: KnowledgeUpdateRun) -> KnowledgeUpdateRun:
        if (
            run.status != KnowledgeUpdateStatus.QUEUED
            or str(getattr(run, "current_stage", "") or "") != "queued"
        ):
            return run
        if bool((getattr(run, "scope", None) or {}).get("force_async")):
            return run
        if not self._should_force_inline_without_worker():
            return run
        started_at = getattr(run, "started_at", None)
        if started_at is not None:
            age_sec = max(0.0, (datetime.now(UTC) - started_at).total_seconds())
            if age_sec < float(self._QUEUE_RECOVERY_GRACE_SEC):
                return run
        return self.execute_run(str(run.update_run_id))

    def _get_running_run_with_recovery(
        self, *, knowledge_base_id: str
    ) -> KnowledgeUpdateRun | None:
        run = self.update_runs.get_running(knowledge_base_id=knowledge_base_id)
        if run is None:
            return None
        recovered = self._maybe_resume_queued_run_inline(run)
        if recovered.status in TERMINAL_UPDATE_STATUSES:
            return None
        return recovered

    def _validate_source(self, source_type: SourceType, base_uri: str | None) -> None:
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise ValidationError(
                "Sprint 2 supports local folder, URL and manual-upload knowledge sources",
                error_code="UNSUPPORTED_SOURCE_TYPE",
            )
        settings = getattr(self, "settings", None)
        validate_source_base_uri(
            source_type=_normalize_source_type(source_type),
            base_uri=base_uri,
            allowed_local_roots=_build_allowed_local_source_roots(settings),
            allow_unrestricted_local_paths=bool(
                getattr(settings, "knowledge_allow_unrestricted_local_sources", False)
            ),
        )

    def _validate_document_uri(self, uri: str) -> None:
        settings = getattr(self, "settings", None)
        validate_document_uri(
            uri,
            allowed_local_roots=_build_allowed_local_source_roots(settings),
            allow_unrestricted_local_paths=bool(
                getattr(settings, "knowledge_allow_unrestricted_local_sources", False)
            ),
        )

    def _probe_source_availability(
        self, source_type: SourceType, base_uri: str | None
    ) -> dict[str, Any]:
        if not base_uri:
            raise SourceAvailabilityError("base_uri is required")
        settings = getattr(self, "settings", None)
        payload = probe_source_availability(
            source_type=_normalize_source_type(source_type),
            base_uri=base_uri,
            timeout_sec=self._resolve_fetch_timeout(),
            allowed_local_roots=_build_allowed_local_source_roots(settings),
            allow_unrestricted_local_paths=bool(
                getattr(settings, "knowledge_allow_unrestricted_local_sources", False)
            ),
        )
        return {"ok": True, **payload, "checked_at": datetime.now(UTC).isoformat()}

    def _resolve_fetch_timeout(self) -> float:
        settings = getattr(self, "settings", None)
        return float(getattr(settings, "knowledge_fetch_timeout_sec", 30.0) or 30.0)

    @staticmethod
    def _coerce_int(value: object, *, default: int = 0) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return default
            try:
                return int(stripped)
            except ValueError:
                return default
        return default

    @classmethod
    def _coerce_optional_int(cls, value: object) -> int | None:
        if value is None:
            return None
        return cls._coerce_int(value)

    def _embedding_service_for_profile(self, profile_code: str | None) -> EmbeddingService:
        current_profile = self._settings_value("embedding_profile", None)
        if not current_profile:
            describe = getattr(getattr(self, "embeddings", None), "describe", None)
            if callable(describe):
                current_profile = describe().get("profile_code")
        normalized_requested = str(profile_code or "").strip()
        normalized_current = str(current_profile or "").strip()
        if not normalized_requested or normalized_requested == normalized_current:
            return self.embeddings
        profile = EmbeddingProfileRegistry.get(normalized_requested)
        return EmbeddingService(
            profile_code=profile.code,
            provider_name=profile.provider_name,
            dimensions=profile.dimensions,
            base_url=self._settings_value("embedding_base_url", None),
            api_key=self._settings_value("embedding_api_key", None),
            timeout_sec=self._settings_value("embedding_timeout_sec", 30.0),
            model_id=profile.model_id,
            batch_size=self._settings_value("embedding_batch_size", 32),
        )

    def resolve_embedding_space(
        self,
        *,
        activate: bool = False,
        embedding_service: EmbeddingService | None = None,
        knowledge_base_id: str | None = None,
    ) -> EmbeddingSpace:
        embedding_service = embedding_service or self.embeddings
        descriptor = embedding_service.describe()
        profile_code = str(descriptor.get("profile_code") or "default")
        embedding_spaces_repo = getattr(self, "embedding_spaces", None)
        if embedding_spaces_repo is None:
            return EmbeddingSpace(
                embedding_space_id=str(uuid4()),
                code=profile_code,
                provider_name=str(
                    descriptor.get("provider_name")
                    or getattr(embedding_service, "provider_name", "unknown")
                ),
                model_id=str(
                    descriptor.get("model_id")
                    or getattr(getattr(embedding_service, "profile", None), "model_id", "unknown")
                ),
                dimensions=self._coerce_int(
                    descriptor.get("dimensions")
                    or getattr(
                        getattr(embedding_service, "profile", None),
                        "dimensions",
                        0,
                    )
                    or 0
                ),
                distance_metric="cosine",
                query_template=str(descriptor.get("query_prefix") or "") or None,
                document_template=str(descriptor.get("document_prefix") or "") or None,
                normalize_l2=bool(descriptor.get("normalize_l2", True)),
                truncate_dim=self._coerce_optional_int(descriptor.get("truncate_dim")),
                is_active=activate,
            )
        space = embedding_spaces_repo.get_by_code(profile_code)
        if space is None:
            if activate:
                current_active = self.embedding_spaces.get_active()
                if current_active is not None and str(current_active.code) != profile_code:
                    current_active.is_active = False
                    self.session.add(current_active)
            space = EmbeddingSpace(
                code=profile_code,
                provider_name=str(
                    descriptor.get("provider_name") or embedding_service.provider_name
                ),
                model_id=str(descriptor.get("model_id") or embedding_service.profile.model_id),
                dimensions=self._coerce_int(
                    descriptor.get("dimensions") or embedding_service.profile.dimensions
                ),
                distance_metric="cosine",
                query_template=str(descriptor.get("query_prefix") or "") or None,
                document_template=str(descriptor.get("document_prefix") or "") or None,
                normalize_l2=bool(descriptor.get("normalize_l2", True)),
                truncate_dim=self._coerce_optional_int(descriptor.get("truncate_dim")),
                is_active=activate,
            )
            try:
                with self.session.begin_nested():
                    self.embedding_spaces.add(space)
                    self.session.flush()
            except IntegrityError:
                space = embedding_spaces_repo.get_by_code(profile_code)
                if space is None:
                    raise
        else:
            changed = False
            if space.provider_name != str(
                descriptor.get("provider_name") or embedding_service.provider_name
            ):
                space.provider_name = str(
                    descriptor.get("provider_name") or embedding_service.provider_name
                )
                changed = True
            if space.model_id != str(
                descriptor.get("model_id") or embedding_service.profile.model_id
            ):
                space.model_id = str(
                    descriptor.get("model_id") or embedding_service.profile.model_id
                )
                changed = True
            target_dimensions = self._coerce_int(
                descriptor.get("dimensions") or embedding_service.profile.dimensions
            )
            if int(space.dimensions) != target_dimensions:
                space.dimensions = target_dimensions
                changed = True
            target_truncate_dim = self._coerce_optional_int(descriptor.get("truncate_dim"))
            if getattr(space, "truncate_dim", None) != target_truncate_dim:
                space.truncate_dim = target_truncate_dim
                changed = True
            if (space.query_template or None) != (
                str(descriptor.get("query_prefix") or "") or None
            ):
                space.query_template = str(descriptor.get("query_prefix") or "") or None
                changed = True
            if (space.document_template or None) != (
                str(descriptor.get("document_prefix") or "") or None
            ):
                space.document_template = str(descriptor.get("document_prefix") or "") or None
                changed = True
            if bool(space.normalize_l2) != bool(descriptor.get("normalize_l2", True)):
                space.normalize_l2 = bool(descriptor.get("normalize_l2", True))
                changed = True
            target_active = bool(activate)
            if target_active and not bool(space.is_active):
                current_active = self.embedding_spaces.get_active()
                if current_active is not None and str(current_active.embedding_space_id) != str(
                    space.embedding_space_id
                ):
                    current_active.is_active = False
                    self.session.add(current_active)
                space.is_active = True
                changed = True
            elif not target_active and bool(space.is_active) and knowledge_base_id is None:
                pass
            if changed:
                self.session.add(space)
                self.session.flush()

        if knowledge_base_id:
            base = self.session.get(KnowledgeBase, knowledge_base_id)
            if base is not None and str(
                getattr(base, "preferred_embedding_space_id", "") or ""
            ) != str(space.embedding_space_id):
                base.preferred_embedding_space_id = space.embedding_space_id
                self.session.add(base)
                self.session.flush()
        return space

    def _ensure_within_sla(self, started: datetime, *, stage: str) -> None:
        limit_sec = int(getattr(self.settings, "knowledge_sync_sla_seconds", 3600) or 3600)
        elapsed_sec = int((datetime.now(UTC) - started).total_seconds())
        if elapsed_sec > limit_sec:
            raise ValidationError(
                "Knowledge update run exceeded the configured SLA budget",
                error_code="KNOWLEDGE_SYNC_SLA_EXCEEDED",
                details={"stage": stage, "elapsed_sec": elapsed_sec, "target_sec": limit_sec},
            )

    def _resolve_execute_inline(self, requested_inline: bool | None) -> bool:
        if requested_inline is not None:
            return bool(requested_inline)
        return bool(self._settings_value("knowledge_execute_inline", False))

    def build_public_start_payload(
        self,
        payload: KnowledgeUpdateRunStartRequest,
        principal: AuthPrincipal,
    ) -> InternalKnowledgeUpdateRunStartRequest:
        requested_by = payload.requested_by or principal_requested_by(principal)
        execute_inline = getattr(payload, "execute_inline", None)
        if execute_inline is None:
            execute_inline = getattr(payload, "execute_update_inline", None)
        return InternalKnowledgeUpdateRunStartRequest(
            knowledge_base_id=payload.knowledge_base_id,
            run_type=payload.run_type,
            source_scope=payload.source_scope,
            selected_source_ids=payload.selected_source_ids,
            document_ids=payload.document_ids,
            removed_document_ids=payload.removed_document_ids,
            force_reindex_all_in_scope=payload.force_reindex_all_in_scope,
            force_reindex_document_ids=payload.force_reindex_document_ids,
            target_embedding_profile=payload.target_embedding_profile,
            reason=payload.reason,
            requested_by=requested_by,
            correlation_id=payload.idempotency_key
            or f"knowledge-update-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            idempotency_key=payload.idempotency_key,
            execute_inline=self._resolve_execute_inline(execute_inline),
            auto_activate_if_validated=False,
        )

    def start_run(
        self,
        payload: InternalKnowledgeUpdateRunStartRequest,
        principal: AuthPrincipal | None = None,
    ) -> RunStartResult:
        run = self._call_create_run(
            payload=payload,
            initiator_user_id=principal_actor_id(principal),
            principal=principal,
            audit_message="Knowledge update run created",
            execute_inline=self._resolve_execute_inline(payload.execute_inline),
        )
        return self._result_from_run(run)

    def start_manual_run(
        self,
        *,
        knowledge_base_id: str | None = None,
        source_scope: SourceScope = SourceScope.ALL,
        selected_source_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        force_reindex_all_in_scope: bool = False,
        force_reindex_document_ids: list[str] | None = None,
        target_embedding_profile: str | None = None,
        correlation_id: str | None = None,
        reason: str | None = None,
        requested_by: str | None = None,
        execute_inline: bool | None = None,
        auto_activate_if_validated: bool = False,
        run_type: UpdateRunType = UpdateRunType.MANUAL,
        principal: AuthPrincipal | None = None,
    ) -> RunStartResult:
        payload = InternalKnowledgeUpdateRunStartRequest(
            knowledge_base_id=knowledge_base_id,
            run_type=run_type,
            source_scope=source_scope,
            selected_source_ids=selected_source_ids or [],
            document_ids=document_ids or [],
            force_reindex_all_in_scope=force_reindex_all_in_scope,
            force_reindex_document_ids=force_reindex_document_ids or [],
            target_embedding_profile=target_embedding_profile,
            reason=reason or "manual_knowledge_update",
            requested_by=requested_by or principal_requested_by(principal),
            correlation_id=correlation_id,
            idempotency_key=None,
            execute_inline=execute_inline,
            auto_activate_if_validated=auto_activate_if_validated,
        )
        return self._result_from_run(
            self._call_create_run(
                payload=payload,
                initiator_user_id=principal_actor_id(principal),
                principal=principal,
                audit_message="Knowledge update run created",
                execute_inline=self._resolve_execute_inline(execute_inline),
            )
        )

    def _call_create_run(
        self,
        *,
        payload: InternalKnowledgeUpdateRunStartRequest,
        initiator_user_id: str | None,
        principal: AuthPrincipal | None,
        audit_message: str,
        execute_inline: bool | None,
    ) -> KnowledgeUpdateRun:
        try:
            return self._create_run(
                payload=payload,
                initiator_user_id=initiator_user_id,
                principal=principal,
                audit_message=audit_message,
                execute_inline=execute_inline,
            )
        except TypeError as exc:
            if "principal" not in str(exc):
                raise
            return self._create_run(
                payload=payload,
                initiator_user_id=initiator_user_id,
                audit_message=audit_message,
                execute_inline=execute_inline,
            )

    def _create_run(
        self,
        *,
        payload: InternalKnowledgeUpdateRunStartRequest,
        initiator_user_id: str | None,
        principal: AuthPrincipal | None = None,
        audit_message: str = "Knowledge update run created",
        execute_inline: bool | None = None,
    ) -> KnowledgeUpdateRun:
        if payload.knowledge_base_id:
            base = self._get_base(str(payload.knowledge_base_id), principal)
        else:
            self._ensure_system_bases(principal)
            base_service = self._make_base_service()
            scope_getter = getattr(base_service, "get_existing_effective_scope", None)
            scope = scope_getter(principal) if callable(scope_getter) else None
            base = getattr(scope, "selected_user_base", None)
            if base is None:
                raise ValidationError(
                    "knowledge_base_id is required when no knowledge base is selected",
                    error_code="KNOWLEDGE_BASE_REQUIRED",
                )
        request_payload = {
            "knowledge_base_id": str(base.knowledge_base_id),
            "run_type": payload.run_type.value,
            "source_scope": payload.source_scope.value,
            "selected_source_ids": sorted(str(item) for item in payload.selected_source_ids),
            "document_ids": sorted(str(item) for item in payload.document_ids),
            "removed_document_ids": sorted(str(item) for item in payload.removed_document_ids),
            "force_reindex_all_in_scope": bool(payload.force_reindex_all_in_scope),
            "force_reindex_document_ids": sorted(
                str(item) for item in payload.force_reindex_document_ids
            ),
            "target_embedding_profile": payload.target_embedding_profile,
            "reason": payload.reason,
            "auto_activate_if_validated": bool(payload.auto_activate_if_validated),
        }
        existing = self.idempotency.resolve_existing(
            actor_user_id=initiator_user_id,
            operation_name="knowledge.update.start",
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
        )
        if existing is not None:
            return self.get_run(existing.target_id)
        running = self._get_running_run_with_recovery(knowledge_base_id=str(base.knowledge_base_id))
        if running is not None:
            raise ConflictError(
                "Another knowledge update run is already active",
                error_code="KNOWLEDGE_UPDATE_ALREADY_RUNNING",
            )
        selected_sources = self._resolve_scope_sources(
            payload.source_scope,
            payload.selected_source_ids,
            knowledge_base_id=str(base.knowledge_base_id),
            allow_archived_selected=_is_delete_run_type(payload.run_type),
        )
        if not selected_sources:
            raise ValidationError(
                "No active knowledge sources available", error_code="NO_ACTIVE_SOURCE_SET"
            )
        run = KnowledgeUpdateRun(
            knowledge_base_id=base.knowledge_base_id,
            run_type=payload.run_type,
            initiator_user_id=initiator_user_id,
            status=KnowledgeUpdateStatus.QUEUED,
            current_stage="queued",
            scope={
                "knowledge_base_id": str(base.knowledge_base_id),
                "source_scope": payload.source_scope.value,
                "selected_source_ids": [str(source.source_id) for source in selected_sources],
                "document_ids": [str(item) for item in payload.document_ids],
                "removed_document_ids": [str(item) for item in payload.removed_document_ids],
                "force_reindex_all_in_scope": bool(payload.force_reindex_all_in_scope),
                "force_reindex_document_ids": [
                    str(item) for item in payload.force_reindex_document_ids
                ],
                "target_embedding_profile": payload.target_embedding_profile,
                "source_count": len(selected_sources),
                "reason": payload.reason,
                "requested_by": payload.requested_by,
                "auto_activate_if_validated": bool(payload.auto_activate_if_validated),
                "force_async": execute_inline is False,
            },
            correlation_id=payload.correlation_id,
            summary={
                "problem_sources": [],
                "quality_summary": {"status": "queued", "source_count": len(selected_sources)},
                "stage_history": [
                    self._stage_event("queued", detail="Knowledge update request accepted")
                ],
            },
        )
        self.update_runs.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            self.session.expire_all()
            running = self._get_running_run_with_recovery(
                knowledge_base_id=str(base.knowledge_base_id)
            )
            if running is not None:
                raise ConflictError(
                    "Another knowledge update run is already active",
                    error_code="KNOWLEDGE_UPDATE_ALREADY_RUNNING",
                ) from exc
            raise
        self.operations.record_step(
            operation_kind="knowledge_update_run",
            operation_id=str(run.update_run_id),
            step_code="queued",
            title="Поставлено в очередь",
            status="queued",
            correlation_id=payload.correlation_id,
            actor_user_id=initiator_user_id,
            detail="Knowledge update request accepted",
            payload={
                "source_scope": payload.source_scope.value,
                "selected_source_ids": request_payload["selected_source_ids"],
                "document_ids": request_payload["document_ids"],
                "target_embedding_profile": payload.target_embedding_profile,
                "force_reindex_all_in_scope": bool(payload.force_reindex_all_in_scope),
            },
        )
        self.idempotency.register(
            actor_user_id=initiator_user_id,
            operation_name="knowledge.update.start",
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            target_type="knowledge_update_run",
            target_id=str(run.update_run_id),
            correlation_id=payload.correlation_id,
        )
        candidate = self._create_candidate_version(run, selected_sources)
        run.summary = {
            "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
            "problem_sources": [],
            "quality_summary": {"status": "queued", "source_count": len(selected_sources)},
            "source_snapshot": candidate.source_snapshot,
            "activation_metadata": None,
            "stage_history": (run.summary or {}).get("stage_history", []),
        }
        self.session.add(run)
        self.audit.record(
            event_type="knowledge.refresh.started",
            target_type="knowledge_update_run",
            target_id=run.update_run_id,
            message=audit_message,
            actor_user_id=initiator_user_id,
            correlation_id=payload.correlation_id,
            payload={
                **(run.scope or {}),
                "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
            },
        )
        self.session.commit()

        def _run_inline() -> KnowledgeUpdateRun:
            return self.execute_run(str(run.update_run_id))

        def _queue_run() -> KnowledgeUpdateRun:
            from app.tasks.jobs.knowledge import run_knowledge_update

            run_knowledge_update.delay(str(run.update_run_id))
            return run

        def _handle_queue_failure(exc: Exception) -> KnowledgeUpdateRun:
            self.session.rollback()
            failed_run = self.get_run(str(run.update_run_id))
            failed_candidate = self.versions.get_by_update_run_id(failed_run.update_run_id)
            finished_at = datetime.now(UTC)
            failed_run.status = KnowledgeUpdateStatus.FAILED
            failed_run.current_stage = "failed"
            failed_run.finished_at = finished_at
            failed_run.duration_sec = int(
                max(0.0, (finished_at - (failed_run.started_at or finished_at)).total_seconds())
            )
            summary = dict(failed_run.summary or {})
            summary["error"] = str(exc)
            summary["error_code"] = getattr(
                exc, "error_code", "KNOWLEDGE_UPDATE_QUEUE_DISPATCH_ERROR"
            )
            summary["stage_history"] = self._append_stage_history(
                summary.get("stage_history", []),
                "failed",
                detail=str(exc),
                stage_status="failed",
            )
            quality_summary = dict(summary.get("quality_summary") or {})
            quality_summary.update(
                {
                    "status": "failed",
                    "processing_error_count": max(
                        1, int(quality_summary.get("processing_error_count") or 0)
                    ),
                    "processing_errors": list(quality_summary.get("processing_errors") or [])
                    + [
                        {
                            "stage": "queue_dispatch",
                            "error_code": getattr(
                                exc, "error_code", "KNOWLEDGE_UPDATE_QUEUE_DISPATCH_ERROR"
                            ),
                            "error_message": str(exc),
                        }
                    ],
                }
            )
            summary["quality_summary"] = quality_summary
            if failed_candidate is not None:
                failed_candidate.status = KnowledgeVersionStatus.FAILED
                failed_candidate.summary = {
                    **(failed_candidate.summary or {}),
                    "error": str(exc),
                    "error_code": getattr(
                        exc, "error_code", "KNOWLEDGE_UPDATE_QUEUE_DISPATCH_ERROR"
                    ),
                }
                summary["candidate_knowledge_version_id"] = str(
                    failed_candidate.knowledge_version_id
                )
                self.session.add(failed_candidate)
            failed_run.summary = summary
            self._record_operation_step(
                failed_run,
                stage="failed",
                status="failed",
                detail=str(exc),
                error_code=getattr(exc, "error_code", "KNOWLEDGE_UPDATE_QUEUE_DISPATCH_ERROR"),
                payload={"dispatch": "queue"},
            )
            self.session.add(failed_run)
            self.audit.record(
                event_type="knowledge.refresh.failed",
                target_type="knowledge_update_run",
                target_id=failed_run.update_run_id,
                message="Knowledge update queue dispatch failed",
                actor_user_id=failed_run.initiator_user_id,
                correlation_id=failed_run.correlation_id,
                payload=failed_run.summary,
                severity=AuditSeverity.ERROR,
            )
            self.session.commit()
            with suppress(Exception):
                self.session.refresh(failed_run)
            return failed_run

        if execute_inline is not False and self._should_force_inline_without_worker():
            return _run_inline()

        return dispatch_run(
            settings=self.settings,
            requested_inline=execute_inline,
            inline_executor=_run_inline,
            queue_dispatcher=_queue_run,
            queue_failure_handler=_handle_queue_failure,
        )

    def get_run(
        self, update_run_id: str, principal: AuthPrincipal | None = None
    ) -> KnowledgeUpdateRun:
        run = self.update_runs.get(update_run_id)
        if run is None:
            raise NotFoundError("KnowledgeUpdateRun", update_run_id)
        if principal is not None:
            self._get_base(str(run.knowledge_base_id), principal)
        return run

    def get_run_response(
        self, update_run_id: str, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        run = self.get_run(update_run_id, principal)
        run = self._maybe_resume_queued_run_inline(run)
        return self._serialize_run(run)

    def _list_visible_recent_runs(
        self,
        *,
        limit: int,
        status: KnowledgeUpdateStatus | None = None,
        knowledge_base_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> list[KnowledgeUpdateRun]:
        batch_size = max(limit, 50)
        offset = 0
        visible: list[KnowledgeUpdateRun] = []
        while len(visible) < limit:
            try:
                page = self.update_runs.list_recent(
                    limit=batch_size,
                    offset=offset,
                    status=status,
                    knowledge_base_id=knowledge_base_id,
                )
            except TypeError:
                if offset:
                    break
                page = self.update_runs.list_recent(
                    limit=batch_size, status=status, knowledge_base_id=knowledge_base_id
                )
            if not page:
                break
            for run in page:
                if principal is not None:
                    try:
                        self._get_base(str(run.knowledge_base_id), principal)
                    except Exception:
                        continue
                visible.append(run)
                if len(visible) >= limit:
                    break
            offset += len(page)
            if len(page) < batch_size:
                break
        return visible

    def list_run_responses(
        self,
        *,
        limit: int = 20,
        status: KnowledgeUpdateStatus | None = None,
        knowledge_base_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> list[dict[str, Any]]:
        if principal is None:
            items = self.update_runs.list_recent(
                limit=limit, status=status, knowledge_base_id=knowledge_base_id
            )
        else:
            items = self._list_visible_recent_runs(
                limit=limit, status=status, knowledge_base_id=knowledge_base_id, principal=principal
            )
        return [self._serialize_run(self._maybe_resume_queued_run_inline(run)) for run in items]

    def get_run_status_payload(
        self, update_run_id: str, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        run = self.get_run(update_run_id, principal)
        run = self._maybe_resume_queued_run_inline(run)
        payload = self._serialize_run(run)
        candidate = self.versions.get_by_update_run_id(run.update_run_id)
        if candidate is not None:
            payload["source_snapshot"] = candidate.source_snapshot
            return payload
        selected_sources = self._resolve_scope_sources(
            SourceScope((run.scope or {}).get("source_scope", SourceScope.ALL.value)),
            (run.scope or {}).get("selected_source_ids") or [],
            knowledge_base_id=str(run.knowledge_base_id),
            allow_archived_selected=_is_delete_run_type(run.run_type),
        )
        payload["source_snapshot"] = self._build_source_snapshot(
            selected_sources, run, include_processing=False
        )
        return payload

    def list_notifications(
        self,
        *,
        limit: int = 20,
        knowledge_base_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> list[dict[str, Any]]:
        base_lookup = {
            str(base.knowledge_base_id): base for base in self._list_visible_bases(principal)
        }
        items: list[dict[str, Any]] = []
        for run in self._list_visible_recent_runs(
            limit=limit, knowledge_base_id=knowledge_base_id, principal=principal
        ):
            base = base_lookup.get(str(run.knowledge_base_id))
            if base is None:
                continue
            summary = dict(run.summary or {})
            quality = dict(summary.get("quality_summary") or {})
            status_value = getattr(run.status, "value", run.status)
            activated_version_id = summary.get("activated_knowledge_version_id")
            candidate_version_id = summary.get("candidate_knowledge_version_id")
            if status_value == "completed":
                title = "База знаний обновлена"
                if activated_version_id:
                    message = f"Создана и активирована версия {activated_version_id}."
                else:
                    message = "Синхронизация завершена успешно."
                tone = "success"
            elif status_value == "completed_with_warnings":
                title = "Обновление базы знаний завершилось с замечаниями"
                message = f"Есть предупреждения или частичные ошибки: {int(quality.get('processing_error_count') or 0)}."
                tone = "warning"
            elif status_value == "failed":
                title = "Обновление базы знаний завершилось ошибкой"
                error_code = (
                    summary.get("error_code")
                    or quality.get("error_code")
                    or "KNOWLEDGE_UPDATE_FAILED"
                )
                validation_report = quality.get("validation_report") or {}
                reason = (
                    validation_report.get("reason") or summary.get("error") or quality.get("error")
                )
                if reason:
                    message = f"Синхронизация не завершилась: {reason}. Код: {error_code}."
                else:
                    message = f"Синхронизация не завершилась. Код: {error_code}."
                tone = "danger"
            else:
                title = "Обновление базы знаний запущено"
                message = "Система обрабатывает источник и собирает новую версию базы."
                tone = "info"
            items.append(
                {
                    "notification_id": f"knowledge-run:{run.update_run_id}",
                    "knowledge_base_id": str(run.knowledge_base_id),
                    "knowledge_base_name": getattr(base, "name", str(run.knowledge_base_id)),
                    "update_run_id": str(run.update_run_id),
                    "knowledge_version_id": activated_version_id or candidate_version_id,
                    "title": title,
                    "message": message,
                    "tone": tone,
                    "status": run.status,
                    "created_at": run.finished_at or run.started_at,
                }
            )
        return items

    def _record_operation_step(
        self,
        run: KnowledgeUpdateRun,
        *,
        stage: str,
        status: str,
        detail: str | None = None,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        titles = {
            "queued": "Поставлено в очередь",
            "loading": "Загрузка источников",
            "parsing": "Обработка документов",
            "validating": "Валидация версии знаний",
            "validated": "Версия знаний validated",
            "active": "Версия знаний active",
            "failed": "Обновление завершилось ошибкой",
            "completed": "Версия знаний подготовлена",
        }
        record_operation_step(
            self.operations,
            operation_kind="knowledge_update_run",
            operation_id=str(run.update_run_id),
            step_code=stage,
            title=titles.get(stage, stage.replace("_", " ").strip().title()),
            status=status,
            correlation_id=run.correlation_id,
            actor_user_id=str(run.initiator_user_id) if run.initiator_user_id is not None else None,
            detail=detail,
            error_code=error_code,
            payload=payload,
        )

    @staticmethod
    def _doc_signature(
        version: KnowledgeVersion | None,
    ) -> set[tuple[str, str | None, str | None, bool]]:
        return build_version_document_signature(version)

    def _build_version_diff_summary(
        self, version: KnowledgeVersion, active: KnowledgeVersion | None
    ) -> dict[str, Any] | None:
        if active is None or str(active.knowledge_version_id) == str(version.knowledge_version_id):
            return None
        active_full = (
            active
            if getattr(active, "version_documents", None)
            else self.versions.get_with_documents(str(active.knowledge_version_id))
        )
        version_full = (
            version
            if getattr(version, "version_documents", None)
            else self.versions.get_with_documents(str(version.knowledge_version_id))
        )
        return build_version_diff_summary(version_full, active_full)

    def _build_active_diff_summary(
        self, candidate: KnowledgeVersion | None
    ) -> dict[str, Any] | None:
        if candidate is None:
            return None
        active = self.versions.get_active(knowledge_base_id=candidate.knowledge_base_id, eager=True)
        return self._build_version_diff_summary(candidate, active)

    def execute_run(self, update_run_id: str) -> KnowledgeUpdateRun:
        return execute_knowledge_update_run(self, update_run_id)

    def _record_document_delta(
        self,
        run: KnowledgeUpdateRun,
        candidate: KnowledgeVersion,
        document: SourceDocument,
        *,
        source_id: str | None,
        delta_kind: DocumentDeltaKind,
        checksum_before: str | None,
        checksum_after: str | None,
        details: dict[str, Any] | None,
    ) -> None:
        source = getattr(document, "source", None)
        registered_at = getattr(document, "registered_at", None)
        discovered_at = getattr(document, "discovered_at", None)
        history_details = {
            "title": getattr(document, "title", None),
            "document_type": getattr(
                getattr(document, "document_type", None),
                "value",
                getattr(document, "document_type", None),
            ),
            "version_label": getattr(document, "version_label", None),
            "document_status": getattr(
                getattr(document, "status", None), "value", getattr(document, "status", None)
            ),
            "registered_at": registered_at.isoformat()
            if isinstance(registered_at, datetime)
            else None,
            "discovered_at": discovered_at.isoformat()
            if isinstance(discovered_at, datetime)
            else None,
            "source_name": getattr(source, "name", None),
            "source_type": getattr(
                _public_source_type(getattr(source, "source_type", None)),
                "value",
                _public_source_type(getattr(source, "source_type", None)),
            )
            if source is not None
            else None,
        }
        self.document_deltas.add(
            DocumentDelta(
                update_run_id=run.update_run_id,
                knowledge_base_id=candidate.knowledge_base_id,
                knowledge_version_id=candidate.knowledge_version_id,
                source_id=source_id,
                document_id=document.document_id
                if getattr(document, "document_id", None) is not None
                else None,
                delta_kind=delta_kind,
                uri=document.uri,
                checksum_before=checksum_before,
                checksum_after=checksum_after,
                details={**history_details, **(details or {})},
            )
        )
        self.session.flush()

    def _clone_document_artifacts(
        self,
        candidate: KnowledgeVersion,
        document: SourceDocument,
        previous_version_document: KnowledgeVersionDocument | None,
        active_snapshot: DocumentSnapshot,
        *,
        source_document_id: str | None = None,
        reuse_mode: str = "cloned_from_previous_version",
    ) -> None:
        role_code = (
            previous_version_document.role_code
            if previous_version_document is not None
            else resolve_basis_assignment(document)[0]
        )
        required_flag = (
            previous_version_document.required_flag
            if previous_version_document is not None
            else resolve_basis_assignment(document)[1]
        )
        candidate.version_documents.append(
            KnowledgeVersionDocument(
                knowledge_version_id=candidate.knowledge_version_id,
                document_id=document.document_id,
                role_code=role_code,
                required_flag=required_flag,
            )
        )
        origin_document_id = str(
            source_document_id or active_snapshot.document_id or document.document_id
        )
        snapshot = DocumentSnapshot(
            knowledge_version_id=candidate.knowledge_version_id,
            document_id=document.document_id,
            checksum=active_snapshot.checksum,
            content_format=active_snapshot.content_format,
            parser_name=active_snapshot.parser_name,
            normalized_text=active_snapshot.normalized_text,
            structure_metadata={
                **(active_snapshot.structure_metadata or {}),
                "reuse_mode": reuse_mode,
                "cloned_from_version_id": str(active_snapshot.knowledge_version_id),
                "source_document_id": origin_document_id,
            },
        )
        self.session.add(snapshot)
        self.session.flush()
        old_to_new_chunk_ids: dict[str, str] = {}
        old_chunks = self.document_chunks.list_for_snapshot(active_snapshot.document_snapshot_id)
        for old_chunk in old_chunks:
            cloned_chunk = DocumentChunk(
                document_snapshot_id=snapshot.document_snapshot_id,
                knowledge_version_id=candidate.knowledge_version_id,
                document_id=document.document_id,
                chunk_index=old_chunk.chunk_index,
                title=old_chunk.title,
                source_location=old_chunk.source_location,
                content=old_chunk.content,
                start_offset=old_chunk.start_offset,
                end_offset=old_chunk.end_offset,
                chunk_metadata=old_chunk.chunk_metadata,
            )
            self.session.add(cloned_chunk)
            self.session.flush()
            old_to_new_chunk_ids[str(old_chunk.document_chunk_id)] = str(
                cloned_chunk.document_chunk_id
            )
        fragment_rows = list(
            self.session.scalars(
                select(KnowledgeFragment)
                .where(
                    KnowledgeFragment.knowledge_version_id == active_snapshot.knowledge_version_id,
                    KnowledgeFragment.document_id == origin_document_id,
                )
                .options(selectinload(KnowledgeFragment.fragment_embeddings))
            )
        )
        for fragment_row in fragment_rows:
            cloned_fragment = KnowledgeFragment(
                knowledge_version_id=candidate.knowledge_version_id,
                document_id=document.document_id,
                fragment_type=fragment_row.fragment_type,
                title=fragment_row.title,
                content=fragment_row.content,
                source_location=fragment_row.source_location,
                fragment_metadata=fragment_row.fragment_metadata,
                embedding_key=fragment_row.embedding_key,
                embedding=fragment_row.embedding,
                status=fragment_row.status,
            )
            candidate.knowledge_fragments.append(cloned_fragment)
            self.session.flush()
            for embedding_row in fragment_row.fragment_embeddings or []:
                cloned_fragment.fragment_embeddings.append(
                    KnowledgeFragmentEmbedding(
                        fragment_id=cloned_fragment.fragment_id,
                        embedding_space_id=embedding_row.embedding_space_id,
                        embedding_key=embedding_row.embedding_key,
                        embedding=list(embedding_row.embedding)
                        if embedding_row.embedding is not None
                        else None,
                    )
                )
        for rule_row in list(
            self.session.scalars(
                select(NormativeRule).where(
                    NormativeRule.knowledge_version_id == active_snapshot.knowledge_version_id,
                    NormativeRule.document_id == origin_document_id,
                )
            )
        ):
            candidate.normative_rules.append(
                NormativeRule(
                    knowledge_version_id=candidate.knowledge_version_id,
                    document_id=document.document_id,
                    rule_code=rule_row.rule_code,
                    rule_name=rule_row.rule_name,
                    rule_text=rule_row.rule_text,
                    rule_category=rule_row.rule_category,
                    applicability_condition=rule_row.applicability_condition,
                    severity_default=rule_row.severity_default,
                    status=rule_row.status,
                )
            )
        for extracted_item in self.extracted_items.list_for_document(
            origin_document_id, knowledge_version_id=str(active_snapshot.knowledge_version_id)
        ):
            candidate.extracted_items.append(
                DocumentExtractedItem(
                    knowledge_version_id=candidate.knowledge_version_id,
                    document_id=document.document_id,
                    document_chunk_id=old_to_new_chunk_ids.get(
                        str(extracted_item.document_chunk_id)
                    )
                    if extracted_item.document_chunk_id
                    else None,
                    item_type=extracted_item.item_type,
                    title=extracted_item.title,
                    content=extracted_item.content,
                    normalized_value=extracted_item.normalized_value,
                    source_location=_fit_source_location(extracted_item.source_location),
                    confidence_score=extracted_item.confidence_score,
                    quality_status=extracted_item.quality_status,
                    evidence_quote=extracted_item.evidence_quote,
                    structured_payload=extracted_item.structured_payload,
                )
            )

    def _attach_document_memory(
        self,
        candidate: KnowledgeVersion,
        *,
        document: SourceDocument,
        normalized_text: str,
        chunk_entities: list[DocumentChunk],
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        llm_config = DocumentMemoryLlmConfig.from_settings(getattr(self, "settings", None))
        llm_skipped_reason = self._document_memory_llm_skip_reason(
            document=document,
            normalized_text=normalized_text,
            chunk_count=len(chunk_entities),
            llm_config=llm_config,
        )
        if llm_skipped_reason:
            llm_config = None
        memory = extract_document_memory(
            document_title=document.title,
            document_type=document.document_type,
            normalized_text=normalized_text,
            chunks=[
                {
                    "document_chunk_id": str(chunk.document_chunk_id),
                    "title": chunk.title,
                    "content": chunk.content,
                    "source_location": chunk.source_location,
                }
                for chunk in chunk_entities
            ],
            llm_config=llm_config,
            progress_callback=progress_callback,
        )
        by_source_location = {
            str(chunk.source_location): chunk for chunk in chunk_entities if chunk.source_location
        }
        for memory_item in memory.items:
            structured_payload = dict(memory_item.structured_payload or {})
            structured_payload.setdefault("llm_attempted", memory.llm_attempted)
            structured_payload.setdefault("fallback_applied", memory.fallback_applied)
            if memory.fallback_reason:
                structured_payload.setdefault("fallback_reason", memory.fallback_reason)
            if llm_skipped_reason:
                structured_payload.setdefault("llm_skipped_reason", llm_skipped_reason)
            raw_source_location = memory_item.source_location
            source_location = _fit_source_location(raw_source_location)
            if raw_source_location and source_location != raw_source_location:
                structured_payload.setdefault("source_location_full", raw_source_location)
            source_chunk = (
                by_source_location.get(str(raw_source_location))
                if raw_source_location
                else None
            )
            candidate.extracted_items.append(
                DocumentExtractedItem(
                    knowledge_version_id=candidate.knowledge_version_id,
                    document_id=document.document_id,
                    document_chunk_id=(
                        source_chunk.document_chunk_id if source_chunk is not None else None
                    ),
                    item_type=memory_item.item_type,
                    title=memory_item.title,
                    content=memory_item.content,
                    normalized_value=memory_item.normalized_value,
                    source_location=source_location,
                    confidence_score=memory_item.confidence_score,
                    quality_status=memory_item.quality_status,
                    evidence_quote=memory_item.evidence_quote,
                    structured_payload=structured_payload,
                )
            )
        return {
            "item_count": len(memory.items),
            "extraction_method": memory.extraction_method,
            "llm_attempted": memory.llm_attempted,
            "llm_skipped": bool(llm_skipped_reason),
            "fallback_applied": memory.fallback_applied,
            "fallback_reason": memory.fallback_reason or llm_skipped_reason,
        }

    def _document_memory_llm_skip_reason(
        self,
        *,
        document: SourceDocument,
        normalized_text: str,
        chunk_count: int,
        llm_config: DocumentMemoryLlmConfig | None,
    ) -> str | None:
        if llm_config is None or not llm_config.is_available():
            return None
        settings = getattr(self, "settings", None)
        threshold_raw = (
            getattr(settings, "knowledge_large_document_threshold_bytes", 1_048_576)
            if settings is not None
            else 1_048_576
        )
        max_chunks_raw = (
            getattr(settings, "knowledge_llm_extraction_max_chunks", 48)
            if settings is not None
            else 48
        )
        threshold_bytes = int(threshold_raw or 0)
        max_chunks = int(max_chunks_raw or 0)
        document_size_bytes = int(getattr(document, "size_bytes", 0) or 0)
        text_size_bytes = len((normalized_text or "").encode("utf-8"))
        if threshold_bytes > 0 and document_size_bytes >= threshold_bytes:
            return (
                "large_document_file_size:"
                f"{document_size_bytes}>={threshold_bytes}"
            )
        if threshold_bytes > 0 and text_size_bytes >= threshold_bytes:
            return f"large_document_text_size:{text_size_bytes}>={threshold_bytes}"
        if max_chunks > 0 and chunk_count > max_chunks:
            return f"chunk_count:{chunk_count}>{max_chunks}"
        return None

    @staticmethod
    def _classify_document_error_code(message: str, *, default: str) -> str:
        return classify_document_error_code(message, default=default)

    def _ensure_scheduled_sync_execution_allowed(self, principal: AuthPrincipal | None) -> None:
        if principal is None:
            return
        if principal.account_type == AccountType.SERVICE:
            return
        settings = getattr(self, "settings", None) or get_settings()
        if settings.is_local_env() or settings.is_local_noauth():
            return
        allowed_roles = settings.normalized_mvp_global_role_codes() or {"ADMIN", "MVP_ADMIN"}
        if principal.has_any_role(set(allowed_roles)):
            return
        raise AuthorizationError("Scheduled sync execution is restricted outside local runtime")

    def run_due_scheduled_syncs(
        self,
        *,
        now: datetime | None = None,
        execute_inline: bool | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        self._ensure_scheduled_sync_execution_allowed(principal)
        reference_time = now or datetime.now(UTC)
        due_runs: list[KnowledgeUpdateRun | dict[str, Any]] = []
        skipped: list[str] = []
        skipped_details: dict[str, str] = {}
        for base in self._list_visible_bases(principal):
            base_id = str(base.knowledge_base_id)
            if getattr(base.status, "value", base.status) == "archived":
                skipped.append(base_id)
                skipped_details[base_id] = "archived"
                continue
            active_sources = [
                item
                for item in self.sources.list_active(knowledge_base_id=base.knowledge_base_id)
                if _uses_auto_sync(getattr(item, "refresh_policy", None))
            ]
            if not active_sources:
                skipped.append(base_id)
                skipped_details[base_id] = "no_auto_sync_sources"
                continue
            due_sources: list[KnowledgeSource] = []
            processing_repo = getattr(self, "processing_results", None)
            latest_finished = (
                self.update_runs.get_latest_finished(knowledge_base_id=base.knowledge_base_id)
                if hasattr(self, "update_runs")
                else None
            )
            for source in active_sources:
                interval_days = _schedule_interval_days(
                    getattr(source, "refresh_policy", None),
                    int(self._settings_value("knowledge_auto_sync_interval_days", 30) or 30),
                )
                latest_success = None
                source_id = getattr(source, "source_id", None)
                if (
                    processing_repo
                    and hasattr(processing_repo, "get_latest_success_for_source")
                    and source_id is not None
                ):
                    latest_success = processing_repo.get_latest_success_for_source(source_id)
                last_discovered_at = getattr(source, "last_discovered_at", None)
                if latest_success is not None or last_discovered_at is not None:
                    anchor = getattr(latest_success, "processed_at", None) or last_discovered_at
                elif not any(
                    hasattr(source, field)
                    for field in ("source_id", "created_at", "last_discovered_at")
                ):
                    anchor = getattr(latest_finished, "finished_at", None)
                else:
                    anchor = None
                if anchor is None or anchor < reference_time - timedelta(days=interval_days):
                    due_sources.append(source)
            if not due_sources:
                skipped.append(base_id)
                skipped_details[base_id] = "fresh"
                continue
            try:
                due_runs.append(
                    self._call_create_run(
                        payload=InternalKnowledgeUpdateRunStartRequest(
                            knowledge_base_id=base_id,
                            run_type=UpdateRunType.SCHEDULED_SYNC,
                            source_scope=SourceScope.SELECTED,
                            selected_source_ids=[
                                str(getattr(item, "source_id", base_id)) for item in due_sources
                            ],
                            document_ids=[],
                            force_reindex_all_in_scope=False,
                            force_reindex_document_ids=[],
                            target_embedding_profile=None,
                            reason="scheduled_sync",
                            requested_by="scheduler",
                            correlation_id=f"scheduled-sync-{uuid4().hex[:12]}",
                            idempotency_key=None,
                            execute_inline=execute_inline,
                        ),
                        initiator_user_id=None,
                        principal=principal,
                        audit_message="Scheduled knowledge update run created",
                        execute_inline=execute_inline,
                    )
                )
            except ConflictError:
                skipped.append(base_id)
                skipped_details[base_id] = "already_running"
        started_run_ids = [
            self._run_identifier(run, field="update_run_id")
            for run in due_runs
            if self._run_identifier(run, field="update_run_id") is not None
        ]
        started_base_ids = [
            self._run_identifier(run, field="knowledge_base_id")
            for run in due_runs
            if self._run_identifier(run, field="knowledge_base_id") is not None
        ]
        return {
            "started_runs": list(due_runs),
            "started_run_ids": started_run_ids,
            "started_knowledge_base_ids": started_base_ids,
            "skipped_knowledge_base_ids": skipped,
            "diagnostics": {
                "reference_time": reference_time.isoformat(),
                "interval_days": int(
                    self._settings_value("knowledge_auto_sync_interval_days", 30) or 30
                ),
                "started_count": len(due_runs),
                "skipped_count": len(skipped),
                "skipped_details": skipped_details,
            },
        }

    def _create_candidate_version(
        self, run: KnowledgeUpdateRun, selected_sources: list[KnowledgeSource]
    ) -> KnowledgeVersion:
        version_no = f"KV-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}"
        candidate = KnowledgeVersion(
            knowledge_base_id=run.knowledge_base_id,
            version_no=version_no,
            update_run_id=run.update_run_id,
            embedding_space_id=None,
            status=KnowledgeVersionStatus.DRAFT,
            summary={
                "status": KnowledgeVersionStatus.DRAFT.value,
                "policy_stack": build_policy_stack(
                    use_case="generation", embeddings=self.embeddings
                ).as_dict(),
                "provider_diagnostics": self.embeddings.describe(),
            },
            source_snapshot=self._build_source_snapshot(
                selected_sources, run, include_processing=False
            ),
            activation_metadata=None,
        )
        self.versions.add(candidate)
        self.session.flush()
        return candidate

    def _get_or_create_candidate_version(self, run: KnowledgeUpdateRun) -> KnowledgeVersion:
        existing = self.versions.get_by_update_run_id(run.update_run_id)
        if existing is not None:
            return existing
        selected_sources = self._resolve_scope_sources(
            SourceScope((run.scope or {}).get("source_scope", SourceScope.ALL.value)),
            (run.scope or {}).get("selected_source_ids") or [],
            knowledge_base_id=str(run.knowledge_base_id),
            allow_archived_selected=_is_delete_run_type(run.run_type),
        )
        return self._create_candidate_version(run, selected_sources)

    def _resolve_scope_sources(
        self,
        source_scope: SourceScope,
        selected_source_ids: list[str] | None,
        *,
        knowledge_base_id: str | None = None,
        allow_archived_selected: bool = False,
    ) -> list[KnowledgeSource]:
        active_visible = {
            str(source.source_id): source
            for source in self.sources.list_active(knowledge_base_id=knowledge_base_id)
        }
        if source_scope == SourceScope.ALL:
            return list(active_visible.values())
        if not selected_source_ids:
            raise ValidationError(
                "selected_source_ids are required when source_scope=selected",
                error_code="INVALID_SCOPE",
            )
        try:
            visible_sources = self.sources.list_visible(
                include_archived=allow_archived_selected,
                knowledge_base_id=knowledge_base_id,
            )
        except TypeError:
            visible_sources = self.sources.list_visible(knowledge_base_id=knowledge_base_id)
        selectable = {
            str(source.source_id): source
            for source in visible_sources
            if source.status != SourceStatus.DRAFT
        }
        selected: list[KnowledgeSource] = []
        for source_id in selected_source_ids:
            source = selectable.get(str(source_id))
            if source is None:
                raise ValidationError(
                    f"Unknown or unavailable source: {source_id}", error_code="INVALID_SCOPE"
                )
            selected.append(source)
        active_required = [
            item for item in active_visible.values() if item.criticality == Criticality.REQUIRED
        ]
        if active_required and len(selected) == len(selectable):
            return list(selectable.values())
        return selected

    def _resolve_documents_for_source(
        self, source: KnowledgeSource, documents: list[SourceDocument]
    ) -> list[SourceDocument]:
        normalized_source_type = _normalize_source_type(source.source_type)
        if normalized_source_type in {SourceType.REPOSITORY, SourceType.MANUAL_UPLOAD}:
            return self.repository_reader.resolve_documents(source, documents)
        if normalized_source_type == SourceType.URL_LIST:
            return self.url_list_reader.resolve_documents(source, documents)
        raise ValidationError(
            "Unsupported source type for Sprint 2", error_code="UNSUPPORTED_SOURCE_TYPE"
        )

    def _upsert_processing_result(
        self,
        run: KnowledgeUpdateRun,
        source: KnowledgeSource,
        document: SourceDocument | None,
        status: SourceProcessingStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> SourceProcessingResult:
        existing = self.processing_results.get_for_scope(
            update_run_id=run.update_run_id,
            source_id=source.source_id,
            document_id=document.document_id if document is not None else None,
        )
        entity = existing or SourceProcessingResult(
            update_run_id=run.update_run_id,
            source_id=source.source_id,
            document_id=document.document_id if document is not None else None,
            status=status,
        )
        entity.status = status
        entity.error_code = error_code
        entity.error_message = error_message
        entity.metrics = metrics
        self.processing_results.add(entity)
        self.session.flush()
        return entity

    def _mark_source_failure(
        self,
        run: KnowledgeUpdateRun,
        source: KnowledgeSource,
        document: SourceDocument | None,
        error_code: str,
        error_message: str,
        *,
        stage: str,
        deactivate_source: bool = True,
    ) -> dict[str, Any]:
        self._upsert_processing_result(
            run,
            source,
            document,
            SourceProcessingStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            metrics={"stage": stage},
        )
        if deactivate_source and source.status == SourceStatus.ACTIVE:
            source.status = SourceStatus.UNAVAILABLE
            self.session.add(source)
        return {
            "source_id": str(source.source_id),
            "knowledge_base_id": str(source.knowledge_base_id),
            "source_name": source.name,
            "document_id": str(document.document_id) if document is not None else None,
            "document_title": document.title if document is not None else None,
            "stage": stage,
            "error_code": error_code,
            "error_message": error_message,
        }

    def _build_source_snapshot(
        self,
        selected_sources: list[KnowledgeSource],
        run: KnowledgeUpdateRun,
        *,
        include_processing: bool,
    ) -> dict[str, Any]:
        processing_by_key: dict[tuple[str, str | None], SourceProcessingResult] = {}
        if include_processing:
            for item in self.processing_results.list_for_run(run.update_run_id):
                processing_by_key[
                    (str(item.source_id), str(item.document_id) if item.document_id else None)
                ] = item
        sources_payload: list[dict[str, Any]] = []
        for source in selected_sources:
            docs_payload: list[dict[str, Any]] = []
            for document in self.documents.list_for_source(source.source_id, include_archived=True):
                processing = processing_by_key.get(
                    (str(source.source_id), str(document.document_id))
                )
                docs_payload.append(
                    {
                        "document_id": str(document.document_id),
                        "title": document.title,
                        "uri": document.uri,
                        "checksum": document.checksum,
                        "document_status": document.status.value,
                        "processing_status": processing.status.value if processing else None,
                        "error_code": processing.error_code if processing else None,
                        "error_message": processing.error_message if processing else None,
                    }
                )
            sources_payload.append(
                {
                    "source_id": str(source.source_id),
                    "source_name": source.name,
                    "source_type": getattr(
                        _public_source_type(source.source_type),
                        "value",
                        _public_source_type(source.source_type),
                    ),
                    "criticality": source.criticality.value,
                    "source_status": source.status.value,
                    "documents": docs_payload,
                }
            )
        return {
            "update_run_id": str(run.update_run_id),
            "knowledge_base_id": str(run.knowledge_base_id),
            "captured_at": datetime.now(UTC).isoformat(),
            "source_scope": (run.scope or {}).get("source_scope", SourceScope.ALL.value),
            "selected_source_ids": (run.scope or {}).get("selected_source_ids", []),
            "document_ids": (run.scope or {}).get("document_ids", []),
            "force_reindex_all_in_scope": bool((run.scope or {}).get("force_reindex_all_in_scope")),
            "force_reindex_document_ids": (run.scope or {}).get("force_reindex_document_ids", []),
            "target_embedding_profile": (run.scope or {}).get("target_embedding_profile"),
            "sources": sources_payload,
        }

    def _auto_activate_candidate_version(
        self, candidate: KnowledgeVersion, run: KnowledgeUpdateRun
    ) -> KnowledgeVersion | None:
        if candidate.status != KnowledgeVersionStatus.VALIDATED:
            return None
        if not bool((run.scope or {}).get("auto_activate_if_validated")):
            return None
        principal = self._build_run_principal(run)
        reason = (
            (run.scope or {}).get("reason") or run.current_stage or "knowledge_update_auto_activate"
        )
        activated_version = KnowledgeVersionService(self.session).activate(
            str(candidate.knowledge_version_id),
            principal,
            reason=reason,
            auto_commit=False,
        )
        self._auto_select_activated_version_for_generation(activated_version, run, principal)
        return activated_version

    def _auto_select_activated_version_for_generation(
        self,
        activated_version: KnowledgeVersion,
        run: KnowledgeUpdateRun,
        principal: AuthPrincipal,
    ) -> KnowledgeBaseSelection | None:
        knowledge_version_id = getattr(activated_version, "knowledge_version_id", None)
        knowledge_base_id = getattr(activated_version, "knowledge_base_id", None)
        if knowledge_version_id is None or knowledge_base_id is None:
            return None
        if not is_generation_selectable_version(activated_version):
            return None

        base = getattr(activated_version, "knowledge_base", None)
        if base is None:
            bases = getattr(self, "bases", None)
            if bases is not None:
                base = bases.get(knowledge_base_id)
        base_kind = getattr(getattr(base, "kind", None), "value", getattr(base, "kind", None))
        if base_kind != KnowledgeBaseKind.USER_MANAGED.value:
            return None

        selection_scope = _selection_scope_for_principal(principal)
        selections = getattr(self, "selections", None)
        if selections is None:
            selections = KnowledgeBaseSelectionRepository(self.session)
            self.selections = selections
        selection = selections.get_for_scope(selection_scope)
        selected_base_id = (
            str(getattr(selection, "selected_knowledge_base_id", ""))
            if selection is not None
            else None
        )
        run_type = getattr(getattr(run, "run_type", None), "value", getattr(run, "run_type", None))
        is_upload_run = run_type == UpdateRunType.UPLOAD.value
        if (
            selection is not None
            and selected_base_id
            and selected_base_id != str(knowledge_base_id)
            and not is_upload_run
        ):
            return None

        if selection is None:
            selection = KnowledgeBaseSelection(
                selection_scope=selection_scope,
                selected_knowledge_base_id=knowledge_base_id,
            )
            selections.add(selection)
            self.session.flush()

        selection.selected_knowledge_base_id = knowledge_base_id
        selection.selected_knowledge_version_id = knowledge_version_id
        selection.updated_by_user_id = principal_actor_id(principal)
        self.session.add(selection)

        activation_metadata = dict(getattr(activated_version, "activation_metadata", None) or {})
        activation_metadata.update(
            {
                "selected_for_generation": True,
                "selection_scope": selection_scope,
                "selected_knowledge_base_id": str(knowledge_base_id),
                "selected_knowledge_version_id": str(knowledge_version_id),
            }
        )
        activated_version.activation_metadata = activation_metadata
        self.session.add(activated_version)
        self.audit.record(
            event_type="knowledge.base.selected",
            target_type="knowledge_base_selection",
            target_id=getattr(selection, "knowledge_base_selection_id", None),
            message="Auto-selected uploaded knowledge version for generation",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.INFO,
            payload={
                "knowledge_base_id": str(knowledge_base_id),
                "knowledge_version_id": str(knowledge_version_id),
                "selection_scope": selection_scope,
                "update_run_id": str(getattr(run, "update_run_id", "")),
                "run_type": run_type,
            },
        )
        return selection

    @staticmethod
    def _build_run_principal(run: KnowledgeUpdateRun) -> AuthPrincipal:
        requested_by = (run.scope or {}).get("requested_by") or "system.knowledge"
        user_id = run.initiator_user_id or requested_by
        return AuthPrincipal(
            user_id=str(user_id),
            login=str(requested_by),
            display_name="Knowledge Update Automation",
            account_type=AccountType.SERVICE,
            role_codes=[],
        )

    def _validate_candidate_version(
        self,
        candidate: KnowledgeVersion,
        selected_sources: list[KnowledgeSource],
        problem_sources: list[dict[str, Any]],
        rules_for_conflicts: list,
    ) -> ValidationSummary:
        grouped_problems: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for problem in problem_sources:
            grouped_problems[problem["source_id"]].append(problem)
        required_failures = [
            source
            for source in selected_sources
            if source.criticality == Criticality.REQUIRED
            and grouped_problems.get(str(source.source_id))
        ]
        optional_failures = [
            source
            for source in selected_sources
            if source.criticality == Criticality.OPTIONAL
            and grouped_problems.get(str(source.source_id))
        ]
        conflict_items = detect_rule_conflicts(rules_for_conflicts)
        document_count = len(candidate.version_documents)
        fragment_count = len(candidate.knowledge_fragments)
        basis_inventory = build_basis_inventory_for_version_documents(candidate.version_documents)
        base_kind = getattr(getattr(candidate, "knowledge_base", None), "kind", None)
        requires_complete_basis = base_kind == KnowledgeBaseKind.SYSTEM_MANDATORY
        run_type = getattr(getattr(candidate, "update_run", None), "run_type", None)
        run_type_value = getattr(run_type, "value", run_type)
        is_user_delete_empty_candidate = (
            run_type_value == UpdateRunType.DELETE.value and not requires_complete_basis
        )
        required_role_codes = [
            item.role_code for item in candidate.version_documents if item.required_flag
        ]
        duplicate_required_roles = (
            sorted({role for role in required_role_codes if required_role_codes.count(role) > 1})
            if requires_complete_basis
            else []
        )
        validation_report = {
            "required_source_failures": [str(item.source_id) for item in required_failures],
            "optional_source_failures": [str(item.source_id) for item in optional_failures],
            "conflicts": conflict_items,
            "rule_conflict_count": len(conflict_items),
            "document_count": document_count,
            "fragment_count": fragment_count,
            "required_packages": basis_inventory.required_packages,
            "missing_required_packages": basis_inventory.missing_required_packages,
            "basis_document_count": len(basis_inventory.basis_documents),
            "optional_reference_present": basis_inventory.optional_reference_present,
            "duplicate_required_role_codes": duplicate_required_roles,
            "processing_error_count": len(problem_sources),
            "processing_errors": [
                {
                    "source_id": item.get("source_id"),
                    "document_id": item.get("document_id"),
                    "stage": item.get("stage"),
                    "error_code": item.get("error_code"),
                    "error_message": item.get("error_message"),
                }
                for item in problem_sources
            ],
        }
        base_details = dict(validation_report)
        if document_count == 0 or fragment_count == 0:
            if is_user_delete_empty_candidate and document_count == 0 and fragment_count == 0:
                validation_report.update(
                    {
                        "validation": "passed",
                        "reason": "All documents were removed from the knowledge base",
                        "empty_knowledge_version": True,
                    }
                )
                return ValidationSummary(
                    run_status=KnowledgeUpdateStatus.COMPLETED,
                    version_status=KnowledgeVersionStatus.VALIDATED,
                    details={
                        **base_details,
                        **validation_report,
                        "validation_report": validation_report,
                    },
                )
            validation_report.update(
                {"validation": "failed", "reason": "No indexed documents or fragments"}
            )
            return ValidationSummary(
                run_status=KnowledgeUpdateStatus.FAILED,
                version_status=KnowledgeVersionStatus.REJECTED,
                details={
                    **base_details,
                    **validation_report,
                    "validation_report": validation_report,
                },
            )
        if required_failures:
            validation_report.update({"validation": "failed", "reason": "Required sources failed"})
            return ValidationSummary(
                run_status=KnowledgeUpdateStatus.FAILED,
                version_status=KnowledgeVersionStatus.REJECTED,
                details={
                    **base_details,
                    **validation_report,
                    "validation_report": validation_report,
                },
            )
        if requires_complete_basis and (
            basis_inventory.missing_required_packages or duplicate_required_roles
        ):
            validation_report.update(
                {"validation": "failed", "reason": "Required basis package is incomplete"}
            )
            return ValidationSummary(
                run_status=KnowledgeUpdateStatus.FAILED,
                version_status=KnowledgeVersionStatus.REJECTED,
                details={
                    **base_details,
                    **validation_report,
                    "validation_report": validation_report,
                },
            )
        if conflict_items or optional_failures:
            validation_report.update({"validation": "warning"})
            return ValidationSummary(
                run_status=KnowledgeUpdateStatus.COMPLETED_WITH_WARNINGS,
                version_status=KnowledgeVersionStatus.VALIDATED,
                details={
                    **base_details,
                    **validation_report,
                    "validation_report": validation_report,
                },
            )
        validation_report.update({"validation": "passed"})
        return ValidationSummary(
            run_status=KnowledgeUpdateStatus.COMPLETED,
            version_status=KnowledgeVersionStatus.VALIDATED,
            details={**base_details, **validation_report, "validation_report": validation_report},
        )

    @staticmethod
    def _stage_event(
        stage: str, *, detail: str | None = None, stage_status: str | None = None
    ) -> dict[str, Any]:
        return build_stage_event(stage, detail=detail, status=stage_status)

    def _append_stage_history(
        self,
        history: list[dict[str, Any]] | None,
        stage: str,
        *,
        detail: str | None = None,
        stage_status: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(history or [])
        items.append(self._stage_event(stage, detail=detail, stage_status=stage_status))
        return items

    def _set_stage(
        self, run: KnowledgeUpdateRun, *, status: KnowledgeUpdateStatus, current_stage: str
    ) -> None:
        run.status = status
        run.current_stage = current_stage
        summary = dict(run.summary or {})
        detail = f"Stage changed to {current_stage}"
        summary["stage_history"] = self._append_stage_history(
            summary.get("stage_history", []),
            current_stage,
            detail=detail,
            stage_status=status.value,
        )
        run.summary = summary
        self.session.add(run)
        self._record_operation_step(run, stage=current_stage, status=status.value, detail=detail)
        self.session.flush()
        self.session.commit()

    def _serialize_run(self, run: KnowledgeUpdateRun | Any) -> dict[str, Any]:
        summary = dict(getattr(run, "summary", None) or {})
        scope = dict(getattr(run, "scope", None) or {})
        versions_repo = getattr(self, "versions", None)
        candidate = (
            versions_repo.get_by_update_run_id(run.update_run_id)
            if versions_repo is not None and hasattr(versions_repo, "get_by_update_run_id")
            else None
        )
        active_diff = self._build_active_diff_summary(candidate)
        quality_summary = dict(summary.get("quality_summary", {}))
        validation_report = quality_summary.get("validation_report") or {
            "validation": quality_summary.get("validation"),
            "missing_required_packages": list(
                quality_summary.get("missing_required_packages") or []
            ),
            "required_source_failures": list(quality_summary.get("required_source_failures") or []),
            "optional_source_failures": list(quality_summary.get("optional_source_failures") or []),
            "document_count": quality_summary.get("document_count"),
            "fragment_count": quality_summary.get("fragment_count"),
            "rule_conflict_count": quality_summary.get("rule_conflict_count"),
            "processing_error_count": quality_summary.get("processing_error_count"),
            "provider_diagnostics": quality_summary.get("provider_diagnostics") or {},
        }
        active_embedding_space_id = quality_summary.get("embedding_space_id") or (
            str(candidate.embedding_space_id)
            if candidate is not None and getattr(candidate, "embedding_space_id", None)
            else None
        )
        active_embedding_space_code = quality_summary.get("embedding_space_code") or (
            getattr(getattr(candidate, "embedding_space", None), "code", None)
            if candidate is not None
            else None
        )
        telemetry_summary = quality_summary.get("telemetry") or build_update_run_telemetry_summary(
            quality_summary
        )
        return {
            "update_run_id": str(run.update_run_id),
            "knowledge_base_id": str(run.knowledge_base_id),
            "run_type": getattr(run, "run_type", None),
            "status": getattr(run, "status", None),
            "current_stage": getattr(run, "current_stage", None),
            "source_scope": SourceScope(scope.get("source_scope", SourceScope.ALL.value)),
            "selected_source_ids": scope.get("selected_source_ids", []),
            "requested_by": scope.get("requested_by"),
            "reason": scope.get("reason"),
            "started_at": getattr(run, "started_at", None),
            "finished_at": getattr(run, "finished_at", None),
            "duration_sec": getattr(run, "duration_sec", None),
            "candidate_knowledge_version_id": summary.get("candidate_knowledge_version_id"),
            "activated_knowledge_version_id": summary.get("activated_knowledge_version_id"),
            "problem_sources": summary.get("problem_sources", []),
            "quality_summary": quality_summary,
            "validation_report": validation_report,
            "comparison_to_active": active_diff,
            "activation_metadata": summary.get("activation_metadata"),
            "active_embedding_space_id": active_embedding_space_id,
            "active_embedding_space_code": active_embedding_space_code,
            "diagnostics": {
                "correlation_id": getattr(run, "correlation_id", None),
                "source_count": scope.get("source_count"),
                "document_scope_count": len(scope.get("document_ids", []) or []),
                "target_embedding_profile": scope.get("target_embedding_profile"),
                "force_reindex_all_in_scope": bool(scope.get("force_reindex_all_in_scope")),
                "force_reindex_document_ids": scope.get("force_reindex_document_ids", []),
                "stage_history": summary.get("stage_history", []),
                "error_code": summary.get("error_code"),
                "operation_id": str(run.update_run_id),
                "operation_kind": "knowledge_update_run",
                "telemetry_summary": telemetry_summary,
            },
        }
