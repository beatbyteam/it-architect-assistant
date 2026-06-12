from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import cast
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.db.enums import DocumentType, SourceDocumentStatus, SourceStatus, SourceType
from app.db.models.knowledge import KnowledgeSource, SourceDocument
from app.integrations.knowledge.content_loader import SUPPORTED_DOCUMENT_SUFFIXES
from app.integrations.knowledge.local_paths import is_local_path_reference, resolve_local_path
from app.integrations.knowledge.source_security import (
    assert_local_path_allowed,
    assert_safe_remote_url,
)

DISCOVERABLE_SUFFIXES = set(SUPPORTED_DOCUMENT_SUFFIXES)
MAX_DISCOVERY_PAGES = 200
MAX_DISCOVERY_DOCUMENTS = 500
MAX_DISCOVERY_DEPTH = 2
MAX_DISCOVERY_PAGE_BYTES = 2_000_000
DISCOVERY_ACCEPT_HEADER = "text/html, text/plain;q=0.9, */*;q=0.8"


KNOWLEDGE_EXCLUDED_METADATA_KEY = "knowledge_excluded"
_BUNDLE_TITLE_METADATA_KEY = "bundle_title"
_BUNDLE_DOCUMENT_TYPE_METADATA_KEY = "bundle_document_type"


def is_document_explicitly_excluded(document: SourceDocument | None) -> bool:
    metadata = (
        dict(getattr(document, "document_metadata", None) or {}) if document is not None else {}
    )
    return bool(metadata.get(KNOWLEDGE_EXCLUDED_METADATA_KEY))


def mark_document_explicitly_excluded(document: SourceDocument, *, reason: str) -> None:
    metadata = dict(getattr(document, "document_metadata", None) or {})
    metadata[KNOWLEDGE_EXCLUDED_METADATA_KEY] = True
    metadata["knowledge_excluded_reason"] = reason
    document.document_metadata = metadata


def clear_document_explicit_exclusion(document: SourceDocument) -> None:
    metadata = dict(getattr(document, "document_metadata", None) or {})
    if not metadata.get(KNOWLEDGE_EXCLUDED_METADATA_KEY):
        return
    metadata.pop(KNOWLEDGE_EXCLUDED_METADATA_KEY, None)
    metadata.pop("knowledge_excluded_reason", None)
    document.document_metadata = metadata or None


class SourceReaderError(RuntimeError):
    pass


class RepositoryReader:
    def resolve_documents(
        self, source: KnowledgeSource, documents: list[SourceDocument]
    ) -> list[SourceDocument]:
        if source.status != SourceStatus.ACTIVE:
            return []
        if not source.base_uri:
            return []
        base_path = _resolve_path(source.base_uri)
        if not base_path.exists() or not base_path.is_dir():
            raise SourceReaderError(f"Repository path is not available: {base_path}")
        discovered = _discover_repository_documents(source, base_path)
        return _merge_with_existing_documents(documents, discovered)


class UrlListReader:
    def __init__(self, *, timeout_sec: float = 30.0) -> None:
        self.timeout_sec = max(1.0, float(timeout_sec or 30.0))

    def resolve_documents(
        self, source: KnowledgeSource, documents: list[SourceDocument]
    ) -> list[SourceDocument]:
        if source.source_type not in {SourceType.URL_LIST, SourceType.URL}:
            raise SourceReaderError("UrlListReader can be used only with url/url_list sources")
        if source.status != SourceStatus.ACTIVE:
            return []
        discovered: list[SourceDocument] = []
        if source.base_uri:
            if _is_local_path(source.base_uri):
                discovered.extend(self._discover_from_local_seed(source))
            else:
                discovered.extend(self._discover_from_remote_seed(source))
        return _merge_with_existing_documents(documents, _deduplicate_documents(discovered))

    def _discover_from_local_seed(self, source: KnowledgeSource) -> list[SourceDocument]:
        seed_path = _resolve_path(source.base_uri or "")
        if not seed_path.exists():
            raise SourceReaderError(f"URL-list seed is not available: {seed_path}")
        if seed_path.is_dir():
            return _discover_repository_documents(source, seed_path)
        suffix = seed_path.suffix.lower()
        if suffix in {".html", ".htm"}:
            html = seed_path.read_text(encoding="utf-8", errors="ignore")
            return self._documents_from_html(source, seed_path.as_uri(), html)
        return self._documents_from_seed_lines(
            source,
            seed_path.as_uri(),
            seed_path.read_text(encoding="utf-8", errors="ignore").splitlines(),
        )

    def _discover_from_remote_seed(self, source: KnowledgeSource) -> list[SourceDocument]:
        seed = source.base_uri or ""
        assert_safe_remote_url(seed)
        scope_seed = seed
        queue: deque[tuple[str, int]] = deque([(seed, 0)])
        visited: set[str] = set()
        discovered: list[SourceDocument] = []
        pages_processed = 0

        with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
            while (
                queue
                and pages_processed < MAX_DISCOVERY_PAGES
                and len(discovered) < MAX_DISCOVERY_DOCUMENTS
            ):
                current, depth = queue.popleft()
                normalized = _normalize_url(current)
                if normalized in visited:
                    continue
                visited.add(normalized)
                suffix = Path(urlparse(current).path).suffix.lower()
                if (
                    current != seed
                    and suffix in DISCOVERABLE_SUFFIXES
                    and suffix not in {".html", ".htm"}
                ):
                    if len(discovered) >= MAX_DISCOVERY_DOCUMENTS:
                        break
                    discovered.append(self._build_document(source, current))
                    continue
                try:
                    response_url, content_type, html = _fetch_remote_discovery_page(client, current)
                except Exception as exc:
                    raise SourceReaderError(
                        f"Failed to inspect source page '{current}': {exc}"
                    ) from exc
                if current == seed:
                    scope_seed = response_url
                pages_processed += 1
                if "html" not in content_type:
                    normalized_content_type = _normalize_media_type(content_type)
                    if (
                        normalized_content_type == "text/plain"
                        and source.source_type == SourceType.URL_LIST
                    ):
                        seed_documents = self._documents_from_seed_lines(
                            source, response_url, html.splitlines()
                        )
                        if seed_documents:
                            discovered.extend(
                                seed_documents[: max(0, MAX_DISCOVERY_DOCUMENTS - len(discovered))]
                            )
                            continue
                    if (
                        _is_supported_target(response_url) or _is_supported_media_type(content_type)
                    ) and len(discovered) < MAX_DISCOVERY_DOCUMENTS:
                        discovered.append(
                            self._build_document(
                                source, response_url, media_type=normalized_content_type
                            )
                        )
                    continue
                for document in self._documents_from_html(source, response_url, html):
                    if len(discovered) >= MAX_DISCOVERY_DOCUMENTS:
                        break
                    discovered.append(document)
                if depth >= MAX_DISCOVERY_DEPTH or len(discovered) >= MAX_DISCOVERY_DOCUMENTS:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                scope_seed_parsed = urlparse(scope_seed)
                for anchor in soup.find_all("a", href=True):
                    href = urljoin(response_url, cast(str, anchor["href"]))
                    href_parsed = urlparse(href)
                    if href_parsed.scheme not in {"http", "https"}:
                        continue
                    try:
                        assert_safe_remote_url(href)
                    except Exception:
                        continue
                    if href_parsed.netloc != scope_seed_parsed.netloc:
                        continue
                    if not _is_within_seed_scope(scope_seed, href):
                        continue
                    href_suffix = Path(href_parsed.path).suffix.lower()
                    if href_suffix in {".html", ".htm", ""}:
                        queue.append((href, depth + 1))
            return _deduplicate_documents(discovered)

    def _documents_from_seed_lines(
        self, source: KnowledgeSource, seed_url: str, lines: list[str]
    ) -> list[SourceDocument]:
        discovered: list[SourceDocument] = []
        seed_root = _resolve_local_page_scope(seed_url) if _is_local_path(seed_url) else None
        for raw_line in lines:
            candidate = raw_line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            href = urljoin(seed_url, candidate)
            parsed_href = urlparse(href)
            if parsed_href.scheme in {"http", "https"}:
                try:
                    assert_safe_remote_url(href)
                except Exception:
                    continue
            elif seed_root is not None:
                try:
                    candidate_path = _resolve_path(href)
                    assert_local_path_allowed(
                        candidate_path, allowed_roots=[str(seed_root)], allow_unrestricted=False
                    )
                    if not candidate_path.exists() or not candidate_path.is_file():
                        continue
                except Exception:
                    continue
            elif parsed_href.scheme:
                continue
            if not _is_supported_target(href) and not (
                parsed_href.scheme in {"http", "https"}
                and source.source_type == SourceType.URL_LIST
            ):
                continue
            discovered.append(self._build_document(source, href))
        return discovered

    def _documents_from_html(
        self, source: KnowledgeSource, page_url: str, html: str
    ) -> list[SourceDocument]:
        soup = BeautifulSoup(html, "html.parser")
        documents: list[SourceDocument] = []
        page_root = _resolve_local_page_scope(page_url) if _is_local_path(page_url) else None
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, cast(str, anchor["href"]))
            parsed_href = urlparse(href)
            if parsed_href.scheme in {"http", "https"}:
                try:
                    assert_safe_remote_url(href)
                except Exception:
                    continue
            elif page_root is not None:
                try:
                    candidate_path = _resolve_path(href)
                    assert_local_path_allowed(
                        candidate_path, allowed_roots=[str(page_root)], allow_unrestricted=False
                    )
                    if not candidate_path.exists() or not candidate_path.is_file():
                        continue
                except Exception:
                    continue
            anchor_text = anchor.get_text(" ", strip=True)
            if not _is_supported_target(href):
                allow_remote_suffixless = parsed_href.scheme in {
                    "http",
                    "https",
                } and _looks_like_document_link(
                    href, anchor_text=anchor_text, has_download_attr=anchor.has_attr("download")
                )
                if not allow_remote_suffixless:
                    continue
            fallback_title = (
                _resolve_path(href).name if _is_local_path(href) else Path(urlparse(href).path).name
            )
            title = anchor_text or fallback_title or href
            document = self._build_document(source, href, title=title)
            document.document_metadata = {
                **(document.document_metadata or {}),
                "discovered_from": page_url,
            }
            documents.append(document)
        return documents

    @staticmethod
    def _build_document(
        source: KnowledgeSource,
        uri: str,
        *,
        title: str | None = None,
        media_type: str | None = None,
    ) -> SourceDocument:
        if _is_local_path(uri):
            resolved_path = _resolve_path(uri)
            filename = resolved_path.name or title or uri
            suffix = resolved_path.suffix.lower()
        else:
            parsed = urlparse(uri)
            filename = Path(parsed.path).name or title or uri
            suffix = Path(parsed.path).suffix.lower()
        resolved_media_type = media_type or _guess_media_type(suffix)
        return SourceDocument(
            source_id=source.source_id,
            document_type=guess_document_type_from_name(filename),
            title=title or filename,
            uri=uri,
            resolved_uri=uri,
            media_type=resolved_media_type,
            document_metadata={"discovered_from": source.base_uri},
            is_latest=True,
            status=SourceDocumentStatus.REGISTERED,
        )


def _resolve_path(base_uri: str) -> Path:
    return resolve_local_path(base_uri)


def _resolve_local_page_scope(page_url: str) -> Path:
    page_path = _resolve_path(page_url)
    return page_path.parent if page_path.is_file() or page_path.suffix else page_path


def _is_local_path(uri: str) -> bool:
    return is_local_path_reference(uri)


def _is_supported_target(uri: str) -> bool:
    if _is_local_path(uri):
        suffix = _resolve_path(uri).suffix.lower()
    else:
        parsed = urlparse(uri)
        suffix = Path(parsed.path).suffix.lower()
    return suffix in DISCOVERABLE_SUFFIXES


def _normalize_media_type(media_type: str | None) -> str | None:
    normalized = (media_type or "").split(";", 1)[0].strip().lower()
    return normalized or None


def _is_supported_media_type(media_type: str | None) -> bool:
    return _normalize_media_type(media_type) in {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
        "application/xhtml+xml",
        "text/markdown",
        "text/x-markdown",
        "text/plain",
        "application/json",
        "text/json",
    }


def _looks_like_document_link(
    uri: str, *, anchor_text: str | None = None, has_download_attr: bool = False
) -> bool:
    if has_download_attr:
        return True
    parsed = urlparse(uri)
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    title = (anchor_text or "").lower()
    haystack = " ".join(part for part in (path, query, title) if part)
    return any(
        token in haystack
        for token in {
            "download",
            "export",
            "attachment",
            "file",
            "document",
            "pdf",
            "docx",
            "odt",
            "xlsx",
            "archimate",
            "json",
            "txt",
            "markdown",
            "raw",
        }
    )


def _fetch_remote_discovery_page(client: httpx.Client, uri: str) -> tuple[str, str, str]:
    with client.stream("GET", uri, headers={"Accept": DISCOVERY_ACCEPT_HEADER}) as response:
        response.raise_for_status()
        assert_safe_remote_url(str(response.url))
        content_type = response.headers.get("content-type", "")
        chunks: list[bytes] = []
        total_bytes = 0
        for part in response.iter_bytes():
            if not part:
                continue
            total_bytes += len(part)
            if total_bytes > MAX_DISCOVERY_PAGE_BYTES:
                raise SourceReaderError(
                    f"Discovery page '{uri}' exceeds the allowed size limit of {MAX_DISCOVERY_PAGE_BYTES} bytes"
                )
            chunks.append(part)
        encoding = response.encoding or "utf-8"
        html = b"".join(chunks).decode(encoding, errors="ignore")
        return str(response.url), content_type, html


def _seed_scope_path(seed: str) -> str:
    parsed = urlparse(seed)
    path = parsed.path or "/"
    suffix = Path(path).suffix.lower()
    if suffix in DISCOVERABLE_SUFFIXES:
        parent = Path(path).parent.as_posix()
        return parent if parent.startswith("/") else f"/{parent}"
    normalized = path.rstrip("/")
    return normalized or "/"


def _is_within_seed_scope(seed: str, candidate: str) -> bool:
    seed_parsed = urlparse(seed)
    candidate_parsed = urlparse(candidate)
    if seed_parsed.netloc != candidate_parsed.netloc:
        return False
    root_path = _seed_scope_path(seed)
    candidate_path = candidate_parsed.path or "/"
    if root_path == "/":
        return True
    return candidate_path == root_path or candidate_path.startswith(f"{root_path}/")


def guess_document_type_from_name(filename: str) -> DocumentType:
    lowered = filename.lower()
    if any(token in lowered for token in {"api", "swagger", "openapi"}):
        return DocumentType.API
    if any(token in lowered for token in {"archimate", "modelling", "modeling"}):
        return DocumentType.ARCHITECTURE
    if any(token in lowered for token in {"операцион", "технолог", "радар"}):
        return DocumentType.TECHNOLOGY
    if any(
        token in lowered
        for token in {"norm", "policy", "rule", "requirement", "standard", "стандарт", "togaf"}
    ):
        return DocumentType.NORMATIVE
    if any(token in lowered for token in {"arch", "component", "integration", "solution"}):
        return DocumentType.ARCHITECTURE
    if any(token in lowered for token in {"tech", "stack", "deploy", "platform"}):
        return DocumentType.TECHNOLOGY
    return DocumentType.OTHER


def _guess_media_type(suffix: str) -> str | None:
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".odt": "application/vnd.oasis.opendocument.text",
        ".archimate": "application/xml",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".text": "text/plain",
        ".json": "application/json",
    }.get(suffix)


def _discover_repository_documents(
    source: KnowledgeSource, base_path: Path
) -> list[SourceDocument]:
    discovered: list[SourceDocument] = []
    allow_any_file = source.source_type == SourceType.MANUAL_UPLOAD
    for path in sorted(base_path.rglob("*")):
        if len(discovered) >= MAX_DISCOVERY_DOCUMENTS:
            break
        if not path.is_file():
            continue
        if not allow_any_file and path.suffix.lower() not in DISCOVERABLE_SUFFIXES:
            continue
        relative_path = path.relative_to(base_path)
        if max(len(relative_path.parts) - 1, 0) > MAX_DISCOVERY_DEPTH:
            continue
        resolved = path.resolve()
        discovered.append(
            SourceDocument(
                source_id=source.source_id,
                document_type=guess_document_type_from_name(path.name),
                title=path.name,
                uri=resolved.as_uri(),
                resolved_uri=resolved.as_uri(),
                media_type=_guess_media_type(path.suffix.lower()),
                size_bytes=path.stat().st_size,
                document_metadata={
                    "discovered_from": str(base_path.resolve()),
                    "path": str(relative_path),
                },
                is_latest=True,
                status=SourceDocumentStatus.REGISTERED,
            )
        )
    return discovered


def _canonical_document_uri(uri: str | None) -> str:
    value = str(uri or "").strip()
    if not value:
        return value
    if _is_local_path(value):
        try:
            return _resolve_path(value).as_uri()
        except Exception:
            return value
    return value


def _merge_with_existing_documents(
    existing_documents: list[SourceDocument], discovered_documents: list[SourceDocument]
) -> list[SourceDocument]:
    existing_by_uri: dict[str, SourceDocument] = {
        _canonical_document_uri(str(item.uri)): item for item in existing_documents
    }
    seen_uris: set[str] = set()
    merged: list[SourceDocument] = []

    for discovered in discovered_documents:
        uri = _canonical_document_uri(str(discovered.uri))
        seen_uris.add(uri)
        existing = existing_by_uri.get(uri)
        if existing is None:
            merged.append(discovered)
            continue
        excluded = is_document_explicitly_excluded(existing)
        existing_metadata = dict(getattr(existing, "document_metadata", None) or {})
        bundle_document_type = existing_metadata.get(_BUNDLE_DOCUMENT_TYPE_METADATA_KEY)
        bundle_title = existing_metadata.get(_BUNDLE_TITLE_METADATA_KEY)
        if bundle_document_type:
            try:
                existing.document_type = DocumentType(str(bundle_document_type))
            except Exception:
                existing.document_type = discovered.document_type
        else:
            existing.document_type = discovered.document_type
        existing.title = str(bundle_title).strip() if bundle_title else discovered.title
        existing.resolved_uri = discovered.resolved_uri
        existing.media_type = discovered.media_type
        existing.size_bytes = discovered.size_bytes
        merged_metadata = {
            **existing_metadata,
            **(dict(getattr(discovered, "document_metadata", None) or {})),
        }
        existing.document_metadata = merged_metadata or None
        if excluded:
            existing.is_latest = False
            existing.status = SourceDocumentStatus.ARCHIVED
            continue
        existing.is_latest = True
        if existing.status == SourceDocumentStatus.ARCHIVED:
            existing.status = SourceDocumentStatus.REGISTERED
            clear_document_explicit_exclusion(existing)
        merged.append(existing)

    for uri, existing in existing_by_uri.items():
        if uri in seen_uris:
            continue
        existing.is_latest = False
        existing.status = SourceDocumentStatus.ARCHIVED

    return merged


def _deduplicate_documents(documents: list[SourceDocument]) -> list[SourceDocument]:
    unique: dict[str, SourceDocument] = {}
    for document in documents:
        if document.status == SourceDocumentStatus.ARCHIVED:
            continue
        key = _canonical_document_uri(str(document.uri))
        existing = unique.get(key)
        if existing is None:
            unique[key] = document
            continue
        if (
            getattr(existing, "document_id", None) is None
            and getattr(document, "document_id", None) is not None
        ):
            unique[key] = document
    return list(unique.values())


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    normalized_path = parsed.path or "/"
    return parsed._replace(path=normalized_path, fragment="").geturl()
