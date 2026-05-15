from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.bootstrap.bundles import load_bundle_manifest
from app.db.enums import (
    CheckResultStatus,
    Criticality,
    ProtocolSummaryStatus,
    Severity,
    SourceStatus,
    SourceType,
)
from app.db.models.knowledge import KnowledgeSource
from app.integrations.knowledge.evaluation import load_retrieval_eval_cases
from app.integrations.knowledge.source_readers import UrlListReader
from app.integrations.knowledge.source_security import (
    probe_source_availability,
    validate_source_base_uri,
)
from app.integrations.verification.contracts import (
    VerificationCheckResultPayload,
    VerificationProtocolPayload,
)


def _check(status: CheckResultStatus) -> VerificationCheckResultPayload:
    kwargs = {
        "check_name": f"check-{status.value}",
        "status": status,
        "severity": Severity.MEDIUM,
    }
    if status in {
        CheckResultStatus.WARNING,
        CheckResultStatus.FAILED,
        CheckResultStatus.NOT_DETERMINED,
    }:
        kwargs["finding_text"] = "details"
        kwargs["evidence_ref"] = "doc:1"
    return VerificationCheckResultPayload(**kwargs)


def test_validate_url_list_source_accepts_local_seed_file(tmp_path: Path) -> None:
    seed = tmp_path / "index.html"
    seed.write_text("<html></html>", encoding="utf-8")

    validate_source_base_uri(
        source_type=SourceType.URL_LIST,
        base_uri=seed.as_uri(),
        allowed_local_roots=[str(tmp_path)],
    )

    payload = probe_source_availability(
        source_type=SourceType.URL_LIST,
        base_uri=seed.as_uri(),
        timeout_sec=0.1,
        allowed_local_roots=[str(tmp_path)],
    )
    assert payload["kind"] == "local"
    assert payload["is_file"] is True


def test_url_list_reader_blocks_local_html_links_outside_seed_scope(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    inside = docs_dir / "allowed.md"
    inside.write_text("ok", encoding="utf-8")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    index = tmp_path / "index.html"
    index.write_text(
        '<a href="docs/allowed.md">inside</a><a href="../outside.md">outside</a>',
        encoding="utf-8",
    )
    source = KnowledgeSource(
        source_type=SourceType.URL_LIST,
        name="seed",
        base_uri=index.as_uri(),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )

    documents = UrlListReader().resolve_documents(source, [])

    assert [item.title for item in documents] == ["inside"]
    assert documents[0].uri.endswith("allowed.md")


def test_load_retrieval_eval_cases_accepts_json_string_payload() -> None:
    dataset_name, knowledge_version_id, cases = load_retrieval_eval_cases(
        json.dumps(
            {
                "dataset_name": "inline",
                "knowledge_version_id": "kv-1",
                "cases": [
                    {
                        "case_id": "c1",
                        "query_text": "api gateway",
                        "expected_fragment_ids": ["frag-1"],
                    }
                ],
            }
        )
    )

    assert dataset_name == "inline"
    assert knowledge_version_id == "kv-1"
    assert len(cases) == 1
    assert cases[0].case_id == "c1"


def test_verification_protocol_rejects_not_determined_for_passed_with_comments() -> None:
    with pytest.raises(PydanticValidationError):
        VerificationProtocolPayload(
            summary="summary",
            final_status=ProtocolSummaryStatus.PASSED_WITH_COMMENTS,
            check_results=[
                _check(CheckResultStatus.WARNING),
                _check(CheckResultStatus.NOT_DETERMINED),
            ],
        )


def test_verification_protocol_rejects_not_determined_for_failed_summary() -> None:
    with pytest.raises(PydanticValidationError):
        VerificationProtocolPayload(
            summary="summary",
            final_status=ProtocolSummaryStatus.FAILED,
            check_results=[
                _check(CheckResultStatus.FAILED),
                _check(CheckResultStatus.NOT_DETERMINED),
            ],
        )


def test_load_bundle_manifest_accepts_fetch_uri_three_value_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.bootstrap.bundles.fetch_uri",
        lambda manifest_uri: (
            json.dumps({"bundle_code": "demo", "sources": []}).encode("utf-8"),
            manifest_uri,
            "application/json",
        ),
    )

    manifest, manifest_root = load_bundle_manifest("https://example.com/bundle.json")

    assert manifest["bundle_code"] == "demo"
    assert manifest_root == "https://example.com"
