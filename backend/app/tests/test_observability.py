from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from app.core.logging import JsonFormatter
from app.core.request_context import bind_log_context
from app.domain.services.knowledge_telemetry import record_stage_metric
from app.domain.services.observability import summarize_stage_metrics
from app.domain.services.operations import OperationsQueryService


def test_json_logging_includes_bound_context_and_record_context() -> None:
    formatter = JsonFormatter()
    with bind_log_context(
        correlation_id="corr-42", generation_run_id="gen-7", business_task_id="task-9"
    ):
        record = logging.makeLogRecord(
            {
                "name": "tests.observability",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "stage completed",
                "stage": "retrieving",
                "stage_status": "completed",
                "duration_ms": 12.5,
                "event_type": "stage_finished",
            }
        )
        payload = json.loads(formatter.format(record))
    assert payload["correlation_id"] == "corr-42"
    assert payload["generation_run_id"] == "gen-7"
    assert payload["business_task_id"] == "task-9"
    assert payload["stage"] == "retrieving"
    assert payload["duration_ms"] == 12.5
    assert payload["event_type"] == "stage_finished"


def test_summarize_stage_metrics_tracks_failed_stage_count() -> None:
    stage_metrics: dict[str, dict] = {}
    record_stage_metric(
        stage_metrics,
        "retrieving",
        started_at="2026-04-04T10:00:00+00:00",
        finished_at="2026-04-04T10:00:02+00:00",
        duration_sec=2.0,
        extra={"outcome": "completed"},
    )
    record_stage_metric(
        stage_metrics,
        "publishing",
        started_at="2026-04-04T10:00:02+00:00",
        finished_at="2026-04-04T10:00:03+00:00",
        duration_sec=1.0,
        extra={"outcome": "failed", "error_code": "PUBLISHING_ERROR"},
    )
    summary = summarize_stage_metrics(stage_metrics)
    assert summary["stage_count"] == 2
    assert summary["failed_stage_count"] == 1
    assert summary["total_stage_duration_sec"] == 3.0
    assert summary["longest_stage"] == "retrieving"


def test_operations_metrics_include_pipeline_observability_dashboard() -> None:
    service = OperationsQueryService.__new__(OperationsQueryService)
    service.settings = SimpleNamespace()
    service.knowledge_runs = SimpleNamespace(
        list_recent=lambda limit: [
            SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                summary={
                    "quality_summary": {
                        "pipeline_telemetry": {
                            "stage_count": 4,
                            "failed_stage_count": 0,
                            "longest_stage": "indexing",
                            "total_stage_duration_sec": 12.0,
                            "total_runtime_sec": 15.0,
                        },
                        "policy_stack": {
                            "embedding_model_version": "emb-v1",
                            "chunking_policy_version": "chunk-v1",
                        },
                    }
                },
            )
        ]
    )
    service.generation_runs = SimpleNamespace(
        list_recent=lambda limit, eager=True: [
            SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                diagnostics={
                    "quality_outcomes": {"groundedness_score": 0.9, "citation_coverage": 0.8},
                    "pipeline_telemetry": {
                        "stage_count": 5,
                        "failed_stage_count": 0,
                        "longest_stage": "validating",
                        "total_stage_duration_sec": 9.0,
                        "total_runtime_sec": 11.0,
                    },
                    "policy_stack": {
                        "retrieval_policy_version": "ret-v1",
                        "embedding_model_version": "emb-v2",
                    },
                },
            )
        ]
    )
    service.verification_runs = SimpleNamespace(
        list_recent=lambda limit, eager=True: [
            SimpleNamespace(
                status=SimpleNamespace(value="failed"),
                diagnostics={
                    "quality_outcomes": {"check_count": 8},
                    "pipeline_telemetry": {
                        "stage_count": 3,
                        "failed_stage_count": 1,
                        "longest_stage": "verification",
                        "total_stage_duration_sec": 7.0,
                        "total_runtime_sec": 8.5,
                    },
                    "policy_stack": {
                        "retrieval_policy_version": "ret-v1",
                        "embedding_model_version": "emb-v2",
                    },
                },
            )
        ]
    )
    service.audit = SimpleNamespace(list_filtered=lambda limit: [])

    snapshot = service.get_metrics_snapshot()
    dashboard = snapshot["data_llm_dashboard"]["pipeline_observability"]
    assert dashboard["knowledge_updates"]["average_runtime_sec"] == 15.0
    assert dashboard["generation_runs"]["longest_stage_distribution"] == {"validating": 1}
    assert dashboard["verification_runs"]["average_failed_stage_count"] == 1.0
