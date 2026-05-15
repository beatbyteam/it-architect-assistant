from __future__ import annotations

from typing import Any

from app.db.models.publication import PublishedArtifact


def build_next_action_hint(
    *,
    task_state: str,
    readiness_assessment: dict[str, Any] | None,
    open_clarification_count: int,
) -> str | None:
    readiness = readiness_assessment or {}
    missing = list(readiness.get("missing_inputs") or [])
    if task_state == "draft":
        return "Доработай описание и отправь задачу на проверку входных данных."
    if open_clarification_count or missing:
        return "Ответь на уточняющие вопросы. После этого система повторно проверит полноту входных данных."
    if task_state == "ready_for_generation":
        return "Входных данных достаточно. Можно запускать подготовку решения."
    return None


def retention_policy_payload(*, target_type: str) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "delete_supported": False,
        "soft_retention_only": True,
        "supersede_policy": "new_publication_revision_supersedes_current",
        "archival_policy": "artifacts_and_versions_remain_traceable",
    }


def publication_revision_payload(artifact: PublishedArtifact) -> dict[str, Any]:
    return {
        "published_artifact_id": str(artifact.published_artifact_id),
        "revision_no": artifact.revision_no,
        "state": artifact.state,
        "published_at": artifact.published_at,
        "created_at": artifact.created_at,
        "superseded_at": artifact.superseded_at,
        "version_hash": artifact.version_hash,
        "metadata": dict(artifact.artifact_metadata or {}),
    }
