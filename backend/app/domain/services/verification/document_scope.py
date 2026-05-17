from __future__ import annotations

from typing import Any

from app.core.exceptions import ValidationError


def normalize_document_ids(document_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in document_ids or []:
        document_id = str(value or "").strip()
        if not document_id or document_id in seen:
            continue
        normalized.append(document_id)
        seen.add(document_id)
    return normalized


def selected_document_ids_from_scope(scope_snapshot: Any) -> list[str]:
    if not isinstance(scope_snapshot, dict):
        return []
    document_scope = scope_snapshot.get("document_scope")
    if not isinstance(document_scope, dict):
        return []
    if document_scope.get("mode") != "selected":
        return []
    return normalize_document_ids(document_scope.get("selected_document_ids") or [])


def effective_document_ids_from_scope(scope_snapshot: Any) -> list[str]:
    if not isinstance(scope_snapshot, dict):
        return []
    document_scope = scope_snapshot.get("document_scope")
    if not isinstance(document_scope, dict):
        return []
    if document_scope.get("mode") == "selected":
        return normalize_document_ids(document_scope.get("selected_document_ids") or [])
    return normalize_document_ids(document_scope.get("effective_document_ids") or [])


def filter_version_documents(
    version_documents: list[Any] | tuple[Any, ...] | Any,
    selected_document_ids: list[str] | None,
) -> list[Any]:
    rows = list(version_documents or [])
    selected = set(normalize_document_ids(selected_document_ids))
    if not selected:
        return rows
    return [
        item
        for item in rows
        if str(getattr(item, "document_id", "") or "") in selected
    ]


def filter_version_documents_for_scope(
    version_documents: list[Any] | tuple[Any, ...] | Any,
    scope_snapshot: Any,
) -> list[Any]:
    rows = list(version_documents or [])
    scoped_ids = effective_document_ids_from_scope(scope_snapshot)
    if not scoped_ids:
        seen: set[str] = set()
        deduped: list[Any] = []
        for item in rows:
            document_id = str(getattr(item, "document_id", "") or "")
            if document_id and document_id in seen:
                continue
            if document_id:
                seen.add(document_id)
            deduped.append(item)
        return deduped
    document_by_id: dict[str, Any] = {}
    for item in rows:
        document_id = str(getattr(item, "document_id", "") or "")
        if document_id:
            document_by_id[document_id] = item
    return [
        document_by_id[document_id]
        for document_id in scoped_ids
        if document_id in document_by_id
    ]


def serialize_version_document(item: Any) -> dict[str, Any]:
    document = getattr(item, "document", None)
    return {
        "document_id": str(getattr(item, "document_id", "") or ""),
        "title": getattr(document, "title", None) or "Документ без названия",
        "source_name": getattr(getattr(document, "source", None), "name", None),
        "role_code": getattr(item, "role_code", None),
        "required_flag": bool(getattr(item, "required_flag", False)),
        "version_ref": getattr(document, "version_label", None),
        "document_type": getattr(
            getattr(document, "document_type", None),
            "value",
            getattr(document, "document_type", None),
        ),
    }


def build_document_scope_snapshot(
    *,
    knowledge_versions: list[Any],
    selected_document_ids: list[str] | None,
) -> dict[str, Any]:
    selected_ids = normalize_document_ids(selected_document_ids)
    version_documents = [
        item
        for version in knowledge_versions
        for item in list(getattr(version, "version_documents", []) or [])
    ]
    document_by_id = {
        str(getattr(item, "document_id", "") or ""): item
        for item in version_documents
        if str(getattr(item, "document_id", "") or "")
    }
    if selected_ids:
        missing_ids = [document_id for document_id in selected_ids if document_id not in document_by_id]
        if missing_ids:
            raise ValidationError(
                "Выбранные документы базы знаний отсутствуют в активной области знаний",
                error_code="KNOWLEDGE_DOCUMENT_SCOPE_INVALID",
                details={"document_ids": missing_ids},
            )
        documents = [serialize_version_document(document_by_id[document_id]) for document_id in selected_ids]
        return {
            "mode": "selected",
            "selected_document_ids": selected_ids,
            "effective_document_ids": selected_ids,
            "document_count": len(selected_ids),
            "selected_documents": documents,
        }
    all_ids = sorted(document_by_id)
    return {
        "mode": "full",
        "selected_document_ids": [],
        "effective_document_ids": all_ids,
        "document_count": len(all_ids),
        "selected_documents": [],
    }
