from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.db.enums import SourceDocumentStatus, SourceStatus


def derive_source_availability_status(status: SourceStatus, latest_error_code: str | None) -> str:
    if status == SourceStatus.ARCHIVED:
        return "archived"
    if status == SourceStatus.DISABLED:
        return "disabled"
    if status == SourceStatus.DRAFT:
        return "draft"
    if status == SourceStatus.UNAVAILABLE or latest_error_code:
        return "unavailable"
    return "active"


def serialize_source(
    source: Any,
    *,
    documents: list[Any],
    latest_processing: Any | None,
    latest_success: Any | None,
    auto_sync_enabled: bool,
    auto_sync_interval_days: int,
) -> dict[str, Any]:
    availability_status = derive_source_availability_status(
        source.status,
        getattr(latest_processing, "error_code", None) if latest_processing else None,
    )
    last_sync_time = getattr(latest_success, "processed_at", None)
    next_sync_time = None
    if auto_sync_enabled:
        anchor = last_sync_time or source.last_discovered_at or source.created_at
        next_sync_time = (
            anchor + timedelta(days=auto_sync_interval_days) if anchor is not None else None
        )
    return {
        "source_id": str(source.source_id),
        "knowledge_base_id": str(source.knowledge_base_id),
        "source_type": getattr(
            getattr(source, "source_type", None), "value", getattr(source, "source_type", None)
        ),
        "name": source.name,
        "base_uri": source.base_uri,
        "criticality": source.criticality,
        "status": source.status,
        "refresh_policy": source.refresh_policy,
        "sync_mode": source.sync_mode,
        "source_metadata": source.source_metadata,
        "created_at": source.created_at,
        "last_discovered_at": source.last_discovered_at,
        "last_sync_time": last_sync_time,
        "next_sync_time": next_sync_time,
        "availability_status": availability_status,
        "document_count": len(
            [doc for doc in documents if doc.status != SourceDocumentStatus.ARCHIVED]
        ),
        "latest_document_registered_at": max(
            (doc.registered_at for doc in documents), default=None
        ),
        "last_processed_at": getattr(latest_processing, "processed_at", None)
        if latest_processing
        else None,
        "last_processing_status": getattr(
            getattr(latest_processing, "status", None),
            "value",
            getattr(latest_processing, "status", None),
        )
        if latest_processing
        else None,
        "last_error_code": getattr(latest_processing, "error_code", None)
        if latest_processing
        else None,
        "last_error_message": getattr(latest_processing, "error_message", None)
        if latest_processing
        else None,
        "update_run_id": str(source.update_run_id)
        if getattr(source, "update_run_id", None)
        else None,
    }


def serialize_document(document: Any, *, latest_processing: Any | None) -> dict[str, Any]:
    source = getattr(document, "source", None)
    base_metadata = dict(getattr(document, "document_metadata", None) or {})
    if source is not None and "source_type" not in base_metadata:
        base_metadata["source_type"] = getattr(
            getattr(source, "source_type", None), "value", getattr(source, "source_type", None)
        )
    return {
        "document_id": str(document.document_id),
        "knowledge_base_id": str(source.knowledge_base_id) if source is not None else None,
        "source_id": str(document.source_id),
        "source_type": getattr(
            getattr(source, "source_type", None), "value", getattr(source, "source_type", None)
        )
        if source is not None
        else None,
        "document_type": document.document_type,
        "title": document.title,
        "uri": document.uri,
        "version_label": document.version_label,
        "checksum": document.checksum,
        "media_type": document.media_type,
        "size_bytes": document.size_bytes,
        "resolved_uri": document.resolved_uri,
        "fetched_at": document.fetched_at,
        "discovered_at": document.discovered_at,
        "document_metadata": base_metadata or None,
        "is_latest": document.is_latest,
        "status": document.status,
        "registered_at": document.registered_at,
        "availability_status": "unavailable"
        if latest_processing and latest_processing.error_code
        else "available",
        "last_processed_at": getattr(latest_processing, "processed_at", None)
        if latest_processing
        else None,
        "last_processing_status": getattr(
            getattr(latest_processing, "status", None),
            "value",
            getattr(latest_processing, "status", None),
        )
        if latest_processing
        else None,
        "last_error_code": getattr(latest_processing, "error_code", None)
        if latest_processing
        else None,
        "last_error_message": getattr(latest_processing, "error_message", None)
        if latest_processing
        else None,
        "update_run_id": str(document.update_run_id)
        if getattr(document, "update_run_id", None)
        else None,
    }


def serialize_document_snapshot(snapshot: Any, *, serialize_document_chunk: Any) -> dict[str, Any]:
    return {
        "document_snapshot_id": str(snapshot.document_snapshot_id),
        "knowledge_version_id": str(snapshot.knowledge_version_id),
        "document_id": str(snapshot.document_id),
        "checksum": snapshot.checksum,
        "content_format": snapshot.content_format,
        "parser_name": snapshot.parser_name,
        "normalized_text": snapshot.normalized_text,
        "structure_metadata": snapshot.structure_metadata,
        "created_at": snapshot.created_at,
        "chunks": [
            serialize_document_chunk(item)
            for item in sorted(snapshot.chunks, key=lambda item: item.chunk_index)
        ],
    }


def serialize_document_chunk(chunk: Any) -> dict[str, Any]:
    return {
        "document_chunk_id": str(chunk.document_chunk_id),
        "document_snapshot_id": str(chunk.document_snapshot_id),
        "knowledge_version_id": str(chunk.knowledge_version_id),
        "document_id": str(chunk.document_id),
        "chunk_index": chunk.chunk_index,
        "title": chunk.title,
        "source_location": chunk.source_location,
        "content": chunk.content,
        "start_offset": chunk.start_offset,
        "end_offset": chunk.end_offset,
        "chunk_metadata": chunk.chunk_metadata,
        "created_at": chunk.created_at,
    }


def serialize_extracted_item(item: Any) -> dict[str, Any]:
    return {
        "extracted_item_id": str(item.extracted_item_id),
        "knowledge_version_id": str(item.knowledge_version_id),
        "document_id": str(item.document_id),
        "document_chunk_id": str(item.document_chunk_id) if item.document_chunk_id else None,
        "item_type": item.item_type,
        "title": item.title,
        "content": item.content,
        "normalized_value": item.normalized_value,
        "source_location": item.source_location,
        "confidence_score": item.confidence_score,
        "quality_status": item.quality_status,
        "evidence_quote": item.evidence_quote,
        "structured_payload": item.structured_payload,
        "created_at": item.created_at,
    }
