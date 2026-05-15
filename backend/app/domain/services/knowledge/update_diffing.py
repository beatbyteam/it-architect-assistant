from __future__ import annotations

from typing import Any


def build_version_document_signature(
    version: Any | None,
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


def build_version_diff_summary(candidate: Any, active: Any | None) -> dict[str, Any] | None:
    if active is None or str(active.knowledge_version_id) == str(candidate.knowledge_version_id):
        return None
    active_docs = {item[0]: item[1:] for item in build_version_document_signature(active)}
    candidate_docs = {item[0]: item[1:] for item in build_version_document_signature(candidate)}
    added = set(candidate_docs) - set(active_docs)
    removed = set(active_docs) - set(candidate_docs)
    changed = {
        doc_id
        for doc_id in set(candidate_docs) & set(active_docs)
        if candidate_docs.get(doc_id) != active_docs.get(doc_id)
    }
    active_summary = dict((active.summary or {}) if active is not None else {})
    candidate_summary = dict(candidate.summary or {})
    return {
        "active_knowledge_version_id": str(active.knowledge_version_id),
        "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
        "active_version_no": active.version_no,
        "candidate_version_no": candidate.version_no,
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


def classify_document_error_code(message: str, *, default: str) -> str:
    lowered = (message or "").lower()
    if "exceeds allowed limit" in lowered or ("size" in lowered and "limit" in lowered):
        return "DOCUMENT_SIZE_LIMIT_EXCEEDED"
    if "unsupported" in lowered and "document" in lowered:
        return "UNSUPPORTED_DOCUMENT_TYPE"
    if "forbidden" in lowered and "host" in lowered:
        return "SOURCE_URL_FORBIDDEN_HOST"
    if "forbidden" in lowered and "network" in lowered:
        return "SOURCE_URL_FORBIDDEN_NETWORK"
    return default
