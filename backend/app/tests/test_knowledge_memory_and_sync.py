from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.db.enums import DocumentType, SourceStatus
from app.domain.services.knowledge.update_runtime import dense_embedding_skip_reason
from app.domain.services.knowledge_core import KnowledgeSourceService, KnowledgeUpdateService
from app.integrations.knowledge.knowledge_extraction import (
    DocumentMemoryLlmConfig,
    extract_document_memory,
)


def test_extract_document_memory_returns_summary_and_structured_items() -> None:
    memory = extract_document_memory(
        document_title="Integration Standard",
        document_type=DocumentType.NORMATIVE,
        normalized_text=(
            "API Gateway must validate JWT tokens. "
            "Customer Profile: canonical customer aggregate. "
            "Risk: dependency on external IAM provider. "
            "CRM System -> Billing System over REST API."
        ),
        chunks=[
            {
                "title": "Security Policy",
                "content": (
                    "API Gateway must validate JWT tokens.\n"
                    "Customer Profile: canonical customer aggregate.\n"
                    "Risk: dependency on external IAM provider.\n"
                    "CRM System -> Billing System over REST API."
                ),
                "source_location": "section:1.1",
            }
        ],
    )

    item_types = {item.item_type.value for item in memory.items}
    assert memory.summary
    assert "summary" in item_types
    assert "normative_rule" in item_types
    assert "term" in item_types
    assert "risk" in item_types
    assert "entity_relation" in item_types


def test_heuristic_marker_matching_uses_word_boundaries_and_prefixes() -> None:
    memory = extract_document_memory(
        document_title="Platform Notes",
        document_type=DocumentType.ARCHITECTURE,
        normalized_text=(
            "Rapid delivery page describes the context.\n"
            "Integration layer exposes REST API for billing events.\n"
            "Хранилище не должно превышать ограничения по сроку хранения."
        ),
        chunks=[
            {
                "title": "Platform Notes",
                "content": (
                    "Rapid delivery page describes the context.\n"
                    "Integration layer exposes REST API for billing events.\n"
                    "Хранилище не должно превышать ограничения по сроку хранения."
                ),
                "source_location": "section:2",
            }
        ],
    )

    integration_items = [
        item for item in memory.items if item.item_type.value == "integration_requirement"
    ]
    assert integration_items
    assert all("Rapid delivery" not in item.content for item in integration_items)
    assert any("api" in item.structured_payload.get("matched_markers", []) for item in integration_items)

    constraint_items = [item for item in memory.items if item.item_type.value == "constraint"]
    assert any(
        "ограничения" in item.structured_payload.get("matched_markers", [])
        for item in constraint_items
    )


def test_heuristic_extraction_recognizes_architecture_domain_concepts() -> None:
    content = (
        "The Architecture Repository stores Architecture Building Blocks and Solution Building Blocks.\n"
        "Product Offering and Product Catalog Management are TM Forum domain concepts.\n"
        "The ADM produces an Architecture Definition Document, Statement of Architecture Work, "
        "and Implementation and Migration Plan.\n"
        "Architecture Board reviews Architecture Compliance for the Architecture Contract.\n"
        "Business Capability Map, Value Stream Map, and Application Communication Diagram "
        "capture stakeholder concerns.\n"
        "Целевая архитектура описывает будущий контур платформы.\n"
        "Архитектурный принцип должен соответствовать целевой архитектуре."
    )

    memory = extract_document_memory(
        document_title="TOGAF and TM Forum Notes",
        document_type=DocumentType.ARCHITECTURE,
        normalized_text=content,
        chunks=[
            {
                "title": "TOGAF and TM Forum Notes",
                "content": content,
                "source_location": "section:domain",
            }
        ],
    )

    architecture_items = [
        item
        for item in memory.items
        if item.structured_payload.get("category") == "architecture_concept"
    ]
    assert architecture_items
    matched_markers = {
        marker
        for item in architecture_items
        for marker in item.structured_payload.get("matched_markers", [])
    }
    assert "architecture repository" in matched_markers
    assert "solution building blocks" in matched_markers
    assert "product offering" in matched_markers
    assert "architecture definition document" in matched_markers
    assert "statement of architecture work" in matched_markers
    assert "implementation and migration plan" in matched_markers
    assert "architecture board" in matched_markers
    assert "architecture compliance" in matched_markers
    assert "business capability map" in matched_markers
    assert "application communication diagram" in matched_markers
    assert "целевая архитектура" in matched_markers
    assert any(item.item_type.value == "architectural_principle" for item in memory.items)


def test_heuristic_extraction_recognizes_telecom_and_operating_model_markers() -> None:
    content = (
        "BSS and OSS integration follows Service Oriented Architecture principles.\n"
        "Microservice evolution can reduce Total Cost of Ownership but may create technical debt.\n"
        "The platform exposes an API and authenticates channel partners."
    )

    memory = extract_document_memory(
        document_title="Telecom Operating Model",
        document_type=DocumentType.ARCHITECTURE,
        normalized_text=content,
        chunks=[
            {
                "title": "Telecom Operating Model",
                "content": content,
                "source_location": "section:telecom",
            }
        ],
    )

    integration_markers = {
        marker
        for item in memory.items
        if item.item_type.value == "integration_requirement"
        for marker in item.structured_payload.get("matched_markers", [])
    }
    technology_markers = {
        marker
        for item in memory.items
        if item.item_type.value == "technology_standard"
        for marker in item.structured_payload.get("matched_markers", [])
    }
    risk_markers = {
        marker
        for item in memory.items
        if item.item_type.value == "risk"
        for marker in item.structured_payload.get("matched_markers", [])
    }
    rule_markers = {
        marker
        for item in memory.items
        if item.item_type.value == "mandatory_requirement"
        for marker in item.structured_payload.get("matched_markers", [])
    }

    assert {"bss", "oss", "service oriented architecture"}.issubset(integration_markers)
    assert {"microservice", "soa"}.intersection(technology_markers)
    assert {"total cost of ownership", "technical debt"}.issubset(risk_markers)
    assert {"exposes", "authenticates"}.issubset(rule_markers)


def test_heuristic_extraction_prioritizes_marker_sentences_in_large_chunks() -> None:
    neutral_rows = [
        f"Neutral row {index} describes background context for migration planning."
        for index in range(35)
    ]
    important_row = "Critical Service must validate access tokens before processing requests."
    content = "\n".join([*neutral_rows, important_row])

    memory = extract_document_memory(
        document_title="Security Standard",
        document_type=DocumentType.NORMATIVE,
        normalized_text=content,
        chunks=[
            {
                "title": "Security Standard",
                "content": content,
                "source_location": "table:1",
            }
        ],
    )

    rules = [item for item in memory.items if item.item_type.value == "normative_rule"]
    assert any("Critical Service must validate" in item.content for item in rules)


def test_document_memory_payload_aggregates_items() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.get_document = lambda document_id: object()
    item_a = SimpleNamespace(
        extracted_item_id="i1",
        knowledge_version_id="kv-1",
        document_id="doc-1",
        document_chunk_id=None,
        item_type=SimpleNamespace(value="summary"),
        title="Doc",
        content="Summary",
        normalized_value=None,
        source_location="document:summary",
        confidence_score=0.9,
        quality_status=SimpleNamespace(value="inferred"),
        evidence_quote="q",
        structured_payload={},
        created_at=datetime.now(UTC),
    )
    item_b = SimpleNamespace(
        extracted_item_id="i2",
        knowledge_version_id="kv-1",
        document_id="doc-1",
        document_chunk_id=None,
        item_type=SimpleNamespace(value="constraint"),
        title="Constraint",
        content="Constraint text",
        normalized_value=None,
        source_location="section:1",
        confidence_score=0.8,
        quality_status=SimpleNamespace(value="extracted"),
        evidence_quote="c",
        structured_payload={},
        created_at=datetime.now(UTC),
    )
    service.extracted_items = SimpleNamespace(
        list_for_document=lambda document_id, knowledge_version_id=None: [item_a, item_b]
    )
    service._serialize_extracted_item = KnowledgeSourceService._serialize_extracted_item

    payload = KnowledgeSourceService.get_document_memory_payload(
        service, "doc-1", knowledge_version_id="kv-1"
    )

    assert payload["summary"] == "Summary"
    assert payload["counters"] == {"constraint": 1, "summary": 1}
    assert len(payload["items"]) == 2


def test_large_document_memory_does_not_skip_llm_extraction() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.settings = SimpleNamespace(
        knowledge_large_document_threshold_bytes=1024,
        knowledge_llm_extraction_max_chunks=48,
    )
    document = SimpleNamespace(size_bytes=2048)
    llm_config = DocumentMemoryLlmConfig(
        provider="openai_compatible",
        base_url="http://localhost:11434",
        model_id="demo",
        timeout_sec=1.0,
    )

    reason = KnowledgeUpdateService._document_memory_llm_skip_reason(
        service,
        document=document,
        normalized_text="short text",
        chunk_count=1,
        llm_config=llm_config,
    )

    assert reason is None


def test_large_local_embedding_run_uses_lexical_only_policy() -> None:
    reason = dense_embedding_skip_reason(
        embedding_descriptor={"provider_name": "local_inference"},
        chunk_count=120,
        index_metadata={"adaptive_chunking_reason": "large_document"},
        settings=SimpleNamespace(knowledge_local_embedding_max_chunks=96),
    )

    assert reason == "local_embedding_large_document_chunk_count:120>96"
    assert (
        dense_embedding_skip_reason(
            embedding_descriptor={"provider_name": "openai_compatible"},
            chunk_count=120,
            index_metadata={"adaptive_chunking_reason": "large_document"},
            settings=SimpleNamespace(knowledge_local_embedding_max_chunks=96),
        )
        is None
    )


def test_run_due_scheduled_syncs_starts_only_overdue_bases() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    now = datetime.now(UTC)
    due_base = SimpleNamespace(knowledge_base_id="kb-due", status=SourceStatus.ACTIVE)
    fresh_base = SimpleNamespace(knowledge_base_id="kb-fresh", status=SourceStatus.ACTIVE)
    service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)
    service.sources = SimpleNamespace(list_active=lambda knowledge_base_id=None: [object()])
    service.update_runs = SimpleNamespace(
        get_latest_finished=lambda knowledge_base_id=None: None
        if knowledge_base_id == "kb-due"
        else SimpleNamespace(finished_at=now - timedelta(days=1))
    )
    service._create_run = lambda **kwargs: SimpleNamespace(
        update_run_id=f"run-{kwargs['payload'].knowledge_base_id}",
        knowledge_base_id=kwargs["payload"].knowledge_base_id,
    )
    service.session = None

    base_repo = SimpleNamespace(list_visible=lambda: [due_base, fresh_base])
    fake_base_service = SimpleNamespace(bases=base_repo)

    # patch constructor usage inside the method by temporarily rebinding module global
    import app.domain.services.knowledge_core as knowledge_core_module

    original_service = knowledge_core_module.KnowledgeBaseService
    knowledge_core_module.KnowledgeBaseService = lambda session: fake_base_service
    try:
        payload = KnowledgeUpdateService.run_due_scheduled_syncs(
            service, now=now, execute_inline=False
        )
    finally:
        knowledge_core_module.KnowledgeBaseService = original_service

    assert payload["started_knowledge_base_ids"] == ["kb-due"]
    assert "kb-fresh" in payload["skipped_knowledge_base_ids"]
