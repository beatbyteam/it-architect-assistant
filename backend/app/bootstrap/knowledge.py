from __future__ import annotations

from sqlalchemy.orm import Session

from app.bootstrap.bundles import import_knowledge_bundle, system_bundle_principal
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.enums import KnowledgeVersionStatus
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_core import KnowledgeUpdateService, KnowledgeVersionService


def _ensure_bootstrap_principal(session: Session):
    del session
    return system_bundle_principal()


def bootstrap_knowledge_baseline(
    session: Session,
    *,
    manifest_uri: str | None = None,
    activate_if_missing: bool = True,
    execute_update_inline: bool = True,
) -> dict[str, object]:
    versions = KnowledgeVersionService(session)
    bases = KnowledgeBaseService(session)
    bases.ensure_system_bases()
    mandatory_base = bases.get_mandatory_base()
    active = versions.versions.get_active(knowledge_base_id=mandatory_base.knowledge_base_id)
    if active is not None:
        return {
            "bootstrapped": False,
            "active_knowledge_version_id": str(active.knowledge_version_id),
            "knowledge_version_status": active.status.value,
            "manifest_uri": manifest_uri,
        }

    running = KnowledgeUpdateService(session, get_settings())._get_running_run_with_recovery(
        knowledge_base_id=str(mandatory_base.knowledge_base_id)
    )
    if running is not None:
        return {
            "bootstrapped": False,
            "active_knowledge_version_id": None,
            "knowledge_version_status": running.status.value,
            "manifest_uri": manifest_uri,
            "update_in_progress": True,
            "update_run_id": str(running.update_run_id),
        }

    if not manifest_uri:
        raise ValidationError(
            "Bootstrap manifest URI is required when no active knowledge version is present",
            error_code="KNOWLEDGE_BOOTSTRAP_MANIFEST_REQUIRED",
        )

    principal = _ensure_bootstrap_principal(session)
    result = import_knowledge_bundle(
        session,
        manifest_uri=manifest_uri,
        knowledge_base_id=str(mandatory_base.knowledge_base_id),
        principal=principal,
        start_update=True,
        activate_if_validated=activate_if_missing,
        execute_update_inline=execute_update_inline,
        reason="bootstrap_initial_baseline",
        requested_by="system.bootstrap",
    ).as_dict()

    active = versions.versions.get_active(knowledge_base_id=mandatory_base.knowledge_base_id)
    candidate_id = result.get("candidate_knowledge_version_id")
    candidate = versions.get_version(candidate_id) if candidate_id else None
    return {
        "bootstrapped": True,
        "active_knowledge_version_id": str(active.knowledge_version_id) if active else None,
        "knowledge_version_status": active.status.value
        if active
        else (candidate.status.value if candidate else KnowledgeVersionStatus.FAILED.value),
        **result,
    }
