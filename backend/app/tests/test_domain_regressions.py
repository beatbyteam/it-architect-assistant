from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import AccountType, BusinessTaskStatus, ClarificationRequestStatus
from app.domain.architecture.sectioning import (
    derive_structured_architecture_model,
    should_apply_section_fallback,
)
from app.domain.architecture.standards import extract_archimate_elements
from app.domain.services.health import HealthService
from app.domain.services.idempotency import IdempotencyService
from app.domain.services.mvp_canonical import CanonicalTaskService


class _HealthScopeService:
    def __init__(self) -> None:
        self.readonly_calls = 0
        self.mutating_calls = 0

    def get_existing_effective_scope(self):
        self.readonly_calls += 1
        return None

    def get_effective_scope(self):  # pragma: no cover - should not be used by the probe
        self.mutating_calls += 1
        raise AssertionError("mutating scope lookup must not be used by health probe")


class _NestedSession:
    def __init__(self) -> None:
        self.records: list[object] = []
        self.flush_calls = 0
        self.rollback_calls = 0
        self.nested_entries = 0

    def add(self, obj: object) -> None:
        self.records.append(obj)

    @contextmanager
    def begin_nested(self):
        self.nested_entries += 1
        yield

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_calls == 1:
            raise IntegrityError("insert into idempotency_records", {}, Exception("duplicate key"))

    def rollback(self) -> None:  # pragma: no cover - used only to guard against regressions
        self.rollback_calls += 1


class _IdempotencyRepo:
    def __init__(self, record: object) -> None:
        self.record = record
        self.calls = 0

    def get_by_scope(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return None
        return self.record


class _TaskSession:
    def __init__(self, items: list[object] | None = None) -> None:
        self.items = items or []
        self.added: list[object] = []
        self.commits = 0
        self.scalar_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def scalars(self, _statement):
        self.scalar_calls += 1
        return iter(self.items)


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )


def test_active_knowledge_probe_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.domain.services.health as health_module

    scope_service = _HealthScopeService()
    monkeypatch.setattr(health_module, "KnowledgeBaseService", lambda session: scope_service)
    service = HealthService(SimpleNamespace(), Settings())

    probe = service._probe_active_knowledge_version()

    assert probe.status == "missing"
    assert probe.healthy is False
    assert scope_service.readonly_calls == 1
    assert scope_service.mutating_calls == 0


def test_idempotency_register_uses_nested_transaction_without_session_rollback() -> None:
    session = _NestedSession()
    existing_record = SimpleNamespace(
        request_fingerprint=IdempotencyService._fingerprint({"task_id": "task-1"}),
        last_seen_at=None,
    )
    service = IdempotencyService(session)
    service.records = _IdempotencyRepo(existing_record)

    resolved = service.register(
        actor_user_id="user-1",
        operation_name="mvp.task.create",
        idempotency_key="idem-1",
        request_payload={"task_id": "task-1"},
        target_type="business_task",
        target_id="task-1",
    )

    assert resolved is existing_record
    assert session.nested_entries == 1
    assert session.rollback_calls == 0
    assert session.flush_calls >= 2


def test_answer_clarification_rejects_duplicate_existing_answers() -> None:
    task = SimpleNamespace(
        business_task_id="task-1",
        task_metadata={},
        status=BusinessTaskStatus.REQUIRES_CLARIFICATION,
        clarification_requests=[
            SimpleNamespace(
                clarification_id="clar-1",
                state=ClarificationRequestStatus.ANSWERED,
                question_items=[{"question_code": "goal", "question_text": "Какова цель?"}],
                answers=[SimpleNamespace(question_code="goal", sort_order=1)],
                answered_at=datetime.now(UTC),
            )
        ],
    )
    service = CanonicalTaskService.__new__(CanonicalTaskService)
    service.session = _TaskSession()
    service._get_task = lambda task_id, principal=None: task
    service._reassess_task = lambda task, principal, reopen=True: None
    service.audit = Mock()

    with pytest.raises(ValidationError) as exc_info:
        service.answer_clarification(
            "task-1",
            "clar-1",
            [{"question_code": "goal", "answer_text": "Сократить время обработки"}],
            _principal(),
        )

    assert exc_info.value.error_code == "CLARIFICATION_ANSWER_ALREADY_EXISTS"
    assert service.session.commits == 0


def test_extract_archimate_elements_does_not_treat_plain_api_as_application_interface() -> None:
    detected = extract_archimate_elements(
        "Сервис публикует API для внешней интеграции и журналирует запросы."
    )

    assert "application_interface" not in detected


def test_section_fallback_is_not_forced_for_substantive_text_without_explicit_archimate_terms() -> (
    None
):
    section_body = (
        "В прикладном контуре выделены сервис обработки заявок, модуль оркестрации, точка входа для внешних вызовов "
        "и внутренний механизм маршрутизации. Команда фиксирует сценарии обмена, распределение ответственности между "
        "частями решения и правила обработки ошибок для целевого бизнес-потока."
    )

    assert (
        should_apply_section_fallback(
            "application_architecture", section_body, {"status": "partial"}
        )
        is False
    )


def test_derive_structured_architecture_model_skips_unresolved_relations() -> None:
    payload = SimpleNamespace(
        sections=[],
        components=[
            SimpleNamespace(
                component_name="Workflow Service",
                role_description="Application Component реализует прикладную логику.",
                boundary_type="application_architecture",
                external_flag=False,
                technology_stack="Python",
            )
        ],
        integrations=[
            SimpleNamespace(
                from_component="Workflow Service",
                to_component="Missing Component",
                interaction="Передача статуса",
                protocol="HTTPS",
            )
        ],
    )

    model = derive_structured_architecture_model(payload)

    assert model["diagnostics"]["relation_count"] == 0
    assert model["diagnostics"]["skipped_relation_count"] == 1


def test_list_tasks_uses_single_eager_query_without_reloading_each_task() -> None:
    task = SimpleNamespace(business_task_id="task-1")
    session = _TaskSession(items=[task])
    service = CanonicalTaskService.__new__(CanonicalTaskService)
    service.session = session
    service._has_global_scope = lambda principal: False
    service._get_task = lambda task_id, principal=None: (_ for _ in ()).throw(
        AssertionError("_get_task must not be called")
    )

    items = service.list_tasks(_principal())

    assert items == [task]
    assert session.scalar_calls == 1
