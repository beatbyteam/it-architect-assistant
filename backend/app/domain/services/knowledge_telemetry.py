from __future__ import annotations

from collections.abc import Sized
from typing import Any


def record_stage_metric(
    stage_metrics: dict[str, dict[str, Any]],
    stage_name: str,
    *,
    started_at: str,
    finished_at: str,
    duration_sec: float,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = dict(extra or {})
    entry = dict(stage_metrics.get(stage_name) or {})
    count = int(entry.get("count") or 0) + 1
    total_duration = float(entry.get("total_duration_sec") or 0.0) + float(duration_sec)
    max_duration = max(float(entry.get("max_duration_sec") or 0.0), float(duration_sec))
    numeric_totals = dict(entry.get("numeric_totals") or {})
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            numeric_totals[key] = round(float(numeric_totals.get(key) or 0.0) + float(value), 6)
    samples = list(entry.get("samples") or [])
    sample_payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": round(float(duration_sec), 6),
        **payload,
    }
    samples.append(sample_payload)
    if len(samples) > 3:
        samples = samples[-3:]
    stage_metrics[stage_name] = {
        "count": count,
        "first_started_at": entry.get("first_started_at") or started_at,
        "last_finished_at": finished_at,
        "total_duration_sec": round(total_duration, 6),
        "avg_duration_sec": round(total_duration / max(count, 1), 6),
        "max_duration_sec": round(max_duration, 6),
        "last_duration_sec": round(float(duration_sec), 6),
        "numeric_totals": numeric_totals,
        "last": payload,
        "samples": samples,
    }


def build_update_run_telemetry_summary(quality_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(quality_summary or {})
    processed_documents = int(summary.get("processed_documents") or 0)
    reused_documents = int(summary.get("reused_documents") or 0)
    processing_errors = int(summary.get("processing_error_count") or 0)
    total_documents = processed_documents + reused_documents + processing_errors
    embeddings_calculated = int(summary.get("embeddings_calculated") or 0)
    embeddings_reused = int(summary.get("embeddings_reused") or 0)
    chunk_count = int(summary.get("chunk_count") or 0)
    extracted_item_count = int(summary.get("extracted_item_count") or 0)
    stage_metrics = dict(summary.get("stage_metrics") or {})
    total_stage_duration = round(
        sum(
            float((item or {}).get("total_duration_sec") or 0.0) for item in stage_metrics.values()
        ),
        6,
    )
    longest_stage = None
    if stage_metrics:
        longest_stage = max(
            stage_metrics.items(),
            key=lambda pair: float((pair[1] or {}).get("total_duration_sec") or 0.0),
        )[0]
    throughput_docs_per_min = 0.0
    sla = dict(summary.get("sla") or {})
    actual_sec = float(sla.get("actual_sec") or 0.0)
    if processed_documents > 0 and actual_sec > 0:
        throughput_docs_per_min = round(processed_documents / (actual_sec / 60.0), 3)
    embedding_total = embeddings_calculated + embeddings_reused
    return {
        "execution_mode": summary.get("execution_mode"),
        "embedding_space_id": summary.get("embedding_space_id"),
        "embedding_space_code": summary.get("embedding_space_code"),
        "embedding_profile": summary.get("requested_embedding_profile")
        or ((summary.get("provider_diagnostics") or {}).get("profile_code")),
        "embedding_model_id": (summary.get("provider_diagnostics") or {}).get("model_id"),
        "processed_documents": processed_documents,
        "reused_documents": reused_documents,
        "processing_errors": processing_errors,
        "document_scope_count": int(summary.get("document_scope_count") or 0),
        "total_documents_seen": total_documents,
        "document_reuse_ratio": round(
            reused_documents / max(processed_documents + reused_documents, 1), 4
        ),
        "embedding_reuse_ratio": round(embeddings_reused / max(embedding_total, 1), 4),
        "processing_error_rate": round(processing_errors / max(total_documents, 1), 4),
        "avg_chunks_per_processed_document": round(chunk_count / max(processed_documents, 1), 3),
        "avg_extracted_items_per_processed_document": round(
            extracted_item_count / max(processed_documents, 1), 3
        ),
        "throughput_docs_per_min": throughput_docs_per_min,
        "total_stage_duration_sec": total_stage_duration,
        "longest_stage": longest_stage,
        "stage_count": len(stage_metrics),
    }


def build_retrieval_telemetry_summary(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    timings = dict(payload.get("timings_ms") or {})
    coverage = dict(payload.get("coverage_summary") or {})
    selected_counts = dict(payload.get("selected_counts") or {})
    candidate_pool = dict(payload.get("candidate_pool_summary") or {})
    reranker = dict(payload.get("reranker") or {})
    retrieval_ms = float(timings.get("total") or 0.0)
    selected_documents = selected_counts.get("documents")
    selected_document_count = (
        len(selected_documents)
        if isinstance(selected_documents, Sized)
        else int(coverage.get("retrieved_document_count") or 0)
    )
    return {
        "retrieval_backend": payload.get("retrieval_backend"),
        "policy_id": payload.get("policy_id"),
        "knowledge_version_id": payload.get("knowledge_version_id"),
        "knowledge_version_ids": list(payload.get("knowledge_version_ids") or []),
        "active_embedding_space_code": payload.get("active_embedding_space_code"),
        "active_embedding_space_id": payload.get("active_embedding_space_id"),
        "latency_ms": round(retrieval_ms, 3),
        "vector_candidate_count": int(payload.get("vector_candidate_count") or 0),
        "lexical_candidate_count": int(payload.get("lexical_candidate_count") or 0),
        "keyword_candidate_count": int(payload.get("keyword_candidate_count") or 0),
        "fused_candidate_count": int(payload.get("fused_candidate_count") or 0),
        "reranked_candidate_count": int(payload.get("reranked_candidate_count") or 0),
        "selected_fragment_count": int(
            payload.get("reranked_count") or coverage.get("retrieved_fragment_count") or 0
        ),
        "selected_document_count": selected_document_count,
        "candidate_pool_fragment_count": int(candidate_pool.get("fragment_count") or 0),
        "candidate_pool_with_embeddings": int(
            candidate_pool.get("fragment_with_embedding_count") or 0
        ),
        "empty_result": bool(payload.get("empty_result")),
        "empty_result_reason": payload.get("empty_result_reason"),
        "coverage_ok": payload.get("coverage_ok"),
        "required_role_coverage": coverage.get("required_role_coverage"),
        "missing_required_roles": list(coverage.get("missing_required_roles") or []),
        "reranker_provider": reranker.get("provider_name"),
        "reranker_backend": reranker.get("backend"),
        "reranker_latency_ms": reranker.get("latency_ms"),
    }
