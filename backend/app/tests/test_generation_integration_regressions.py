from __future__ import annotations

import json

from app.db.enums import CheckResultStatus, DocumentType, ProtocolSummaryStatus, Severity
from app.integrations.generation.llm_gateway import (
    LLMGateway,
    OpenAICompatibleSolutionProvider,
    RetrievedFragment,
)
from app.integrations.generation.prompt_builder import GenerationPromptBuilder
from app.integrations.generation.prompt_registry import PromptTemplate
from app.integrations.generation.token_budget import TokenBudgetManager
from app.integrations.knowledge.content_loader import normalize_document_payload
from app.integrations.knowledge.embedding import OpenAICompatibleEmbeddingProvider
from app.integrations.knowledge.knowledge_extraction import (
    DocumentMemoryLlmConfig,
    _resolve_chat_completions_url,
    extract_document_memory,
)
from app.integrations.knowledge.reranker import OpenAICompatibleRerankerProvider
from app.integrations.knowledge.retrieval_policies import GENERATION_POLICY_V1, RetrievalCandidate
from app.integrations.knowledge.text_processing import chunk_text
from app.integrations.verification.contracts import (
    VerificationCheckResultPayload,
    VerificationProtocolPayload,
)
from app.integrations.verification.renderer import VerificationProtocolRenderer


def test_token_budget_never_exceeds_model_input_limit() -> None:
    manager = TokenBudgetManager(max_input_tokens=200, reserved_output_tokens=300)
    assert manager.available_input_tokens == 0


def test_prompt_builder_tracks_non_contiguous_fragment_selection() -> None:
    builder = GenerationPromptBuilder(
        TokenBudgetManager(max_input_tokens=300, reserved_output_tokens=0)
    )
    template = PromptTemplate(
        version_id="generation.test",
        template_name="Generation Test",
        system_prompt="Return JSON",
        user_prompt_template="{task_text}\n{context_block}\n{knowledge_block}\n{section_plan_block}",
        output_contract_name="generation",
    )
    fragments = [
        RetrievedFragment(
            fragment_id="frag-1", document_id="doc-1", title="One", content="Short evidence."
        ),
        RetrievedFragment(
            fragment_id="frag-2",
            document_id="doc-2",
            title="Two",
            content=" ".join(["oversized"] * 1000),
        ),
        RetrievedFragment(
            fragment_id="frag-3",
            document_id="doc-3",
            title="Three",
            content="Another short evidence.",
        ),
    ]

    artifact = builder.build(
        template=template,
        task_title="Task",
        task_text="Describe the architecture.",
        context_items=[],
        retrieved_fragments=fragments,
    )

    assert artifact.included_fragment_ids == ["frag-1", "frag-3"]
    assert artifact.dropped_fragment_ids == ["frag-2"]
    assert [item["fragment_id"] for item in artifact.retrieval_trace["included_fragments"]] == [
        "frag-1",
        "frag-3",
    ]


def test_openai_compatible_urls_are_resolved_to_v1_endpoints() -> None:
    llm_provider = OpenAICompatibleSolutionProvider(
        base_url="http://localhost:11434", model_id="demo"
    )
    embedding_provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://localhost:11434", model_id="embed-demo"
    )

    assert (
        llm_provider._resolve_chat_completions_url() == "http://localhost:11434/v1/chat/completions"
    )
    assert embedding_provider._resolve_embeddings_url() == "http://localhost:11434/v1/embeddings"
    assert (
        _resolve_chat_completions_url("http://localhost:11434")
        == "http://localhost:11434/v1/chat/completions"
    )


def test_llm_healthcheck_treats_missing_route_as_unhealthy(monkeypatch) -> None:
    class _Response:
        status_code = 404

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def get(self, url: str):
            return _Response()

    monkeypatch.setattr("app.integrations.generation.llm_gateway.httpx.Client", _Client)
    gateway = LLMGateway(
        provider="openai_compatible",
        base_url="http://localhost:11434",
        model_id="demo",
    )

    result = gateway.healthcheck()

    assert result["healthy"] is False
    assert result["status_code"] == 404


def test_llm_healthcheck_accepts_method_not_allowed_probe(monkeypatch) -> None:
    class _Response:
        status_code = 405

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def get(self, url: str):
            return _Response()

    monkeypatch.setattr("app.integrations.generation.llm_gateway.httpx.Client", _Client)
    gateway = LLMGateway(
        provider="openai_compatible",
        base_url="http://localhost:11434",
        model_id="demo",
    )

    result = gateway.healthcheck()

    assert result["healthy"] is True
    assert result["status_code"] == 405


def test_suffixless_uri_can_be_normalized_by_media_type() -> None:
    payload = normalize_document_payload(
        "https://example.com/download?id=42",
        b'{"service": "gateway", "status": "active"}',
        media_type="application/json; charset=utf-8",
    )
    assert payload.content_format == "json"
    assert '"service": "gateway"' in payload.text


def test_plain_text_documents_are_supported() -> None:
    payload = normalize_document_payload("notes.txt", b"Line one\n\nLine two")
    assert payload.content_format == "txt"
    assert "Line one" in payload.text


def test_architecture_chunking_keeps_preamble_before_first_heading() -> None:
    chunks = chunk_text(
        document_type=DocumentType.ARCHITECTURE,
        text="Context and scope for the solution.\n\n# Business Architecture\n\nBusiness flow description.",
        max_chars=300,
    )
    assert chunks[0].content.startswith("Context and scope")
    assert chunks[0].title is not None


def test_heuristic_document_memory_extracts_cyrillic_entities() -> None:
    memory = extract_document_memory(
        document_title="Архитектурное решение",
        document_type=DocumentType.ARCHITECTURE,
        normalized_text="Платежный Шлюз интегрируется с CRM Система.",
        chunks=[
            {
                "document_chunk_id": "chunk-1",
                "title": "Контекст",
                "content": "Платежный Шлюз интегрируется с CRM Система.",
                "source_location": "lines:1-1",
            }
        ],
        llm_config=None,
    )
    entities = [item.normalized_value for item in memory.items if item.item_type.value == "entity"]
    assert any(entity == "Платежный Шлюз" for entity in entities)


def test_verification_renderer_outputs_unknown_groups() -> None:
    payload = VerificationProtocolPayload(
        final_status=ProtocolSummaryStatus.PASSED_WITH_COMMENTS,
        summary="Checks completed",
        check_results=[
            VerificationCheckResultPayload(
                rule_group="traceability",
                rule_code="TRACE-1",
                check_name="Traceability matrix",
                status=CheckResultStatus.WARNING,
                severity=Severity.MINOR,
                finding_text="Matrix is partial",
                evidence_ref="sec-1",
                related_section_ref="general_information",
            )
        ],
    )
    html = VerificationProtocolRenderer().render_html(protocol_no="VP-1", payload=payload)
    assert "Traceability" in html
    assert "TRACE-1" in html


def test_document_memory_llm_unwraps_wrapped_json_payload(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"result":{"summary":"Gateway summary","items":[{"item_type":"integration_requirement","title":"POST /payments","content":"Gateway exposes POST /payments","source_location":"lines:1-1"}]}}\n'
                                "```"
                            )
                        }
                    }
                ]
            }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def post(self, url: str, json: dict[str, object], headers: dict[str, str]):
            return _Response()

    monkeypatch.setattr("app.integrations.knowledge.knowledge_extraction.httpx.Client", _Client)

    memory = extract_document_memory(
        document_title="Payments API",
        document_type=DocumentType.API,
        normalized_text="POST /payments integrates with the gateway.",
        chunks=[
            {
                "document_chunk_id": "chunk-1",
                "title": "API",
                "content": "POST /payments integrates with the gateway.",
                "source_location": "lines:1-1",
            }
        ],
        llm_config=DocumentMemoryLlmConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434",
            api_key=None,
            model_id="demo",
            timeout_sec=1.0,
        ),
    )

    item_types = {item.item_type.value for item in memory.items}
    assert memory.extraction_method == "llm"
    assert memory.fallback_applied is False
    assert "integration_requirement" in item_types


def test_document_memory_llm_batches_all_chunks(monkeypatch) -> None:
    captured_chunk_locations: list[str] = []
    progress_events: list[dict[str, object]] = []

    class _Response:
        def __init__(self, summary: str, source_location: str) -> None:
            self._summary = summary
            self._source_location = source_location

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": self._summary,
                                    "items": [
                                        {
                                            "item_type": "entity",
                                            "title": self._summary,
                                            "content": self._summary,
                                            "source_location": self._source_location,
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def post(self, url: str, json: dict[str, object], headers: dict[str, str]):
            request_payload = __import__("json").loads(
                str(json["messages"][1]["content"])  # type: ignore[index]
            )
            chunk_locations = [chunk["source_location"] for chunk in request_payload["chunks"]]
            captured_chunk_locations.extend(chunk_locations)
            return _Response(
                summary=f"Batch {request_payload['chunk_batch_index']}",
                source_location=str(chunk_locations[-1]),
            )

    monkeypatch.setattr("app.integrations.knowledge.knowledge_extraction.httpx.Client", _Client)

    chunks = [
        {
            "document_chunk_id": f"chunk-{index}",
            "title": f"Page {index}",
            "content": f"Important information from page {index}.",
            "source_location": f"page:{index}",
        }
        for index in range(1, 11)
    ]
    memory = extract_document_memory(
        document_title="Large Component Spec",
        document_type=DocumentType.OTHER,
        normalized_text="\n".join(str(chunk["content"]) for chunk in chunks),
        chunks=chunks,
        llm_config=DocumentMemoryLlmConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434",
            api_key=None,
            model_id="demo",
            timeout_sec=1.0,
        ),
        progress_callback=lambda event: progress_events.append(event),
    )

    assert captured_chunk_locations == [f"page:{index}" for index in range(1, 11)]
    assert progress_events[0]["completed_batches"] == 0
    assert progress_events[0]["total_batches"] == 3
    assert progress_events[-1]["completed_batches"] == 3
    assert progress_events[-1]["total_chunks"] == 10
    assert memory.extraction_method == "llm"
    assert memory.fallback_applied is False
    assert memory.items[0].structured_payload["extraction_batches"] == 3
    assert memory.items[0].structured_payload["covered_chunk_count"] == 10


def test_document_memory_invalid_llm_json_falls_back_to_heuristic(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "not-json-at-all"}}]}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def post(self, url: str, json: dict[str, object], headers: dict[str, str]):
            return _Response()

    monkeypatch.setattr("app.integrations.knowledge.knowledge_extraction.httpx.Client", _Client)

    memory = extract_document_memory(
        document_title="Payments API",
        document_type=DocumentType.API,
        normalized_text="GET /status shall be available for health probes.",
        chunks=[
            {
                "document_chunk_id": "chunk-1",
                "title": "API",
                "content": "GET /status shall be available for health probes.",
                "source_location": "lines:1-1",
            }
        ],
        llm_config=DocumentMemoryLlmConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434",
            api_key=None,
            model_id="demo",
            timeout_sec=1.0,
        ),
    )

    assert memory.llm_attempted is True
    assert memory.fallback_applied is True
    assert memory.extraction_method == "heuristic"
    assert memory.fallback_reason
    assert any(
        item.structured_payload.get("extraction_method") == "heuristic" for item in memory.items
    )


def test_reranker_unwraps_fenced_wrapped_scores_payload(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"result":{"scores":[{"fragment_id":"frag-2","score":0.99},{"fragment_id":"frag-1","score":0.01}]}}\n'
                                "```"
                            )
                        }
                    }
                ]
            }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def post(self, url: str, json: dict[str, object], headers: dict[str, str]):
            return _Response()

    monkeypatch.setattr("app.integrations.knowledge.reranker.httpx.Client", _Client)

    provider = OpenAICompatibleRerankerProvider(
        base_url="http://localhost:11434",
        api_key=None,
        timeout_sec=1.0,
        model_id="rerank-demo",
    )
    candidates = [
        RetrievalCandidate(
            fragment_id="frag-1",
            document_id="doc-1",
            title="Payments",
            content="payments gateway api",
        ),
        RetrievalCandidate(
            fragment_id="frag-2",
            document_id="doc-2",
            title="Other",
            content="unrelated content",
        ),
    ]

    ranked, diagnostics = provider.rerank(
        query_text="payments gateway api",
        candidates=candidates,
        policy=GENERATION_POLICY_V1,
    )

    assert diagnostics.backend == "semantic_llm"
    assert diagnostics.fallback_used is False
    assert ranked[0].candidate.fragment_id == "frag-2"


def test_reranker_falls_back_when_llm_payload_has_no_scores(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"result":{"items":[]}}'}}]}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb) -> None:
            return None

        def post(self, url: str, json: dict[str, object], headers: dict[str, str]):
            return _Response()

    monkeypatch.setattr("app.integrations.knowledge.reranker.httpx.Client", _Client)

    provider = OpenAICompatibleRerankerProvider(
        base_url="http://localhost:11434",
        api_key=None,
        timeout_sec=1.0,
        model_id="rerank-demo",
    )
    candidates = [
        RetrievalCandidate(
            fragment_id="frag-1",
            document_id="doc-1",
            title="Payments",
            content="payments gateway api",
        ),
        RetrievalCandidate(
            fragment_id="frag-2",
            document_id="doc-2",
            title="Other",
            content="unrelated content",
        ),
    ]

    ranked, diagnostics = provider.rerank(
        query_text="payments gateway api",
        candidates=candidates,
        policy=GENERATION_POLICY_V1,
    )

    assert diagnostics.backend == "heuristic_fallback"
    assert diagnostics.fallback_used is True
    assert ranked[0].candidate.fragment_id == "frag-1"
