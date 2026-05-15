from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    ExtractedKnowledgeType,
    ExtractionQualityStatus,
    FragmentStatus,
    FragmentType,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    RuleCategory,
    Severity,
)
from app.db.models.knowledge import (
    DocumentChunk,
    DocumentExtractedItem,
    DocumentSnapshot,
    EmbeddingSpace,
    KnowledgeFragment,
    KnowledgeFragmentEmbedding,
    KnowledgeUpdateRun,
    KnowledgeVersion,
    NormativeRule,
)
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.schemas.knowledge import KnowledgeUpdateRunStartRequest


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="local.system",
        login="local.user",
        display_name="Local User",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )


def test_build_public_start_payload_preserves_document_scope_and_profile_switch() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    payload = KnowledgeUpdateRunStartRequest(
        knowledge_base_id="kb-1",
        selected_source_ids=["src-1"],
        source_scope="selected",
        document_ids=["doc-1", "doc-1", "doc-2"],
        force_reindex_all_in_scope=True,
        force_reindex_document_ids=["doc-2"],
        target_embedding_profile="embeddinggemma_lite",
        reason="switch profile",
    )

    internal = KnowledgeUpdateService.build_public_start_payload(service, payload, _principal())

    assert internal.document_ids == ["doc-1", "doc-2"]
    assert internal.force_reindex_all_in_scope is True
    assert internal.force_reindex_document_ids == ["doc-2"]
    assert internal.target_embedding_profile == "embeddinggemma_lite"


def test_clone_document_artifacts_can_reuse_snapshot_from_another_document_id() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.session = SimpleNamespace(add=lambda *_: None, flush=lambda: None)
    service.document_chunks = SimpleNamespace(
        list_for_snapshot=lambda snapshot_id: [
            DocumentChunk(
                document_chunk_id="chunk-old-1",
                document_snapshot_id=snapshot_id,
                knowledge_version_id="kv-src",
                document_id="doc-origin",
                chunk_index=1,
                title="Section A",
                source_location="p1",
                content="Important architecture rule",
                start_offset=0,
                end_offset=24,
                chunk_metadata={"kind": "section"},
            )
        ]
    )
    service.extracted_items = SimpleNamespace(
        list_for_document=lambda document_id, knowledge_version_id=None: [
            DocumentExtractedItem(
                extracted_item_id="item-1",
                knowledge_version_id="kv-src",
                document_id=document_id,
                document_chunk_id="chunk-old-1",
                item_type=ExtractedKnowledgeType.SUMMARY,
                title="Summary",
                content="Cached summary",
                normalized_value=None,
                source_location="p1",
                confidence_score=0.9,
                quality_status=ExtractionQualityStatus.EXTRACTED,
                evidence_quote=None,
                structured_payload={"cached": True},
            )
        ]
    )

    source_fragment = KnowledgeFragment(
        fragment_id="frag-old-1",
        knowledge_version_id="kv-src",
        document_id="doc-origin",
        fragment_type=FragmentType.RULE,
        title="Rule",
        content="Important architecture rule",
        source_location="p1",
        fragment_metadata={"document_title": "Origin"},
        embedding_key="legacy",
        embedding=None,
        status=FragmentStatus.ACTIVE,
    )
    source_fragment.fragment_embeddings = [
        KnowledgeFragmentEmbedding(
            fragment_embedding_id="emb-1",
            fragment_id="frag-old-1",
            embedding_space_id="space-1",
            embedding_key="space-key",
            embedding=[0.1, 0.2],
        )
    ]
    source_rule = NormativeRule(
        rule_id="rule-1",
        knowledge_version_id="kv-src",
        document_id="doc-origin",
        rule_code="R-1",
        rule_name="Rule 1",
        rule_text="Do the thing",
        rule_category=RuleCategory.ARCHITECTURE,
        applicability_condition=None,
        severity_default=Severity.MAJOR,
        status="active",
    )
    service.session = SimpleNamespace(
        add=lambda *_: None,
        flush=lambda: None,
        scalars=lambda stmt: [source_fragment]
        if "knowledge_fragments" in str(stmt)
        else [source_rule],
    )

    candidate = KnowledgeVersion(
        knowledge_version_id="kv-target",
        knowledge_base_id="kb-1",
        version_no="KV-1",
        update_run_id="run-1",
        status=KnowledgeVersionStatus.DRAFT,
    )
    candidate.version_documents = []
    candidate.knowledge_fragments = []
    candidate.normative_rules = []
    candidate.extracted_items = []
    active_snapshot = DocumentSnapshot(
        document_snapshot_id="snap-1",
        knowledge_version_id="kv-src",
        document_id="doc-origin",
        checksum="abc",
        content_format="text/markdown",
        parser_name="md",
        normalized_text="Important architecture rule",
        structure_metadata={"source": "origin"},
    )
    document = SimpleNamespace(document_id="doc-target")
    previous_version_document = SimpleNamespace(role_code="reference_only", required_flag=False)

    KnowledgeUpdateService._clone_document_artifacts(
        service,
        candidate,
        document,
        previous_version_document,
        active_snapshot,
        source_document_id="doc-origin",
        reuse_mode="content_addressable_checksum_cache",
    )

    assert len(candidate.version_documents) == 1
    assert len(candidate.knowledge_fragments) == 1
    assert len(candidate.normative_rules) == 1
    assert len(candidate.extracted_items) == 1
    assert candidate.knowledge_fragments[0].document_id == "doc-target"
    assert candidate.normative_rules[0].document_id == "doc-target"
    assert candidate.extracted_items[0].document_id == "doc-target"


def test_resolve_preferred_embedding_space_prefers_version_space_over_global_active() -> None:
    version_space = EmbeddingSpace(
        embedding_space_id="space-version",
        code="bge_m3_default",
        provider_name="x",
        model_id="bge",
        dimensions=1024,
        distance_metric="cosine",
        is_active=False,
    )
    global_space = EmbeddingSpace(
        embedding_space_id="space-global",
        code="embeddinggemma_lite",
        provider_name="x",
        model_id="gemma",
        dimensions=768,
        distance_metric="cosine",
        is_active=True,
    )
    fragment = KnowledgeFragment(
        fragment_id="frag-1",
        knowledge_version_id="kv-1",
        document_id="doc-1",
        fragment_type=FragmentType.RULE,
        title="t",
        content="c",
        source_location=None,
        fragment_metadata=None,
        embedding_key=None,
        embedding=None,
        status=FragmentStatus.ACTIVE,
    )
    fragment.fragment_embeddings = [
        KnowledgeFragmentEmbedding(
            fragment_embedding_id="e1",
            fragment_id="frag-1",
            embedding_space_id="space-version",
            embedding_key="k",
            embedding=[0.1, 0.2],
        )
    ]
    fragment.fragment_embeddings[0].embedding_space = version_space

    service = KnowledgeQueryService.__new__(KnowledgeQueryService)
    service.session = SimpleNamespace(
        get=lambda model, key: KnowledgeVersion(
            knowledge_version_id="kv-1",
            knowledge_base_id="kb-1",
            version_no="KV-1",
            update_run_id="run-1",
            embedding_space_id="space-version",
            status=KnowledgeVersionStatus.ACTIVE,
        )
    )
    service.embedding_spaces = SimpleNamespace(
        get_active=lambda: global_space,
        get=lambda key: version_space if str(key) == "space-version" else None,
    )

    resolved = KnowledgeQueryService._resolve_preferred_embedding_space(service, "kv-1", [fragment])

    assert resolved is version_space


def test_serialize_run_includes_active_embedding_metadata() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    candidate = KnowledgeVersion(
        knowledge_version_id="kv-1",
        knowledge_base_id="kb-1",
        version_no="KV-1",
        update_run_id="run-1",
        embedding_space_id="space-1",
        status=KnowledgeVersionStatus.VALIDATED,
    )
    candidate.embedding_space = EmbeddingSpace(
        embedding_space_id="space-1",
        code="bge_m3_default",
        provider_name="x",
        model_id="bge",
        dimensions=1024,
        distance_metric="cosine",
        is_active=False,
    )
    service.versions = SimpleNamespace(get_by_update_run_id=lambda update_run_id: candidate)
    service._build_active_diff_summary = lambda candidate: None

    run = KnowledgeUpdateRun(
        update_run_id="run-1",
        knowledge_base_id="kb-1",
        run_type="rebuild",
        status=KnowledgeUpdateStatus.COMPLETED,
        current_stage="completed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_sec=3,
        scope={
            "source_scope": "all",
            "selected_source_ids": [],
            "target_embedding_profile": "bge_m3_default",
            "document_ids": ["doc-1"],
        },
        summary={
            "quality_summary": {
                "embedding_space_id": "space-1",
                "embedding_space_code": "bge_m3_default",
            }
        },
    )

    payload = KnowledgeUpdateService._serialize_run(service, run)

    assert payload["active_embedding_space_id"] == "space-1"
    assert payload["active_embedding_space_code"] == "bge_m3_default"
    assert payload["diagnostics"]["target_embedding_profile"] == "bge_m3_default"
