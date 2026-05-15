from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.db.models.knowledge import KnowledgeVersion
from app.domain.services.knowledge_basis import build_basis_inventory_for_version_documents


def _safe_isoformat(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def build_knowledge_version_snapshot(version: KnowledgeVersion | None) -> dict[str, Any]:
    if version is None:
        return {}
    version_documents = list(getattr(version, "version_documents", []) or [])
    basis_inventory = build_basis_inventory_for_version_documents(version_documents)
    source_snapshot = dict(getattr(version, "source_snapshot", {}) or {})
    basis_documents = [
        {
            "document_id": str(item.document_id),
            "title": item.title,
            "role_code": item.role_code,
            "version_ref": item.version_ref,
            "required_flag": item.required_flag,
        }
        for item in sorted(
            basis_inventory.basis_documents,
            key=lambda row: ((0 if row.required_flag else 1), row.role_code, row.title),
        )
    ]
    snapshot = {
        "knowledge_version_id": str(version.knowledge_version_id),
        "knowledge_base_id": str(version.knowledge_base_id),
        "knowledge_base_code": getattr(getattr(version, "knowledge_base", None), "code", None),
        "version_code": version.version_no,
        "status": getattr(version.status, "value", version.status),
        "created_at": _safe_isoformat(getattr(version, "created_at", None)),
        "activated_at": _safe_isoformat(getattr(version, "activated_at", None)),
        "activated_by_user_id": str(version.activated_by_user_id)
        if getattr(version, "activated_by_user_id", None)
        else None,
        "required_packages": list(basis_inventory.required_packages),
        "missing_required_packages": list(basis_inventory.missing_required_packages),
        "required_basis_present": basis_inventory.required_basis_present,
        "basis_document_count": len(basis_documents),
        "basis_documents": basis_documents,
        "document_count": len(version_documents),
        "source_scope": source_snapshot.get("source_scope"),
        "selected_source_ids": list(source_snapshot.get("selected_source_ids") or []),
        "source_count": len(source_snapshot.get("sources") or []),
        "source_snapshot_ref": str(version.knowledge_version_id),
    }
    snapshot["snapshot_hash"] = sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return snapshot


def build_knowledge_scope_snapshot(
    *, mandatory_version: KnowledgeVersion | None, selected_user_version: KnowledgeVersion | None
) -> dict[str, Any]:
    mandatory_snapshot = build_knowledge_version_snapshot(mandatory_version)
    selected_snapshot = build_knowledge_version_snapshot(selected_user_version)
    scope = {
        "mandatory_version": mandatory_snapshot,
        "selected_user_version": selected_snapshot,
        "effective_version_ids": [
            value
            for value in [
                mandatory_snapshot.get("knowledge_version_id"),
                selected_snapshot.get("knowledge_version_id"),
            ]
            if value
        ],
        "selected_generation_version_id": selected_snapshot.get("knowledge_version_id")
        or mandatory_snapshot.get("knowledge_version_id"),
        "basis_documents": [
            *list(mandatory_snapshot.get("basis_documents") or []),
            *list(selected_snapshot.get("basis_documents") or []),
        ],
    }
    scope["snapshot_hash"] = sha256(
        json.dumps(scope, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return scope
