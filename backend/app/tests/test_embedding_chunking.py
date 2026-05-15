from __future__ import annotations

from app.db.enums import DocumentType
from app.integrations.knowledge.content_loader import NormalizedDocument, StructuredSection
from app.integrations.knowledge.embedding import (
    EmbeddingBatchResult,
    EmbeddingProfileRegistry,
    EmbeddingService,
)
from app.integrations.knowledge.indexing_pipeline import prepare_document_index
from app.integrations.knowledge.text_processing import chunk_document, estimate_token_count


def test_bge_m3_profile_is_available_for_local_retrieval() -> None:
    profile = EmbeddingProfileRegistry.get("bge_m3_default")
    assert profile.provider_name == "local_openai_compatible"
    assert profile.model_id == "bge-m3"
    assert profile.dimensions == 1024


def test_chunk_document_uses_sections_and_token_budget() -> None:
    sections = [
        StructuredSection(
            heading="Business Architecture",
            content="System actor performs onboarding and submits request. " * 40,
            source_location="section:business",
            metadata={"line_range": [1, 10]},
        ),
        StructuredSection(
            heading="Application Architecture",
            content="Service component publishes integration event and persists audit trail. " * 40,
            source_location="section:application",
            metadata={"line_range": [11, 20]},
        ),
    ]
    chunks = chunk_document(
        "",
        document_type=DocumentType.ARCHITECTURE,
        sections=sections,
        target_tokens=90,
        overlap_tokens=12,
        max_chars=600,
        document_title="Architecture Guide",
    )
    assert len(chunks) >= 2
    assert chunks[0].title == "Business Architecture"
    assert chunks[0].source_location == "section:business"
    assert chunks[0].metadata["document_title"] == "Architecture Guide"
    assert chunks[0].metadata["chunk_token_count"] <= 110
    assert all(estimate_token_count(chunk.content) <= 110 for chunk in chunks)


def test_chunk_document_respects_zero_overlap() -> None:
    sections = [
        StructuredSection(
            heading="Large Section",
            content="\n\n".join(f"Sentence {index} " * 20 for index in range(1, 12)),
            source_location="section:large",
        )
    ]

    chunks = chunk_document(
        "",
        document_type=DocumentType.OTHER,
        sections=sections,
        target_tokens=70,
        overlap_tokens=0,
        max_chars=500,
        document_title="Large Guide",
    )

    assert len(chunks) > 1
    assert "Sentence 1" in chunks[0].content
    assert "Sentence 1" not in chunks[1].content


def test_remote_embedding_service_batches_large_document_requests() -> None:
    class RecordingProvider:
        provider_name = "fake_remote"
        model_id = "fake-model"

        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def encode_texts(self, texts: list[str], *, dimensions: int) -> EmbeddingBatchResult:
            self.batch_sizes.append(len(texts))
            return EmbeddingBatchResult(
                vectors=[[float(len(self.batch_sizes))] * dimensions for _ in texts],
                provider_name=self.provider_name,
                model_id=self.model_id,
                dimensions=dimensions,
                diagnostics={"text_count": len(texts), "latency_ms": 1.5},
            )

    service = EmbeddingService(
        provider_name="openai_compatible",
        dimensions=4,
        base_url="http://embeddings.example.test",
        model_id="fake-model",
        batch_size=16,
    )
    provider = RecordingProvider()
    service.provider = provider
    progress_events: list[dict[str, object]] = []

    result = service.encode_documents(
        [f"chunk {index}" for index in range(35)],
        progress_callback=lambda event: progress_events.append(event),
    )

    assert provider.batch_sizes == [16, 16, 3]
    assert len(result.vectors) == 35
    assert result.diagnostics["mode"] == "batched"
    assert result.diagnostics["batch_count"] == 3
    assert [event["completed_batches"] for event in progress_events] == [1, 2, 3]
    assert progress_events[-1]["completed_texts"] == 35


def test_prepare_document_index_uses_large_document_policy() -> None:
    large_text = "Large document sentence. " * 150
    normalized = NormalizedDocument(
        text=large_text,
        content_format="markdown",
        parser_name="test",
        sections=[
            StructuredSection(
                heading="Large",
                content=large_text,
                source_location="lines:1-150",
            )
        ],
    )

    result = prepare_document_index(
        normalized,
        document_type=DocumentType.OTHER,
        document_title="Large guide",
        chunk_target_tokens=420,
        chunk_overlap_pct=12,
        chunk_max_chars=2200,
        large_document_threshold_bytes=1024,
        large_document_chunk_target_tokens=900,
        large_document_chunk_overlap_pct=0,
        large_document_chunk_max_chars=6000,
        original_size_bytes=13_400_000,
    )

    assert result.canonical_metadata["adaptive_chunking"] is True
    assert result.canonical_metadata["adaptive_chunking_reason"] == "large_document"
    assert result.canonical_metadata["chunk_target_tokens"] == 900
    assert result.canonical_metadata["chunk_overlap_pct"] == 0
    assert result.canonical_metadata["chunk_max_chars"] == 6000
    assert result.canonical_metadata["document_input_size_bytes"] == 13_400_000
