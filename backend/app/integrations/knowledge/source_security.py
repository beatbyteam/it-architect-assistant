from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.exceptions import ValidationError
from app.db.enums import SourceType
from app.integrations.knowledge.local_paths import is_local_path_reference, resolve_local_path

DEFAULT_FORBIDDEN_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "host.docker.internal",
    "metadata.google.internal",
}
FORBIDDEN_IP_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
SUPPORTED_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".docx",
    ".odt",
    ".archimate",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".json",
    ".xlsx",
<<<<<<< HEAD
=======
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
>>>>>>> 13932af (Updating to the correct version(hopefully))
}

_AUTO_DIRECTORY_SOURCE_TYPES = {
    SourceType.REPOSITORY,
    SourceType.LOCAL_FOLDER,
    SourceType.MANUAL_UPLOAD,
}
_REMOTE_ONLY_URL_SOURCE_TYPES = {SourceType.URL}
_LOCAL_OR_REMOTE_URL_SOURCE_TYPES = {SourceType.URL_LIST}
_URL_SOURCE_TYPES = _REMOTE_ONLY_URL_SOURCE_TYPES | _LOCAL_OR_REMOTE_URL_SOURCE_TYPES
type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class SourceSecurityError(ValidationError):
    def __init__(self, message: str, *, error_code: str, details: dict | None = None) -> None:
        super().__init__(message, error_code=error_code, details=details or {})


class SourceAvailabilityError(RuntimeError):
    pass


class SourceDocumentPolicyError(RuntimeError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def normalize_allowed_local_roots(allowed_roots: list[str] | tuple[str, ...] | None) -> list[Path]:
    roots = [
        Path(item).expanduser().resolve() for item in (allowed_roots or []) if str(item).strip()
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def assert_local_path_allowed(
    path: Path,
    *,
    allowed_roots: list[str] | tuple[str, ...] | None = None,
    allow_unrestricted: bool = False,
) -> None:
    roots = normalize_allowed_local_roots(allowed_roots)
    resolved = path.expanduser().resolve()
    if not roots:
        if allow_unrestricted:
            return
        raise SourceSecurityError(
            "Local sources are disabled until allowed roots are configured",
            error_code="SOURCE_PATH_POLICY_UNCONFIGURED",
            details={"path": str(resolved)},
        )
    for root in roots:
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue
    raise SourceSecurityError(
        "The specified local source path is outside the allowed roots",
        error_code="SOURCE_PATH_FORBIDDEN",
        details={"path": str(resolved), "allowed_roots": [str(item) for item in roots]},
    )


def validate_source_base_uri(
    *,
    source_type: SourceType,
    base_uri: str | None,
    allowed_local_roots: list[str] | tuple[str, ...] | None = None,
    allow_unrestricted_local_paths: bool = False,
) -> None:
    if not base_uri:
        raise SourceSecurityError(
            "base_uri is required for the selected source type", error_code="BASE_URI_REQUIRED"
        )
    parsed = urlparse(base_uri)
    if source_type in _AUTO_DIRECTORY_SOURCE_TYPES:
        if not is_local_path_reference(base_uri):
            raise SourceSecurityError(
                "Local-folder and manual-upload sources must point to a local path or file:// URI",
                error_code="SOURCE_URI_INVALID",
                details={"base_uri": base_uri, "source_type": source_type.value},
            )
        assert_local_path_allowed(
            resolve_local_path(base_uri),
            allowed_roots=allowed_local_roots,
            allow_unrestricted=allow_unrestricted_local_paths,
        )
        return
    if source_type in _REMOTE_ONLY_URL_SOURCE_TYPES:
        if parsed.scheme in {"http", "https"}:
            assert_safe_remote_url(base_uri)
            return
        raise SourceSecurityError(
            "URL sources must use http(s) URIs",
            error_code="SOURCE_URI_INVALID",
            details={"base_uri": base_uri, "source_type": source_type.value},
        )
    if source_type in _LOCAL_OR_REMOTE_URL_SOURCE_TYPES:
        if parsed.scheme in {"http", "https"}:
            assert_safe_remote_url(base_uri)
            return
        if is_local_path_reference(base_uri):
            assert_local_path_allowed(
                resolve_local_path(base_uri),
                allowed_roots=allowed_local_roots,
                allow_unrestricted=allow_unrestricted_local_paths,
            )
            return
        raise SourceSecurityError(
            "URL-list sources must use http(s), local path or file:// URI",
            error_code="SOURCE_URI_INVALID",
            details={"base_uri": base_uri, "source_type": source_type.value},
        )
    raise SourceSecurityError(
        "Unsupported knowledge source type",
        error_code="UNSUPPORTED_SOURCE_TYPE",
        details={"source_type": getattr(source_type, "value", source_type)},
    )


def validate_document_uri(
    uri: str,
    *,
    allowed_local_roots: list[str] | tuple[str, ...] | None = None,
    allow_unrestricted_local_paths: bool = False,
    allow_any_suffix: bool = False,
) -> None:
    parsed = urlparse(uri)
    if is_local_path_reference(uri):
        local_path = resolve_local_path(uri)
        assert_local_path_allowed(
            local_path,
            allowed_roots=allowed_local_roots,
            allow_unrestricted=allow_unrestricted_local_paths,
        )
        ensure_supported_document_target(uri, allow_any_suffix=allow_any_suffix)
        return
    if parsed.scheme in {"http", "https"}:
        assert_safe_remote_url(uri)
        ensure_supported_document_target(uri, allow_suffixless_remote=True)
        return
    raise SourceSecurityError(
        "Document URI must use http(s), local path or file:// URI",
        error_code="DOCUMENT_URI_INVALID",
        details={"uri": uri},
    )

def ensure_supported_document_target(
    uri: str,
    *,
    allow_suffixless_remote: bool = False,
    allow_any_suffix: bool = False,
) -> None:
    if is_local_path_reference(uri):
        if allow_any_suffix:
            return
        suffix = resolve_local_path(uri).suffix.lower()
    else:
        suffix = Path(urlparse(uri).path or uri).suffix.lower()
    if suffix in SUPPORTED_DOCUMENT_SUFFIXES:
        return
    if allow_suffixless_remote and not suffix and urlparse(uri).scheme in {"http", "https"}:
        return
    raise SourceSecurityError(
<<<<<<< HEAD
        "Only PDF, DOCX, ODT, XLSX, ArchiMate, HTML, Markdown, plain-text and JSON documents are supported",
=======
        "Only PDF, DOCX, ODT, XLSX, ArchiMate, HTML, Markdown, plain-text, JSON and PNG/JPG/WebP images are supported",
>>>>>>> 13932af (Updating to the correct version(hopefully))
        error_code="UNSUPPORTED_DOCUMENT_TYPE",
        details={"uri": uri, "suffix": suffix or None},
    )


def assert_safe_remote_url(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        raise SourceSecurityError(
            "Only http(s) URLs are allowed for remote sources",
            error_code="SOURCE_URI_INVALID",
            details={"uri": uri},
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise SourceSecurityError(
            "Remote URL host is required", error_code="SOURCE_URI_INVALID", details={"uri": uri}
        )
    if host in DEFAULT_FORBIDDEN_HOSTS:
        raise SourceSecurityError(
            "The specified URL host is forbidden by security policy",
            error_code="SOURCE_URL_FORBIDDEN_HOST",
            details={"uri": uri, "host": host},
        )
    _assert_host_not_private(host, uri)


def _assert_host_not_private(host: str, uri: str) -> None:
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _ip_is_forbidden(literal_ip):
            raise SourceSecurityError(
                "The specified URL resolves to a forbidden network",
                error_code="SOURCE_URL_FORBIDDEN_NETWORK",
                details={"uri": uri, "host": host, "ip": str(literal_ip)},
            )
        return
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return
    forbidden_ips: list[str] = []
    for info in infos:
        address = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(address)
        except ValueError:
            continue
        if _ip_is_forbidden(ip_obj):
            forbidden_ips.append(str(ip_obj))
    if forbidden_ips:
        raise SourceSecurityError(
            "The specified URL resolves to a forbidden network",
            error_code="SOURCE_URL_FORBIDDEN_NETWORK",
            details={"uri": uri, "host": host, "resolved_ips": forbidden_ips},
        )


def _ip_is_forbidden(ip_obj: IPAddress) -> bool:
    if (
        ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_private
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return True
    return any(ip_obj in network for network in FORBIDDEN_IP_NETWORKS)


def probe_source_availability(
    *,
    source_type: SourceType,
    base_uri: str,
    timeout_sec: float,
    allowed_local_roots: list[str] | tuple[str, ...] | None = None,
    allow_unrestricted_local_paths: bool = False,
) -> dict[str, object]:
    validate_source_base_uri(
        source_type=source_type,
        base_uri=base_uri,
        allowed_local_roots=allowed_local_roots,
        allow_unrestricted_local_paths=allow_unrestricted_local_paths,
    )
    parsed = urlparse(base_uri)
    if source_type in _AUTO_DIRECTORY_SOURCE_TYPES:
        path = resolve_local_path(base_uri)
        assert_local_path_allowed(
            path,
            allowed_roots=allowed_local_roots,
            allow_unrestricted=allow_unrestricted_local_paths,
        )
        auto_created = False
        if not path.exists():
            if source_type == SourceType.MANUAL_UPLOAD:
                path.mkdir(parents=True, exist_ok=True)
                auto_created = True
            else:
                raise SourceAvailabilityError(f"Source path is not available: {path}")
        if not path.is_dir():
            raise SourceAvailabilityError(f"Local-folder source must point to a directory: {path}")
        return {
            "kind": "local",
            "path": str(path),
            "exists": True,
            "is_dir": path.is_dir(),
            "auto_created": auto_created,
        }

    if is_local_path_reference(base_uri):
        if source_type not in _LOCAL_OR_REMOTE_URL_SOURCE_TYPES:
            raise SourceAvailabilityError("URL source must use http(s) URI")
        path = resolve_local_path(base_uri)
        assert_local_path_allowed(
            path,
            allowed_roots=allowed_local_roots,
            allow_unrestricted=allow_unrestricted_local_paths,
        )
        if not path.exists():
            raise SourceAvailabilityError(f"Source path is not available: {path}")
        return {
            "kind": "local",
            "path": str(path),
            "exists": True,
            "is_dir": path.is_dir(),
            "is_file": path.is_file(),
        }

    if parsed.scheme not in {"http", "https"}:
        raise SourceAvailabilityError("URL source must use http(s) URI")
    assert_safe_remote_url(base_uri)
    accept_header = "text/html, text/plain;q=0.9, */*;q=0.8"
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            head_response = client.request("HEAD", base_uri, headers={"Accept": accept_header})
            if head_response.status_code not in {403, 405, 501}:
                head_response.raise_for_status()
                assert_safe_remote_url(str(head_response.url))
                return {
                    "kind": "remote",
                    "status_code": head_response.status_code,
                    "resolved_url": str(head_response.url),
                    "content_type": head_response.headers.get("content-type"),
                    "probe_method": "HEAD",
                }
            with client.stream("GET", base_uri, headers={"Accept": accept_header}) as response:
                response.raise_for_status()
                assert_safe_remote_url(str(response.url))
                return {
                    "kind": "remote",
                    "status_code": response.status_code,
                    "resolved_url": str(response.url),
                    "content_type": response.headers.get("content-type"),
                    "probe_method": "GET_STREAM",
                }
    except Exception as exc:  # pragma: no cover
        raise SourceAvailabilityError(str(exc)) from exc


def enforce_document_size_limit(size_bytes: int, *, max_size_bytes: int) -> None:
    if size_bytes > max_size_bytes:
        raise SourceDocumentPolicyError(
            f"Document size {size_bytes} bytes exceeds allowed limit {max_size_bytes} bytes",
            error_code="DOCUMENT_SIZE_LIMIT_EXCEEDED",
        )
