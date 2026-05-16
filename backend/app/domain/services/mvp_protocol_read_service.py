from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.security import AuthPrincipal
from app.db.models.knowledge import KnowledgeVersion, KnowledgeVersionDocument
from app.db.models.verification import (
    VerificationBasisDocument,
    VerificationProtocol,
    VerificationRun,
)
from app.domain.services.knowledge_basis import build_basis_inventory_for_version_documents
from app.domain.services.presenters import (
    retention_policy_payload,
)
from app.domain.services.verification.document_scope import (
    filter_version_documents,
    selected_document_ids_from_scope,
)
from app.schemas.verification import InternalVerificationRunStartRequest


def start_verification(
    service,
    solution_version_id: str,
    *,
    correlation_id: str | None,
    principal: AuthPrincipal,
    idempotency_key: str | None = None,
    knowledge_document_ids: list[str] | None = None,
    verification_run_service_factory,
):
    return verification_run_service_factory(service.session, service.settings).start_run(
        InternalVerificationRunStartRequest(
            solution_version_id=solution_version_id,
            validation_scope="full",
            knowledge_document_ids=knowledge_document_ids or [],
            correlation_id=correlation_id or idempotency_key,
            idempotency_key=idempotency_key,
        ),
        principal,
    )


def get_verification_run_payload(
    service, run_id: str, principal: AuthPrincipal, *, verification_run_service_factory
) -> dict[str, Any]:
    run = verification_run_service_factory(service.session, service.settings).get_run(
        run_id, principal
    )
    diagnostics = service._safe_dict(run.diagnostics)
    diagnostics.setdefault("operation_kind", "verification_run")
    diagnostics.setdefault("operation_id", str(run.verification_run_id))
    return {
        "verification_run_id": str(run.verification_run_id),
        "solution_version_id": str(run.solution_version_id),
        "knowledge_version_id": str(run.knowledge_version_id),
        "state": service.map_verification_run_state(run.status),
        "run_state": getattr(run.status, "value", run.status),
        "current_stage": run.current_stage,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "protocol_id": str(run.protocol.verification_protocol_id) if run.protocol else None,
        "knowledge_scope": service._extract_knowledge_scope(
            getattr(run, "scope_snapshot", None), fallback_version_id=str(run.knowledge_version_id)
        ),
        "diagnostics": diagnostics,
    }


def get_verification_protocol_payload(
    service, protocol_id: str, principal: AuthPrincipal, *, verification_query_service_factory
) -> dict[str, Any]:
    statement = (
        select(VerificationProtocol)
        .where(VerificationProtocol.verification_protocol_id == protocol_id)
        .options(
            selectinload(VerificationProtocol.check_results),
            selectinload(VerificationProtocol.basis_documents),
            selectinload(VerificationProtocol.verification_run)
            .selectinload(VerificationRun.knowledge_version)
            .selectinload(KnowledgeVersion.version_documents)
            .selectinload(KnowledgeVersionDocument.document),
        )
    )
    protocol = service.session.scalar(statement)
    if protocol is None:
        raise NotFoundError("VerificationProtocol", protocol_id)
    verification_query_service_factory(service.session)._ensure_solution_access(
        protocol.verification_run.solution_version, principal
    )
    current_publication = service.publication_artifacts.get_current(
        target_type="verification_protocol", target_id=str(protocol.verification_protocol_id)
    )
    basis_documents = list(protocol.basis_documents)
    if not basis_documents:
        basis_documents = service._materialize_basis_documents(protocol)
    findings = sorted(protocol.check_results, key=lambda row: row.sort_order)
    totals_by_status: dict[str, int] = {}
    totals_by_severity: dict[str, int] = {}
    for item in findings:
        status_value = getattr(item.status, "value", item.status)
        severity_value = getattr(item.severity, "value", item.severity)
        totals_by_status[status_value] = totals_by_status.get(status_value, 0) + 1
        totals_by_severity[severity_value] = totals_by_severity.get(severity_value, 0) + 1
    finding_rows = [
        {
            "check_result_id": str(item.check_result_id),
            "rule_id": str(item.rule_id) if item.rule_id else None,
            "rule_name": item.rule_name or item.check_name,
            "rule_group": service._rule_group_for_result(
                rule_name=item.rule_name, check_name=item.check_name
            ),
            "severity": getattr(item.severity, "value", item.severity),
            "status": getattr(item.status, "value", item.status),
            "finding_text": item.finding_text,
            "evidence": item.evidence_ref,
            "related_section_ref": item.related_section_ref,
            "sort_order": item.sort_order,
        }
        for item in findings
    ]
    grouped_findings = service._group_verification_findings(finding_rows)
    compliance_summary = {
        "groups": {
            group: {
                "count": len(items),
                "failed": sum(1 for row in items if row.get("status") == "failed"),
                "warnings": sum(1 for row in items if row.get("status") == "warning"),
                "incomplete": sum(1 for row in items if row.get("status") == "not_determined"),
            }
            for group, items in grouped_findings.items()
        },
        "critical_violation_count": sum(
            1
            for row in finding_rows
            if row.get("severity") == "critical"
            and row.get("status") in {"failed", "warning", "not_determined"}
        ),
        "relevant_violation_count": sum(
            1
            for row in finding_rows
            if row.get("rule_group") in {"structure", "normative"}
            and row.get("status") in {"failed", "warning", "not_determined"}
        ),
    }
    return {
        "protocol_id": str(protocol.verification_protocol_id),
        "verification_run_id": str(protocol.verification_run_id),
        "solution_version_id": str(protocol.verification_run.solution_version_id),
        "knowledge_version_id": str(protocol.verification_run.knowledge_version_id),
        "created_at": protocol.issued_at,
        "state": service.map_protocol_state(protocol.status, protocol.summary_status),
        "protocol_state": service.map_protocol_state(protocol.status, protocol.summary_status),
        "summary_status": getattr(protocol.summary_status, "value", protocol.summary_status),
        "summary_text": protocol.summary_text,
        "totals_by_status": totals_by_status,
        "totals_by_severity": totals_by_severity,
        "basis_documents": [
            {
                "protocol_basis_document_id": str(item.protocol_basis_document_id)
                if getattr(item, "protocol_basis_document_id", None)
                else None,
                "document_id": str(item.document_id)
                if getattr(item, "document_id", None)
                else None,
                "title": item.title,
                "role_code": item.role_code,
                "version_ref": item.version_ref,
                "required_flag": bool(item.required_flag),
                "sort_order": item.sort_order,
            }
            for item in sorted(basis_documents, key=lambda row: row.sort_order)
        ],
        "findings": finding_rows,
        "grouped_findings": grouped_findings,
        "compliance_summary": compliance_summary,
        "diagnostics": {
            **service._safe_dict(protocol.verification_run.diagnostics),
            "operation_kind": "verification_run",
            "operation_id": str(protocol.verification_run.verification_run_id),
        },
        "publication_artifact_id": str(current_publication.published_artifact_id)
        if current_publication
        else None,
        "publication_revision_no": current_publication.revision_no if current_publication else None,
        "artifact_state": current_publication.state if current_publication else None,
        "version_hash": current_publication.version_hash if current_publication else None,
        "publication_history": service._list_publication_revisions(
            target_type="verification_protocol", target_id=str(protocol.verification_protocol_id)
        ),
        "retention_policy": retention_policy_payload(target_type="verification_protocol"),
        "scope_snapshot": protocol.verification_run.scope_snapshot,
        "knowledge_scope": service._extract_knowledge_scope(
            protocol.verification_run.scope_snapshot,
            fallback_version_id=str(protocol.verification_run.knowledge_version_id),
        ),
        "snapshot_summary": service._build_snapshot_summary(
            protocol.verification_run.scope_snapshot
        ),
    }


def get_verification_protocol_violations_payload(
    service, protocol_id: str, principal: AuthPrincipal, *, verification_query_service_factory
) -> dict[str, Any]:
    payload = get_verification_protocol_payload(
        service,
        protocol_id,
        principal,
        verification_query_service_factory=verification_query_service_factory,
    )
    findings = list(payload.get("findings") or [])
    violations = [
        item
        for item in findings
        if item.get("rule_group") in {"structure", "normative", "consistency"}
        and item.get("status") in {"failed", "warning", "not_determined"}
    ]
    return {
        "protocol_id": payload["protocol_id"],
        "violations": violations,
    }


def get_verification_protocol_rendered_payload(
    service, protocol_id: str, principal: AuthPrincipal, *, verification_query_service_factory
) -> dict[str, Any]:
    payload = get_verification_protocol_payload(
        service,
        protocol_id,
        principal,
        verification_query_service_factory=verification_query_service_factory,
    )
    rendered = verification_query_service_factory(service.session).get_protocol_view(
        protocol_id, principal
    )
    protocol = verification_query_service_factory(service.session).get_protocol(
        protocol_id, principal
    )
    return {
        "protocol_id": str(rendered["verification_protocol_id"]),
        "created_at": rendered["issued_at"],
        "summary_status": getattr(rendered["summary_status"], "value", rendered["summary_status"]),
        "protocol_state": service.map_protocol_state(
            rendered["protocol_status"], rendered["summary_status"]
        ),
        "rendered_html": rendered["rendered_html"],
        "publication_artifact_id": rendered.get("publication_artifact_id"),
        "publication_revision_no": rendered.get("publication_revision_no"),
        "artifact_state": rendered.get("artifact_state"),
        "version_hash": rendered.get("version_hash"),
        "publication_history": service._list_publication_revisions(
            target_type="verification_protocol", target_id=str(protocol.verification_protocol_id)
        ),
        "retention_policy": retention_policy_payload(target_type="verification_protocol"),
        "snapshot_summary": service._build_snapshot_summary(
            protocol.verification_run.scope_snapshot
        ),
        "explainability": service._build_protocol_explainability(
            protocol, payload.get("basis_documents") or []
        ),
    }


def _materialize_basis_documents(
    service, protocol: VerificationProtocol
) -> list[VerificationBasisDocument]:
    knowledge_version = protocol.verification_run.knowledge_version
    if knowledge_version is None:
        return []
    selected_document_ids = selected_document_ids_from_scope(
        protocol.verification_run.scope_snapshot
    )
    scoped_version_documents = filter_version_documents(
        knowledge_version.version_documents,
        selected_document_ids,
    )
    if selected_document_ids:
        return [
            VerificationBasisDocument(
                verification_protocol_id=protocol.verification_protocol_id,
                document_id=getattr(item, "document_id", None),
                title=getattr(getattr(item, "document", None), "title", None)
                or "Документ без названия",
                role_code=getattr(item, "role_code", None) or "reference_only",
                version_ref=getattr(getattr(item, "document", None), "version_label", None),
                required_flag=bool(getattr(item, "required_flag", False)),
                sort_order=index,
            )
            for index, item in enumerate(scoped_version_documents, start=1)
        ]
    basis_inventory = build_basis_inventory_for_version_documents(scoped_version_documents)
    return [
        VerificationBasisDocument(
            verification_protocol_id=protocol.verification_protocol_id,
            document_id=descriptor.document_id,
            title=descriptor.title,
            role_code=descriptor.role_code,
            version_ref=descriptor.version_ref,
            required_flag=descriptor.required_flag,
            sort_order=index,
        )
        for index, descriptor in enumerate(
            sorted(
                basis_inventory.basis_documents,
                key=lambda row: ((0 if row.required_flag else 1), row.role_code, row.title),
            ),
            start=1,
        )
    ]
