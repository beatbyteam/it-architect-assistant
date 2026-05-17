from __future__ import annotations

from typing import Any

from app.integrations.verification import VerificationRuleRegistry


def safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def extract_knowledge_scope(
    snapshot: Any, *, fallback_version_id: str | None = None
) -> dict[str, Any] | None:
    payload = safe_dict(snapshot)
    scope = safe_dict(payload.get("knowledge_snapshot"))
    if scope:
        document_scope = safe_dict(payload.get("document_scope"))
        if document_scope:
            scope = {**scope, "document_scope": document_scope}
        return scope
    if payload.get("knowledge_version_id") or payload.get("knowledge_version_ids"):
        return {
            "selected_generation_version_id": payload.get("knowledge_version_id")
            or fallback_version_id,
            "effective_version_ids": list(
                payload.get("knowledge_version_ids")
                or ([fallback_version_id] if fallback_version_id else [])
            ),
            "document_scope": safe_dict(payload.get("document_scope")) or None,
        }
    if fallback_version_id:
        return {
            "selected_generation_version_id": fallback_version_id,
            "effective_version_ids": [fallback_version_id],
        }
    return None


def serialize_solution_source_ref(ref: Any) -> dict[str, Any]:
    fragment = getattr(ref, "fragment", None)
    document = getattr(ref, "document", None) or getattr(fragment, "document", None)
    metadata = safe_dict(getattr(fragment, "fragment_metadata", None))
    source = getattr(document, "source", None)
    return {
        "fragment_id": str(ref.fragment_id) if ref.fragment_id else None,
        "document_id": str(ref.document_id) if ref.document_id else None,
        "quote_text": ref.quote_text,
        "document_title": getattr(document, "title", None) or metadata.get("document_title"),
        "version_ref": getattr(document, "version_label", None) or metadata.get("version_label"),
        "role_code": metadata.get("role_code"),
        "required_flag": bool(metadata.get("required_flag")),
        "source_location": getattr(fragment, "source_location", None)
        or metadata.get("source_location"),
        "source_name": getattr(source, "name", None) or metadata.get("source_name"),
        "document_type": getattr(
            getattr(document, "document_type", None),
            "value",
            getattr(document, "document_type", None),
        )
        or metadata.get("document_type"),
        "fragment_type": getattr(
            getattr(fragment, "fragment_type", None),
            "value",
            getattr(fragment, "fragment_type", None),
        )
        or metadata.get("fragment_type"),
        "sort_order": ref.sort_order,
    }


def build_solution_explainability(solution: Any) -> dict[str, Any]:
    run = solution.generation_run
    diagnostics = safe_dict(getattr(run, "diagnostics", None)) if run is not None else {}
    input_snapshot = safe_dict(getattr(run, "input_snapshot", None)) if run is not None else {}
    retrieval = safe_dict(diagnostics.get("retrieval"))
    prompt = safe_dict(diagnostics.get("prompt"))
    validation = safe_dict(diagnostics.get("validation"))
    basis_map: dict[str, dict[str, Any]] = {}
    section_coverage: list[dict[str, Any]] = []
    total_source_refs = 0
    for section in sorted(solution.sections, key=lambda row: row.sort_order):
        refs = [
            serialize_solution_source_ref(ref)
            for ref in sorted(section.source_refs, key=lambda row: row.sort_order)
        ]
        total_source_refs += len(refs)
        document_keys: set[str] = set()
        for ref in refs:
            key = (
                ref.get("document_id")
                or ref.get("document_title")
                or ref.get("fragment_id")
                or f"section:{section.section_code}:{ref['sort_order']}"
            )
            entry = basis_map.setdefault(
                str(key),
                {
                    "document_id": ref.get("document_id"),
                    "title": ref.get("document_title") or "Документ без названия",
                    "role_code": ref.get("role_code"),
                    "version_ref": ref.get("version_ref"),
                    "required_flag": bool(ref.get("required_flag")),
                    "source_name": ref.get("source_name"),
                    "document_type": ref.get("document_type"),
                    "fragment_count": 0,
                    "sections": [],
                },
            )
            entry["fragment_count"] += 1
            if section.section_code not in entry["sections"]:
                entry["sections"].append(section.section_code)
            if ref.get("document_id"):
                document_keys.add(str(ref.get("document_id")))
            elif ref.get("document_title"):
                document_keys.add(str(ref.get("document_title")))
        section_coverage.append(
            {
                "section_code": section.section_code,
                "title": section.title,
                "source_ref_count": len(refs),
                "basis_document_count": len(document_keys),
            }
        )
    basis_documents = sorted(
        basis_map.values(),
        key=lambda row: (
            (0 if row.get("required_flag") else 1),
            str(row.get("role_code") or "zz-reference"),
            str(row.get("title") or ""),
        ),
    )
    explainability_payload = safe_dict(diagnostics.get("explainability"))
    return {
        "knowledge_snapshot": input_snapshot.get("knowledge_snapshot"),
        "retrieval_summary": {
            "policy_id": retrieval.get("policy_id"),
            "retrieval_backend": retrieval.get("retrieval_backend"),
            "query_profile": retrieval.get("query_profile"),
            "selected_counts": retrieval.get("selected_counts"),
            "selected_fragments": retrieval.get("selected_fragments") or [],
            "coverage_summary": retrieval.get("coverage_summary")
            or diagnostics.get("coverage_summary"),
            "token_budget": prompt.get("token_budget"),
            "included_fragment_ids": prompt.get("included_fragment_ids") or [],
            "dropped_fragment_ids": prompt.get("dropped_fragment_ids") or [],
        },
        "basis_documents": basis_documents,
        "basis_documents_used": explainability_payload.get("basis_documents_used") or [],
        "section_coverage": section_coverage,
        "assumptions": explainability_payload.get("assumptions")
        or [
            item.item_text
            for item in solution.list_items
            if getattr(
                getattr(item, "item_group", None), "value", getattr(item, "item_group", None)
            )
            == "assumption"
        ],
        "next_steps": explainability_payload.get("next_steps")
        or [
            item.item_text
            for item in solution.list_items
            if getattr(
                getattr(item, "item_group", None), "value", getattr(item, "item_group", None)
            )
            == "next_step"
        ],
        "evidence_coverage": {
            "section_count": len(solution.sections),
            "total_source_refs": total_source_refs,
            "sections_with_evidence": sum(
                1 for item in section_coverage if item["source_ref_count"] > 0
            ),
            "sections_without_evidence": [
                item["section_code"] for item in section_coverage if item["source_ref_count"] == 0
            ],
        },
        "quality_summary": {
            "groundedness_score": validation.get("groundedness_score"),
            "citation_coverage": validation.get("citation_coverage"),
            "evidence_link_count": validation.get("evidence_link_count"),
            "quality_outcomes": diagnostics.get("quality_outcomes") or {},
            "validation_summary": explainability_payload.get("validation_summary") or validation,
        },
        "section_readiness": explainability_payload.get("section_readiness")
        or validation.get("section_readiness")
        or [],
        "structured_model": explainability_payload.get("structured_model") or {},
    }


def build_architecture_model_payload(solution: Any) -> dict[str, Any]:
    explainability = build_solution_explainability(solution)
    diagnostics = (
        safe_dict(
            safe_dict(getattr(solution.generation_run, "diagnostics", None)).get("validation")
        ).get("structured_model_summary")
        or {}
    )
    entities = [
        {
            "architecture_entity_id": str(item.architecture_entity_id),
            "entity_key": item.entity_key,
            "display_name": item.display_name,
            "source_kind": item.source_kind,
            "section_code": item.section_code,
            "archimate_layer": item.archimate_layer,
            "archimate_element_code": item.archimate_element_code,
            "archimate_element_title": item.archimate_element_title,
            "normalized_flag": bool(item.normalized_flag),
            "confidence": item.confidence,
            "entity_metadata": item.entity_metadata,
            "sort_order": item.sort_order,
        }
        for item in sorted(
            getattr(solution, "architecture_entities", []) or [], key=lambda row: row.sort_order
        )
    ]
    relations = [
        {
            "architecture_relation_id": str(item.architecture_relation_id),
            "relation_key": item.relation_key,
            "relation_type": item.relation_type,
            "source_entity_key": item.source_entity_key,
            "target_entity_key": item.target_entity_key,
            "section_code": item.section_code,
            "normalized_flag": bool(item.normalized_flag),
            "confidence": item.confidence,
            "relation_metadata": item.relation_metadata,
            "sort_order": item.sort_order,
        }
        for item in sorted(
            getattr(solution, "architecture_relations", []) or [], key=lambda row: row.sort_order
        )
    ]
    structured_model = safe_dict(explainability.get("structured_model"))
    return {
        "version": str(structured_model.get("version") or "sectioned-architecture-model.v1"),
        "entities": entities,
        "relations": relations,
        "section_summaries": list(structured_model.get("section_summaries") or []),
        "diagnostics": {
            "entity_count": len(entities),
            "relation_count": len(relations),
            **diagnostics,
        },
    }


def build_section_assessments_payload(solution: Any) -> list[dict[str, Any]]:
    return [
        {
            "section_assessment_id": str(item.section_assessment_id),
            "section_code": item.section_code,
            "heading": item.heading,
            "status": item.status,
            "score": item.score,
            "observed_signal_groups": list(item.observed_signal_groups or []),
            "missing_signal_groups": list(item.missing_signal_groups or []),
            "reasons": list(item.reasons or []),
            "allowed_archimate_elements": list(item.allowed_archimate_elements or []),
            "fallback_applied": bool(item.fallback_applied),
            "details": item.details,
            "sort_order": item.sort_order,
        }
        for item in sorted(
            getattr(solution, "section_assessments", []) or [], key=lambda row: row.sort_order
        )
    ]


def rule_group_for_result(*, rule_name: str | None, check_name: str | None) -> str | None:
    registry = VerificationRuleRegistry()
    target_names = {str(value).strip() for value in (rule_name, check_name) if value}
    for rule in registry.list_rules():
        if rule.name in target_names or rule.code in target_names:
            return rule.group
    return None


def group_verification_findings(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in findings:
        key = str(item.get("rule_group") or "other")
        groups.setdefault(key, []).append(item)
    return groups


def build_protocol_explainability(
    protocol: Any, basis_documents: list[dict[str, Any]]
) -> dict[str, Any]:
    diagnostics = safe_dict(getattr(protocol.verification_run, "diagnostics", None))
    scope_snapshot = safe_dict(getattr(protocol.verification_run, "scope_snapshot", None))
    findings = sorted(protocol.check_results, key=lambda row: row.sort_order)
    evidence_linked = [item for item in findings if item.evidence_ref or item.related_section_ref]
    findings_without_evidence = [
        item.rule_name or item.check_name
        for item in findings
        if not (
            item.evidence_ref
            or item.related_section_ref
            or getattr(item, "diagnostics", None)
        )
    ]
    findings_without_sections = [
        item.rule_name or item.check_name
        for item in findings
        if not item.related_section_ref
        and getattr(item.status, "value", item.status) in {"warning", "failed", "not_determined"}
    ]
    return {
        "knowledge_snapshot": diagnostics.get("knowledge_snapshot")
        or scope_snapshot.get("knowledge_snapshot"),
        "basis_package": {
            "basis_document_count": len(basis_documents),
            "required_basis_count": sum(1 for item in basis_documents if item.get("required_flag")),
            "missing_required_packages": safe_dict(diagnostics.get("validation")).get(
                "missing_required_packages"
            )
            or [],
            "basis_documents": basis_documents,
        },
        "evidence_coverage": {
            "finding_count": len(findings),
            "findings_with_evidence": len(evidence_linked),
            "findings_without_evidence": findings_without_evidence,
            "findings_without_section_links": findings_without_sections,
        },
        "rule_execution": {
            "rulebook_version": scope_snapshot.get("rulebook_version"),
            "validation_scope": scope_snapshot.get("validation_scope"),
            "executed_rule_groups": diagnostics.get("executed_rule_groups") or [],
            "current_rule_group": diagnostics.get("current_rule_group"),
            "score": diagnostics.get("verification_score"),
        },
    }


def build_snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = safe_dict(snapshot)
    snapshot_meta = safe_dict(snapshot.get("_snapshot"))
    return {
        "snapshot_meta": snapshot_meta,
        "knowledge_snapshot": snapshot.get("knowledge_snapshot"),
        "prompt_contract": snapshot.get("prompt_contract"),
        "rulebook_version": snapshot.get("rulebook_version"),
        "validation_scope": snapshot.get("validation_scope"),
        "retention_policy": snapshot.get("retention_policy"),
    }
