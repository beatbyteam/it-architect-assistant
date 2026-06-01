# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    AuditSeverity,
    DocumentDeltaKind,
    DocumentType,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    SourceDocumentStatus,
    SourceScope,
    SourceStatus,
    SourceType,
    UpdateRunType,
)
from app.db.models.knowledge import (
    DocumentChunk,
    DocumentExtractedItem,
    DocumentSnapshot,
    KnowledgeSource,
    SourceDocument,
    SourceProcessingResult,
)
from app.db.repositories.knowledge import (
    DocumentChunkRepository,
    DocumentDeltaRepository,
    DocumentExtractedItemRepository,
    DocumentSnapshotRepository,
    KnowledgeBaseRepository,
    KnowledgeSourceRepository,
    KnowledgeVersionRepository,
    SourceDocumentRepository,
    SourceProcessingResultRepository,
)
from app.domain.services.audit import AuditService
from app.domain.services.knowledge.serializers import (
    derive_source_availability_status,
    serialize_document,
    serialize_document_chunk,
    serialize_document_snapshot,
    serialize_extracted_item,
    serialize_source,
)
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.knowledge_bases import KnowledgeBaseService, _owner_key_for_principal
from app.domain.services.principal_keys import principal_actor_id
from app.integrations.knowledge.source_readers import (
    clear_document_explicit_exclusion,
    guess_document_type_from_name,
    mark_document_explicitly_excluded,
)
from app.integrations.knowledge.source_security import (
    SourceAvailabilityError,
    probe_source_availability,
    validate_document_uri,
    validate_source_base_uri,
)
from app.schemas.knowledge import (
    InternalKnowledgeUpdateRunStartRequest,
    SourceCreateRequest,
    SourceDocumentCreateRequest,
    SourceDocumentUpdateRequest,
    SourceUpdateRequest,
)

from .common import (
    SUPPORTED_SOURCE_TYPES,
    _build_allowed_local_source_roots,
    _default_refresh_policy_for_source,
    _normalize_refresh_policy,
    _normalize_source_type,
    _public_source_type,
    _schedule_interval_days,
    _uses_auto_sync,
)

_BASE_KNOWLEDGE_UPDATE_SERVICE_CLS = KnowledgeUpdateService


class KnowledgeSourceService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.bases = KnowledgeBaseRepository(session)
        self.sources = KnowledgeSourceRepository(session)
        self.documents = SourceDocumentRepository(session)
        self.processing_results = SourceProcessingResultRepository(session)
        self.document_snapshots = DocumentSnapshotRepository(session)
        self.document_chunks = DocumentChunkRepository(session)
        self.extracted_items = DocumentExtractedItemRepository(session)
        self.document_deltas = DocumentDeltaRepository(session)
        self.versions = KnowledgeVersionRepository(session)
        self.audit = AuditService(session)

    @staticmethod
    def _resolve_update_service_class():
        from app.domain.services import knowledge_core as knowledge_core_module

        local_cls = KnowledgeUpdateService
        core_cls = getattr(knowledge_core_module, "KnowledgeUpdateService", local_cls)
        if core_cls is not _BASE_KNOWLEDGE_UPDATE_SERVICE_CLS:
            return core_cls
        if local_cls is not _BASE_KNOWLEDGE_UPDATE_SERVICE_CLS:
            return local_cls
        return local_cls

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
        self,
        knowledge_base_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ):
        base_service = self._make_base_service()
        get_base = base_service.get_base
        try:
            return get_base(knowledge_base_id, principal, include_archived=include_archived)
        except TypeError:
            return get_base(knowledge_base_id)

    def _ensure_system_bases(self, principal: AuthPrincipal | None = None) -> None:
        base_service = self._make_base_service()
        ensure = base_service.ensure_system_bases
        try:
            ensure(principal)
        except TypeError:
            ensure()

    def _get_default_user_base(self, principal: AuthPrincipal | None = None):
        base_service = self._make_base_service()
        getter = base_service.get_default_user_base
        try:
            return getter(principal)
        except TypeError:
            return getter()

    def _get_document_compat(
        self, document_id: str, principal: AuthPrincipal | None = None
    ) -> SourceDocument:
        try:
            return self.get_document(document_id, principal)
        except TypeError:
            return self.get_document(document_id)

    def _get_source_compat(
        self, source_id: str, principal: AuthPrincipal | None = None
    ) -> KnowledgeSource:
        try:
            return self.get_source(source_id, principal)
        except TypeError:
            return self.get_source(source_id)

    def list_sources(
        self,
        *,
        knowledge_base_id: str | None = None,
        principal: AuthPrincipal | None = None,
        include_archived: bool = False,
    ) -> list[KnowledgeSource]:
        if knowledge_base_id is not None:
            self._get_base(knowledge_base_id, principal, include_archived=include_archived)
        owner_user_id = _owner_key_for_principal(principal) if principal is not None else None
        return self.sources.list_visible(
            knowledge_base_id=knowledge_base_id,
            include_archived=include_archived,
            owner_user_id=owner_user_id,
        )

    def list_source_payloads(
        self,
        *,
        knowledge_base_id: str | None = None,
        principal: AuthPrincipal | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        items = self.list_sources(
            knowledge_base_id=knowledge_base_id,
            principal=principal,
            include_archived=include_archived,
        )
        if not items:
            return []
        source_ids: list[UUID | str] = [item.source_id for item in items]
        processing_repo = getattr(self, "processing_results", None)
        documents_by_source = (
            self.documents.list_for_sources(source_ids, include_archived=True)
            if hasattr(self.documents, "list_for_sources")
            else {}
        )
        latest_by_source = (
            processing_repo.get_latest_for_sources(source_ids)
            if processing_repo and hasattr(processing_repo, "get_latest_for_sources")
            else {}
        )
        latest_success_by_source = (
            processing_repo.get_latest_success_for_sources(source_ids)
            if processing_repo and hasattr(processing_repo, "get_latest_success_for_sources")
            else {}
        )
        return [
            self._serialize_source(
                item,
                documents=documents_by_source.get(str(item.source_id)),
                latest_processing=latest_by_source.get(str(item.source_id)),
                latest_success=latest_success_by_source.get(str(item.source_id)),
            )
            for item in items
        ]

    def get_source(
        self,
        source_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ) -> KnowledgeSource:
        source = self.sources.get(source_id)
        if source is None:
            raise NotFoundError("KnowledgeSource", source_id)
        self._get_base(
            str(source.knowledge_base_id),
            principal,
            include_archived=include_archived,
        )
        return source

    def get_source_payload(
        self,
        source_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return self._serialize_source(
            self.get_source(source_id, principal, include_archived=include_archived)
        )

    def create_source(
        self, payload: SourceCreateRequest, principal: AuthPrincipal, *, auto_commit: bool = True
    ) -> KnowledgeSource:
        payload.source_type = _normalize_source_type(payload.source_type)
        if payload.refresh_policy is None:
            payload.refresh_policy = _default_refresh_policy_for_source(payload.source_type)
        self._validate_source(payload.source_type, payload.base_uri)
        if payload.knowledge_base_id:
            base = self._get_base(str(payload.knowledge_base_id), principal)
        else:
            raise ValidationError(
                "knowledge_base_id is required when creating a knowledge source",
                error_code="KNOWLEDGE_BASE_REQUIRED",
            )
        self._assert_base_mutable(base, principal, operation="create source")
        source_metadata = dict(payload.source_metadata or {})
        try:
            source_metadata["preflight"] = self._probe_source_availability(
                payload.source_type, payload.base_uri
            )
        except SourceAvailabilityError as exc:
            source_metadata["preflight"] = {"ok": False, "error": str(exc)}
        initial_status = (
            SourceStatus.ACTIVE
            if source_metadata.get("preflight", {}).get("ok") is True
            else SourceStatus.DRAFT
        )
        source = KnowledgeSource(
            knowledge_base_id=base.knowledge_base_id,
            source_type=payload.source_type,
            name=payload.name,
            base_uri=payload.base_uri,
            criticality=payload.criticality,
            status=initial_status,
            refresh_policy=payload.refresh_policy,
            sync_mode=payload.sync_mode,
            source_metadata=source_metadata,
        )
        self.sources.add(source)
        self.session.flush()
        self.audit.record(
            event_type="knowledge.source.created",
            target_type="knowledge_source",
            target_id=source.source_id,
            message=f"Knowledge source '{source.name}' registered in {source.status.value} state",
            actor_user_id=principal_actor_id(principal),
        )
        if auto_commit:
            self.session.commit()
            self.session.refresh(source)
        return source

    def update_source(
        self,
        source_id: str,
        payload: SourceUpdateRequest,
        principal: AuthPrincipal,
        *,
        auto_commit: bool = True,
        settings: Settings | None = None,
        execute_inline: bool | None = None,
    ) -> KnowledgeSource:
        try:
            source = self._get_source_compat(source_id, principal)
        except TypeError:
            source = self.get_source(source_id)
        self._assert_source_mutable(source, principal, operation="update source")
        next_source_type = _normalize_source_type(source.source_type)
        next_base_uri = payload.base_uri if payload.base_uri is not None else source.base_uri
        if payload.refresh_policy is None and getattr(source, "refresh_policy", None) is None:
            payload.refresh_policy = _default_refresh_policy_for_source(next_source_type)
        elif payload.refresh_policy is not None:
            payload.refresh_policy = _normalize_refresh_policy(payload.refresh_policy)
        self._validate_source(next_source_type, next_base_uri)
        if payload.status is not None:
            if payload.status == SourceStatus.UNAVAILABLE:
                raise ValidationError(
                    "Source availability is computed automatically; unavailable cannot be set manually",
                    error_code="KNOWLEDGE_SOURCE_STATUS_MANAGED",
                )
            self._validate_source_transition(source.status, payload.status)
        original_status = source.status
        original_base_uri = source.base_uri
        next_source_metadata = dict(source.source_metadata or {})
        if payload.source_metadata is not None:
            next_source_metadata.update(payload.source_metadata)
        try:
            next_source_metadata["preflight"] = self._probe_source_availability(
                next_source_type, next_base_uri
            )
        except SourceAvailabilityError as exc:
            next_source_metadata["preflight"] = {"ok": False, "error": str(exc)}
            if payload.status == SourceStatus.ACTIVE:
                raise ValidationError(
                    "Source is not reachable and cannot be activated",
                    error_code="KNOWLEDGE_SOURCE_UNAVAILABLE",
                    details={"source_id": source_id, "base_uri": next_base_uri, "error": str(exc)},
                ) from exc
        for field in ("name", "base_uri", "criticality", "refresh_policy", "sync_mode"):
            value = getattr(payload, field)
            if value is not None:
                setattr(source, field, value)
        source.source_metadata = next_source_metadata
        if payload.status is not None:
            source.status = payload.status
        self.session.add(source)
        self.audit.record(
            event_type="knowledge.source.updated",
            target_type="knowledge_source",
            target_id=source.source_id,
            message=f"Knowledge source '{source.name}' updated",
            actor_user_id=principal_actor_id(principal),
            payload={"status": source.status.value, "criticality": source.criticality.value},
        )
        self.session.flush()
        if payload.status is not None and payload.status != original_status:
            self._refresh_base_status_for_source_state(source.knowledge_base_id, principal)
        composition_changed = (
            payload.base_uri is not None and payload.base_uri != original_base_uri
        ) or (payload.status is not None and payload.status != original_status)
        if auto_commit and settings is not None and composition_changed:
            run_payload = self._start_source_update_run(
                source,
                principal,
                settings=settings,
                run_type=UpdateRunType.REBUILD,
                reason=f"source_update:{source_id}",
                execute_inline=execute_inline,
            )
            self.session.refresh(source)
            cast(Any, source).update_run_id = run_payload.get("update_run_id")
            return source
        if auto_commit:
            self.session.commit()
            self.session.refresh(source)
        return source

    def disable_source(
        self,
        source_id: str,
        principal: AuthPrincipal,
        *,
        settings: Settings | None = None,
        execute_inline: bool | None = None,
    ) -> KnowledgeSource:
        try:
            source = self._get_source_compat(source_id, principal)
        except TypeError:
            source = self.get_source(source_id)
        self._assert_source_mutable(source, principal, operation="disable source")
        self._validate_source_transition(source.status, SourceStatus.DISABLED)
        disabled_document_ids = [
            str(document.document_id)
            for document in self.documents.list_for_source(source.source_id, include_archived=False)
            if getattr(document, "document_id", None) is not None
        ]
        source.status = SourceStatus.DISABLED
        self.session.add(source)
        self.audit.record(
            event_type="knowledge.source.disabled",
            target_type="knowledge_source",
            target_id=source.source_id,
            message=f"Knowledge source '{source.name}' disabled",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.WARNING,
        )
        self.session.flush()
        self._refresh_base_status_for_source_state(source.knowledge_base_id, principal)
        if settings is not None:
            run_payload = self._start_source_update_run(
                source,
                principal,
                settings=settings,
                run_type=UpdateRunType.DELETE,
                reason=f"disable_source:{source_id}",
                execute_inline=execute_inline,
                removed_document_ids=disabled_document_ids,
            )
            self.session.refresh(source)
            cast(Any, source).update_run_id = run_payload.get("update_run_id")
            return source
        self.session.commit()
        self.session.refresh(source)
        return source

    def archive_source(
        self,
        source_id: str,
        principal: AuthPrincipal,
        *,
        settings: Settings | None = None,
        execute_inline: bool | None = None,
    ) -> KnowledgeSource:
        try:
            source = self._get_source_compat(source_id, principal)
        except TypeError:
            source = self.get_source(source_id)
        self._assert_source_mutable(source, principal, operation="archive source")
        self._validate_source_transition(source.status, SourceStatus.ARCHIVED)
        archived_document_ids = [
            str(document.document_id)
            for document in self.documents.list_for_source(source.source_id, include_archived=False)
            if getattr(document, "document_id", None) is not None
        ]
        source.status = SourceStatus.ARCHIVED
        self.session.add(source)
        self.audit.record(
            event_type="knowledge.source.archived",
            target_type="knowledge_source",
            target_id=source.source_id,
            message=f"Knowledge source '{source.name}' archived",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.WARNING,
        )
        self.session.flush()
        self._refresh_base_status_for_source_state(source.knowledge_base_id, principal)
        if settings is not None:
            run_payload = self._start_source_update_run(
                source,
                principal,
                settings=settings,
                run_type=UpdateRunType.DELETE,
                reason=f"archive_source:{source_id}",
                execute_inline=execute_inline,
                removed_document_ids=archived_document_ids,
            )
            self.session.refresh(source)
            cast(Any, source).update_run_id = run_payload.get("update_run_id")
            return source
        self.session.commit()
        self.session.refresh(source)
        return source

    def restore_source(
        self,
        source_id: str,
        principal: AuthPrincipal,
    ) -> KnowledgeSource:
        try:
            source = self.get_source(source_id, principal, include_archived=True)
        except TypeError:
            source = self.get_source(source_id, principal)
        self._assert_source_mutable(source, principal, operation="restore source")
        if source.status != SourceStatus.ARCHIVED:
            return source
        source.status = SourceStatus.ACTIVE
        self.session.add(source)
        self._refresh_base_status_for_source_state(source.knowledge_base_id, principal)
        self.audit.record(
            event_type="knowledge.source.restored",
            target_type="knowledge_source",
            target_id=source.source_id,
            message=f"Knowledge source '{source.name}' restored from archive",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.INFO,
            payload={"requires_knowledge_update": True},
        )
        self.session.commit()
        self.session.refresh(source)
        return source

    def list_documents(
        self,
        source_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ) -> list[SourceDocument]:
        _ = self.get_source(source_id, principal, include_archived=include_archived)
        return self.documents.list_for_source(source_id, include_archived=include_archived)

    def list_document_payloads(
        self,
        source_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            self._serialize_document(item)
            for item in self.list_documents(
                source_id,
                principal,
                include_archived=include_archived,
            )
        ]

    def get_document(
        self,
        document_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ) -> SourceDocument:
        document = self.documents.get(document_id)
        if document is None:
            raise NotFoundError("SourceDocument", document_id)
        if getattr(document, "source_id", None):
            source = self.sources.get(str(document.source_id))
            if source is not None:
                self._get_base(
                    str(source.knowledge_base_id),
                    principal,
                    include_archived=include_archived,
                )
        return document

    def get_document_payload(
        self,
        document_id: str,
        principal: AuthPrincipal | None = None,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return self._serialize_document(
            self.get_document(document_id, principal, include_archived=include_archived)
        )

    def get_document_snapshot_payload(
        self,
        document_id: str,
        *,
        knowledge_version_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        _ = self._get_document_compat(document_id, principal)
        snapshot = self.document_snapshots.get_latest_for_document(
            document_id, knowledge_version_id=knowledge_version_id
        )
        if snapshot is None:
            raise NotFoundError("DocumentSnapshot", document_id)
        return self._serialize_document_snapshot(snapshot)

    def list_document_chunk_payloads(
        self,
        document_id: str,
        *,
        knowledge_version_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> list[dict[str, Any]]:
        _ = self._get_document_compat(document_id, principal)
        snapshot = self.document_snapshots.get_latest_for_document(
            document_id, knowledge_version_id=knowledge_version_id
        )
        if snapshot is None:
            return []
        return [
            self._serialize_document_chunk(item)
            for item in self.document_chunks.list_for_snapshot(snapshot.document_snapshot_id)
        ]

    def get_document_memory_payload(
        self,
        document_id: str,
        *,
        knowledge_version_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            _ = self._get_document_compat(document_id, principal)
        except TypeError:
            _ = self.get_document(document_id)
        items = self.extracted_items.list_for_document(
            document_id, knowledge_version_id=knowledge_version_id
        )
        summary_item = next(
            (
                item
                for item in items
                if getattr(item.item_type, "value", item.item_type) == "summary"
            ),
            None,
        )
        counters: dict[str, int] = {}
        for item in items:
            key = getattr(item.item_type, "value", item.item_type)
            counters[key] = counters.get(key, 0) + 1
        diagnostic_source = (
            getattr(summary_item, "structured_payload", None) if summary_item is not None else None
        )
        return {
            "document_id": document_id,
            "knowledge_version_id": str(items[0].knowledge_version_id)
            if items
            else knowledge_version_id,
            "summary": getattr(summary_item, "content", None),
            "counters": dict(sorted(counters.items())),
            "extraction_method": diagnostic_source.get("extraction_method")
            if isinstance(diagnostic_source, dict)
            else None,
            "llm_attempted": bool(diagnostic_source.get("llm_attempted"))
            if isinstance(diagnostic_source, dict)
            else False,
            "fallback_applied": bool(diagnostic_source.get("fallback_applied"))
            if isinstance(diagnostic_source, dict)
            else False,
            "fallback_reason": diagnostic_source.get("fallback_reason")
            if isinstance(diagnostic_source, dict)
            else None,
            "items": [self._serialize_extracted_item(item) for item in items],
        }

    def list_document_extracted_item_payloads(
        self,
        document_id: str,
        *,
        knowledge_version_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        _ = self._get_document_compat(document_id, principal)
        items = self.extracted_items.list_for_document(
            document_id, knowledge_version_id=knowledge_version_id
        )
        return {
            "document_id": document_id,
            "knowledge_version_id": str(items[0].knowledge_version_id)
            if items
            else knowledge_version_id,
            "item_count": len(items),
            "items": [self._serialize_extracted_item(item) for item in items],
        }

    def register_document(
        self,
        source_id: str,
        payload: SourceDocumentCreateRequest,
        principal: AuthPrincipal,
        *,
        auto_commit: bool = True,
    ) -> SourceDocument:
        try:
            source = self._get_source_compat(source_id, principal)
        except TypeError:
            source = self.get_source(source_id)
        self._assert_source_mutable(source, principal, operation="register document")
        source_type = getattr(source, "source_type", None)
        allow_any_suffix = source_type is not None and (
            _normalize_source_type(cast(SourceType, source_type)) == SourceType.MANUAL_UPLOAD
        )
        self._validate_document_uri(payload.uri, allow_any_suffix=allow_any_suffix)
        document_type = payload.document_type
        if document_type == DocumentType.OTHER:
            infer_candidates = [payload.uri, payload.title]
            for candidate in infer_candidates:
                if not candidate:
                    continue
                document_type = guess_document_type_from_name(candidate)
                if document_type != DocumentType.OTHER:
                    break
        existing = self.documents.get_by_source_and_uri(source.source_id, payload.uri)
        if existing is not None:
            raise ConflictError(
                "Document URI is already registered for this source",
                error_code="DOCUMENT_URI_EXISTS",
                technical_message="A source document with the same URI already exists for the selected knowledge source",
            )
        document = SourceDocument(
            source_id=source.source_id,
            document_type=document_type,
            title=payload.title,
            uri=payload.uri,
            version_label=payload.version_label,
            checksum=payload.checksum,
            is_latest=payload.is_latest,
            status=SourceDocumentStatus.REGISTERED,
        )
        if payload.is_latest:
            self.documents.unset_latest_for_uri(source_id=source.source_id, uri=payload.uri)
        self.documents.add(document)
        self.session.flush()
        self.audit.record(
            event_type="knowledge.document.registered",
            target_type="source_document",
            target_id=document.document_id,
            message=f"Document '{document.title}' registered",
            actor_user_id=principal_actor_id(principal),
        )
        if auto_commit:
            self.session.commit()
            self.session.refresh(document)
        return document

    def update_document(
        self, document_id: str, payload: SourceDocumentUpdateRequest, principal: AuthPrincipal
    ) -> SourceDocument:
        try:
            document = self._get_document_compat(document_id, principal)
        except TypeError:
            document = self.get_document(document_id)
        self._assert_document_mutable(document, principal, operation="update document")
        target_uri = payload.uri if payload.uri is not None else document.uri
        source_type = getattr(getattr(document, "source", None), "source_type", None)
        if source_type is None:
            source_type = getattr(self.get_source(str(document.source_id)), "source_type", None)
        allow_any_suffix = source_type is not None and (
            _normalize_source_type(cast(SourceType, source_type)) == SourceType.MANUAL_UPLOAD
        )
        self._validate_document_uri(target_uri, allow_any_suffix=allow_any_suffix)
        if target_uri != document.uri:
            existing = self.documents.get_by_source_and_uri(document.source_id, target_uri)
            if existing is not None and str(existing.document_id) != str(document.document_id):
                raise ConflictError(
                    "Document URI is already registered for this source",
                    error_code="DOCUMENT_URI_EXISTS",
                    technical_message="A source document with the same URI already exists for the selected knowledge source",
                )
        for field in ("document_type", "title", "uri", "version_label", "checksum", "status"):
            value = getattr(payload, field)
            if value is not None:
                setattr(document, field, value)
        if payload.is_latest is not None:
            document.is_latest = payload.is_latest
            if payload.is_latest:
                self.documents.unset_latest_for_uri(
                    source_id=document.source_id,
                    uri=document.uri,
                    exclude_document_id=document.document_id,
                )
        self.session.add(document)
        self.audit.record(
            event_type="knowledge.document.updated",
            target_type="source_document",
            target_id=document.document_id,
            message=f"Document '{document.title}' updated",
            actor_user_id=principal_actor_id(principal),
        )
        self.session.commit()
        self.session.refresh(document)
        return document

    def disable_document(
        self,
        document_id: str,
        principal: AuthPrincipal,
        *,
        settings: Settings | None = None,
        execute_inline: bool | None = None,
        reason: str | None = None,
    ) -> SourceDocument:
        try:
            document = self._get_document_compat(document_id, principal)
        except TypeError:
            document = self.get_document(document_id)
        self._assert_document_mutable(document, principal, operation="disable document")
        mark_document_explicitly_excluded(document, reason="disabled")
        document.status = SourceDocumentStatus.ARCHIVED
        document.is_latest = False
        self.session.add(document)
        self.audit.record(
            event_type="knowledge.document.disabled",
            target_type="source_document",
            target_id=document.document_id,
            message=f"Document '{document.title}' disabled",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.WARNING,
        )
        self.session.flush()
        if settings is not None:
            try:
                source = self._get_source_compat(str(document.source_id), principal)
            except TypeError:
                source = self.get_source(str(document.source_id))
            run_payload = self._start_source_update_run(
                source,
                principal,
                settings=settings,
                run_type=UpdateRunType.DELETE,
                reason=reason or f"disable_document:{document_id}",
                execute_inline=execute_inline,
                removed_document_ids=[str(document.document_id)],
            )
            self.session.refresh(document)
            cast(Any, document).update_run_id = run_payload.get("update_run_id")
            return document
        self.session.commit()
        self.session.refresh(document)
        return document

    def remove_document_and_start_update(
        self,
        document_id: str,
        principal: AuthPrincipal,
        *,
        settings: Settings,
        execute_inline: bool | None = None,
        reason: str | None = None,
    ) -> tuple[SourceDocument, dict[str, Any]]:
        try:
            document = self._get_document_compat(document_id, principal)
        except TypeError:
            document = self.get_document(document_id)
        self._assert_document_mutable(document, principal, operation="remove document")
        try:
            source = self._get_source_compat(str(document.source_id), principal)
        except TypeError:
            source = self.get_source(str(document.source_id))
        if source.status == SourceStatus.ARCHIVED:
            raise ValidationError(
                "Archived sources cannot be used for versioned document removal",
                error_code="DOCUMENT_SOURCE_ARCHIVED",
            )
        mark_document_explicitly_excluded(document, reason="removed")
        document.status = SourceDocumentStatus.ARCHIVED
        document.is_latest = False
        self.session.add(document)
        self.audit.record(
            event_type="knowledge.document.removed",
            target_type="source_document",
            target_id=document.document_id,
            message=f"Document '{document.title}' removed from active knowledge base composition",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.WARNING,
            payload={
                "knowledge_base_id": str(source.knowledge_base_id),
                "source_id": str(source.source_id),
            },
        )
        self.session.flush()
        updater = self._resolve_update_service_class()(self.session, settings)
        try:
            run_payload = updater.start_run(
                InternalKnowledgeUpdateRunStartRequest(
                    knowledge_base_id=str(source.knowledge_base_id),
                    run_type=UpdateRunType.DELETE,
                    source_scope=SourceScope.SELECTED,
                    selected_source_ids=[str(source.source_id)],
                    removed_document_ids=[str(document.document_id)],
                    reason=reason or f"delete_document:{document_id}",
                    requested_by=principal.login
                    or principal.display_name
                    or principal_actor_id(principal)
                    or "system",
                    correlation_id=f"knowledge-delete-{uuid4().hex[:12]}",
                    idempotency_key=None,
                    execute_inline=execute_inline,
                ),
                principal,
            )
        except Exception:
            self.session.rollback()
            raise
        self.session.commit()
        self.session.refresh(document)
        return document, run_payload

    def restore_document(
        self,
        document_id: str,
        principal: AuthPrincipal,
        *,
        reason: str | None = None,
    ) -> SourceDocument:
        try:
            document = self.get_document(document_id, principal, include_archived=True)
        except TypeError:
            document = self.get_document(document_id, principal)
        try:
            source = self.get_source(
                str(document.source_id),
                principal,
                include_archived=True,
            )
        except TypeError:
            source = self.get_source(str(document.source_id), principal)
        base = self._get_base(
            str(source.knowledge_base_id),
            principal,
            include_archived=True,
        )
        self._assert_base_mutable(base, principal, operation="restore document")
        source_status_before_restore = source.status
        source_was_archived = source_status_before_restore == SourceStatus.ARCHIVED
        source_was_disabled = source_status_before_restore == SourceStatus.DISABLED
        if source_status_before_restore in {SourceStatus.ARCHIVED, SourceStatus.DISABLED}:
            source.status = SourceStatus.ACTIVE
            self.session.add(source)
            self._refresh_base_status_for_source_state(source.knowledge_base_id, principal)
            self.audit.record(
                event_type="knowledge.source.restored",
                target_type="knowledge_source",
                target_id=source.source_id,
                message=f"Knowledge source '{source.name}' restored while restoring document '{document.title}'",
                actor_user_id=principal_actor_id(principal),
                severity=AuditSeverity.INFO,
                payload={
                    "knowledge_base_id": str(source.knowledge_base_id),
                    "document_id": str(document.document_id),
                    "source_status_before_restore": getattr(
                        source_status_before_restore,
                        "value",
                        source_status_before_restore,
                    ),
                    "reason": reason or "restore_document",
                    "requires_knowledge_update": True,
                },
            )
        clear_document_explicit_exclusion(document)
        document.status = SourceDocumentStatus.REGISTERED
        document.is_latest = True
        self.documents.unset_latest_for_uri(
            source_id=document.source_id,
            uri=document.uri,
            exclude_document_id=document.document_id,
        )
        self.session.add(document)
        self.audit.record(
            event_type="knowledge.document.restored",
            target_type="source_document",
            target_id=document.document_id,
            message=f"Document '{document.title}' restored from archive",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.INFO,
            payload={
                "knowledge_base_id": str(source.knowledge_base_id),
                "source_id": str(source.source_id),
                "source_restored": source_was_archived,
                "source_reenabled": source_was_disabled,
                "reason": reason or "restore_document",
                "requires_knowledge_update": True,
            },
        )
        self.session.commit()
        self.session.refresh(document)
        return document

    def list_base_document_payloads(
        self,
        knowledge_base_id: str,
        *,
        knowledge_version_id: str | None = None,
        include_deleted: bool = True,
        include_archived_base: bool = False,
        principal: AuthPrincipal | None = None,
    ) -> list[dict[str, Any]]:
        base = self._get_base(
            knowledge_base_id,
            principal,
            include_archived=include_archived_base,
        )
        version = (
            self.versions.get_with_documents(knowledge_version_id)
            if knowledge_version_id
            else self.versions.get_active(knowledge_base_id=base.knowledge_base_id, eager=True)
        )
        if version is None:
            return (
                self._archived_document_payloads_for_base(
                    base,
                    knowledge_version_id=None,
                    excluded_document_ids=set(),
                )
                if include_deleted
                else []
            )
        if str(version.knowledge_base_id) != str(base.knowledge_base_id):
            raise ValidationError(
                "Knowledge version does not belong to the selected knowledge base",
                error_code="KNOWLEDGE_VERSION_BASE_MISMATCH",
            )
        delta_by_document_id: dict[str, Any] = {}
        deleted_entries: list[dict[str, Any]] = []
        processing_by_document_id: dict[str, Any] = {}
        if version.update_run_id:
            processing_repo = getattr(self, "processing_results", None)
            if processing_repo and hasattr(processing_repo, "list_for_run"):
                for processing in processing_repo.list_for_run(version.update_run_id):
                    document_id = getattr(processing, "document_id", None)
                    if document_id is not None:
                        processing_by_document_id[str(document_id)] = processing
            for delta in self.document_deltas.list_for_run(version.update_run_id):
                document_key = str(delta.document_id) if delta.document_id is not None else None
                if document_key:
                    delta_by_document_id[document_key] = delta
                if include_deleted and delta.delta_kind == DocumentDeltaKind.DELETED:
                    document = (
                        self.documents.get(str(delta.document_id)) if delta.document_id else None
                    )
                    source = (
                        document.source
                        if document is not None and getattr(document, "source", None) is not None
                        else (self.sources.get(str(delta.source_id)) if delta.source_id else None)
                    )
                    delta_details = dict(delta.details or {})
                    processing = (
                        processing_by_document_id.get(str(delta.document_id))
                        if delta.document_id
                        else None
                    )
                    deleted_entries.append(
                        {
                            "document_id": str(delta.document_id) if delta.document_id else None,
                            "knowledge_base_id": str(base.knowledge_base_id),
                            "knowledge_version_id": str(version.knowledge_version_id),
                            "source_id": str(delta.source_id) if delta.source_id else None,
                            "source_name": delta_details.get("source_name")
                            or getattr(source, "name", None),
                            "source_type": delta_details.get("source_type")
                            or getattr(
                                _public_source_type(getattr(source, "source_type", None)),
                                "value",
                                _public_source_type(getattr(source, "source_type", None)),
                            ),
                            "source_status": (
                                getattr(
                                    getattr(source, "status", None),
                                    "value",
                                    getattr(source, "status", None),
                                )
                                if source is not None
                                else delta_details.get("source_status")
                            ),
                            "title": delta_details.get("title")
                            or getattr(document, "title", None)
                            or delta.uri
                            or "Deleted document",
                            "uri": delta.uri,
                            "document_type": delta_details.get("document_type")
                            or (
                                getattr(
                                    getattr(document, "document_type", None),
                                    "value",
                                    getattr(document, "document_type", None),
                                )
                                if document is not None
                                else None
                            ),
                            "version_label": delta_details.get("version_label")
                            or (
                                getattr(document, "version_label", None)
                                if document is not None
                                else None
                            ),
                            "checksum": delta.checksum_before,
                            "role_code": None,
                            "required_flag": False,
                            "present_in_version": False,
                            "delta_kind": getattr(delta.delta_kind, "value", delta.delta_kind),
                            "document_status": (
                                getattr(
                                    getattr(document, "status", None),
                                    "value",
                                    getattr(document, "status", None),
                                )
                                if document is not None
                                else delta_details.get("document_status")
                            ),
                            "processing_status": getattr(
                                getattr(processing, "status", None),
                                "value",
                                getattr(processing, "status", None),
                            )
                            if processing is not None
                            else None,
                            "processing_error_code": getattr(processing, "error_code", None)
                            if processing is not None
                            else None,
                            "processing_error_message": getattr(processing, "error_message", None)
                            if processing is not None
                            else None,
                            "registered_at": delta_details.get("registered_at")
                            or (
                                getattr(document, "registered_at", None)
                                if document is not None
                                else None
                            ),
                            "discovered_at": delta_details.get("discovered_at")
                            or (
                                getattr(document, "discovered_at", None)
                                if document is not None
                                else None
                            ),
                        }
                    )
        rows: list[dict[str, Any]] = []
        for version_document in sorted(
            version.version_documents,
            key=lambda row: (
                (0 if row.required_flag else 1),
                row.role_code or "",
                getattr(row.document, "title", ""),
            ),
        ):
            document = version_document.document
            if document is None:
                continue
            source = document.source
            document_delta = delta_by_document_id.get(str(document.document_id))
            processing = processing_by_document_id.get(str(document.document_id))
            rows.append(
                {
                    "document_id": str(document.document_id),
                    "knowledge_base_id": str(base.knowledge_base_id),
                    "knowledge_version_id": str(version.knowledge_version_id),
                    "source_id": str(document.source_id),
                    "source_name": getattr(source, "name", None),
                    "source_type": getattr(
                        _public_source_type(getattr(source, "source_type", None)),
                        "value",
                        _public_source_type(getattr(source, "source_type", None)),
                    ),
                    "source_status": getattr(
                        getattr(source, "status", None),
                        "value",
                        getattr(source, "status", None),
                    ),
                    "title": document.title,
                    "uri": document.uri,
                    "document_type": getattr(
                        document.document_type, "value", document.document_type
                    ),
                    "version_label": document.version_label,
                    "checksum": document.checksum,
                    "role_code": version_document.role_code,
                    "required_flag": bool(version_document.required_flag),
                    "present_in_version": True,
                    "delta_kind": getattr(
                        getattr(document_delta, "delta_kind", None),
                        "value",
                        getattr(document_delta, "delta_kind", None),
                    ),
                    "document_status": getattr(document.status, "value", document.status),
                    "processing_status": getattr(
                        getattr(processing, "status", None),
                        "value",
                        getattr(processing, "status", None),
                    )
                    if processing is not None
                    else None,
                    "processing_error_code": getattr(processing, "error_code", None)
                    if processing is not None
                    else None,
                    "processing_error_message": getattr(processing, "error_message", None)
                    if processing is not None
                    else None,
                    "registered_at": document.registered_at,
                    "discovered_at": document.discovered_at,
                }
            )
        archived_entries = (
            self._archived_document_payloads_for_base(
                base,
                knowledge_version_id=str(version.knowledge_version_id),
                excluded_document_ids={
                    str(item["document_id"])
                    for item in [*rows, *deleted_entries]
                    if item.get("document_id")
                },
            )
            if include_deleted
            else []
        )
        return rows + deleted_entries + archived_entries

    def _archived_document_payloads_for_base(
        self,
        base: Any,
        *,
        knowledge_version_id: str | None,
        excluded_document_ids: set[str],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not callable(getattr(self.documents, "list_for_source", None)):
            return entries
        for source in self.sources.list_for_base(base.knowledge_base_id, include_archived=True):
            source_status = getattr(source.status, "value", source.status)
            for document in self.documents.list_for_source(source.source_id, include_archived=True):
                document_id = str(document.document_id)
                document_status = getattr(document.status, "value", document.status)
                if document_id in excluded_document_ids:
                    continue
                if document_status != SourceDocumentStatus.ARCHIVED.value and source_status != SourceStatus.ARCHIVED.value:
                    continue
                entries.append(
                    {
                        "document_id": document_id,
                        "knowledge_base_id": str(base.knowledge_base_id),
                        "knowledge_version_id": knowledge_version_id or "archive",
                        "source_id": str(source.source_id),
                        "source_name": getattr(source, "name", None),
                        "source_type": getattr(
                            _public_source_type(getattr(source, "source_type", None)),
                            "value",
                            _public_source_type(getattr(source, "source_type", None)),
                        ),
                        "source_status": source_status,
                        "title": document.title,
                        "uri": document.uri,
                        "document_type": getattr(
                            getattr(document, "document_type", None),
                            "value",
                            getattr(document, "document_type", None),
                        ),
                        "version_label": document.version_label,
                        "checksum": document.checksum,
                        "role_code": None,
                        "required_flag": False,
                        "present_in_version": False,
                        "delta_kind": DocumentDeltaKind.DELETED.value,
                        "document_status": document_status,
                        "processing_status": None,
                        "processing_error_code": None,
                        "processing_error_message": None,
                        "registered_at": document.registered_at,
                        "discovered_at": document.discovered_at,
                    }
                )
        return entries

    def _assert_base_mutable(self, base, principal: AuthPrincipal, *, operation: str) -> None:
        if (
            getattr(base.kind, "value", base.kind) == KnowledgeBaseKind.SYSTEM_MANDATORY.value
            and principal.account_type != AccountType.SERVICE
        ):
            raise ValidationError(
                f"System mandatory knowledge base is immutable for user operation: {operation}",
                error_code="SYSTEM_KNOWLEDGE_BASE_IMMUTABLE",
            )

    def _assert_source_mutable(
        self, source: KnowledgeSource, principal: AuthPrincipal, *, operation: str
    ) -> None:
        base = self._get_base(str(source.knowledge_base_id), principal)
        self._assert_base_mutable(base, principal, operation=operation)

    def _assert_document_mutable(
        self, document: SourceDocument, principal: AuthPrincipal, *, operation: str
    ) -> None:
        try:
            source = self._get_source_compat(str(document.source_id), principal)
        except TypeError:
            source = self.get_source(str(document.source_id))
        self._assert_source_mutable(source, principal, operation=operation)

    def _start_source_update_run(
        self,
        source: KnowledgeSource,
        principal: AuthPrincipal,
        *,
        settings: Settings,
        run_type: UpdateRunType,
        reason: str,
        execute_inline: bool | None = None,
        removed_document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        updater = self._resolve_update_service_class()(self.session, settings)
        try:
            run_payload = updater.start_run(
                InternalKnowledgeUpdateRunStartRequest(
                    knowledge_base_id=str(source.knowledge_base_id),
                    run_type=run_type,
                    source_scope=SourceScope.SELECTED,
                    selected_source_ids=[str(source.source_id)],
                    removed_document_ids=[str(item) for item in (removed_document_ids or [])],
                    reason=reason,
                    requested_by=principal.login
                    or principal.display_name
                    or principal_actor_id(principal)
                    or "system",
                    correlation_id=f"knowledge-source-mutation-{uuid4().hex[:12]}",
                    idempotency_key=None,
                    execute_inline=execute_inline,
                ),
                principal,
            )
        except Exception:
            self.session.rollback()
            raise
        return run_payload

    def _refresh_base_status_for_source_state(
        self,
        knowledge_base_id: UUID | str,
        principal: AuthPrincipal | None,
    ) -> None:
        try:
            base = self._get_base(str(knowledge_base_id), principal, include_archived=True)
        except (AuthorizationError, NotFoundError):
            return
        if getattr(base, "kind", None) != KnowledgeBaseKind.USER_MANAGED:
            return
        if getattr(base, "status", None) == KnowledgeBaseStatus.ARCHIVED:
            return
        sources = self.sources.list_for_base(base.knowledge_base_id, include_archived=True)
        has_active_source = any(source.status == SourceStatus.ACTIVE for source in sources)
        target_status = (
            KnowledgeBaseStatus.ACTIVE if has_active_source else KnowledgeBaseStatus.DISABLED
        )
        if base.status == target_status:
            return
        base.status = target_status
        self.session.add(base)

    def _serialize_source(
        self,
        source: KnowledgeSource,
        *,
        documents: list[SourceDocument] | None = None,
        latest_processing: SourceProcessingResult | None = None,
        latest_success: SourceProcessingResult | None = None,
    ) -> dict[str, Any]:
        processing_repo = getattr(self, "processing_results", None)
        if latest_processing is None:
            latest_processing = (
                processing_repo.get_latest_for_source(source.source_id)
                if processing_repo and hasattr(processing_repo, "get_latest_for_source")
                else None
            )
        if latest_success is None:
            latest_success = (
                processing_repo.get_latest_success_for_source(source.source_id)
                if processing_repo and hasattr(processing_repo, "get_latest_success_for_source")
                else latest_processing
            )
        if documents is None:
            documents = self.documents.list_for_source(source.source_id, include_archived=True)
        interval_days = _schedule_interval_days(
            source.refresh_policy,
            int(
                getattr(getattr(self, "settings", None), "knowledge_auto_sync_interval_days", 30)
                or 30
            ),
        )
        payload = serialize_source(
            source,
            documents=documents,
            latest_processing=latest_processing,
            latest_success=latest_success,
            auto_sync_enabled=_uses_auto_sync(source.refresh_policy),
            auto_sync_interval_days=interval_days,
        )
        payload["source_type"] = _public_source_type(source.source_type)
        return payload

    def _serialize_document(self, document: SourceDocument) -> dict[str, Any]:
        latest_processing = self.processing_results.get_latest_for_document(document.document_id)
        return serialize_document(document, latest_processing=latest_processing)

    @staticmethod
    def _serialize_document_snapshot(snapshot: DocumentSnapshot) -> dict[str, Any]:
        return serialize_document_snapshot(
            snapshot, serialize_document_chunk=KnowledgeSourceService._serialize_document_chunk
        )

    @staticmethod
    def _serialize_document_chunk(chunk: DocumentChunk) -> dict[str, Any]:
        return serialize_document_chunk(chunk)

    @staticmethod
    def _serialize_extracted_item(item: DocumentExtractedItem) -> dict[str, Any]:
        return serialize_extracted_item(item)

    @staticmethod
    def _derive_availability_status(status: SourceStatus, latest_error_code: str | None) -> str:
        return derive_source_availability_status(status, latest_error_code)

    @staticmethod
    def _validate_source_transition(current: SourceStatus, target: SourceStatus) -> None:
        allowed = {
            SourceStatus.DRAFT: {SourceStatus.ACTIVE, SourceStatus.DISABLED, SourceStatus.DRAFT},
            SourceStatus.ACTIVE: {
                SourceStatus.ACTIVE,
                SourceStatus.UNAVAILABLE,
                SourceStatus.DISABLED,
                SourceStatus.ARCHIVED,
            },
            SourceStatus.UNAVAILABLE: {
                SourceStatus.UNAVAILABLE,
                SourceStatus.ACTIVE,
                SourceStatus.DISABLED,
            },
            SourceStatus.DISABLED: {
                SourceStatus.DISABLED,
                SourceStatus.ACTIVE,
                SourceStatus.ARCHIVED,
            },
            SourceStatus.ARCHIVED: {SourceStatus.ARCHIVED},
        }
        if target not in allowed.get(current, {current}):
            raise ValidationError(
                f"Invalid source lifecycle transition: {current.value} -> {target.value}",
                error_code="KNOWLEDGE_SOURCE_INVALID_TRANSITION",
                technical_message="Knowledge source lifecycle transition is not allowed by MVP rules",
                details={"from": current.value, "to": target.value},
            )

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

    def _validate_document_uri(self, uri: str, *, allow_any_suffix: bool = False) -> None:
        settings = getattr(self, "settings", None)
        validate_document_uri(
            uri,
            allowed_local_roots=_build_allowed_local_source_roots(settings),
            allow_unrestricted_local_paths=bool(
                getattr(settings, "knowledge_allow_unrestricted_local_sources", False)
            ),
            allow_any_suffix=allow_any_suffix,
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
