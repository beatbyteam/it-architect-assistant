from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.enums import DocumentType
from app.integrations.knowledge.content_loader import NormalizedDocument
from app.integrations.knowledge.text_processing import (
    CHUNKING_POLICY_VERSION,
    ChunkedText,
    chunk_document,
    summarize_chunk_distribution,
)

INDEXING_PIPELINE_VERSION = "knowledge-indexing-v1"
DEFAULT_LARGE_DOCUMENT_THRESHOLD_BYTES = 1_048_576
DEFAULT_LARGE_DOCUMENT_CHUNK_TARGET_TOKENS = 900
DEFAULT_LARGE_DOCUMENT_MAX_TARGET_TOKENS = 1800
DEFAULT_LARGE_DOCUMENT_CHUNK_MAX_CHARS = 6000
DEFAULT_LARGE_DOCUMENT_CHUNK_OVERLAP_PCT = 0
DEFAULT_LARGE_DOCUMENT_MAX_CHUNKS = 240


@dataclass(slots=True)
class PreparedDocumentIndex:
    chunks: list[ChunkedText]
    metrics: dict[str, Any]
    canonical_metadata: dict[str, Any]


def prepare_document_index(
    normalized: NormalizedDocument,
    *,
    document_type: DocumentType,
    document_title: str | None,
    chunk_target_tokens: int,
    chunk_overlap_pct: int,
    chunk_max_chars: int,
    large_document_threshold_bytes: int | None = None,
    large_document_chunk_target_tokens: int | None = None,
    large_document_chunk_overlap_pct: int | None = None,
    large_document_chunk_max_chars: int | None = None,
    original_size_bytes: int | None = None,
    large_document_max_chunks: int | None = None,
) -> PreparedDocumentIndex:
    resolved_target_tokens = int(chunk_target_tokens)
    resolved_overlap_pct = int(chunk_overlap_pct)
    resolved_max_chars = int(chunk_max_chars)
    large_threshold = (
        DEFAULT_LARGE_DOCUMENT_THRESHOLD_BYTES
        if large_document_threshold_bytes is None
        else int(large_document_threshold_bytes)
    )
    text_size_bytes = len((normalized.text or "").encode("utf-8"))
    input_size_bytes = max(text_size_bytes, int(original_size_bytes or 0))
    is_large_document = large_threshold > 0 and input_size_bytes >= large_threshold
    adaptive_chunking = False
    adaptive_reason: str | None = None
    large_max_chunks = (
        DEFAULT_LARGE_DOCUMENT_MAX_CHUNKS
        if large_document_max_chunks is None
        else int(large_document_max_chunks)
    )
    if is_large_document:
        resolved_target_tokens = max(
            resolved_target_tokens,
            int(
                large_document_chunk_target_tokens
                or DEFAULT_LARGE_DOCUMENT_CHUNK_TARGET_TOKENS
            ),
        )
        resolved_max_chars = max(
            resolved_max_chars,
            int(large_document_chunk_max_chars or DEFAULT_LARGE_DOCUMENT_CHUNK_MAX_CHARS),
        )
        resolved_overlap_pct = int(
            large_document_chunk_overlap_pct
            if large_document_chunk_overlap_pct is not None
            else DEFAULT_LARGE_DOCUMENT_CHUNK_OVERLAP_PCT
        )
        estimated_tokens = max(1, text_size_bytes // 4)
        if large_max_chunks > 0 and estimated_tokens / max(resolved_target_tokens, 1) > large_max_chunks:
            capped_target_tokens = min(
                round(estimated_tokens / large_max_chunks),
                DEFAULT_LARGE_DOCUMENT_MAX_TARGET_TOKENS,
            )
            resolved_target_tokens = max(resolved_target_tokens, capped_target_tokens)
            resolved_max_chars = max(resolved_max_chars, resolved_target_tokens * 6)
        adaptive_chunking = True
        adaptive_reason = "large_document"
    elif normalized.content_format == "xlsx" and len(normalized.text) > 1_000_000:
        resolved_target_tokens = max(resolved_target_tokens, 800)
        resolved_max_chars = max(resolved_max_chars, 4500)
        resolved_overlap_pct = 0
        adaptive_chunking = True
        adaptive_reason = "large_xlsx"

    overlap_tokens = max(0, round(resolved_target_tokens * max(0, resolved_overlap_pct) / 100))
    chunks = chunk_document(
        normalized.text,
        max_chars=resolved_max_chars,
        document_type=document_type,
        sections=normalized.sections,
        target_tokens=resolved_target_tokens,
        overlap_tokens=overlap_tokens,
        document_title=document_title,
    )
    chunk_metrics = summarize_chunk_distribution(chunks)
    canonical_metadata = {
        "indexing_pipeline_version": INDEXING_PIPELINE_VERSION,
        "chunking_policy_version": CHUNKING_POLICY_VERSION,
        "chunk_target_tokens": int(resolved_target_tokens),
        "chunk_overlap_pct": int(resolved_overlap_pct),
        "chunk_overlap_tokens": int(overlap_tokens),
        "chunk_max_chars": int(resolved_max_chars),
        "large_document_max_target_tokens": int(DEFAULT_LARGE_DOCUMENT_MAX_TARGET_TOKENS),
        "adaptive_chunking": adaptive_chunking,
        "adaptive_chunking_reason": adaptive_reason,
        "large_document_threshold_bytes": int(large_threshold),
        "large_document_max_chunks": int(large_max_chunks),
        "document_text_size_bytes": int(text_size_bytes),
        "document_input_size_bytes": int(input_size_bytes),
        "section_count": len(normalized.sections),
        "chunk_count": len(chunks),
    }
    return PreparedDocumentIndex(
        chunks=chunks,
        metrics={
            **chunk_metrics,
            **canonical_metadata,
        },
        canonical_metadata=canonical_metadata,
    )
