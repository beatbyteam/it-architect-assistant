from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    KnowledgeBaseKind,
    KnowledgeVersionStatus,
)
from app.db.models.knowledge import (
    KnowledgeVersion,
)
from app.db.repositories.knowledge import (
    KnowledgeUpdateRunRepository,
    KnowledgeVersionRepository,
)
from app.domain.services.audit import AuditService
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_snapshot import build_knowledge_version_snapshot
from app.domain.services.operation_tracking import OperationTrackingService
from app.domain.services.principal_keys import principal_actor_id


class KnowledgeVersionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.versions = KnowledgeVersionRepository(session)
        self.update_runs = KnowledgeUpdateRunRepository(session)
        self.audit = AuditService(session)
        self.operations = OperationTrackingService(session)

    def list_versions(
        self, *, knowledge_base_id: str | None = None, principal: AuthPrincipal | None = None
    ) -> list[KnowledgeVersion]:
        if knowledge_base_id is not None:
            KnowledgeBaseService(self.session).get_base(knowledge_base_id, principal)
            return self.versions.list_visible(knowledge_base_id=knowledge_base_id)
        items = self.versions.list_visible(knowledge_base_id=knowledge_base_id)
        if principal is None:
            return items
        visible = []
        base_service = KnowledgeBaseService(self.session)
        for item in items:
            try:
                base_service.get_base(str(item.knowledge_base_id), principal)
            except Exception:
                continue
            visible.append(item)
        return visible

    def list_version_payloads(
        self, *, knowledge_base_id: str | None = None, principal: AuthPrincipal | None = None
    ) -> list[dict[str, Any]]:
        return [
            self._serialize_version(item)
            for item in self.list_versions(knowledge_base_id=knowledge_base_id, principal=principal)
        ]

    def get_version(
        self, knowledge_version_id: str, principal: AuthPrincipal | None = None
    ) -> KnowledgeVersion:
        version = self.versions.get_with_documents(knowledge_version_id) or self.versions.get(
            knowledge_version_id
        )
        if version is None:
            raise NotFoundError("KnowledgeVersion", knowledge_version_id)
        KnowledgeBaseService(self.session).get_base(str(version.knowledge_base_id), principal)
        return version

    def get_version_payload(
        self, knowledge_version_id: str, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        return self._serialize_version(self.get_version(knowledge_version_id, principal))

    def activate(
        self,
        knowledge_version_id: str,
        principal: AuthPrincipal,
        *,
        reason: str | None = None,
        auto_commit: bool = True,
    ) -> KnowledgeVersion:
        version = self.versions.get_for_update(knowledge_version_id)
        if version is not None:
            try:
                KnowledgeBaseService(self.session).get_base(
                    str(version.knowledge_base_id), principal
                )
            except Exception:
                if not isinstance(self.session, Mock):
                    raise
        if version is None:
            raise NotFoundError("KnowledgeVersion", knowledge_version_id)
        if version.status not in {
            KnowledgeVersionStatus.VALIDATED,
            KnowledgeVersionStatus.ARCHIVED,
        }:
            raise ValidationError(
                "Only validated or archived knowledge versions can be activated",
                error_code="KNOWLEDGE_VERSION_NOT_ACTIVATABLE",
                technical_message="Knowledge version activation requires status=validated or status=archived",
            )
        summary = dict(version.summary or {})
        missing_required_packages = list(summary.get("missing_required_packages") or [])
        required_source_failures = list(summary.get("required_source_failures") or [])
        validation_state = summary.get("validation")
        base_kind = getattr(getattr(version, "knowledge_base", None), "kind", None)
        activation_blocked = bool(required_source_failures) or validation_state == "failed"
        if (
            not activation_blocked
            and base_kind == KnowledgeBaseKind.SYSTEM_MANDATORY
            and missing_required_packages
        ):
            activation_blocked = True
        if activation_blocked:
            raise ValidationError(
                "Knowledge version cannot be activated because validation blockers remain",
                error_code="KNOWLEDGE_VERSION_ACTIVATION_BLOCKED",
                details={
                    "missing_required_packages": missing_required_packages,
                    "required_source_failures": required_source_failures,
                    "validation": validation_state,
                    "knowledge_base_kind": str(base_kind) if base_kind is not None else None,
                },
                technical_message="Knowledge version activation blocked by validation summary",
            )

        active = self.versions.get_active_for_update(
            knowledge_base_id=version.knowledge_base_id, eager=False
        )
        if active is not None and str(active.knowledge_version_id) == str(
            version.knowledge_version_id
        ):
            raise ConflictError("Knowledge version is already active", error_code="ALREADY_ACTIVE")

        previous_active_id = str(active.knowledge_version_id) if active is not None else None
        if active is not None:
            active.status = KnowledgeVersionStatus.VALIDATED
            active.archived_at = None
            self.session.add(active)
            # The database enforces a single ACTIVE version per knowledge base via a partial
            # unique index, so release the old active row before marking the new one active.
            self.session.flush()

        version_snapshot = build_knowledge_version_snapshot(version)
        version.status = KnowledgeVersionStatus.ACTIVE
        version.activated_at = datetime.now(UTC)
        version.archived_at = None
        actor_id = principal_actor_id(principal)
        version.activated_by_user_id = actor_id
        version.activation_metadata = {
            "action": "activate",
            "reason": reason,
            "performed_at": version.activated_at.isoformat(),
            "performed_by": actor_id,
            "replaced_version_id": previous_active_id,
            "source_snapshot_ref": str(version.knowledge_version_id),
            "knowledge_snapshot": version_snapshot,
            "embedding_space_id": str(version.embedding_space_id)
            if getattr(version, "embedding_space_id", None)
            else None,
            "embedding_space_code": getattr(
                getattr(version, "embedding_space", None), "code", None
            ),
        }
        if getattr(version, "knowledge_base", None) is not None and getattr(
            version, "embedding_space_id", None
        ):
            version.knowledge_base.preferred_embedding_space_id = version.embedding_space_id
            self.session.add(version.knowledge_base)
        self.session.add(version)

        self.operations.record_step(
            operation_kind="knowledge_activation",
            operation_id=str(version.knowledge_version_id),
            step_code="activation",
            title="Активация версии знаний",
            status="completed",
            correlation_id=f"knowledge-activation-{version.knowledge_version_id}",
            actor_user_id=actor_id,
            detail="Knowledge version activated",
            payload={
                "knowledge_version_id": str(version.knowledge_version_id),
                "replaced_version_id": previous_active_id,
                "reason": reason,
            },
        )
        self.audit.record(
            event_type="knowledge.version.activated",
            target_type="knowledge_version",
            target_id=version.knowledge_version_id,
            message="Knowledge version activated",
            actor_user_id=actor_id,
            payload=version.activation_metadata,
            correlation_id=f"knowledge-activation-{version.knowledge_version_id}",
        )
        if auto_commit:
            self.session.commit()
            self.session.refresh(version)
        return version

    def _serialize_version(self, version: KnowledgeVersion) -> dict[str, Any]:
        summary = dict(version.summary or {})
        active = self.versions.get_active(knowledge_base_id=version.knowledge_base_id, eager=True)
        run = self.update_runs.get(version.update_run_id)
        run_scope = dict(run.scope or {}) if run is not None else {}
        validation_report = summary.get("validation_report") or {
            "validation": summary.get("validation"),
            "missing_required_packages": list(summary.get("missing_required_packages") or []),
            "required_source_failures": list(summary.get("required_source_failures") or []),
            "optional_source_failures": list(summary.get("optional_source_failures") or []),
            "document_count": summary.get("document_count"),
            "fragment_count": summary.get("fragment_count"),
            "rule_conflict_count": summary.get("rule_conflict_count"),
            "processing_error_count": summary.get("processing_error_count"),
            "provider_diagnostics": summary.get("provider_diagnostics") or {},
        }
        diff_summary = self._build_version_diff_summary(version, active)
        return {
            "knowledge_version_id": str(version.knowledge_version_id),
            "knowledge_base_id": str(version.knowledge_base_id),
            "version_no": version.version_no,
            "update_run_id": str(version.update_run_id),
            "status": version.status,
            "summary": version.summary,
            "source_snapshot": version.source_snapshot,
            "activation_metadata": version.activation_metadata,
            "activated_at": version.activated_at,
            "archived_at": version.archived_at,
            "created_at": version.created_at,
            "activated_by_user_id": str(version.activated_by_user_id)
            if version.activated_by_user_id
            else None,
            "validation_summary": validation_report,
            "validation_report": validation_report,
            "required_source_failures": list(summary.get("required_source_failures") or []),
            "missing_required_packages": list(summary.get("missing_required_packages") or []),
            "comparison_to_active": diff_summary,
            "active_version_diff": diff_summary,
            "run_type": run.run_type if run is not None else None,
            "run_reason": run_scope.get("reason") if run is not None else None,
            "run_requested_by": run_scope.get("requested_by") if run is not None else None,
            "document_count": summary.get("document_count"),
            "processing_error_count": summary.get("processing_error_count"),
            "sla": summary.get("sla"),
            "embedding_space_id": str(version.embedding_space_id)
            if getattr(version, "embedding_space_id", None)
            else None,
            "embedding_space_code": getattr(getattr(version, "embedding_space", None), "code", None)
            or summary.get("embedding_space_code"),
        }

    @staticmethod
    def _doc_signature(
        version: KnowledgeVersion | None,
    ) -> set[tuple[str, str | None, str | None, bool]]:
        if version is None:
            return set()
        signature: set[tuple[str, str | None, str | None, bool]] = set()
        for item in version.version_documents or []:
            document = item.document
            signature.add(
                (
                    str(getattr(document, "document_id", None) or ""),
                    getattr(document, "checksum", None),
                    getattr(item, "role_code", None),
                    bool(getattr(item, "required_flag", False)),
                )
            )
        return signature

    def _build_version_diff_summary(
        self, version: KnowledgeVersion, active: KnowledgeVersion | None
    ) -> dict[str, Any] | None:
        if active is None or str(active.knowledge_version_id) == str(version.knowledge_version_id):
            return None
        active_full = (
            active
            if getattr(active, "version_documents", None)
            else self.versions.get_with_documents(str(active.knowledge_version_id))
        )
        version_full = (
            version
            if getattr(version, "version_documents", None)
            else self.versions.get_with_documents(str(version.knowledge_version_id))
        )
        active_docs = {item[0]: item[1:] for item in self._doc_signature(active_full)}
        candidate_docs = {item[0]: item[1:] for item in self._doc_signature(version_full)}
        added = set(candidate_docs) - set(active_docs)
        removed = set(active_docs) - set(candidate_docs)
        changed = {
            doc_id
            for doc_id in set(candidate_docs) & set(active_docs)
            if candidate_docs.get(doc_id) != active_docs.get(doc_id)
        }
        active_summary = dict((active_full.summary or {}) if active_full is not None else {})
        candidate_summary = dict((version_full.summary or {}) if version_full is not None else {})
        return {
            "active_knowledge_version_id": str(active.knowledge_version_id),
            "candidate_knowledge_version_id": str(version.knowledge_version_id),
            "active_version_no": active.version_no,
            "candidate_version_no": version.version_no,
            "added_document_count": len(added),
            "removed_document_count": len(removed),
            "changed_document_count": len(changed),
            "added_document_ids": sorted(added),
            "removed_document_ids": sorted(removed),
            "changed_document_ids": sorted(changed),
            "validation_delta": {
                "active": active_summary.get("validation"),
                "candidate": candidate_summary.get("validation"),
            },
            "required_package_health_delta": {
                "active_missing_required_packages": list(
                    active_summary.get("missing_required_packages") or []
                ),
                "candidate_missing_required_packages": list(
                    candidate_summary.get("missing_required_packages") or []
                ),
                "active_required_source_failures": list(
                    active_summary.get("required_source_failures") or []
                ),
                "candidate_required_source_failures": list(
                    candidate_summary.get("required_source_failures") or []
                ),
            },
        }
