from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.enums import (
    AuditSeverity,
    DocumentDeltaKind,
    FragmentStatus,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceProcessingStatus,
    SourceScope,
    SourceStatus,
    UpdateRunType,
)
from app.db.models.knowledge import (
    DocumentChunk,
    DocumentSnapshot,
    KnowledgeFragment,
    KnowledgeFragmentEmbedding,
    KnowledgeVersionDocument,
    NormativeRule,
)
from app.domain.architecture import infer_knowledge_guidance
from app.domain.services.knowledge.common import TERMINAL_UPDATE_STATUSES, _public_source_type
from app.domain.services.knowledge_telemetry import (
    build_update_run_telemetry_summary,
    record_stage_metric,
)
from app.domain.services.observability import summarize_stage_metrics
from app.integrations.knowledge.content_loader import (
    ContentLoadError,
    checksum_sha256,
    compute_embedding_key,
)
from app.integrations.knowledge.indexing_pipeline import (
    INDEXING_PIPELINE_VERSION,
    prepare_document_index,
)
from app.integrations.knowledge.policy_stack import build_policy_stack
from app.integrations.knowledge.text_processing import (
    CHUNKING_POLICY_VERSION,
    extract_normative_rules,
)

logger = logging.getLogger(__name__)


def _is_delete_run_type(value: Any) -> bool:
    return getattr(value, "value", value) == UpdateRunType.DELETE.value


class KnowledgeUpdateCanceled(Exception):
    """Internal signal used to stop a knowledge update worker after API cancellation."""


LOCAL_DENSE_EMBEDDING_PROVIDERS = {"local_inference", "ollama", "local_openai_compatible"}


def dense_embedding_skip_reason(
    *,
    embedding_descriptor: dict[str, object],
    chunk_count: int,
    index_metadata: dict[str, Any],
    settings: Any,
) -> str | None:
    provider_name = str(embedding_descriptor.get("provider_name") or "").strip().lower()
    if provider_name not in LOCAL_DENSE_EMBEDDING_PROVIDERS:
        return None
    max_chunks = int(getattr(settings, "knowledge_local_embedding_max_chunks", 96) or 0)
    if max_chunks <= 0 or chunk_count <= max_chunks:
        return None
    is_large_document = (
        index_metadata.get("adaptive_chunking_reason") == "large_document"
        or bool(index_metadata.get("adaptive_chunking"))
    )
    if not is_large_document:
        return None
    return f"local_embedding_large_document_chunk_count:{chunk_count}>{max_chunks}"


def is_embedding_timeout_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return isinstance(exc, TimeoutError) or "timed out" in message or "timeout" in message


def execute_knowledge_update_run(service: Any, update_run_id: str):
    from app.domain.services import knowledge_core as knowledge_core_module

    run = service.get_run(update_run_id)
    if run.status in TERMINAL_UPDATE_STATUSES:
        return run

    started = run.started_at or datetime.now(UTC)
    problem_sources: list[dict[str, Any]] = []
    processed_documents = 0
    fetched_documents = 0
    reused_documents = 0
    chunk_count = 0
    rule_count = 0
    extracted_item_count = 0
    embeddings_calculated = 0
    embeddings_reused = 0
    reused_chunk_count = 0
    rules_for_conflicts: list[NormativeRule] = []
    stage_metrics: dict[str, dict[str, Any]] = {}
    candidate = None
    selected_sources: list[Any] = []
    embedding_space = None
    requested_embedding_profile = None
    last_progress_commit_at: datetime | None = None

    def _setting(name: str, default: Any) -> Any:
        return getattr(getattr(service, "settings", None), name, default)

    def _raise_if_update_canceled() -> None:
        with suppress(Exception):
            service.session.refresh(run)
        if run.status == KnowledgeUpdateStatus.CANCELED:
            raise KnowledgeUpdateCanceled()

    def _publish_progress(stage_name: str, *, force: bool = False, **extra: Any) -> None:
        nonlocal last_progress_commit_at
        _raise_if_update_canceled()
        now = datetime.now(UTC)
        if (
            not force
            and last_progress_commit_at is not None
            and (now - last_progress_commit_at).total_seconds() < 2
        ):
            return
        last_progress_commit_at = now
        quality_summary = dict((run.summary or {}).get("quality_summary") or {})
        quality_summary.update(
            {
                "status": getattr(run.status, "value", run.status),
                "current_stage": run.current_stage,
                "processed_documents": processed_documents,
                "reused_documents": reused_documents,
                "fetched_documents": fetched_documents,
                "chunk_count": int(extra.get("chunk_count", chunk_count) or 0),
                "reused_chunk_count": reused_chunk_count,
                "embeddings_calculated": int(
                    extra.get("embeddings_calculated", embeddings_calculated) or 0
                ),
                "embeddings_reused": embeddings_reused,
                "rule_count": rule_count,
                "extracted_item_count": extracted_item_count,
                "processing_error_count": len(problem_sources),
                "stage_metrics": stage_metrics,
                "requested_embedding_profile": requested_embedding_profile,
                "embedding_space_id": str(getattr(embedding_space, "embedding_space_id", "") or "")
                or None,
                "embedding_space_code": getattr(embedding_space, "code", None),
                "execution_mode": "delta_first",
                "active_stage": {
                    "stage": stage_name,
                    "updated_at": now.isoformat(),
                    **extra,
                },
            }
        )
        quality_summary["telemetry"] = build_update_run_telemetry_summary(quality_summary)
        run.summary = {**(run.summary or {}), "quality_summary": quality_summary}
        service.session.add(run)
        commit = getattr(service.session, "commit", None)
        if callable(commit):
            commit()
        else:
            flush = getattr(service.session, "flush", None)
            if callable(flush):
                flush()

    def _finish_stage(stage_name: str, stage_started_at: datetime, **extra: Any) -> None:
        _raise_if_update_canceled()
        finished_at = datetime.now(UTC)
        duration_sec = max(0.0, (finished_at - stage_started_at).total_seconds())
        record_stage_metric(
            stage_metrics,
            stage_name,
            started_at=stage_started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_sec=duration_sec,
            extra=extra,
        )
        logger.info(
            "knowledge_update_stage_sample",
            extra={
                "correlation_id": run.correlation_id,
                "operation_kind": "knowledge_update_run",
                "operation_id": str(run.update_run_id),
                "knowledge_update_run_id": str(run.update_run_id),
                "knowledge_version_id": str(getattr(candidate, "knowledge_version_id", "") or ""),
                "stage": stage_name,
                "stage_status": str(extra.get("outcome") or "completed"),
                "duration_ms": round(duration_sec * 1000.0, 3),
                "error_code": extra.get("error_code"),
                "outcome": str(extra.get("outcome") or "completed"),
                "event_type": "stage_finished",
            },
        )
        _publish_progress(stage_name, force=True, **extra)

    def _discard_document_candidate_artifacts(
        *,
        document_id: str,
        document_snapshot: DocumentSnapshot | None = None,
        chunk_entities: list[DocumentChunk] | None = None,
    ) -> None:
        delete = getattr(service.session, "delete", None)
        for collection_name in (
            "version_documents",
            "knowledge_fragments",
            "normative_rules",
            "extracted_items",
        ):
            collection = getattr(candidate, collection_name, None)
            if collection is None:
                continue
            for item in list(collection):
                if str(getattr(item, "document_id", "") or "") != document_id:
                    continue
                with suppress(ValueError):
                    collection.remove(item)
                if callable(delete):
                    delete(item)
        if chunk_entities:
            for item in list(chunk_entities):
                if callable(delete):
                    delete(item)
        if document_snapshot is not None and callable(delete):
            delete(document_snapshot)
        flush = getattr(service.session, "flush", None)
        if callable(flush):
            flush()

    try:
        _raise_if_update_canceled()
        current_embedding_profile = getattr(
            getattr(service, "settings", None), "embedding_profile", None
        )
        if not current_embedding_profile:
            describe = getattr(getattr(service, "embeddings", None), "describe", None)
            if callable(describe):
                current_embedding_profile = describe().get("profile_code")
        candidate = service._get_or_create_candidate_version(run)
        run_type = getattr(run, "run_type", UpdateRunType.MANUAL)
        try:
            selected_sources = service._resolve_scope_sources(
                SourceScope((run.scope or {}).get("source_scope", SourceScope.ALL.value)),
                (run.scope or {}).get("selected_source_ids") or [],
                knowledge_base_id=str(run.knowledge_base_id),
                allow_archived_selected=_is_delete_run_type(run_type),
            )
        except TypeError:  # compatibility with simplified test doubles
            selected_sources = service._resolve_scope_sources(
                SourceScope((run.scope or {}).get("source_scope", SourceScope.ALL.value)),
                (run.scope or {}).get("selected_source_ids") or [],
                knowledge_base_id=str(run.knowledge_base_id),
            )
        requested_embedding_profile = str(
            (run.scope or {}).get("target_embedding_profile")
            or current_embedding_profile
            or "statistical_default"
        )
        service.embeddings = service._embedding_service_for_profile(requested_embedding_profile)
        embedding_space = service.resolve_embedding_space(
            activate=False,
            embedding_service=service.embeddings,
            knowledge_base_id=str(candidate.knowledge_base_id),
        )
        candidate.embedding_space_id = embedding_space.embedding_space_id
        service.session.add(candidate)
        service.session.flush()
        embedding_descriptor = service.embeddings.describe()

        active_version = service.versions.get_active(
            knowledge_base_id=candidate.knowledge_base_id, eager=True
        )
        active_version_documents = (
            {str(item.document_id): item for item in (active_version.version_documents or [])}
            if active_version is not None
            else {}
        )
        selected_source_ids = {str(source.source_id) for source in selected_sources}
        selected_document_ids = {
            str(item) for item in ((run.scope or {}).get("document_ids") or [])
        }
        removed_document_ids = {
            str(item) for item in ((run.scope or {}).get("removed_document_ids") or [])
        }
        force_reindex_all_in_scope = bool((run.scope or {}).get("force_reindex_all_in_scope"))
        force_reindex_document_ids = {
            str(item) for item in ((run.scope or {}).get("force_reindex_document_ids") or [])
        }

        logger.info(
            "knowledge_update_run_started",
            extra={
                "correlation_id": run.correlation_id,
                "operation_kind": "knowledge_update_run",
                "operation_id": str(run.update_run_id),
                "knowledge_update_run_id": str(run.update_run_id),
                "knowledge_version_id": str(candidate.knowledge_version_id),
                "stage": "queued",
                "stage_status": "running",
                "run_id": str(run.update_run_id),
                "entity_id": str(run.knowledge_base_id),
                "event_type": "pipeline_started",
            },
        )

        loading_started = datetime.now(UTC)
        service._set_stage(run, status=KnowledgeUpdateStatus.LOADING, current_stage="loading")
        loading_finished = False
        current_document_ids: set[str] = set()
        scanned_source_ids: set[str] = set()

        def _finish_loading_once() -> None:
            nonlocal loading_finished
            if loading_finished:
                return
            _finish_stage(
                "loading",
                loading_started,
                fetched_documents=fetched_documents,
                scanned_source_count=len(scanned_source_ids),
            )
            loading_finished = True

        for source in selected_sources:
            _raise_if_update_canceled()
            source_documents = service.documents.list_for_source(
                source.source_id, include_archived=True
            )
            if source.status == SourceStatus.ARCHIVED:
                scanned_source_ids.add(str(source.source_id))
                service._upsert_processing_result(
                    run,
                    source,
                    None,
                    SourceProcessingStatus.SKIPPED,
                    metrics={"stage": "loading", "reason": "source_archived"},
                )
                continue
            try:
                availability_payload = service._probe_source_availability(
                    source.source_type, source.base_uri
                )
                source.source_metadata = {
                    **(source.source_metadata or {}),
                    "last_availability_check": availability_payload,
                }
                if source.status == SourceStatus.UNAVAILABLE:
                    source.status = SourceStatus.ACTIVE
                service.session.add(source)
            except KnowledgeUpdateCanceled:
                raise
            except Exception as exc:
                source.status = SourceStatus.UNAVAILABLE
                source.source_metadata = {
                    **(source.source_metadata or {}),
                    "last_availability_check": {
                        "ok": False,
                        "error": str(exc),
                        "checked_at": datetime.now(UTC).isoformat(),
                    },
                }
                service.session.add(source)
                problem_sources.append(
                    service._mark_source_failure(
                        run, source, None, "SOURCE_UNAVAILABLE", str(exc), stage="loading"
                    )
                )
                continue

            try:
                _raise_if_update_canceled()
                documents = service._resolve_documents_for_source(source, source_documents)
            except KnowledgeUpdateCanceled:
                raise
            except Exception as exc:
                problem_sources.append(
                    service._mark_source_failure(
                        run, source, None, "SOURCE_READER_ERROR", str(exc), stage="loading"
                    )
                )
                continue

            if selected_document_ids:
                documents = [
                    item
                    for item in documents
                    if str(getattr(item, "document_id", "")) in selected_document_ids
                ]
            scanned_source_ids.add(str(source.source_id))
            if not documents:
                service._upsert_processing_result(
                    run,
                    source,
                    None,
                    SourceProcessingStatus.SKIPPED,
                    metrics={
                        "stage": "loading",
                        "reason": "no_documents_in_scope",
                        "document_scope_active": bool(selected_document_ids),
                    },
                )
                continue

            source.last_discovered_at = datetime.now(UTC)
            service.session.add(source)

            for document in documents:
                _raise_if_update_canceled()
                if document.document_id is None:
                    service.documents.add(document)
                    service.session.flush()
                current_document_ids.add(str(document.document_id))
                service._upsert_processing_result(
                    run,
                    source,
                    document,
                    SourceProcessingStatus.QUEUED,
                    metrics={"stage": "queued"},
                )

                try:
                    blob, resolved_uri, media_type = knowledge_core_module.fetch_uri(
                        document.uri,
                        timeout_sec=float(_setting("knowledge_fetch_timeout_sec", 30.0) or 30.0),
                        max_size_bytes=int(
                            _setting("knowledge_max_document_size_bytes", 104_857_600)
                            or 104_857_600
                        ),
                    )
                    document.resolved_uri = resolved_uri
                    document.media_type = media_type or document.media_type
                    document.size_bytes = len(blob)
                    document.fetched_at = datetime.now(UTC)
                    document.checksum = checksum_sha256(blob)
                    document.status = SourceDocumentStatus.FETCHED
                    service.session.add(document)
                    fetched_documents += 1
                    service._upsert_processing_result(
                        run,
                        source,
                        document,
                        SourceProcessingStatus.FETCHED,
                        metrics={
                            "stage": "fetched",
                            "bytes": len(blob),
                            "uri": resolved_uri,
                            "media_type": media_type,
                        },
                    )
                except ContentLoadError as exc:
                    problem_sources.append(
                        service._mark_source_failure(
                            run,
                            source,
                            document,
                            service._classify_document_error_code(str(exc), default="FETCH_FAILED"),
                            str(exc),
                            stage="loading",
                            deactivate_source=False,
                        )
                    )
                    document.status = SourceDocumentStatus.FAILED
                    service.session.add(document)
                    continue

                active_snapshot = (
                    service.document_snapshots.get_latest_for_document(
                        str(document.document_id),
                        knowledge_version_id=str(active_version.knowledge_version_id)
                        if active_version is not None
                        else None,
                    )
                    if active_version is not None
                    else None
                )
                previous_version_document = active_version_documents.get(str(document.document_id))
                force_reindex_document = (
                    force_reindex_all_in_scope
                    or str(document.document_id) in force_reindex_document_ids
                )
                active_space_matches = bool(
                    active_version is not None
                    and str(getattr(active_version, "embedding_space_id", "") or "")
                    == str(embedding_space.embedding_space_id)
                )

                reusable_snapshot = None
                reuse_reason = None
                reuse_source_document_id = None
                if (
                    not force_reindex_document
                    and active_snapshot is not None
                    and active_snapshot.checksum
                    and active_snapshot.checksum == document.checksum
                    and active_space_matches
                ):
                    reusable_snapshot = active_snapshot
                    reuse_reason = "unchanged_checksum_same_space"
                    reuse_source_document_id = str(document.document_id)
                elif not force_reindex_document and document.checksum:
                    find_reusable_by_checksum = getattr(
                        service.document_snapshots, "find_reusable_by_checksum", None
                    )
                    if callable(find_reusable_by_checksum):
                        reusable_snapshot = find_reusable_by_checksum(
                            document.checksum,
                            embedding_space_id=str(embedding_space.embedding_space_id),
                            exclude_knowledge_version_id=str(candidate.knowledge_version_id),
                        )
                    if reusable_snapshot is not None:
                        reuse_reason = "content_addressable_checksum_cache"
                        reuse_source_document_id = str(reusable_snapshot.document_id)

                if reusable_snapshot is not None:
                    service._record_document_delta(
                        run,
                        candidate,
                        document,
                        source_id=str(source.source_id),
                        delta_kind=DocumentDeltaKind.UNCHANGED,
                        checksum_before=reusable_snapshot.checksum,
                        checksum_after=document.checksum,
                        details={
                            "reuse_from_version_id": str(reusable_snapshot.knowledge_version_id),
                            "reuse_reason": reuse_reason,
                            "embedding_space_id": str(embedding_space.embedding_space_id),
                        },
                    )
                    service._clone_document_artifacts(
                        candidate,
                        document,
                        previous_version_document,
                        reusable_snapshot,
                        source_document_id=reuse_source_document_id,
                        reuse_mode=reuse_reason or "reused",
                    )
                    reused_documents += 1
                    reused_chunks = len(
                        service.document_chunks.list_for_snapshot(
                            reusable_snapshot.document_snapshot_id
                        )
                    )
                    chunk_count += reused_chunks
                    reused_chunk_count += reused_chunks
                    origin_document_id = str(reuse_source_document_id or document.document_id)
                    reused_embeddings = len(
                        list(
                            service.session.scalars(
                                select(KnowledgeFragmentEmbedding)
                                .join(
                                    KnowledgeFragment,
                                    KnowledgeFragment.fragment_id
                                    == KnowledgeFragmentEmbedding.fragment_id,
                                )
                                .where(
                                    KnowledgeFragment.knowledge_version_id
                                    == reusable_snapshot.knowledge_version_id,
                                    KnowledgeFragment.document_id == origin_document_id,
                                )
                            )
                        )
                    )
                    embeddings_reused += reused_embeddings
                    rule_count += len(
                        list(
                            service.session.scalars(
                                select(NormativeRule).where(
                                    NormativeRule.knowledge_version_id
                                    == reusable_snapshot.knowledge_version_id,
                                    NormativeRule.document_id == origin_document_id,
                                )
                            )
                        )
                    )
                    extracted_item_count += len(
                        service.extracted_items.list_for_document(
                            origin_document_id,
                            knowledge_version_id=str(reusable_snapshot.knowledge_version_id),
                        )
                    )
                    service._upsert_processing_result(
                        run,
                        source,
                        document,
                        SourceProcessingStatus.REUSED,
                        metrics={
                            "stage": "reused",
                            "reason": reuse_reason,
                            "active_knowledge_version_id": str(active_version.knowledge_version_id)
                            if active_version is not None
                            else None,
                            "reused_chunk_count": reused_chunks,
                            "reused_embedding_count": reused_embeddings,
                            "indexing_pipeline_version": INDEXING_PIPELINE_VERSION,
                            "embedding_space_id": str(embedding_space.embedding_space_id),
                        },
                    )
                    _finish_loading_once()
                    continue

                delta_kind = (
                    DocumentDeltaKind.CHANGED
                    if active_snapshot is not None
                    else DocumentDeltaKind.NEW
                )
                service._record_document_delta(
                    run,
                    candidate,
                    document,
                    source_id=str(source.source_id),
                    delta_kind=delta_kind,
                    checksum_before=getattr(active_snapshot, "checksum", None),
                    checksum_after=document.checksum,
                    details={
                        "active_knowledge_version_id": str(active_version.knowledge_version_id)
                        if active_version is not None
                        else None,
                        "force_reindex": force_reindex_document,
                        "embedding_space_id": str(embedding_space.embedding_space_id),
                    },
                )

                _finish_loading_once()
                _raise_if_update_canceled()
                service._ensure_within_sla(started, stage="parsing")
                parsing_started = datetime.now(UTC)
                service._set_stage(
                    run, status=KnowledgeUpdateStatus.PARSING, current_stage="parsing"
                )
                try:
                    _raise_if_update_canceled()
                    try:
                        normalized = knowledge_core_module.normalize_document_payload(
                            document.resolved_uri or document.uri,
                            blob,
                            media_type=document.media_type,
                        )
                    except TypeError as exc:
                        if "media_type" not in str(exc):
                            raise
                        normalized = knowledge_core_module.normalize_document_payload(
                            document.resolved_uri or document.uri, blob
                        )
                    normalized_text = normalized.text
                except KnowledgeUpdateCanceled:
                    raise
                except ContentLoadError as exc:
                    problem_sources.append(
                        service._mark_source_failure(
                            run,
                            source,
                            document,
                            service._classify_document_error_code(str(exc), default="PARSE_FAILED"),
                            str(exc),
                            stage="parsing",
                            deactivate_source=False,
                        )
                    )
                    document.status = SourceDocumentStatus.FAILED
                    service.session.add(document)
                    continue

                processed_documents += 1
                document.status = SourceDocumentStatus.PARSED
                service.session.add(document)
                if source.status == SourceStatus.UNAVAILABLE:
                    source.status = SourceStatus.ACTIVE
                    service.session.add(source)
                role_code, required_flag = knowledge_core_module.resolve_basis_assignment(document)
                candidate.version_documents.append(
                    KnowledgeVersionDocument(
                        knowledge_version_id=candidate.knowledge_version_id,
                        document_id=document.document_id,
                        role_code=role_code,
                        required_flag=required_flag,
                    )
                )
                index_payload = prepare_document_index(
                    normalized,
                    document_type=document.document_type,
                    document_title=document.title,
                    chunk_target_tokens=int(_setting("knowledge_chunk_target_tokens", 800) or 800),
                    chunk_overlap_pct=int(_setting("knowledge_chunk_overlap_pct", 5)),
                    chunk_max_chars=int(_setting("knowledge_chunk_max_chars", 6000) or 6000),
                    large_document_threshold_bytes=int(
                        _setting("knowledge_large_document_threshold_bytes", 1_048_576)
                    ),
                    large_document_chunk_target_tokens=int(
                        _setting("knowledge_large_document_chunk_target_tokens", 900) or 900
                    ),
                    large_document_chunk_overlap_pct=int(
                        _setting("knowledge_large_document_chunk_overlap_pct", 0) or 0
                    ),
                    large_document_chunk_max_chars=int(
                        _setting("knowledge_large_document_chunk_max_chars", 6000) or 6000
                    ),
                    original_size_bytes=int(getattr(document, "size_bytes", 0) or 0),
                    large_document_max_chunks=int(
                        _setting("knowledge_large_document_max_chunks", 240)
                    ),
                )
                document_snapshot = DocumentSnapshot(
                    knowledge_version_id=candidate.knowledge_version_id,
                    document_id=document.document_id,
                    checksum=document.checksum,
                    content_format=normalized.content_format,
                    parser_name=normalized.parser_name,
                    normalized_text=normalized_text,
                    structure_metadata={
                        **(normalized.metadata or {}),
                        **index_payload.canonical_metadata,
                        "source_id": str(source.source_id),
                        "source_name": source.name,
                        "section_count": len(normalized.sections),
                        "reuse_mode": "recomputed",
                        "document_title": document.title,
                    },
                )
                service.session.add(document_snapshot)
                service.session.flush()
                service._upsert_processing_result(
                    run,
                    source,
                    document,
                    SourceProcessingStatus.PARSED,
                    metrics={
                        "stage": "parsed",
                        "characters": len(normalized_text),
                        "content_format": normalized.content_format,
                        "parser_name": normalized.parser_name,
                        "section_count": len(normalized.sections),
                        "canonical_text_stats": (normalized.metadata or {}).get(
                            "canonical_text_stats"
                        ),
                        "indexing_pipeline_version": INDEXING_PIPELINE_VERSION,
                        "embedding_profile": embedding_descriptor.get("profile_code"),
                    },
                )
                _finish_stage(
                    "parsing",
                    parsing_started,
                    document_id=str(document.document_id),
                    content_format=normalized.content_format,
                )

                chunk_entities: list[DocumentChunk] = []
                chunk_vectors: list[list[float] | None] = []
                try:
                    _raise_if_update_canceled()
                    service._ensure_within_sla(started, stage="indexing")
                    indexing_started = datetime.now(UTC)
                    service._set_stage(
                        run, status=KnowledgeUpdateStatus.INDEXING, current_stage="indexing"
                    )
                    chunks = index_payload.chunks
                    _publish_progress(
                        "indexing",
                        force=True,
                        operation="chunking_prepared",
                        document_id=str(document.document_id),
                        document_title=document.title,
                        current_document_chunk_count=len(chunks),
                        planned_chunk_count=chunk_count + len(chunks),
                        chunk_metrics=index_payload.metrics,
                    )
                    last_embedding_progress: dict[str, object] = {}

                    def _on_embedding_progress(progress: dict[str, object]) -> None:
                        _raise_if_update_canceled()
                        service._ensure_within_sla(started, stage="indexing")
                        completed_texts = int(progress.get("completed_texts") or 0)
                        completed_batches = int(progress.get("completed_batches") or 0)
                        total_batches = int(progress.get("total_batches") or 0)
                        last_embedding_progress.clear()
                        last_embedding_progress.update(
                            {
                                "embedding_batches_completed": completed_batches,
                                "embedding_batches_total": total_batches,
                                "embedding_batch_size": progress.get("batch_size"),
                                "embedding_total_texts": progress.get("total_texts"),
                            }
                        )
                        _publish_progress(
                            "indexing",
                            force=completed_texts == 0
                            or (total_batches > 0 and completed_batches >= total_batches),
                            operation="embedding",
                            document_id=str(document.document_id),
                            document_title=document.title,
                            current_document_chunk_count=len(chunks),
                            planned_chunk_count=chunk_count + len(chunks),
                            chunk_count=chunk_count + completed_texts,
                            embeddings_calculated=embeddings_calculated + completed_texts,
                            **last_embedding_progress,
                        )

                    embedding_skip_reason = dense_embedding_skip_reason(
                        embedding_descriptor=embedding_descriptor,
                        chunk_count=len(chunks),
                        index_metadata=index_payload.canonical_metadata,
                        settings=getattr(service, "settings", None),
                    )
                    if embedding_skip_reason:
                        chunk_vectors = []
                        _publish_progress(
                            "indexing",
                            force=True,
                            operation="embedding_skipped",
                            document_id=str(document.document_id),
                            document_title=document.title,
                            current_document_chunk_count=len(chunks),
                            planned_chunk_count=chunk_count + len(chunks),
                            embedding_skip_reason=embedding_skip_reason,
                            embedding_mode="lexical_only",
                        )
                    else:
                        try:
                            chunk_vectors = (
                                service.embeddings.encode_documents(
                                    [chunk.content for chunk in chunks],
                                    titles=[chunk.title for chunk in chunks],
                                    progress_callback=_on_embedding_progress,
                                ).vectors
                                if chunks
                                else []
                            )
                        except Exception as exc:
                            if not is_embedding_timeout_error(exc):
                                raise
                            embedding_skip_reason = f"embedding_timeout:{exc}"
                            chunk_vectors = []
                            _publish_progress(
                                "indexing",
                                force=True,
                                operation="embedding_skipped",
                                document_id=str(document.document_id),
                                document_title=document.title,
                                current_document_chunk_count=len(chunks),
                                planned_chunk_count=chunk_count + len(chunks),
                                embedding_skip_reason=embedding_skip_reason,
                                embedding_mode="lexical_only",
                            )
                    embeddings_calculated += len(chunk_vectors)
                    cursor = 0
                    for index, chunk in enumerate(chunks, start=1):
                        chunk_count += 1
                        raw_start_offset = (
                            normalized_text.find(chunk.content[:80], cursor)
                            if chunk.content
                            else -1
                        )
                        start_offset: int | None
                        if raw_start_offset < 0:
                            start_offset = None
                            end_offset = None
                        else:
                            start_offset = raw_start_offset
                            end_offset = start_offset + len(chunk.content)
                            cursor = end_offset
                        chunk_entity = DocumentChunk(
                            document_snapshot_id=document_snapshot.document_snapshot_id,
                            knowledge_version_id=candidate.knowledge_version_id,
                            document_id=document.document_id,
                            chunk_index=index,
                            title=chunk.title,
                            source_location=chunk.source_location or f"chunk:{index}",
                            content=chunk.content,
                            start_offset=start_offset,
                            end_offset=end_offset,
                            chunk_metadata={
                                **(chunk.metadata or {}),
                                "role_code": role_code,
                                "required_flag": required_flag,
                            },
                        )
                        service.session.add(chunk_entity)
                        service.session.flush()
                        chunk_entities.append(chunk_entity)
                        fragment_entity = KnowledgeFragment(
                            knowledge_version_id=candidate.knowledge_version_id,
                            document_id=document.document_id,
                            fragment_type=chunk.fragment_type,
                            title=chunk.title,
                            content=chunk.content,
                            source_location=chunk.source_location or f"chunk:{index}",
                            fragment_metadata={
                                **(chunk.metadata or {}),
                                **infer_knowledge_guidance(
                                    title=document.title,
                                    uri=document.uri,
                                    document_type=getattr(
                                        document.document_type, "value", document.document_type
                                    ),
                                    text=f"{chunk.title or ''}\n{chunk.content}",
                                    role_code=role_code,
                                ),
                                "embedding_model_version": embedding_descriptor["model_id"],
                                "embedding_provider": embedding_descriptor["provider_name"],
                                "embedding_dimensions": embedding_descriptor["dimensions"],
                                "embedding_profile": embedding_descriptor["profile_code"],
                                "embedding_mode": "lexical_only"
                                if embedding_skip_reason
                                else "dense",
                                "embedding_skipped": bool(embedding_skip_reason),
                                "embedding_skip_reason": embedding_skip_reason,
                                "role_code": role_code,
                                "required_flag": required_flag,
                                "document_title": document.title,
                                "version_label": document.version_label,
                                "source_id": str(source.source_id),
                                "source_name": source.name,
                                "source_type": getattr(
                                    _public_source_type(source.source_type),
                                    "value",
                                    _public_source_type(source.source_type),
                                ),
                            },
                            embedding_key=None,
                            embedding=None,
                            status=FragmentStatus.ACTIVE,
                        )
                        candidate.knowledge_fragments.append(fragment_entity)
                        service.session.flush()
                        fragment_vector = (
                            chunk_vectors[index - 1] if index - 1 < len(chunk_vectors) else None
                        )
                        fragment_embedding_key = compute_embedding_key(
                            chunk.content,
                            profile_code=str(embedding_descriptor.get("profile_code") or "default"),
                            model_id=str(embedding_descriptor.get("model_id") or "default"),
                            dimensions=int(embedding_descriptor.get("dimensions") or 0),
                            task_mode="document",
                        )
                        fragment_entity.embedding_key = fragment_embedding_key
                        fragment_entity.embedding = fragment_vector
                        fragment_entity.fragment_embeddings.append(
                            KnowledgeFragmentEmbedding(
                                fragment_id=fragment_entity.fragment_id,
                                embedding_space_id=embedding_space.embedding_space_id,
                                embedding_key=fragment_embedding_key,
                                embedding=fragment_vector,
                            )
                        )
                    _finish_stage(
                        "indexing",
                        indexing_started,
                        document_id=str(document.document_id),
                        document_title=document.title,
                        chunk_count=len(chunk_entities),
                        chunk_metrics=index_payload.metrics,
                        embedding_count=len(chunk_vectors),
                        embedding_profile=embedding_descriptor.get("profile_code"),
                        embedding_mode="lexical_only" if embedding_skip_reason else "dense",
                        embedding_skipped=bool(embedding_skip_reason),
                        embedding_skip_reason=embedding_skip_reason,
                        **last_embedding_progress,
                    )
                except KnowledgeUpdateCanceled:
                    raise
                except Exception as exc:
                    _discard_document_candidate_artifacts(
                        document_id=str(document.document_id),
                        document_snapshot=document_snapshot,
                        chunk_entities=chunk_entities,
                    )
                    problem_sources.append(
                        service._mark_source_failure(
                            run,
                            source,
                            document,
                            service._classify_document_error_code(
                                str(exc), default="INDEXING_FAILED"
                            ),
                            str(exc),
                            stage="indexing",
                            deactivate_source=False,
                        )
                    )
                    document.status = SourceDocumentStatus.FAILED
                    service.session.add(document)
                    continue

                extracted_rules: list[NormativeRule] = []
                try:
                    _raise_if_update_canceled()
                    service._ensure_within_sla(started, stage="extracting")
                    extracting_started = datetime.now(UTC)
                    service._set_stage(
                        run, status=KnowledgeUpdateStatus.EXTRACTING, current_stage="extracting"
                    )
                    _publish_progress(
                        "extracting",
                        force=True,
                        operation="document_memory_start",
                        document_id=str(document.document_id),
                        document_title=document.title,
                        current_document_chunk_count=len(chunk_entities),
                        extraction_method="pending",
                    )
                    extracted_rules = extract_normative_rules(
                        knowledge_version_id=candidate.knowledge_version_id,
                        document_id=document.document_id,
                        document_type=document.document_type,
                        text=normalized_text,
                    )
                    rule_count += len(extracted_rules)
                    rules_for_conflicts.extend(extracted_rules)
                    candidate.normative_rules.extend(extracted_rules)

                    def _on_memory_progress(progress: dict[str, object]) -> None:
                        _raise_if_update_canceled()
                        service._ensure_within_sla(started, stage="extracting")
                        completed_batches = int(progress.get("completed_batches") or 0)
                        total_batches = int(progress.get("total_batches") or 0)
                        _publish_progress(
                            "extracting",
                            force=True,
                            operation=progress.get("operation") or "document_memory_llm",
                            document_id=str(document.document_id),
                            document_title=document.title,
                            current_document_chunk_count=len(chunk_entities),
                            llm_batch_status=progress.get("status"),
                            llm_current_batch=progress.get("current_batch"),
                            llm_batches_completed=completed_batches,
                            llm_batches_total=total_batches,
                            llm_batch_size=progress.get("batch_size"),
                            llm_completed_chunks=progress.get("completed_chunks"),
                            llm_total_chunks=progress.get("total_chunks"),
                        )

                    memory_stats = service._attach_document_memory(
                        candidate,
                        document=document,
                        normalized_text=normalized_text,
                        chunk_entities=chunk_entities,
                        progress_callback=_on_memory_progress,
                    )
                    doc_item_count = int(memory_stats.get("item_count") or 0)
                    extracted_item_count += doc_item_count
                    quality_summary = dict((run.summary or {}).get("quality_summary") or {})
                    if memory_stats.get("llm_attempted"):
                        quality_summary["llm_documents_attempted"] = (
                            int(quality_summary.get("llm_documents_attempted") or 0) + 1
                        )
                    if memory_stats.get("llm_skipped"):
                        quality_summary["llm_documents_skipped"] = (
                            int(quality_summary.get("llm_documents_skipped") or 0) + 1
                        )
                    if memory_stats.get("fallback_applied"):
                        quality_summary["llm_fallback_document_count"] = (
                            int(quality_summary.get("llm_fallback_document_count") or 0) + 1
                        )
                        fallback_details = list(quality_summary.get("llm_fallback_documents") or [])
                        fallback_details.append(
                            {
                                "document_id": str(document.document_id),
                                "title": document.title,
                                "reason": memory_stats.get("fallback_reason"),
                            }
                        )
                        quality_summary["llm_fallback_documents"] = fallback_details
                        run.summary = {**(run.summary or {}), "quality_summary": quality_summary}
                    service._upsert_processing_result(
                        run,
                        source,
                        document,
                        SourceProcessingStatus.EXTRACTED,
                        metrics={
                            "stage": "extracted",
                            "rule_count": len(extracted_rules),
                            "extracted_item_count": doc_item_count,
                            "extraction_method": memory_stats.get("extraction_method"),
                            "llm_attempted": bool(memory_stats.get("llm_attempted")),
                            "llm_skipped": bool(memory_stats.get("llm_skipped")),
                            "fallback_applied": bool(memory_stats.get("fallback_applied")),
                            "fallback_reason": memory_stats.get("fallback_reason"),
                            "indexing_pipeline_version": INDEXING_PIPELINE_VERSION,
                        },
                    )
                    _finish_stage(
                        "extracting",
                        extracting_started,
                        document_id=str(document.document_id),
                        rule_count=len(extracted_rules),
                        extracted_item_count=doc_item_count,
                        extraction_method=memory_stats.get("extraction_method"),
                        llm_skipped=bool(memory_stats.get("llm_skipped")),
                        fallback_applied=bool(memory_stats.get("fallback_applied")),
                    )
                except KnowledgeUpdateCanceled:
                    raise
                except Exception as exc:
                    _discard_document_candidate_artifacts(
                        document_id=str(document.document_id),
                        document_snapshot=document_snapshot,
                        chunk_entities=chunk_entities,
                    )
                    problem_sources.append(
                        service._mark_source_failure(
                            run,
                            source,
                            document,
                            service._classify_document_error_code(
                                str(exc), default="DOCUMENT_PROCESSING_FAILED"
                            ),
                            str(exc),
                            stage="extracting",
                            deactivate_source=False,
                        )
                    )
                    document.status = SourceDocumentStatus.FAILED
                    service.session.add(document)
                    continue

        _finish_loading_once()
        _raise_if_update_canceled()
        if active_version is not None:
            recorded_deleted_document_ids: set[str] = set()
            if removed_document_ids:
                for previous in active_version.version_documents or []:
                    previous_document = previous.document
                    previous_document_id = (
                        str(previous_document.document_id)
                        if previous_document is not None
                        else None
                    )
                    if (
                        previous_document is None
                        or previous_document_id not in removed_document_ids
                        or str(previous_document.source_id) not in selected_source_ids
                    ):
                        continue
                    previous_snapshot = service.document_snapshots.get_latest_for_document(
                        str(previous_document.document_id),
                        knowledge_version_id=str(active_version.knowledge_version_id),
                    )
                    service._record_document_delta(
                        run,
                        candidate,
                        previous_document,
                        source_id=str(previous_document.source_id),
                        delta_kind=DocumentDeltaKind.DELETED,
                        checksum_before=getattr(previous_snapshot, "checksum", None),
                        checksum_after=None,
                        details={
                            "active_knowledge_version_id": str(active_version.knowledge_version_id),
                            "deletion_mode": "explicit_removed_document",
                        },
                    )
                    recorded_deleted_document_ids.add(previous_document_id)
            if not selected_document_ids:
                for previous in active_version.version_documents or []:
                    previous_document = previous.document
                    previous_document_id = (
                        str(previous_document.document_id)
                        if previous_document is not None
                        else None
                    )
                    previous_source_id = (
                        str(previous_document.source_id) if previous_document is not None else None
                    )
                    if (
                        previous_document is None
                        or previous_source_id not in selected_source_ids
                        or previous_source_id not in scanned_source_ids
                        or previous_document_id in current_document_ids
                        or previous_document_id in recorded_deleted_document_ids
                    ):
                        continue
                    previous_snapshot = service.document_snapshots.get_latest_for_document(
                        str(previous_document.document_id),
                        knowledge_version_id=str(active_version.knowledge_version_id),
                    )
                    service._record_document_delta(
                        run,
                        candidate,
                        previous_document,
                        source_id=str(previous_document.source_id),
                        delta_kind=DocumentDeltaKind.DELETED,
                        checksum_before=getattr(previous_snapshot, "checksum", None),
                        checksum_after=None,
                        details={
                            "active_knowledge_version_id": str(active_version.knowledge_version_id)
                        },
                    )

            carried_forward_document_ids = {
                str(item.document_id)
                for item in (candidate.version_documents or [])
                if getattr(item, "document_id", None) is not None
            }
            for previous in active_version.version_documents or []:
                previous_document = previous.document
                previous_document_id = (
                    str(previous_document.document_id) if previous_document is not None else None
                )
                previous_source_id = (
                    str(previous_document.source_id) if previous_document is not None else None
                )
                if (
                    previous_document is None
                    or previous_document_id is None
                    or previous_document_id in carried_forward_document_ids
                    or previous_document_id in recorded_deleted_document_ids
                    or previous_document_id in removed_document_ids
                ):
                    continue
                if (
                    not selected_document_ids
                    and previous_source_id in selected_source_ids
                    and previous_source_id in scanned_source_ids
                ):
                    continue
                previous_snapshot = service.document_snapshots.get_latest_for_document(
                    previous_document_id,
                    knowledge_version_id=str(active_version.knowledge_version_id),
                )
                if previous_snapshot is None:
                    logger.warning(
                        "knowledge_update_preserve_snapshot_missing",
                        extra={
                            "correlation_id": run.correlation_id,
                            "operation_kind": "knowledge_update_run",
                            "operation_id": str(run.update_run_id),
                            "knowledge_update_run_id": str(run.update_run_id),
                            "knowledge_version_id": str(candidate.knowledge_version_id),
                            "document_id": previous_document_id,
                            "source_id": previous_source_id,
                            "stage": "loading",
                            "stage_status": "carry_forward_skipped",
                        },
                    )
                    continue
                service._clone_document_artifacts(
                    candidate,
                    previous_document,
                    previous,
                    previous_snapshot,
                    source_document_id=previous_document_id,
                    reuse_mode="carried_forward_out_of_scope",
                )
                carried_forward_document_ids.add(previous_document_id)

        _raise_if_update_canceled()
        service._ensure_within_sla(started, stage="validating")
        candidate.status = KnowledgeVersionStatus.DRAFT
        service.session.add(candidate)
        service._set_stage(run, status=KnowledgeUpdateStatus.VALIDATING, current_stage="validating")
        validating_started = datetime.now(UTC)
        validation = service._validate_candidate_version(
            candidate, selected_sources, problem_sources, rules_for_conflicts
        )
        _raise_if_update_canceled()
        candidate.status = validation.version_status
        _finish_stage(
            "validating", validating_started, validation=validation.details.get("validation")
        )
        processing_errors = [
            {
                "source_id": item.get("source_id"),
                "document_id": item.get("document_id"),
                "stage": item.get("stage"),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
            }
            for item in problem_sources
        ]
        delta_summary = service.document_deltas.summarize_for_run(run.update_run_id)
        quality_summary = {
            **validation.details,
            "policy_stack": build_policy_stack(
                use_case="generation", embeddings=service.embeddings
            ).as_dict(),
            "provider_diagnostics": service.embeddings.describe(),
            "processed_documents": processed_documents,
            "reused_documents": reused_documents,
            "fetched_documents": fetched_documents,
            "chunk_count": chunk_count,
            "reused_chunk_count": reused_chunk_count,
            "embeddings_calculated": embeddings_calculated,
            "embeddings_reused": embeddings_reused,
            "indexing_pipeline_version": INDEXING_PIPELINE_VERSION,
            "chunking_policy_version": CHUNKING_POLICY_VERSION,
            "rule_count": rule_count,
            "extracted_item_count": extracted_item_count,
            "delta_summary": delta_summary,
            "processing_error_count": len(processing_errors),
            "processing_errors": processing_errors,
            "stage_metrics": stage_metrics,
            "embedding_space_id": str(embedding_space.embedding_space_id),
            "embedding_space_code": embedding_space.code,
            "requested_embedding_profile": requested_embedding_profile,
            "document_scope_count": len(selected_document_ids),
            "explicit_removed_document_count": len(removed_document_ids),
            "force_reindex_all_in_scope": force_reindex_all_in_scope,
            "force_reindex_document_count": len(force_reindex_document_ids),
            "execution_mode": "delta_first",
        }
        quality_summary["telemetry"] = build_update_run_telemetry_summary(quality_summary)
        candidate.summary = quality_summary
        candidate.source_snapshot = service._build_source_snapshot(
            selected_sources, run, include_processing=True
        )
        quality_summary["comparison_to_active"] = service._build_active_diff_summary(candidate)
        _raise_if_update_canceled()
        activated_version = service._auto_activate_candidate_version(candidate, run)
        _raise_if_update_canceled()
        activated_version_id = (
            str(activated_version.knowledge_version_id) if activated_version is not None else None
        )
        run.status = validation.run_status
        run.current_stage = candidate.status.value
        run.finished_at = datetime.now(UTC)
        run.duration_sec = int((run.finished_at - started).total_seconds())
        quality_summary["sla"] = {
            "target_sec": int(_setting("knowledge_sync_sla_seconds", 3600) or 3600),
            "actual_sec": run.duration_sec,
            "within_sla": run.duration_sec
            <= int(_setting("knowledge_sync_sla_seconds", 3600) or 3600),
        }
        quality_summary["pipeline_telemetry"] = {
            **summarize_stage_metrics(stage_metrics),
            "total_runtime_sec": run.duration_sec,
            "status": run.status.value,
            "current_stage": run.current_stage,
        }
        stage_history = service._append_stage_history(
            (run.summary or {}).get("stage_history", []),
            validation.version_status.value,
            detail=f"Validation {validation.details.get('validation', 'completed')}",
            stage_status=validation.run_status.value,
        )
        if activated_version is not None:
            stage_history = service._append_stage_history(
                stage_history,
                "active",
                detail="Knowledge version activated automatically",
                stage_status=validation.run_status.value,
            )
        stage_history = service._append_stage_history(
            stage_history,
            "completed",
            detail="Candidate knowledge version prepared",
            stage_status=validation.run_status.value,
        )
        run.summary = {
            "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
            "activated_knowledge_version_id": activated_version_id,
            "problem_sources": problem_sources,
            "quality_summary": quality_summary,
            "source_snapshot": candidate.source_snapshot,
            "activation_metadata": candidate.activation_metadata,
            "stage_history": stage_history,
        }
        service._record_operation_step(
            run,
            stage=validation.version_status.value,
            status=validation.run_status.value,
            detail=f"Validation {validation.details.get('validation', 'completed')}",
            payload={"candidate_knowledge_version_id": str(candidate.knowledge_version_id)},
        )
        if activated_version is not None:
            service._record_operation_step(
                run,
                stage="active",
                status=validation.run_status.value,
                detail="Knowledge version activated automatically",
                payload={
                    "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
                    "activated_knowledge_version_id": activated_version_id,
                },
            )
        service.session.add(candidate)
        service.session.add(run)
        service.audit.record(
            event_type="knowledge.refresh.completed",
            target_type="knowledge_update_run",
            target_id=run.update_run_id,
            message="Knowledge update run completed",
            actor_user_id=run.initiator_user_id,
            correlation_id=run.correlation_id,
            payload=run.summary,
        )
        service.session.commit()
        service.session.refresh(run)
        logger.info(
            "knowledge_update_run_completed",
            extra={
                "correlation_id": run.correlation_id,
                "operation_kind": "knowledge_update_run",
                "operation_id": str(run.update_run_id),
                "knowledge_update_run_id": str(run.update_run_id),
                "knowledge_version_id": str(candidate.knowledge_version_id),
                "stage": "completed",
                "stage_status": run.status.value,
                "run_id": str(run.update_run_id),
                "entity_id": str(run.knowledge_base_id),
                "duration_ms": round(float(run.duration_sec or 0) * 1000.0, 3),
                "outcome": "completed",
                "event_type": "pipeline_finished",
            },
        )
        return run
    except KnowledgeUpdateCanceled:
        rollback = getattr(service.session, "rollback", None)
        if callable(rollback):
            rollback()
        run = service.get_run(update_run_id)
        logger.info(
            "knowledge_update_run_canceled",
            extra={
                "correlation_id": run.correlation_id,
                "operation_kind": "knowledge_update_run",
                "operation_id": str(run.update_run_id),
                "knowledge_update_run_id": str(run.update_run_id),
                "stage": run.current_stage,
                "stage_status": "canceled",
                "run_id": str(run.update_run_id),
                "entity_id": str(run.knowledge_base_id),
                "outcome": "canceled",
                "event_type": "pipeline_finished",
            },
        )
        return run
    except Exception as exc:
        rollback = getattr(service.session, "rollback", None)
        if callable(rollback):
            rollback()
        run = service.get_run(update_run_id)
        candidate = service._get_or_create_candidate_version(run)
        run.status = KnowledgeUpdateStatus.FAILED
        run.current_stage = "failed"
        run.finished_at = datetime.now(UTC)
        run.duration_sec = int((run.finished_at - started).total_seconds())
        candidate.status = KnowledgeVersionStatus.FAILED
        candidate.summary = {
            "error": str(exc),
            "error_code": getattr(exc, "error_code", "KNOWLEDGE_UPDATE_RUNTIME_ERROR"),
        }
        stage_history = service._append_stage_history(
            (run.summary or {}).get("stage_history", []),
            "failed",
            detail=str(exc),
            stage_status="failed",
        )
        run.summary = {
            **(run.summary or {}),
            "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
            "problem_sources": problem_sources,
            "error": str(exc),
            "error_code": getattr(exc, "error_code", "KNOWLEDGE_UPDATE_RUNTIME_ERROR"),
            "quality_summary": {
                **dict((run.summary or {}).get("quality_summary") or {}),
                "status": "failed",
                "processed_documents": processed_documents,
                "reused_documents": reused_documents,
                "fetched_documents": fetched_documents,
                "chunk_count": chunk_count,
                "reused_chunk_count": reused_chunk_count,
                "embeddings_calculated": embeddings_calculated,
                "embeddings_reused": embeddings_reused,
                "rule_count": rule_count,
                "extracted_item_count": extracted_item_count,
                "indexing_pipeline_version": INDEXING_PIPELINE_VERSION,
                "chunking_policy_version": CHUNKING_POLICY_VERSION,
                "delta_summary": service.document_deltas.summarize_for_run(run.update_run_id),
                "processing_error_count": len(problem_sources),
                "processing_errors": problem_sources,
                "stage_metrics": stage_metrics,
                "embedding_space_id": str(getattr(candidate, "embedding_space_id", "") or "")
                or None,
                "embedding_space_code": str(embedding_space.code)
                if embedding_space is not None
                else None,
                "requested_embedding_profile": requested_embedding_profile,
                "execution_mode": "delta_first",
            },
            "stage_history": stage_history,
        }
        run.summary["quality_summary"]["telemetry"] = build_update_run_telemetry_summary(
            run.summary["quality_summary"]
        )
        run.summary["quality_summary"]["pipeline_telemetry"] = {
            **summarize_stage_metrics(stage_metrics),
            "total_runtime_sec": run.duration_sec,
            "status": run.status.value,
            "current_stage": run.current_stage,
        }
        service._record_operation_step(
            run,
            stage="failed",
            status="failed",
            detail=str(exc),
            error_code=getattr(exc, "error_code", "KNOWLEDGE_UPDATE_RUNTIME_ERROR"),
            payload={"candidate_knowledge_version_id": str(candidate.knowledge_version_id)},
        )
        service.session.add(candidate)
        service.session.add(run)
        service.audit.record(
            event_type="knowledge.refresh.failed",
            target_type="knowledge_update_run",
            target_id=run.update_run_id,
            message="Knowledge update run failed",
            actor_user_id=run.initiator_user_id,
            correlation_id=run.correlation_id,
            payload=run.summary,
            severity=AuditSeverity.ERROR,
        )
        service.session.commit()
        service.session.refresh(run)
        logger.error(
            "knowledge_update_run_failed",
            exc_info=True,
            extra={
                "correlation_id": run.correlation_id,
                "operation_kind": "knowledge_update_run",
                "operation_id": str(run.update_run_id),
                "knowledge_update_run_id": str(run.update_run_id),
                "knowledge_version_id": str(candidate.knowledge_version_id),
                "stage": "failed",
                "stage_status": "failed",
                "run_id": str(run.update_run_id),
                "entity_id": str(run.knowledge_base_id),
                "error_code": getattr(exc, "error_code", "KNOWLEDGE_UPDATE_RUNTIME_ERROR"),
                "duration_ms": round(float(run.duration_sec or 0) * 1000.0, 3),
                "outcome": "failed",
                "event_type": "pipeline_finished",
            },
        )
        return run
