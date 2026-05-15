# Observability and correlation context

- Structured JSON logs now include request/correlation and operation entity IDs.
- Generation, verification, and knowledge update runs emit stage-level duration metrics.
- Operations metrics dashboard aggregates pipeline observability across generation, verification, and knowledge updates.

Key payload locations:
- generation run -> diagnostics.pipeline_telemetry / diagnostics.stage_metrics
- verification run -> diagnostics.pipeline_telemetry / diagnostics.stage_metrics
- knowledge update -> summary.quality_summary.pipeline_telemetry / stage_metrics
