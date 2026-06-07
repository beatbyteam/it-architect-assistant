from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import AccountType, KnowledgeBaseKind, KnowledgeBaseStatus, KnowledgeVersionStatus
from app.db.models.knowledge import KnowledgeBase, KnowledgeBaseSelection, KnowledgeVersion
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.knowledge.version_service import KnowledgeVersionService
from app.domain.services.knowledge_bases import KnowledgeBaseService


def _service_principal(login: str = "svc.worker") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=None,
        login=login,
        display_name="Service Worker",
        account_type=AccountType.SERVICE,
        role_codes=["SERVICE"],
        is_authenticated=True,
    )


def _user_principal(login: str = "local.user") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=None,
        login=login,
        display_name="Local User",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
        is_authenticated=True,
    )


def test_app_main_import_succeeds_without_optional_worker_dependencies() -> None:
    module = importlib.import_module("app.main")

    assert module.app is not None


def test_knowledge_update_start_run_uses_service_login_as_initiator() -> None:
    captured = {}
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service._resolve_execute_inline = lambda value: value
    service._result_from_run = lambda run: run

    def _call_create_run(**kwargs):
        captured.update(kwargs)
        return {"update_run_id": "run-1"}

    service._call_create_run = _call_create_run

    result = service.start_run(SimpleNamespace(execute_inline=None), _service_principal())

    assert result == {"update_run_id": "run-1"}
    assert captured["initiator_user_id"] == "svc.worker"


def test_knowledge_base_payloads_drop_stale_selected_version_from_other_base() -> None:
    principal = _service_principal()
    base = KnowledgeBase(
        knowledge_base_id="kb-default",
        code="default_user_knowledge_base__svc_worker",
        name="Default",
        kind=KnowledgeBaseKind.USER_MANAGED,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id="svc.worker",
    )
    foreign_version = KnowledgeVersion(
        knowledge_version_id="kv-foreign",
        knowledge_base_id="kb-foreign",
        version_no="KV-foreign",
        update_run_id="run-foreign",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    active_version = KnowledgeVersion(
        knowledge_version_id="kv-default",
        knowledge_base_id="kb-default",
        version_no="KV-default",
        update_run_id="run-default",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    selection = KnowledgeBaseSelection(
        knowledge_base_selection_id="sel-1",
        selection_scope="generation:svc.worker",
        selected_knowledge_base_id="kb-default",
        selected_knowledge_version_id="kv-foreign",
    )

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = SimpleNamespace()
    service._assert_base_access = lambda _base_obj, principal=None: None
    service._is_base_accessible = lambda _base_obj, principal=None: True
    service._base_stats = lambda _base_obj: {}
    service.bases = SimpleNamespace(
        list_visible=lambda owner_user_id=None: [base],
        get=lambda knowledge_base_id: base if knowledge_base_id == "kb-default" else None,
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: selection)
    service.versions = SimpleNamespace(
        get=lambda knowledge_version_id: foreign_version
        if knowledge_version_id == "kv-foreign"
        else None,
        get_active=lambda knowledge_base_id: active_version
        if knowledge_base_id == "kb-default"
        else None,
        list_visible=lambda knowledge_base_id: [active_version],
    )
    service.sources = SimpleNamespace(list_for_base=lambda knowledge_base_id: [])
    service.documents = SimpleNamespace(
        list_for_source=lambda source_id, include_archived=False: []
    )
    service.update_runs = SimpleNamespace(
        get_latest_finished=lambda knowledge_base_id: None,
        list_recent=lambda limit, knowledge_base_id: [],
    )

    items = service.list_payloads(principal)
    payload = service.get_base_payload("kb-default", principal)

    assert items[0]["selected_for_generation"] is True
    assert items[0]["selected_knowledge_version_id"] is None
    assert items[0]["selected_knowledge_version_no"] is None
    assert payload["selected_for_generation"] is True
    assert payload["selected_knowledge_version_id"] is None
    assert payload["selected_knowledge_version_no"] is None


def test_ensure_system_bases_creates_only_mandatory_base() -> None:
    principal = _service_principal()
    created_bases: list[KnowledgeBase] = []
    created_selections: list[KnowledgeBaseSelection] = []

    def _flush() -> None:
        for index, base in enumerate(created_bases, start=1):
            if getattr(base, "knowledge_base_id", None) is None:
                base.knowledge_base_id = f"kb-{index}"
        for index, selection in enumerate(created_selections, start=1):
            if getattr(selection, "knowledge_base_selection_id", None) is None:
                selection.knowledge_base_selection_id = f"sel-{index}"

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = SimpleNamespace(flush=_flush, commit=lambda: None, refresh=lambda obj: None)
    service.bases = SimpleNamespace(
        get_by_code=lambda code, owner_user_id=None: None,
        add=lambda base: created_bases.append(base),
    )
    service.selections = SimpleNamespace(
        get_for_scope=lambda scope: None,
        add=lambda selection: created_selections.append(selection),
    )

    mandatory, default_user = service.ensure_system_bases(principal)

    assert default_user is None
    assert [base.kind for base in created_bases] == [KnowledgeBaseKind.SYSTEM_MANDATORY]
    assert mandatory.name == "Mandatory Architecture Baseline"
    assert created_selections[0].selected_knowledge_base_id == mandatory.knowledge_base_id


def test_list_payloads_ensures_system_base_exists_before_listing() -> None:
    principal = _service_principal()
    base = KnowledgeBase(
        knowledge_base_id="kb-mandatory",
        code="mandatory_architecture_baseline",
        name="Mandatory Architecture Baseline",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id=None,
    )
    ensured: list[AuthPrincipal | None] = []

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = SimpleNamespace()
    service.ensure_system_bases = lambda principal=None: ensured.append(principal)
    service._assert_base_access = lambda _base_obj, principal=None: None
    service._is_base_accessible = lambda _base_obj, principal=None: True
    service._base_stats = lambda _base_obj: {}
    service.bases = SimpleNamespace(
        list_visible=lambda include_archived=False, owner_user_id=None: [base]
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: None)
    service.versions = SimpleNamespace(
        get=lambda knowledge_version_id: None,
        get_active=lambda knowledge_base_id: None,
        list_visible=lambda knowledge_base_id: [],
    )
    service.sources = SimpleNamespace(list_for_base=lambda knowledge_base_id: [])
    service.documents = SimpleNamespace(
        list_for_source=lambda source_id, include_archived=False: []
    )
    service.update_runs = SimpleNamespace(
        get_latest_finished=lambda knowledge_base_id: None,
        list_recent=lambda limit, knowledge_base_id: [],
    )

    items = service.list_payloads(principal)

    assert ensured == [principal]
    assert len(items) == 1
    assert items[0]["code"] == "mandatory_architecture_baseline"


def test_select_user_base_uses_service_actor_key_for_traceability() -> None:
    principal = _service_principal()
    base = KnowledgeBase(
        knowledge_base_id="kb-default",
        code="default_user_knowledge_base__svc_worker",
        name="Default",
        kind=KnowledgeBaseKind.USER_MANAGED,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id="svc.worker",
    )
    selection = KnowledgeBaseSelection(
        knowledge_base_selection_id="sel-1",
        selection_scope="generation:svc.worker",
        selected_knowledge_base_id=None,
        selected_knowledge_version_id=None,
        updated_by_user_id=None,
    )
    audit = Mock()
    session = SimpleNamespace(
        add=lambda obj: None, flush=lambda: None, commit=lambda: None, refresh=lambda obj: None
    )

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = session
    service.audit = audit
    service.get_base = lambda knowledge_base_id, principal=None: base
    service.selections = SimpleNamespace(
        get_for_scope=lambda scope: selection, add=lambda obj: None
    )
    service.versions = SimpleNamespace(get=lambda knowledge_version_id: None)

    resolved = service.select_user_base("kb-default", principal)

    assert resolved.updated_by_user_id == "svc.worker"
    assert audit.record.call_args.kwargs["actor_user_id"] == "svc.worker"


def test_knowledge_update_rejects_user_run_for_system_mandatory_base() -> None:
    principal = _user_principal()
    base = KnowledgeBase(
        knowledge_base_id="kb-mandatory",
        code="mandatory_architecture_baseline",
        name="Mandatory Architecture Baseline",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id=None,
    )
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service._get_base = lambda knowledge_base_id, principal=None: base

    with pytest.raises(ValidationError) as exc_info:
        service._create_run(
            payload=SimpleNamespace(
                knowledge_base_id="kb-mandatory",
                run_type=SimpleNamespace(value="manual"),
                source_scope=SimpleNamespace(value="all"),
                selected_source_ids=[],
                document_ids=[],
                removed_document_ids=[],
                force_reindex_all_in_scope=False,
                force_reindex_document_ids=[],
                target_embedding_profile=None,
                reason="manual_sync",
                auto_activate_if_validated=False,
                idempotency_key=None,
                requested_by=principal.login,
                correlation_id="corr-1",
                execute_inline=False,
            ),
            initiator_user_id=principal.login,
            principal=principal,
            execute_inline=False,
        )

    assert exc_info.value.error_code == "SYSTEM_KNOWLEDGE_BASE_IMMUTABLE"


def test_select_user_base_rejects_change_while_generation_is_running() -> None:
    captured = {}

    def _running_for_owner(owner):
        captured["owner"] = owner
        return SimpleNamespace(generation_run_id="gen-1")

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.generation_runs = SimpleNamespace(get_running_for_owner=_running_for_owner)

    with pytest.raises(ValidationError) as exc_info:
        service.select_user_base("kb-default", _service_principal())

    assert exc_info.value.error_code == "KNOWLEDGE_BASE_SELECTION_GENERATION_IN_PROGRESS"
    assert captured["owner"] == "svc.worker"


def test_activate_version_uses_service_actor_key_in_metadata_and_audit() -> None:
    principal = _service_principal()
    version = KnowledgeVersion(
        knowledge_version_id="kv-1",
        knowledge_base_id="kb-default",
        version_no="KV-1",
        update_run_id="run-1",
        status=KnowledgeVersionStatus.VALIDATED,
        summary={
            "validation": "passed",
            "missing_required_packages": [],
            "required_source_failures": [],
        },
    )
    audit = Mock()
    operations = Mock()
    session = Mock()
    session.add.return_value = None
    session.commit.return_value = None
    session.refresh.return_value = None

    service = KnowledgeVersionService.__new__(KnowledgeVersionService)
    service.session = session
    service.audit = audit
    service.operations = operations
    service.versions = SimpleNamespace(
        get_for_update=lambda knowledge_version_id: version,
        get_active_for_update=lambda knowledge_base_id, eager=False: None,
    )

    activated = service.activate("kv-1", principal)

    assert activated.activated_by_user_id == "svc.worker"
    assert activated.activation_metadata["performed_by"] == "svc.worker"
    assert operations.record_step.call_args.kwargs["actor_user_id"] == "svc.worker"
    assert audit.record.call_args.kwargs["actor_user_id"] == "svc.worker"
