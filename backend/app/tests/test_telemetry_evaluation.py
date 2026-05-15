from __future__ import annotations

from pathlib import Path

from app.domain.services.knowledge_telemetry import (
    build_retrieval_telemetry_summary,
    build_update_run_telemetry_summary,
    record_stage_metric,
)
from app.integrations.generation.llm_gateway import RetrievedFragment
from app.integrations.knowledge.evaluation import (
    aggregate_retrieval_eval,
    evaluate_retrieval_case,
    load_retrieval_eval_cases,
    parse_eval_case,
)


def test_record_stage_metric_aggregates_multiple_samples() -> None:
    metrics: dict[str, dict] = {}
    record_stage_metric(
        metrics,
        "indexing",
        started_at="2026-04-04T10:00:00Z",
        finished_at="2026-04-04T10:00:02Z",
        duration_sec=2.0,
        extra={"document_id": "doc-1", "chunk_count": 4, "embedding_count": 4},
    )
    record_stage_metric(
        metrics,
        "indexing",
        started_at="2026-04-04T10:01:00Z",
        finished_at="2026-04-04T10:01:03Z",
        duration_sec=3.0,
        extra={"document_id": "doc-2", "chunk_count": 6, "embedding_count": 6},
    )

    payload = metrics["indexing"]
    assert payload["count"] == 2
    assert payload["total_duration_sec"] == 5.0
    assert payload["avg_duration_sec"] == 2.5
    assert payload["numeric_totals"]["chunk_count"] == 10.0
    assert payload["numeric_totals"]["embedding_count"] == 10.0
    assert payload["last"]["document_id"] == "doc-2"


def test_build_update_run_telemetry_summary_derives_ratios() -> None:
    telemetry = build_update_run_telemetry_summary(
        {
            "execution_mode": "delta_first",
            "embedding_space_id": "space-1",
            "embedding_space_code": "bge_m3_default",
            "requested_embedding_profile": "bge_m3_default",
            "provider_diagnostics": {"model_id": "bge-m3"},
            "processed_documents": 4,
            "reused_documents": 6,
            "processing_error_count": 2,
            "chunk_count": 20,
            "extracted_item_count": 12,
            "embeddings_calculated": 20,
            "embeddings_reused": 30,
            "sla": {"actual_sec": 120},
            "stage_metrics": {
                "indexing": {"total_duration_sec": 15.0},
                "extracting": {"total_duration_sec": 10.0},
            },
        }
    )
    assert telemetry["document_reuse_ratio"] == 0.6
    assert telemetry["embedding_reuse_ratio"] == 0.6
    assert telemetry["throughput_docs_per_min"] == 2.0
    assert telemetry["longest_stage"] == "indexing"


def test_build_retrieval_telemetry_summary_extracts_key_fields() -> None:
    summary = build_retrieval_telemetry_summary(
        {
            "retrieval_backend": "python_hybrid_rrf_rerank",
            "policy_id": "generation_retrieval_policy",
            "knowledge_version_id": "kv-1",
            "active_embedding_space_code": "bge_m3_default",
            "vector_candidate_count": 40,
            "lexical_candidate_count": 25,
            "keyword_candidate_count": 25,
            "fused_candidate_count": 30,
            "reranked_candidate_count": 20,
            "reranked_count": 8,
            "candidate_pool_summary": {"fragment_count": 100, "fragment_with_embedding_count": 97},
            "selected_counts": {"documents": {"Doc A": 2, "Doc B": 1}},
            "empty_result": False,
            "timings_ms": {"total": 42.5},
            "reranker": {"provider_name": "heuristic", "backend": "heuristic", "latency_ms": 5.1},
            "coverage_summary": {
                "required_role_coverage": 0.75,
                "missing_required_roles": ["integration_contract"],
            },
        }
    )
    assert summary["latency_ms"] == 42.5
    assert summary["candidate_pool_fragment_count"] == 100
    assert summary["selected_document_count"] == 2
    assert summary["required_role_coverage"] == 0.75


def test_load_retrieval_eval_cases_from_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures" / "retrieval_eval_sample.json"
    dataset_name, knowledge_version_id, cases = load_retrieval_eval_cases(fixture)
    assert dataset_name == "sample_retrieval_eval"
    assert knowledge_version_id == "00000000-0000-0000-0000-000000000001"
    assert len(cases) == 2
    assert cases[0].case_id == "case-api"


def test_evaluate_retrieval_case_and_aggregate_metrics() -> None:
    case = parse_eval_case(
        {
            "case_id": "case-1",
            "query_text": "payment api",
            "expected_fragment_ids": ["frag-2"],
            "expected_document_ids": ["doc-3"],
            "top_k": 10,
        }
    )
    fragments = [
        RetrievedFragment(
            fragment_id="frag-1", document_id="doc-1", title="A", content="alpha", metadata={}
        ),
        RetrievedFragment(
            fragment_id="frag-2", document_id="doc-2", title="B", content="beta", metadata={}
        ),
        RetrievedFragment(
            fragment_id="frag-3", document_id="doc-3", title="C", content="gamma", metadata={}
        ),
    ]
    result = evaluate_retrieval_case(case, fragments, diagnostics={"policy_id": "generation"})
    assert result.recall_at_5 == 1.0
    assert result.mrr_at_10 == 0.5
    assert result.hit_after_rerank == 1.0
    aggregated = aggregate_retrieval_eval(
        [result], dataset_name="demo", knowledge_version_id="kv-1"
    )
    assert aggregated.metrics["Recall@10"] == 1.0
    assert aggregated.metrics["MRR@10"] == 0.5
