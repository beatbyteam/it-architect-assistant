from __future__ import annotations

from pathlib import Path

import pytest

from app.db.enums import SourceType
from app.integrations.knowledge.source_security import (
    assert_local_path_allowed,
    probe_source_availability,
    validate_document_uri,
    validate_source_base_uri,
)


def test_assert_local_path_requires_policy_when_no_roots_configured(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "file.md"
    target.parent.mkdir(parents=True)
    target.write_text("ok", encoding="utf-8")

    with pytest.raises(Exception) as exc:
        assert_local_path_allowed(target, allowed_roots=[])

    assert getattr(exc.value, "error_code", None) == "SOURCE_PATH_POLICY_UNCONFIGURED"


def test_validate_document_uri_rejects_local_file_outside_allowed_roots(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()
    blocked_doc = blocked_root / "secrets.md"
    blocked_doc.write_text("x", encoding="utf-8")

    with pytest.raises(Exception) as exc:
        validate_document_uri(str(blocked_doc), allowed_local_roots=[str(allowed_root)])

    assert getattr(exc.value, "error_code", None) == "SOURCE_PATH_FORBIDDEN"


def test_validate_document_uri_accepts_local_file_inside_allowed_roots(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    document = allowed_root / "doc.md"
    document.write_text("ok", encoding="utf-8")

    validate_document_uri(str(document), allowed_local_roots=[str(allowed_root)])


def test_validate_source_base_uri_respects_unrestricted_override(tmp_path: Path) -> None:
    source_dir = tmp_path / "repo"
    source_dir.mkdir()

    validate_source_base_uri(
        source_type=SourceType.REPOSITORY,
        base_uri=str(source_dir),
        allowed_local_roots=[],
        allow_unrestricted_local_paths=True,
    )


def test_probe_source_availability_accepts_upload_dir_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    payload = probe_source_availability(
        source_type=SourceType.REPOSITORY,
        base_uri=str(upload_dir),
        timeout_sec=0.1,
        allowed_local_roots=[str(upload_dir)],
    )

    assert payload["kind"] == "local"
    assert payload["path"] == str(upload_dir.resolve())
