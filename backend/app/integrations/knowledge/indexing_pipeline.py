from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.enums import DocumentType
from app.integrations.knowledge.content_loader import NormalizedDocument
from app.integrations.knowledge.text_processing import (
    CHUNKING_POLICY_VERSION,
    ChunkedText,
    chunk_document,
    estimate_token_count,
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
    compacted_chunk_count_before: int | None = None
    if is_large_document and large_max_chunks > 0 and len(chunks) > large_max_chunks:
        compacted_chunk_count_before = len(chunks)
        chunks = _compact_chunks_to_limit(chunks, max_chunks=large_max_chunks)
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
        "chunk_compaction_applied": compacted_chunk_count_before is not None,
        "chunk_count_before_compaction": compacted_chunk_count_before,
    }
    return PreparedDocumentIndex(
        chunks=chunks,
        metrics={
            **chunk_metrics,
            **canonical_metadata,
        },
        canonical_metadata=canonical_metadata,
    )


def _compact_chunks_to_limit(chunks: list[ChunkedText], *, max_chunks: int) -> list[ChunkedText]:
    if max_chunks <= 0 or len(chunks) <= max_chunks:
        return chunks
    remaining_tokens = [max(1, estimate_token_count(chunk.content)) for chunk in chunks]
    compacted: list[ChunkedText] = []
    index = 0
    while index < len(chunks) and len(compacted) < max_chunks:
        remaining_groups = max_chunks - len(compacted)
        remaining_token_total = sum(remaining_tokens[index:])
        target_tokens = max(1, round(remaining_token_total / remaining_groups))
        group: list[ChunkedText] = []
        group_tokens = 0
        while index < len(chunks):
            group.append(chunks[index])
            group_tokens += remaining_tokens[index]
            index += 1
            chunks_left = len(chunks) - index
            groups_left = remaining_groups - 1
            if groups_left <= 0:
                continue
            if group_tokens >= target_tokens and chunks_left >= groups_left:
                break
            if chunks_left == groups_left:
                break
        compacted.append(_merge_chunk_group(group, chunk_index=len(compacted) + 1))
    if index < len(chunks):
        tail = _merge_chunk_group(chunks[index:], chunk_index=len(compacted))
        previous = compacted.pop() if compacted else None
        compacted.append(
            _merge_chunk_group(
                [item for item in [previous, tail] if item is not None],
                chunk_index=len(compacted) + 1,
            )
        )
    return compacted


def _merge_chunk_group(group: list[ChunkedText], *, chunk_index: int) -> ChunkedText:
    if len(group) == 1:
        chunk = group[0]
        metadata = {
            **(chunk.metadata or {}),
            "chunk_index": chunk_index,
            "chunk_token_count": estimate_token_count(chunk.content),
        }
        return ChunkedText(
            title=chunk.title,
            content=chunk.content,
            source_location=chunk.source_location,
            fragment_type=chunk.fragment_type,
            metadata=metadata,
        )
    content = "\n\n".join(chunk.content.strip() for chunk in group if chunk.content.strip())
    source_locations = [
        str(chunk.source_location)
        for chunk in group
        if str(chunk.source_location or "").strip()
    ]
    first = group[0]
    metadata = {
        **(first.metadata or {}),
        "chunk_index": chunk_index,
        "chunk_token_count": estimate_token_count(content),
        "compacted_chunk": True,
        "compacted_source_chunk_count": len(group),
        "source_locations": source_locations[:50],
        "source_locations_truncated": len(source_locations) > 50,
    }
    return ChunkedText(
        title=first.title,
        content=content,
        source_location=f"compact:{chunk_index}",
        fragment_type=first.fragment_type,
        metadata=metadata,
    )
