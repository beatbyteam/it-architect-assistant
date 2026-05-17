from __future__ import annotations

from app.integrations.generation.llm_gateway import RetrievedFragment, _sanitize_prompt_artifact
from app.integrations.generation.prompt_builder import (
    RETRIEVAL_CONTEXT_CONTRACT_VERSION,
    GenerationPromptBuilder,
)
from app.integrations.generation.prompt_registry import PromptTemplate
from app.integrations.generation.token_budget import TokenBudgetManager
from app.integrations.knowledge.retrieval_policies import (
    RetrievalCandidate,
    lexical_rank_candidates,
    reciprocal_rank_fuse,
)


def test_lexical_rank_candidates_prefers_exact_term_match() -> None:
    candidates = [
        RetrievalCandidate(
            fragment_id="f1",
            document_id="d1",
            title="Caching strategy",
            content="Redis cache invalidation and TTL strategy",
        ),
        RetrievalCandidate(
            fragment_id="f2",
            document_id="d2",
            title="Billing",
            content="Invoice lifecycle and payment reconciliation",
        ),
    ]

    ranked, diagnostics = lexical_rank_candidates(
        query_text="redis cache ttl", candidates=candidates
    )

    assert ranked[0].fragment_id == "f1"
    assert diagnostics.backend == "bm25_python"
    assert ranked[0].lexical_score > ranked[1].lexical_score


def test_reciprocal_rank_fuse_rewards_candidates_appearing_in_multiple_lists() -> None:
    a = RetrievalCandidate(fragment_id="a", document_id="d1", title="A", content="alpha")
    b = RetrievalCandidate(fragment_id="b", document_id="d2", title="B", content="beta")
    c = RetrievalCandidate(fragment_id="c", document_id="d3", title="C", content="gamma")

    fused = reciprocal_rank_fuse(rankings=[[a, b, c], [b, a], [b]], k=60)

    assert fused["b"] > fused["a"] > fused["c"]


def test_prompt_builder_emits_retrieval_contract_and_provenance() -> None:
    builder = GenerationPromptBuilder(
        TokenBudgetManager(max_input_tokens=4096, reserved_output_tokens=512)
    )
    template = PromptTemplate(
        version_id="test.v1",
        template_name="test",
        system_prompt="Return JSON only",
        user_prompt_template="Task\n{task_text}\n\nContext\n{context_block}\n\nKnowledge\n{knowledge_block}\n\nPlan\n{section_plan_block}",
        output_contract_name="generation",
    )
    fragments = [
        RetrievedFragment(
            fragment_id="frag-1",
            document_id="doc-1",
            title="API Gateway",
            content="Gateway exposes REST endpoints for partner integrations.",
            fragment_type="api",
            source_location="page=2",
            score=0.92,
            lexical_score=0.55,
            vector_score=0.83,
            keyword_score=0.5,
            metadata={
                "document_title": "Partner API Spec",
                "role_code": "api_contract",
                "required_flag": True,
                "document_type": "api",
                "section_heading": "Authentication",
            },
        )
    ]

    artifact = builder.build(
        template=template,
        task_title="Design integration",
        task_text="Need an external partner integration",
        context_items=["Use REST API"],
        retrieved_fragments=fragments,
    )

    assert artifact.retrieval_contract_version == RETRIEVAL_CONTEXT_CONTRACT_VERSION
    assert "Retrieved knowledge evidence only" in artifact.knowledge_block
    assert "document_title=Partner API Spec" in artifact.knowledge_block
    assert "role_code=api_contract" in artifact.knowledge_block
    assert "required_flag=yes" in artifact.knowledge_block
    assert artifact.knowledge_manifest[0]["fragment_id"] == "frag-1"


def test_prompt_builder_caps_large_fragment_content() -> None:
    builder = GenerationPromptBuilder(
        TokenBudgetManager(max_input_tokens=4096, reserved_output_tokens=512),
        fragment_char_limit=240,
    )
    template = PromptTemplate(
        version_id="test.v1",
        template_name="test",
        system_prompt="Return JSON only",
        user_prompt_template="{task_text}\n{context_block}\n{knowledge_block}\n{section_plan_block}",
        output_contract_name="generation",
    )
    fragment = RetrievedFragment(
        fragment_id="frag-large",
        document_id="doc-1",
        title="Large evidence",
        content=" ".join(["important architectural evidence"] * 200),
        fragment_type="requirement",
        metadata={"document_title": "Large Spec"},
    )

    artifact = builder.build(
        template=template,
        task_title="Task",
        task_text="Need architecture.",
        context_items=[],
        retrieved_fragments=[fragment],
    )

    assert "content_truncated=yes" in artifact.knowledge_block
    assert len(artifact.knowledge_block) < len(fragment.content)


def test_sanitize_prompt_artifact_strips_unapproved_payload() -> None:
    payload = {
        "system_prompt": "sys",
        "user_prompt": "usr",
        "knowledge_block": "kb",
        "retrieval_contract_version": RETRIEVAL_CONTEXT_CONTRACT_VERSION,
        "raw_document_payload": {"huge": True},
    }

    sanitized = _sanitize_prompt_artifact(payload)

    assert sanitized is not None
    assert sanitized["retrieval_contract_version"] == RETRIEVAL_CONTEXT_CONTRACT_VERSION
    assert sanitized["raw_documents_included"] is False
    assert "raw_document_payload" not in sanitized
