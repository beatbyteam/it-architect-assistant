from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import (
    ProtocolSummaryStatus,
    VerificationProtocolStatus,
    VerificationRunStatus,
)
from app.db.models.knowledge import (
    KnowledgeVersion,
    KnowledgeVersionDocument,
    NormativeRule,
    SourceDocument,
)
from app.db.models.verification import (
    CheckResult,
    VerificationBasisDocument,
    VerificationProtocol,
    VerificationRun,
)
from app.db.repositories.verification import (
    CheckResultRepository,
    VerificationProtocolRepository,
)
from app.domain.services.knowledge_basis import (
    requires_catalog_basis_for_versions,
    resolve_basis_assignment,
    resolve_scoped_basis_assignment,
)
from app.domain.services.presenters import clean_display_file_name
from app.domain.services.publication import PublicationArtifactService
from app.integrations.verification import (
    VerificationProtocolPayload,
    VerificationProtocolRenderer,
)

from .document_scope import (
    filter_version_documents_for_scope,
    normalize_document_ids,
    selected_document_ids_from_scope,
)

logger = logging.getLogger(__name__)

TERMINAL_VERIFICATION_STATUSES = {
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELED,
}


class VerificationProtocolPersistenceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.protocols = VerificationProtocolRepository(session)
        self.check_results = CheckResultRepository(session)
        self.publication_artifacts = PublicationArtifactService(session)

    def persist(
        self,
        *,
        run: VerificationRun,
        payload: VerificationProtocolPayload,
        rule_lookup: dict[str, NormativeRule],
    ) -> tuple[VerificationProtocol, Any]:
        protocol = VerificationProtocol(
            verification_run_id=run.verification_run_id,
            protocol_no=f"VP-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            summary_status=payload.final_status,
            summary_text=payload.summary,
            status=VerificationProtocolStatus.DRAFT,
        )
        self.session.add(protocol)
        self.session.flush()

        for index, item in enumerate(payload.check_results, start=1):
            resolved_rule = rule_lookup.get(item.rule_code or "")
            rule_id = getattr(resolved_rule, "rule_id", None)
            is_technical_check = bool(item.is_technical_check)

            # Правило целостности check_results требует: если rule_id пуст,
            # запись должна быть явно помечена как technical/system check.
            if rule_id is None:
                is_technical_check = True

            self.session.add(
                CheckResult(
                    check_result_id=uuid4(),
                    verification_protocol_id=protocol.verification_protocol_id,
                    rule_id=rule_id,
                    rule_name=(
                        resolved_rule.rule_name if resolved_rule is not None else item.check_name
                    ),
                    check_name=item.check_name,
                    status=item.status,
                    severity=item.severity,
                    finding_text=item.finding_text,
                    evidence_ref=item.evidence_ref,
                    related_section_ref=item.related_section_ref,
                    sort_order=index,
                    is_technical_check=is_technical_check,
                )
            )

        basis_documents = self._basis_documents_for_run(protocol, run)
        for basis_document in basis_documents:
            self.session.add(basis_document)
        protocol.status = (
            VerificationProtocolStatus.INCOMPLETE
            if payload.final_status == ProtocolSummaryStatus.INCOMPLETE
            else VerificationProtocolStatus.PUBLISHED
        )
        self.session.flush()
        self.session.refresh(protocol)

        rendered_html = VerificationProtocolRenderer().render_html(
            protocol_no=protocol.protocol_no,
            payload=payload,
            basis_documents=[
                {
                    "title": item.title,
                    "role_code": item.role_code,
                    "version_ref": item.version_ref,
                    "required_flag": item.required_flag,
                }
                for item in sorted(basis_documents, key=lambda row: row.sort_order)
            ],
            metadata={
                "verification_run_id": str(protocol.verification_run_id),
                "issued_at": protocol.issued_at.isoformat() if protocol.issued_at else None,
                "protocol_state": getattr(protocol.status, "value", protocol.status),
                "summary_status": getattr(
                    protocol.summary_status, "value", protocol.summary_status
                ),
                "knowledge_version_id": str(run.knowledge_version_id),
                "basis_document_count": len(basis_documents),
                "findings_with_evidence": sum(
                    1
                    for item in payload.check_results
                    if item.evidence_ref or item.related_section_ref
                ),
                "findings_without_section_links": sum(
                    1
                    for item in payload.check_results
                    if not item.related_section_ref
                    and getattr(item.status, "value", item.status)
                    in {"warning", "failed", "not_determined"}
                ),
            },
        )
        artifact = self.publication_artifacts.publish(
            artifact_type="verification_protocol_view",
            target_type="verification_protocol",
            target_id=str(protocol.verification_protocol_id),
            rendered_html=rendered_html,
            rendered_markdown=None,
            created_by_user_id=run.started_by_user_id,
            published_at=protocol.issued_at,
            metadata={
                "verification_protocol_id": str(protocol.verification_protocol_id),
                "verification_run_id": str(protocol.verification_run_id),
                "summary_status": payload.final_status.value,
                "protocol_status": getattr(protocol.status, "value", protocol.status),
            },
        )
        return protocol, artifact

    def _basis_documents_for_run(
        self, protocol: VerificationProtocol, run: VerificationRun
    ) -> list[VerificationBasisDocument]:
        knowledge_versions = self._knowledge_versions_for_run(run)
        version_documents = [
            item
            for version in knowledge_versions
            for item in list(getattr(version, "version_documents", []) or [])
        ]
        scoped_version_documents = filter_version_documents_for_scope(
            version_documents,
            run.scope_snapshot,
        )
        require_catalog_packages = (
            requires_catalog_basis_for_versions(knowledge_versions)
            and not selected_document_ids_from_scope(run.scope_snapshot)
        )
        basis_documents: list[VerificationBasisDocument] = []
        for index, item in enumerate(scoped_version_documents, start=1):
            document = getattr(item, "document", None)
            role_code, required_flag = (
                resolve_basis_assignment(item)
                if require_catalog_packages
                else resolve_scoped_basis_assignment(item)
            )
            title = clean_display_file_name(getattr(document, "title", None)) or "Документ без названия"
            basis_documents.append(
                VerificationBasisDocument(
                    verification_protocol_id=protocol.verification_protocol_id,
                    document_id=getattr(item, "document_id", None),
                    title=title,
                    role_code=role_code,
                    version_ref=getattr(document, "version_label", None),
                    required_flag=bool(required_flag),
                    sort_order=index,
                )
            )
        return basis_documents

    def _knowledge_versions_for_run(self, run: VerificationRun) -> list[KnowledgeVersion]:
        scope_snapshot = run.scope_snapshot if isinstance(run.scope_snapshot, dict) else {}
        version_ids = normalize_document_ids(scope_snapshot.get("knowledge_version_ids") or [])
        if not version_ids:
            knowledge_version = getattr(run, "knowledge_version", None)
            return [knowledge_version] if knowledge_version is not None else []

        statement = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.knowledge_version_id.in_(version_ids))
            .options(
                selectinload(KnowledgeVersion.knowledge_base),
                selectinload(KnowledgeVersion.version_documents)
                .selectinload(KnowledgeVersionDocument.document)
                .selectinload(SourceDocument.source)
            )
        )
        loaded_versions = list(self.session.scalars(statement))
        version_by_id = {
            str(getattr(version, "knowledge_version_id", "") or ""): version
            for version in loaded_versions
        }
        return [
            version_by_id[version_id]
            for version_id in version_ids
            if version_id in version_by_id
        ]
