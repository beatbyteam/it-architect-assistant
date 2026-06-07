from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.responses import Response

from app.api.v1.routes import knowledge_bases_routes
from app.api.v1.routes.health import ready
from app.bootstrap.bundles import (
    _find_existing_source,
    import_knowledge_bundle,
    load_bundle_manifest,
)
from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    CheckResultStatus,
    KnowledgeBaseKind,
    Severity,
    SourceScope,
    SourceType,
    UpdateRunType,
)
from app.domain.services.verification.rule_executors import (
    ConsistencyRulesExecutor,
    VerificationSupportContext,
)
from app.integrations.verification import VerificationRuleDefinition
from app.schemas.knowledge import KnowledgeBundleImportRequest


class _SessionStub:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.expired = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def expire_all(self) -> None:
        self.expired += 1


def _principal(user_id: str = "user-1") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        login=user_id,
        display_name=user_id,
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
        is_authenticated=True,
    )


def _support(
    *,
    business_text: str,
    app_text: str,
    tech_text: str,
    components: list[object],
    integrations: list[object] | None = None,
) -> VerificationSupportContext:
    return VerificationSupportContext(
        section_by_code={
            "business_architecture": SimpleNamespace(body_markdown=business_text),
            "application_architecture": SimpleNamespace(body_markdown=app_text),
            "technology_architecture": SimpleNamespace(body_markdown=tech_text),
        },
        section_codes={
            "business_architecture",
            "application_architecture",
            "technology_architecture",
        },
        combined_section_text="\n".join([business_text, app_text, tech_text]),
        assumptions=[],
        next_steps=[],
        components=components,
        integrations=integrations or [],
        risks=[],
        basis_inventory={},
        required_fragments_by_role={},
        support_summary={},
    )


def test_ready_route_returns_503_when_not_ready(monkeypatch) -> None:
    degraded_payload = SimpleNamespace(status="degraded", dependencies=[])

    class _HealthService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def ready(self):
            return degraded_payload

    monkeypatch.setattr("app.api.v1.routes.health.HealthService", _HealthService)
    response = Response()

    payload = ready(session=SimpleNamespace(), settings=SimpleNamespace(), response=response)

    assert payload is degraded_payload
    assert response.status_code == 503


def test_load_bundle_manifest_validates_uri_and_applies_size_limit(monkeypatch) -> None:
    validated: dict[str, object] = {}
    fetched: dict[str, object] = {}

    def _validate(uri: str, *, allowed_local_roots, allow_unrestricted_local_paths: bool) -> None:
        validated["uri"] = uri
        validated["allowed_local_roots"] = list(allowed_local_roots)
        validated["allow_unrestricted_local_paths"] = allow_unrestricted_local_paths

    def _fetch(uri: str, timeout_sec: float = 10.0, max_size_bytes: int | None = None):
        fetched["uri"] = uri
        fetched["timeout_sec"] = timeout_sec
        fetched["max_size_bytes"] = max_size_bytes
        return (
            json.dumps({"bundle_code": "demo", "sources": []}).encode("utf-8"),
            uri,
            "application/json",
        )

    monkeypatch.setattr("app.bootstrap.bundles.validate_document_uri", _validate)
    monkeypatch.setattr("app.bootstrap.bundles.fetch_uri", _fetch)

    manifest, manifest_root = load_bundle_manifest(
        "file:///safe/bundle.json",
        settings=SimpleNamespace(
            knowledge_fetch_timeout_sec=3.5,
            knowledge_max_document_size_bytes=1234,
            knowledge_allowed_local_source_roots=["/safe"],
            knowledge_upload_dir="/uploads",
        ),
    )

    assert manifest["bundle_code"] == "demo"
    assert manifest_root == "/safe"
    assert validated["uri"] == "file:///safe/bundle.json"
    assert "/safe" in validated["allowed_local_roots"]
    assert validated["allow_unrestricted_local_paths"] is False
    assert fetched["max_size_bytes"] == 1234
    assert fetched["timeout_sec"] == 3.5


def test_import_bundle_requires_explicit_target_base(monkeypatch) -> None:
    session = _SessionStub()

    class _BaseService:
        def __init__(self, _session) -> None:
            self.session = _session

    monkeypatch.setattr(
        "app.bootstrap.bundles.KnowledgeBaseService",
        _BaseService,
    )

    with pytest.raises(ValidationError) as exc_info:
        import_knowledge_bundle(
            session,
            manifest_uri="file:///tmp/bundle.json",
            principal=_principal(),
            start_update=True,
            activate_if_validated=True,
            execute_update_inline=False,
        )

    assert exc_info.value.error_code == "KNOWLEDGE_BASE_REQUIRED"
    assert session.commits == 0


def test_import_bundle_rolls_back_entire_import_on_document_failure(monkeypatch) -> None:
    session = _SessionStub()
    document_calls: list[str] = []

    class _BaseService:
        def __init__(self, _session) -> None:
            self.session = _session

        def get_base(self, knowledge_base_id: str, principal=None):
            return SimpleNamespace(knowledge_base_id=knowledge_base_id)

    monkeypatch.setattr(
        "app.bootstrap.bundles.load_bundle_manifest",
        lambda manifest_uri, settings=None: (
            {
                "bundle_code": "demo",
                "sources": [
                    {
                        "name": "Source",
                        "source_type": "repository",
                        "criticality": "required",
                        "base_uri": "file:///tmp/repo",
                        "documents": [
                            {"title": "Doc 1", "uri": "doc1.md", "document_type": "reference"},
                            {"title": "Doc 2", "uri": "doc2.md", "document_type": "reference"},
                        ],
                    }
                ],
            },
            "/tmp",
        ),
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles._validate_manifest_payload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("app.bootstrap.bundles.KnowledgeBaseService", _BaseService)
    monkeypatch.setattr(
        "app.bootstrap.bundles.KnowledgeSourceService", lambda session: SimpleNamespace()
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles.KnowledgeVersionService", lambda session: SimpleNamespace()
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles._upsert_source",
        lambda *args, **kwargs: SimpleNamespace(source_id="src-1", name="Source"),
    )

    def _upsert_document(*args, **kwargs):
        document_calls.append(
            kwargs["raw_document"]["title"] if "raw_document" in kwargs else args[4]["title"]
        )
        if len(document_calls) == 2:
            raise RuntimeError("boom")
        return SimpleNamespace(document_id="doc-1")

    monkeypatch.setattr("app.bootstrap.bundles._upsert_document", _upsert_document)

    with pytest.raises(RuntimeError, match="boom"):
        import_knowledge_bundle(
            session,
            manifest_uri="file:///tmp/bundle.json",
            knowledge_base_id="kb-1",
            principal=_principal(),
            start_update=False,
        )

    assert session.commits == 0
    assert session.rollbacks == 1
    assert document_calls == ["Doc 1", "Doc 2"]


def test_import_bundle_route_coerces_missing_execute_inline_to_false(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _import_bundle_stub(session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(as_dict=lambda: {"manifest_uri": kwargs["manifest_uri"]})

    monkeypatch.setattr(knowledge_bases_routes, "import_knowledge_bundle", _import_bundle_stub)

    payload = KnowledgeBundleImportRequest(manifest_uri="file:///tmp/bundle.json")
    principal = _principal()

    response = knowledge_bases_routes.import_bundle(
        payload=payload,
        session=object(),
        principal=principal,
        _guard=principal,
    )

    assert captured["execute_update_inline"] is False
    assert response.manifest_uri == "file:///tmp/bundle.json"


def test_system_base_sync_route_imports_demo_bundle_and_starts_service_update(monkeypatch) -> None:
    captured: dict[str, object] = {}
    principal = _principal()
    system_base = SimpleNamespace(
        knowledge_base_id="kb-system",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
    )

    class _BaseService:
        def __init__(self, session) -> None:
            self.session = session

        def get_base(self, knowledge_base_id: str, principal=None):
            return system_base

    class _UpdateService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def get_run_response(self, update_run_id: str, principal=None):
            return {
                "update_run_id": update_run_id,
                "knowledge_base_id": "kb-system",
                "run_type": UpdateRunType.MANUAL,
                "status": "queued",
                "current_stage": "queued",
                "source_scope": SourceScope.SELECTED,
                "selected_source_ids": ["src-1"],
                "requested_by": principal.login if principal is not None else None,
                "reason": "manual_sync",
                "started_at": datetime.now(UTC),
            }

    def _import_bundle_stub(session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(update_run_id="run-system-1")

    monkeypatch.setattr(knowledge_bases_routes, "KnowledgeBaseService", _BaseService)
    monkeypatch.setattr(knowledge_bases_routes, "KnowledgeUpdateService", _UpdateService)
    monkeypatch.setattr(
        knowledge_bases_routes,
        "default_demo_knowledge_bundle_manifest_uri",
        lambda: "file:///demo_knowledge_bundle.json",
    )
    monkeypatch.setattr(knowledge_bases_routes, "import_knowledge_bundle", _import_bundle_stub)

    response = knowledge_bases_routes.start_base_sync(
        knowledge_base_id="kb-system",
        session=object(),
        settings=SimpleNamespace(),
        principal=principal,
        execute_inline=False,
        reason="manual_sync",
        _guard=principal,
    )

    assert captured["manifest_uri"] == "file:///demo_knowledge_bundle.json"
    assert captured["knowledge_base_id"] == "kb-system"
    assert captured["activate_if_validated"] is True
    assert captured["execute_update_inline"] is False
    assert captured["requested_by"] == principal.login
    assert captured["principal"].account_type == AccountType.SERVICE
    assert response.update_run_id == "run-system-1"


def test_find_existing_source_does_not_fallback_to_name_only() -> None:
    service = SimpleNamespace(
        list_sources=lambda knowledge_base_id: [
            SimpleNamespace(
                source_id="src-1",
                source_type="repository",
                name="Common",
                base_uri="file:///a",
                source_metadata={},
            ),
            SimpleNamespace(
                source_id="src-2",
                source_type="repository",
                name="Common",
                base_uri="file:///b",
                source_metadata={},
            ),
        ]
    )

    existing = _find_existing_source(
        service,
        knowledge_base_id="kb-1",
        source_type=SourceType.REPOSITORY,
        base_uri=None,
        source_code=None,
    )

    assert existing is None


def test_consistency_rules_do_not_pass_without_real_cross_layer_link() -> None:
    executor = ConsistencyRulesExecutor()
    context = SimpleNamespace(solution=SimpleNamespace(), run=SimpleNamespace())
    support = _support(
        business_text="Business capability handles orders",
        app_text="Billing API exists",
        tech_text="Kubernetes exists",
        components=[
            SimpleNamespace(
                component_name="Business capability", boundary_type="business_architecture"
            ),
            SimpleNamespace(component_name="Billing API", boundary_type="application_architecture"),
            SimpleNamespace(component_name="Kubernetes", boundary_type="technology_architecture"),
        ],
    )
    rule_cns_03 = VerificationRuleDefinition(
        "VR-CNS-03", "Cross-layer consistency", "consistency", Severity.MEDIUM
    )
    rule_cns_04 = VerificationRuleDefinition(
        "VR-CNS-04", "Technology linkage", "consistency", Severity.MEDIUM
    )

    cns_03 = executor.execute(rule=rule_cns_03, context=context, support=support)
    cns_04 = executor.execute(rule=rule_cns_04, context=context, support=support)

    assert cns_03.status == CheckResultStatus.WARNING
    assert cns_04.status == CheckResultStatus.WARNING
