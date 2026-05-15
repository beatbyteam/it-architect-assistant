from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import DEFAULT_KNOWLEDGE_MAX_FILE_SIZE_BYTES, Settings, get_settings
from app.core.exceptions import ConflictError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    Criticality,
    DocumentType,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceScope,
    SourceStatus,
    SourceType,
)
from app.db.models.knowledge import KnowledgeVersion
from app.domain.services.knowledge.common import _build_allowed_local_source_roots
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_core import (
    KnowledgeSourceService,
    KnowledgeUpdateService,
    KnowledgeVersionService,
)
from app.domain.services.principal_keys import principal_actor_id, principal_requested_by
from app.integrations.knowledge.content_loader import fetch_uri
from app.integrations.knowledge.local_paths import (
    is_local_path_reference,
    is_windows_drive_path,
    normalize_local_path_reference,
)
from app.integrations.knowledge.source_security import validate_document_uri
from app.schemas.knowledge import (
    SourceCreateRequest,
    SourceDocumentCreateRequest,
    SourceUpdateRequest,
)

BUNDLE_IMPORT_LOGIN = "system.bundle_import"
BUNDLE_IMPORT_DISPLAY_NAME = "System Bundle Import"
_BUNDLE_SOURCE_CODE_METADATA_KEY = "bundle_source_code"
_BUNDLE_MANIFEST_ERROR_CODE = "KNOWLEDGE_BUNDLE_MANIFEST_INVALID"
_BUNDLE_TITLE_METADATA_KEY = "bundle_title"
_BUNDLE_DOCUMENT_TYPE_METADATA_KEY = "bundle_document_type"
_BUNDLE_VERSION_LABEL_METADATA_KEY = "bundle_version_label"
_BUNDLE_MANAGED_METADATA_KEY = "bundle_managed"
_BUNDLE_ROLE_CODE_METADATA_KEY = "bundle_role_code"
_BUNDLE_REQUIRED_FLAG_METADATA_KEY = "bundle_required_flag"


@dataclass(slots=True)
class BundleImportDiagnostics:
    manifest_uri: str
    manifest_root: str
    source_count: int
    document_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_uri": self.manifest_uri,
            "manifest_root": self.manifest_root,
            "source_count": self.source_count,
            "document_count": self.document_count,
        }


@dataclass(slots=True)
class BundleImportResult:
    manifest_uri: str
    imported_source_ids: list[str]
    imported_document_ids: list[str]
    update_run_id: str | None
    candidate_knowledge_version_id: str | None
    activated_knowledge_version_id: str | None
    diagnostics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_uri": self.manifest_uri,
            "imported_source_ids": self.imported_source_ids,
            "imported_document_ids": self.imported_document_ids,
            "update_run_id": self.update_run_id,
            "candidate_knowledge_version_id": self.candidate_knowledge_version_id,
            "activated_knowledge_version_id": self.activated_knowledge_version_id,
            "diagnostics": self.diagnostics,
        }


def system_bundle_principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id=BUNDLE_IMPORT_LOGIN,
        login=BUNDLE_IMPORT_LOGIN,
        display_name=BUNDLE_IMPORT_DISPLAY_NAME,
        account_type=AccountType.SERVICE,
        role_codes=["USER"],
        is_authenticated=True,
    )


def _resolve_requested_by(principal: AuthPrincipal, requested_by: str | None = None) -> str:
    return requested_by or principal_requested_by(principal)


def _ensure_update_not_running(session: Session, *, knowledge_base_id: str) -> None:
    running = KnowledgeUpdateService(session, get_settings())._get_running_run_with_recovery(
        knowledge_base_id=knowledge_base_id
    )
    if running is not None:
        raise ConflictError(
            "Another knowledge update run is already active",
            error_code="KNOWLEDGE_UPDATE_ALREADY_RUNNING",
        )


def _validate_manifest_payload(source_payloads: list[dict[str, Any]], manifest_root: str) -> None:
    seen_source_codes: set[str] = set()
    for raw_source in source_payloads:
        if not isinstance(raw_source, dict):
            raise ValidationError(
                "Each source entry must be a JSON object",
                error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE",
            )
        name = str(raw_source.get("name") or "").strip()
        if not name:
            raise ValidationError(
                "Bundle source must define name", error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE"
            )
        _coerce_source_type(raw_source.get("source_type"))
        _coerce_criticality(raw_source.get("criticality"))
        source_code = _normalize_source_code(raw_source.get("source_code"))
        if source_code:
            if source_code in seen_source_codes:
                raise ValidationError(
                    f"Bundle source_code '{source_code}' must be unique inside one manifest",
                    error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE",
                )
            seen_source_codes.add(source_code)
        _resolve_uri(raw_source.get("base_uri"), manifest_root)
        raw_documents = raw_source.get("documents") or []
        if not isinstance(raw_documents, list):
            raise ValidationError(
                f"Source '{name}' has invalid documents payload",
                error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENTS",
            )
        for raw_document in raw_documents:
            if not isinstance(raw_document, dict):
                raise ValidationError(
                    "Each document entry must be a JSON object",
                    error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENT",
                )
            title = str(raw_document.get("title") or "").strip()
            uri = _resolve_uri(raw_document.get("uri"), manifest_root)
            if not uri or not title:
                raise ValidationError(
                    "Bundle document must define title and uri",
                    error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENT",
                )
            _coerce_document_type(raw_document.get("document_type"))


def import_knowledge_bundle(
    session: Session,
    *,
    manifest_uri: str,
    knowledge_base_id: str | None = None,
    principal: AuthPrincipal | None = None,
    start_update: bool = True,
    activate_if_validated: bool = False,
    execute_update_inline: bool = False,
    reason: str | None = None,
    requested_by: str | None = None,
) -> BundleImportResult:
    settings = get_settings()
    principal = principal or system_bundle_principal()

    base_service = KnowledgeBaseService(session)
    if knowledge_base_id:
        target_base = base_service.get_base(knowledge_base_id, principal)
    else:
        base_service.ensure_system_bases()
        target_base = base_service.get_default_user_base(principal)

    try:
        manifest, manifest_root = load_bundle_manifest(manifest_uri, settings=settings)
    except TypeError:
        manifest, manifest_root = load_bundle_manifest(manifest_uri)
    source_payloads = manifest.get("sources")
    if not isinstance(source_payloads, list) or not source_payloads:
        raise ValidationError(
            "Bundle manifest must contain at least one source", error_code="KNOWLEDGE_BUNDLE_EMPTY"
        )

    _validate_manifest_payload(source_payloads, manifest_root)

    source_service = KnowledgeSourceService(session)
    version_service = KnowledgeVersionService(session)
    resolved_requested_by = _resolve_requested_by(principal, requested_by)
    if start_update:
        _ensure_update_not_running(session, knowledge_base_id=str(target_base.knowledge_base_id))
    imported_source_ids: list[str] = []
    imported_document_ids: list[str] = []

    try:
        for raw_source in source_payloads:
            source = _upsert_source(
                session,
                source_service,
                principal,
                raw_source,
                manifest_root,
                str(target_base.knowledge_base_id),
            )
            imported_source_ids.append(str(source.source_id))

            raw_documents = raw_source.get("documents") or []
            if not isinstance(raw_documents, list):
                raise ValidationError(
                    f"Source '{source.name}' has invalid documents payload",
                    error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENTS",
                )
            for raw_document in raw_documents:
                document = _upsert_document(
                    session,
                    source_service,
                    principal,
                    str(source.source_id),
                    raw_document,
                    manifest_root,
                )
                imported_document_ids.append(str(document.document_id))
        if hasattr(session, "commit"):
            session.commit()
    except Exception:
        if hasattr(session, "rollback"):
            session.rollback()
        raise

    diagnostics = BundleImportDiagnostics(
        manifest_uri=manifest_uri,
        manifest_root=manifest_root,
        source_count=len(imported_source_ids),
        document_count=len(imported_document_ids),
    ).as_dict()

    update_run_id: str | None = None
    candidate_knowledge_version_id: str | None = None
    activated_knowledge_version_id: str | None = None
    if start_update:
        updater = KnowledgeUpdateService(session, settings)

        try:
            run = updater.start_manual_run(
                knowledge_base_id=str(target_base.knowledge_base_id),
                source_scope=SourceScope.SELECTED,
                selected_source_ids=imported_source_ids,
                correlation_id=f"bundle-import-{uuid4().hex[:8]}",
                reason=reason
                or f"bundle_import:{manifest.get('bundle_code') or Path(manifest_root).name}",
                requested_by=resolved_requested_by,
                execute_inline=execute_update_inline,
                auto_activate_if_validated=activate_if_validated,
                principal=principal,
            )
        except ConflictError as exc:
            if exc.error_code != "KNOWLEDGE_UPDATE_ALREADY_RUNNING":
                raise
            diagnostics["update_start_skipped"] = True
            diagnostics["update_start_reason"] = exc.message
        else:
            if hasattr(session, "expire_all"):
                session.expire_all()
            update_run_id = str(run.update_run_id)
            candidate = _latest_candidate_for_run(session, update_run_id)
            if candidate is not None:
                candidate_knowledge_version_id = str(candidate.knowledge_version_id)
                if candidate.status == KnowledgeVersionStatus.ACTIVE:
                    activated_knowledge_version_id = str(candidate.knowledge_version_id)
                elif (
                    execute_update_inline
                    and activate_if_validated
                    and candidate.status == KnowledgeVersionStatus.VALIDATED
                ):
                    active = version_service.activate(
                        str(candidate.knowledge_version_id),
                        principal,
                        reason=reason or f"bundle_import:{manifest.get('bundle_code') or 'bundle'}",
                    )
                    activated_knowledge_version_id = str(active.knowledge_version_id)

    return BundleImportResult(
        manifest_uri=manifest_uri,
        imported_source_ids=imported_source_ids,
        imported_document_ids=imported_document_ids,
        update_run_id=update_run_id,
        candidate_knowledge_version_id=candidate_knowledge_version_id,
        activated_knowledge_version_id=activated_knowledge_version_id,
        diagnostics={
            **diagnostics,
            "bundle_code": manifest.get("bundle_code"),
            "bundle_name": manifest.get("bundle_name"),
            "auto_activate_if_validated": bool(activate_if_validated),
        },
    )


def load_bundle_manifest(
    manifest_uri: str, *, settings: Settings | None = None
) -> tuple[dict[str, Any], str]:
    resolved_settings = settings or get_settings()
    allowed_local_roots = _build_allowed_local_source_roots(resolved_settings)
    validate_document_uri(
        manifest_uri,
        allowed_local_roots=allowed_local_roots,
        allow_unrestricted_local_paths=False,
    )
    data, resolved_uri, _media_type = _fetch_manifest_bytes(
        manifest_uri,
        timeout_sec=float(getattr(resolved_settings, "knowledge_fetch_timeout_sec", 30.0) or 30.0),
        max_size_bytes=int(
            getattr(
                resolved_settings,
                "knowledge_max_document_size_bytes",
                DEFAULT_KNOWLEDGE_MAX_FILE_SIZE_BYTES,
            )
            or DEFAULT_KNOWLEDGE_MAX_FILE_SIZE_BYTES
        ),
    )
    try:
        manifest = json.loads(data.decode("utf-8"))
    except Exception as exc:  # pragma: no cover
        raise ValidationError(
            f"Failed to parse bundle manifest: {exc}",
            error_code=_BUNDLE_MANIFEST_ERROR_CODE,
        ) from exc
    if not isinstance(manifest, dict):
        raise ValidationError(
            "Bundle manifest must be a JSON object", error_code=_BUNDLE_MANIFEST_ERROR_CODE
        )
    manifest_root = _manifest_root(resolved_uri)
    return manifest, manifest_root


def _fetch_manifest_bytes(
    manifest_uri: str,
    *,
    timeout_sec: float,
    max_size_bytes: int,
) -> tuple[bytes, str, str | None]:
    try:
        return fetch_uri(manifest_uri, timeout_sec=timeout_sec, max_size_bytes=max_size_bytes)
    except TypeError:
        return fetch_uri(manifest_uri)


def _manifest_root(resolved_uri: str) -> str:
    parsed = urlparse(resolved_uri)
    if is_local_path_reference(resolved_uri):
        normalized_path = Path(normalize_local_path_reference(resolved_uri))
        return normalized_path.parent.as_posix()
    clean_path = parsed.path.rsplit("/", 1)[0] if "/" in parsed.path else ""
    if clean_path:
        return f"{parsed.scheme}://{parsed.netloc}{clean_path}"
    return f"{parsed.scheme}://{parsed.netloc}"


def _resolve_uri(value: str | None, manifest_root: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith(("http://", "https://", "file://")):
        return value
    parsed = urlparse(value)
    if parsed.scheme and len(parsed.scheme) > 1:
        return value
    if is_windows_drive_path(value):
        return value
    root_path = Path(manifest_root)
    if root_path.exists() or manifest_root.startswith("/"):
        return str((root_path / value).resolve())
    return f"{manifest_root.rstrip('/')}/{value.lstrip('/')}"


def _coerce_source_type(raw_value: Any) -> SourceType:
    try:
        return SourceType(str(raw_value))
    except Exception as exc:
        raise ValidationError(
            f"Unsupported source type: {raw_value}", error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE"
        ) from exc


def _coerce_criticality(raw_value: Any) -> Criticality:
    if raw_value is None:
        return Criticality.REQUIRED
    try:
        return Criticality(str(raw_value))
    except Exception as exc:
        raise ValidationError(
            f"Unsupported source criticality: {raw_value}",
            error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE",
        ) from exc


def _coerce_document_type(raw_value: Any) -> DocumentType:
    try:
        return DocumentType(str(raw_value))
    except Exception as exc:
        raise ValidationError(
            f"Unsupported document type: {raw_value}",
            error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENT",
        ) from exc


def _normalize_match_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_source_code(value: Any) -> str | None:
    normalized = _normalize_match_value(str(value) if value is not None else None)
    return normalized


def _bundle_source_metadata(
    raw_source: dict[str, Any], existing_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    merged = dict(existing_metadata or {})
    incoming = raw_source.get("source_metadata")
    if isinstance(incoming, dict):
        merged.update(incoming)
    source_code = _normalize_source_code(raw_source.get("source_code"))
    if source_code:
        merged[_BUNDLE_SOURCE_CODE_METADATA_KEY] = source_code
    return merged


def _match_bundle_source_code(source: Any) -> str | None:
    metadata = dict(getattr(source, "source_metadata", None) or {})
    return _normalize_source_code(metadata.get(_BUNDLE_SOURCE_CODE_METADATA_KEY))


def _pick_unique_source(matches: list[Any], *, reason: str) -> Any | None:
    if not matches:
        return None
    if len(matches) > 1:
        raise ValidationError(
            f"Bundle source identity is ambiguous: {reason}",
            error_code="KNOWLEDGE_BUNDLE_SOURCE_AMBIGUOUS",
            details={
                "reason": reason,
                "matched_source_ids": [str(getattr(item, "source_id", "")) for item in matches],
            },
        )
    return matches[0]


def _find_existing_source(
    service: KnowledgeSourceService,
    *,
    knowledge_base_id: str,
    source_type: SourceType,
    base_uri: str | None,
    source_code: str | None,
):
    normalized_type = str(source_type)
    normalized_base_uri = _normalize_match_value(base_uri)
    normalized_source_code = _normalize_source_code(source_code)
    sources = [
        item
        for item in service.list_sources(knowledge_base_id=knowledge_base_id)
        if str(getattr(item, "source_type", "")) == normalized_type
    ]
    code_matches = (
        [item for item in sources if _match_bundle_source_code(item) == normalized_source_code]
        if normalized_source_code
        else []
    )
    uri_matches = (
        [
            item
            for item in sources
            if _normalize_match_value(getattr(item, "base_uri", None)) == normalized_base_uri
        ]
        if normalized_base_uri
        else []
    )

    selected_by_code = (
        _pick_unique_source(code_matches, reason=f"source_code={normalized_source_code}")
        if normalized_source_code
        else None
    )
    selected_by_uri = (
        _pick_unique_source(uri_matches, reason=f"base_uri={normalized_base_uri}")
        if normalized_base_uri
        else None
    )

    if (
        selected_by_code is not None
        and selected_by_uri is not None
        and str(selected_by_code.source_id) != str(selected_by_uri.source_id)
    ):
        raise ValidationError(
            "Bundle source identity points to different existing sources",
            error_code="KNOWLEDGE_BUNDLE_SOURCE_AMBIGUOUS",
            details={
                "source_code": normalized_source_code,
                "base_uri": normalized_base_uri,
                "matched_source_ids": [
                    str(selected_by_code.source_id),
                    str(selected_by_uri.source_id),
                ],
            },
        )
    return selected_by_code or selected_by_uri


def _upsert_source(
    session: Session,
    service: KnowledgeSourceService,
    principal: AuthPrincipal,
    raw_source: dict[str, Any],
    manifest_root: str,
    knowledge_base_id: str,
):
    if not isinstance(raw_source, dict):
        raise ValidationError(
            "Each source entry must be a JSON object", error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE"
        )
    name = str(raw_source.get("name") or "").strip()
    if not name:
        raise ValidationError(
            "Bundle source must define name", error_code="KNOWLEDGE_BUNDLE_INVALID_SOURCE"
        )
    source_type = _coerce_source_type(raw_source.get("source_type"))
    base_uri = _resolve_uri(raw_source.get("base_uri"), manifest_root)
    refresh_policy = raw_source.get("refresh_policy")
    criticality = _coerce_criticality(raw_source.get("criticality"))
    source_code = _normalize_source_code(raw_source.get("source_code"))

    existing = _find_existing_source(
        service,
        knowledge_base_id=knowledge_base_id,
        source_type=source_type,
        base_uri=base_uri,
        source_code=source_code,
    )
    source_metadata = _bundle_source_metadata(
        raw_source, getattr(existing, "source_metadata", None) if existing is not None else None
    )
    if existing is None:
        created = service.create_source(
            SourceCreateRequest(
                knowledge_base_id=knowledge_base_id,
                source_type=source_type,
                name=name,
                base_uri=base_uri,
                criticality=criticality,
                refresh_policy=refresh_policy,
                source_metadata=source_metadata or None,
            ),
            principal,
            auto_commit=False,
        )
        return service.update_source(
            str(created.source_id),
            SourceUpdateRequest(
                status=SourceStatus.ACTIVE,
                source_metadata=source_metadata or None,
            ),
            principal,
            auto_commit=False,
        )
    return service.update_source(
        str(existing.source_id),
        SourceUpdateRequest(
            name=name,
            base_uri=base_uri,
            criticality=criticality,
            refresh_policy=refresh_policy,
            status=SourceStatus.ACTIVE,
            source_metadata=source_metadata or None,
        ),
        principal,
        auto_commit=False,
    )


def _upsert_document(
    session: Session,
    service: KnowledgeSourceService,
    principal: AuthPrincipal,
    source_id: str,
    raw_document: dict[str, Any],
    manifest_root: str,
):
    if not isinstance(raw_document, dict):
        raise ValidationError(
            "Each document entry must be a JSON object",
            error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENT",
        )
    uri = _resolve_uri(raw_document.get("uri"), manifest_root)
    title = str(raw_document.get("title") or "").strip()
    if not uri or not title:
        raise ValidationError(
            "Bundle document must define title and uri",
            error_code="KNOWLEDGE_BUNDLE_INVALID_DOCUMENT",
        )
    payload = SourceDocumentCreateRequest(
        document_type=_coerce_document_type(raw_document.get("document_type")),
        title=title,
        uri=uri,
        version_label=raw_document.get("version_label"),
        checksum=raw_document.get("checksum"),
        is_latest=bool(raw_document.get("is_latest", True)),
    )
    bundle_metadata = {
        _BUNDLE_MANAGED_METADATA_KEY: True,
        _BUNDLE_TITLE_METADATA_KEY: payload.title,
        _BUNDLE_DOCUMENT_TYPE_METADATA_KEY: payload.document_type.value,
        _BUNDLE_VERSION_LABEL_METADATA_KEY: payload.version_label,
    }
    if raw_document.get("role_code") is not None:
        bundle_metadata[_BUNDLE_ROLE_CODE_METADATA_KEY] = str(raw_document.get("role_code"))
    if raw_document.get("required_flag") is not None:
        bundle_metadata[_BUNDLE_REQUIRED_FLAG_METADATA_KEY] = bool(
            raw_document.get("required_flag")
        )
    existing = next((item for item in service.list_documents(source_id) if item.uri == uri), None)
    if existing is None:
        document = service.register_document(source_id, payload, principal, auto_commit=False)
        document.document_metadata = {
            **(dict(getattr(document, "document_metadata", None) or {})),
            **bundle_metadata,
        }
        service.session.add(document)
        service.session.flush()
        return document
    existing.document_type = payload.document_type
    existing.title = payload.title
    existing.uri = payload.uri
    existing.version_label = payload.version_label
    existing.checksum = payload.checksum
    existing.status = SourceDocumentStatus.REGISTERED
    existing.is_latest = payload.is_latest
    existing.document_metadata = {
        **(dict(getattr(existing, "document_metadata", None) or {})),
        **bundle_metadata,
    }
    if payload.is_latest:
        service.documents.unset_latest_for_uri(
            source_id=existing.source_id,
            uri=existing.uri,
            exclude_document_id=existing.document_id,
        )
    service.session.add(existing)
    service.audit.record(
        event_type="knowledge.document.updated",
        target_type="source_document",
        target_id=existing.document_id,
        message=f"Document '{existing.title}' updated",
        actor_user_id=principal_actor_id(principal),
    )
    service.session.flush()
    return existing


def _latest_candidate_for_run(session: Session, run_id: str) -> KnowledgeVersion | None:
    return KnowledgeVersionService(session).versions.get_by_update_run_id(run_id)
