from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    Criticality,
    DocumentType,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    SourceStatus,
    SourceType,
)
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_core import KnowledgeSourceService
from app.integrations.knowledge.content_loader import ContentLoadError, fetch_uri
from app.integrations.knowledge.source_security import (
    SourceAvailabilityError,
    validate_source_base_uri,
)
from app.schemas.knowledge import SourceDocumentCreateRequest, SourceUpdateRequest


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )


def test_forbidden_remote_url_is_rejected_for_source() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_source_base_uri(
            source_type=SourceType.URL_LIST, base_uri="http://localhost/knowledge/index.html"
        )
    assert exc.value.error_code == "SOURCE_URL_FORBIDDEN_HOST"


def test_update_source_cannot_activate_unavailable_endpoint() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service.settings = SimpleNamespace(
        knowledge_allowed_local_source_roots=["/tmp"],
        knowledge_upload_dir=None,
    )
    source = SimpleNamespace(
        source_id="src-1",
        source_type=SourceType.URL_LIST,
        base_uri="https://example.com/index.html",
        source_metadata={},
        name="Remote KB",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.DRAFT,
    )
    service.get_source = lambda source_id: source
    service._assert_source_mutable = lambda *args, **kwargs: None
    service._validate_source = lambda *args, **kwargs: None
    service._validate_source_transition = lambda *args, **kwargs: None
    service._probe_source_availability = lambda *args, **kwargs: (_ for _ in ()).throw(
        SourceAvailabilityError("timeout")
    )

    with pytest.raises(ValidationError) as exc:
        KnowledgeSourceService.update_source(
            service,
            "src-1",
            SourceUpdateRequest(status=SourceStatus.ACTIVE),
            _principal(),
        )

    assert exc.value.error_code == "KNOWLEDGE_SOURCE_UNAVAILABLE"


def test_register_document_rejects_unsupported_extension() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service.settings = SimpleNamespace(
        knowledge_allowed_local_source_roots=["/tmp"],
        knowledge_upload_dir=None,
    )
    service.documents = SimpleNamespace(
        get_by_source_and_uri=lambda source_id, uri: None,
        unset_latest_for_uri=lambda **kwargs: None,
        add=lambda item: None,
    )
    source = SimpleNamespace(source_id="src-1", source_type=SourceType.REPOSITORY)
    service.get_source = lambda source_id: source
    service._assert_source_mutable = lambda *args, **kwargs: None

    with pytest.raises(ValidationError) as exc:
        KnowledgeSourceService.register_document(
            service,
            "src-1",
            SourceDocumentCreateRequest(
                document_type=DocumentType.OTHER,
                title="notes.csv",
                uri="file:///tmp/notes.csv",
            ),
            _principal(),
        )

    assert exc.value.error_code == "UNSUPPORTED_DOCUMENT_TYPE"


def test_register_document_allows_supported_pdf_when_type_is_not_inferred() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service.documents = SimpleNamespace(
        get_by_source_and_uri=lambda source_id, uri: None,
        unset_latest_for_uri=lambda **kwargs: None,
        add=lambda item: None,
    )
    source = SimpleNamespace(source_id="src-1")
    service.get_source = lambda source_id: source
    service._assert_source_mutable = lambda *args, **kwargs: None
    service._validate_document_uri = lambda uri, **kwargs: None

    document = KnowledgeSourceService.register_document(
        service,
        "src-1",
        SourceDocumentCreateRequest(
            document_type=DocumentType.OTHER,
            title="TMFC001_Product_Catalog_Management_v2.1.1.pdf",
            uri="file:///tmp/TMFC001_Product_Catalog_Management_v2.1.1.pdf",
        ),
        _principal(),
    )

    assert document.document_type == DocumentType.OTHER


def test_register_document_allows_any_extension_for_manual_upload_source() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service.documents = SimpleNamespace(
        get_by_source_and_uri=lambda source_id, uri: None,
        unset_latest_for_uri=lambda **kwargs: None,
        add=lambda item: None,
    )
    source = SimpleNamespace(source_id="src-1", source_type=SourceType.MANUAL_UPLOAD)
    service.get_source = lambda source_id: source
    service._assert_source_mutable = lambda *args, **kwargs: None
    service._validate_document_uri = lambda uri, allow_any_suffix=False: None

    document = KnowledgeSourceService.register_document(
        service,
        "src-1",
        SourceDocumentCreateRequest(
            document_type=DocumentType.OTHER,
            title="catalog.csv",
            uri="file:///tmp/catalog.csv",
        ),
        _principal(),
    )

    assert document.document_type == DocumentType.OTHER


def test_update_user_base_blocks_system_base_modification() -> None:
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = Mock()
    service.audit = Mock()
    mandatory_base = SimpleNamespace(
        knowledge_base_id="kb-mandatory",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
        status=KnowledgeBaseStatus.ACTIVE,
        name="Mandatory Architecture Baseline",
    )
    service.get_base = lambda knowledge_base_id: mandatory_base

    with pytest.raises(ValidationError) as exc:
        KnowledgeBaseService.update_user_base(
            service,
            "kb-mandatory",
            name="New name",
            description=None,
            status=None,
            principal=_principal(),
        )

    assert exc.value.error_code == "KNOWLEDGE_BASE_IMMUTABLE"


def test_fetch_uri_rejects_oversized_local_file(tmp_path: Path) -> None:
    oversized = tmp_path / "huge.md"
    oversized.write_text("x" * 32, encoding="utf-8")

    with pytest.raises(ContentLoadError) as exc:
        fetch_uri(str(oversized), max_size_bytes=16)

    assert "exceeds allowed limit" in str(exc.value)
