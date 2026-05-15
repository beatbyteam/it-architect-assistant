from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    BusinessTaskStatus,
    SolutionVersionStatus,
    SourceScope,
    UpdateRunType,
)
from app.domain.services.generation.run_service import GenerationRunService
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.principal_keys import principal_requested_by
from app.domain.services.publication import PublicationArtifactService
from app.domain.services.verification.run_service import VerificationRunService


class _RunRaceSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.rollback_calls = 0
        self.expire_all_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    def rollback(self) -> None:
        self.rollback_calls += 1

    def expire_all(self) -> None:
        self.expire_all_calls += 1


class _PublicationRetrySession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0
        self.refresh_calls = 0
        self.nested_entries = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    @contextmanager
    def begin_nested(self):
        self.nested_entries += 1
        yield

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_calls == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key"))

    def refresh(self, _obj: object) -> None:
        self.refresh_calls += 1


class _PublicationFailSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.rollback_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    def rollback(self) -> None:
        self.rollback_calls += 1


class _PublicationRepo:
    def __init__(self) -> None:
        self.supersede_calls = 0
        self.next_revision = 0

    def supersede_current(self, **_kwargs) -> list[object]:
        self.supersede_calls += 1
        return []

    def get_next_revision_no(self, **_kwargs) -> int:
        self.next_revision += 1
        return self.next_revision

    def get_latest_for_target(self, **_kwargs):
        return None

    def list_for_target(self, **_kwargs) -> list[object]:
        return []


class _IdempotencyCapture:
    def __init__(self) -> None:
        self.request_payload: dict | None = None

    def resolve_existing(self, **kwargs):
        self.request_payload = kwargs["request_payload"]
        raise RuntimeError("captured")


class _NoopIdempotency:
    def resolve_existing(self, **_kwargs):
        return None

    def register(self, **_kwargs):
        return None


class _PolicyStack:
    def as_dict(self) -> dict[str, object]:
        return {}


class _GenerationScope:
    def __init__(self, version_id: str) -> None:
        self._version = SimpleNamespace(knowledge_version_id=version_id)
        self.mandatory_version = None
        self.selected_user_version = self._version

    def selected_generation_version(self):
        return self._version


class _VerificationScope(_GenerationScope):
    pass


class _Principal(AuthPrincipal):
    pass


def _service_principal(login: str = "svc.worker") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=None,
        login=login,
        display_name=None,
        account_type=AccountType.SERVICE,
        role_codes=["SERVICE"],
        is_authenticated=True,
    )


def test_principal_requested_by_uses_fallback_instead_of_string_none() -> None:
    principal = AuthPrincipal(
        user_id=None,
        login=None,
        display_name=None,
        account_type=AccountType.SERVICE,
        role_codes=["SERVICE"],
        is_authenticated=True,
    )

    assert principal_requested_by(principal) == "system.user"


def test_generation_idempotency_payload_ignores_correlation_id() -> None:
    task = SimpleNamespace(business_task_id="task-1")
    payload = GenerationRunService._build_generation_idempotency_request_payload(
        task=task,
        active_version_id="kv-1",
        knowledge_snapshot={"effective_version_ids": ["kv-1"], "snapshot_hash": "scope-hash"},
        input_snapshot={"_snapshot": {"payload_hash": "input-hash"}},
        prompt_version="prompt-v1",
    )

    assert "correlation_id" not in payload


def test_verification_idempotency_payload_ignores_correlation_id() -> None:
    solution = SimpleNamespace(solution_version_id="sol-1")
    payload = VerificationRunService._build_verification_idempotency_request_payload(
        solution=solution,
        validation_scope="full",
        knowledge_version_id="kv-1",
        scope_snapshot={
            "knowledge_version_ids": ["kv-1"],
            "knowledge_snapshot": {"snapshot_hash": "scope-hash"},
            "_snapshot": {"payload_hash": "verification-hash"},
            "rule_codes": ["rule-1"],
            "publication_snapshot": {"revision_no": 3, "version_hash": "pub-hash"},
        },
        publication_artifact=None,
        rulebook_version="rules-v2",
    )

    assert "correlation_id" not in payload


def test_knowledge_update_idempotency_payload_ignores_requested_by_and_correlation() -> None:
    capture = _IdempotencyCapture()
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.idempotency = capture
    service._get_base = lambda knowledge_base_id, principal=None: SimpleNamespace(
        knowledge_base_id=knowledge_base_id
    )
    service._ensure_system_bases = lambda principal=None: None
    service._get_default_user_base = lambda principal=None: SimpleNamespace(
        knowledge_base_id="kb-default"
    )

    with pytest.raises(RuntimeError, match="captured"):
        service._create_run(
            payload=SimpleNamespace(
                knowledge_base_id="kb-1",
                run_type=UpdateRunType.MANUAL,
                source_scope=SourceScope.ALL,
                selected_source_ids=[],
                document_ids=[],
                removed_document_ids=[],
                force_reindex_all_in_scope=False,
                force_reindex_document_ids=[],
                target_embedding_profile=None,
                reason="manual",
                requested_by="svc.worker",
                correlation_id="corr-1",
                idempotency_key="idem-1",
                auto_activate_if_validated=False,
            ),
            initiator_user_id="svc.worker",
            principal=_service_principal(),
        )

    assert capture.request_payload is not None
    assert "requested_by" not in capture.request_payload
    assert "correlation_id" not in capture.request_payload


def test_generation_start_run_translates_active_run_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.domain.services.generation.run_service as generation_module

    monkeypatch.setattr(generation_module, "build_policy_stack", lambda **_kwargs: _PolicyStack())
    monkeypatch.setattr(
        generation_module,
        "build_knowledge_scope_snapshot",
        lambda **_kwargs: {"effective_version_ids": ["kv-1"], "snapshot_hash": "scope-hash"},
    )

    service = GenerationRunService.__new__(GenerationRunService)
    service.session = _RunRaceSession()
    service._get_task = lambda business_task_id: SimpleNamespace(
        business_task_id=business_task_id,
        status=BusinessTaskStatus.READY_FOR_GENERATION,
        clarification_requests=[],
        task_metadata={},
        title="Task",
        task_text="Generate architecture",
    )
    service._make_base_service = lambda: SimpleNamespace(
        get_effective_scope=lambda principal=None: _GenerationScope("kv-1")
    )
    service.prompt_registry = SimpleNamespace(
        get_generation_template=lambda: SimpleNamespace(
            version_id="prompt-v1", template_name="tpl", output_contract_name="contract"
        )
    )
    service.retrieval = SimpleNamespace(knowledge_query=SimpleNamespace(embeddings=object()))
    service._build_generation_input_snapshot = lambda **_kwargs: {
        "_snapshot": {"payload_hash": "input-hash"}
    }
    service.idempotency = _NoopIdempotency()
    service.runs = SimpleNamespace(
        get_running_for_task=lambda business_task_id: None
        if not service.session.rollback_calls
        else SimpleNamespace(generation_run_id="run-1")
    )

    with pytest.raises(ConflictError) as exc_info:
        service.start_run(
            SimpleNamespace(
                business_task_id="task-1", correlation_id="corr-1", idempotency_key="idem-1"
            ),
            _service_principal(),
        )

    assert exc_info.value.error_code == "GENERATION_ALREADY_RUNNING"
    assert service.session.rollback_calls == 1
    assert service.session.expire_all_calls == 1


def test_verification_start_run_translates_active_run_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.domain.services.verification.run_service as verification_module

    monkeypatch.setattr(verification_module, "build_policy_stack", lambda **_kwargs: _PolicyStack())
    monkeypatch.setattr(
        verification_module,
        "build_knowledge_scope_snapshot",
        lambda **_kwargs: {"effective_version_ids": ["kv-1"], "snapshot_hash": "scope-hash"},
    )

    service = VerificationRunService.__new__(VerificationRunService)
    service.session = _RunRaceSession()
    service._get_solution = lambda solution_version_id: SimpleNamespace(
        solution_version_id=solution_version_id,
        generation_run_id="gen-1",
        status=SolutionVersionStatus.PUBLISHED,
        sections=[],
        components=[],
        integrations=[],
        risks=[],
        solution_title="Solution",
    )
    service._select_rules = lambda validation_scope: [SimpleNamespace(code="rule-1")]
    service.registry = SimpleNamespace(version="rules-v2")
    service.engine = SimpleNamespace()
    service.validator = SimpleNamespace()
    service.publication_artifacts = SimpleNamespace(get_current=lambda **_kwargs: None)
    service.knowledge_query = SimpleNamespace(embeddings=object())
    service.knowledge_versions = SimpleNamespace()
    service.runs = SimpleNamespace(
        get_running_for_solution=lambda solution_version_id: None
        if not service.session.rollback_calls
        else SimpleNamespace(verification_run_id="ver-1")
    )
    service.idempotency = _NoopIdempotency()

    monkeypatch.setattr(
        verification_module,
        "KnowledgeBaseService",
        lambda session: SimpleNamespace(
            get_effective_scope=lambda principal=None: _VerificationScope("kv-1")
        ),
    )

    with pytest.raises(ConflictError) as exc_info:
        service.start_run(
            SimpleNamespace(
                solution_version_id="sol-1",
                validation_scope="full",
                correlation_id="corr-1",
                idempotency_key="idem-1",
            ),
            _service_principal(),
        )

    assert exc_info.value.error_code == "VERIFICATION_ALREADY_RUNNING"
    assert service.session.rollback_calls == 1
    assert service.session.expire_all_calls == 1


def test_knowledge_update_create_run_translates_active_run_integrity_error_to_conflict() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.session = _RunRaceSession()
    service.idempotency = _NoopIdempotency()
    service._get_base = lambda knowledge_base_id, principal=None: SimpleNamespace(
        knowledge_base_id=knowledge_base_id
    )
    service._ensure_system_bases = lambda principal=None: None
    service._get_default_user_base = lambda principal=None: SimpleNamespace(
        knowledge_base_id="kb-default"
    )
    service._resolve_scope_sources = (
        lambda source_scope, selected_source_ids, knowledge_base_id=None: [
            SimpleNamespace(source_id="src-1")
        ]
    )
    service.update_runs = SimpleNamespace(add=lambda run: service.session.add(run))
    service._get_running_run_with_recovery = (
        lambda knowledge_base_id=None: None
        if not service.session.rollback_calls
        else SimpleNamespace(update_run_id="upd-1")
    )

    with pytest.raises(ConflictError) as exc_info:
        service._create_run(
            payload=SimpleNamespace(
                knowledge_base_id="kb-1",
                run_type=UpdateRunType.MANUAL,
                source_scope=SourceScope.ALL,
                selected_source_ids=[],
                document_ids=[],
                removed_document_ids=[],
                force_reindex_all_in_scope=False,
                force_reindex_document_ids=[],
                target_embedding_profile=None,
                reason="manual",
                requested_by="svc.worker",
                correlation_id="corr-1",
                idempotency_key="idem-1",
                auto_activate_if_validated=False,
            ),
            initiator_user_id="svc.worker",
            principal=_service_principal(),
        )

    assert exc_info.value.error_code == "KNOWLEDGE_UPDATE_ALREADY_RUNNING"
    assert service.session.rollback_calls == 1
    assert service.session.expire_all_calls == 1


def test_publication_service_retries_after_revision_conflict_with_nested_transaction() -> None:
    service = PublicationArtifactService.__new__(PublicationArtifactService)
    service.session = _PublicationRetrySession()
    service.artifacts = _PublicationRepo()

    artifact = service.publish(
        artifact_type="solution_html",
        target_type="solution_version",
        target_id="sol-1",
        rendered_html="<p>ok</p>",
    )

    assert artifact.revision_no == 2
    assert service.session.flush_calls == 2
    assert service.session.refresh_calls == 1
    assert service.artifacts.supersede_calls == 2


def test_publication_service_maps_repeated_revision_conflicts_to_domain_conflict() -> None:
    service = PublicationArtifactService.__new__(PublicationArtifactService)
    service.session = _PublicationFailSession()
    service.artifacts = _PublicationRepo()

    with pytest.raises(ConflictError) as exc_info:
        service.publish(
            artifact_type="solution_html",
            target_type="solution_version",
            target_id="sol-1",
            rendered_html="<p>ok</p>",
        )

    assert exc_info.value.error_code == "PUBLICATION_REVISION_CONFLICT"
    assert service.session.rollback_calls == 3
