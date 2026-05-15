from __future__ import annotations

from pathlib import Path

from app.db.enums import Criticality, DocumentType, SourceDocumentStatus, SourceStatus, SourceType
from app.db.models.knowledge import KnowledgeSource, SourceDocument
from app.integrations.knowledge.source_readers import RepositoryReader, UrlListReader


def test_repository_reader_discovers_supported_documents(tmp_path: Path) -> None:
    (tmp_path / "architecture.md").write_text("# Architecture\n\nText", encoding="utf-8")
    (tmp_path / "rules.docx").write_bytes(b"docx-placeholder")
    (tmp_path / "ignore.xlsx").write_bytes(b"binary")
    source = KnowledgeSource(
        source_type=SourceType.REPOSITORY,
        name="repo",
        base_uri=str(tmp_path),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    documents = RepositoryReader().resolve_documents(source, [])
    discovered_names = sorted(item.title for item in documents)
    assert discovered_names == ["architecture.md", "rules.docx"]


def test_url_list_reader_discovers_documents_from_local_html_index(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "baseline.md").write_text("# Baseline", encoding="utf-8")
    (docs_dir / "standard.pdf").write_bytes(b"%PDF-1.4\n%stub")
    html = """
    <html><body>
      <a href="docs/baseline.md">Baseline</a>
      <a href="docs/standard.pdf">Standard</a>
      <a href="docs/ignored.txt">Ignored</a>
    </body></html>
    """
    index_path = tmp_path / "index.html"
    index_path.write_text(html, encoding="utf-8")
    source = KnowledgeSource(
        source_type=SourceType.URL_LIST,
        name="index",
        base_uri=index_path.as_uri(),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    documents = UrlListReader().resolve_documents(source, [])
    discovered_titles = sorted(item.title for item in documents)
    assert discovered_titles == ["Baseline", "Standard"]
    assert all(item.uri.startswith("file://") for item in documents)


def test_repository_reader_preserves_bundle_metadata_for_existing_documents(
    tmp_path: Path,
) -> None:
    technology_path = tmp_path / "selected_technology_standard.md"
    technology_path.write_text("# Selected Technology Standard\n", encoding="utf-8")
    source = KnowledgeSource(
        source_type=SourceType.REPOSITORY,
        name="repo",
        base_uri=str(tmp_path),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    existing = SourceDocument(
        source_id=source.source_id,
        document_type=DocumentType.TECHNOLOGY,
        title="Selected Technology Standard",
        uri=technology_path.resolve().as_uri(),
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
        document_metadata={
            "bundle_title": "Selected Technology Standard",
            "bundle_document_type": DocumentType.TECHNOLOGY.value,
        },
    )

    documents = RepositoryReader().resolve_documents(source, [existing])

    assert documents == [existing]
    assert existing.title == "Selected Technology Standard"
    assert existing.document_type == DocumentType.TECHNOLOGY


def test_manual_upload_reader_keeps_registered_document_for_unknown_extension(
    tmp_path: Path,
) -> None:
    upload_path = tmp_path / "desktop-export.custombin"
    upload_path.write_bytes(b"custom upload payload")
    source = KnowledgeSource(
        source_type=SourceType.MANUAL_UPLOAD,
        name="uploads",
        base_uri=tmp_path.as_uri(),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    existing = SourceDocument(
        document_id="doc-1",
        source_id=source.source_id,
        document_type=DocumentType.OTHER,
        title="Desktop Export",
        uri=upload_path.resolve().as_uri(),
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
    )

    documents = RepositoryReader().resolve_documents(source, [existing])

    assert documents == [existing]
    assert existing.document_id == "doc-1"
    assert existing.status == SourceDocumentStatus.REGISTERED
    assert existing.media_type is None
    assert existing.size_bytes == len(b"custom upload payload")
