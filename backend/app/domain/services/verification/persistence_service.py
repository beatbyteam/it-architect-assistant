from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.enums import (
    ProtocolSummaryStatus,
    VerificationProtocolStatus,
    VerificationRunStatus,
)
from app.db.models.knowledge import (
    NormativeRule,
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
from app.domain.services.knowledge_basis import build_basis_inventory_for_version_documents
from app.domain.services.publication import PublicationArtifactService
from app.integrations.verification import (
    VerificationProtocolPayload,
    VerificationProtocolRenderer,
)

from .document_scope import filter_version_documents, selected_document_ids_from_scope

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

        knowledge_version = getattr(run, "knowledge_version", None)
        version_documents = (
            getattr(knowledge_version, "version_documents", [])
            if knowledge_version is not None
            else []
        )
        selected_document_ids = selected_document_ids_from_scope(run.scope_snapshot)
        scoped_version_documents = filter_version_documents(
            version_documents, selected_document_ids
        )
        if selected_document_ids:
            basis_documents = [
                VerificationBasisDocument(
                    verification_protocol_id=protocol.verification_protocol_id,
                    document_id=getattr(item, "document_id", None),
                    title=getattr(getattr(item, "document", None), "title", None)
                    or "Untitled document",
                    role_code=getattr(item, "role_code", None) or "reference_only",
                    version_ref=getattr(getattr(item, "document", None), "version_label", None),
                    required_flag=bool(getattr(item, "required_flag", False)),
                    sort_order=index,
                )
                for index, item in enumerate(scoped_version_documents, start=1)
            ]
        else:
            basis_inventory = build_basis_inventory_for_version_documents(scoped_version_documents)
            basis_documents = [
                VerificationBasisDocument(
                    verification_protocol_id=protocol.verification_protocol_id,
                    document_id=basis_item.document_id,
                    title=basis_item.title,
                    role_code=basis_item.role_code,
                    version_ref=basis_item.version_ref,
                    required_flag=basis_item.required_flag,
                    sort_order=index,
                )
                for index, basis_item in enumerate(
                    sorted(
                        basis_inventory.basis_documents,
                        key=lambda row: ((0 if row.required_flag else 1), row.role_code, row.title),
                    ),
                    start=1,
                )
            ]
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
