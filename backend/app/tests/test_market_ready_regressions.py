from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthorizationError
from app.core.security import AuthPrincipal
from app.db.enums import AccountType, GenerationRunStatus
from app.db.repositories.knowledge import SourceDocumentRepository
from app.domain.services.generation.task_service import BusinessTaskService
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.mvp_access import has_mvp_global_scope
from app.domain.services.mvp_registry_presenters import list_solutions
from app.domain.services.operations import OperationsQueryService


def _principal(
    user_id: str = "user-1",
    *,
    roles: list[str] | None = None,
    account_type: AccountType = AccountType.HUMAN,
) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        login=user_id,
        display_name=user_id,
        account_type=account_type,
        role_codes=roles or ["USER"],
        is_authenticated=True,
    )


def _settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "local",
        "AUTH_MODE": "local_noauth",
        "MVP_PERMISSIVE_LOCAL_ACCESS": True,
        "MVP_GLOBAL_ROLE_CODES": ["MVP_ADMIN"],
        "EMBEDDING_BASE_URL": "http://localhost:8001",
        "LLM_BASE_URL": "http://localhost:8002",
    }
    values.update(overrides)
    return Settings(**values)


def test_mvp_global_scope_is_permissive_only_in_local_mode() -> None:
    assert (
        has_mvp_global_scope(
            _settings(APP_ENV="local", AUTH_MODE="local_noauth"),
            _principal("user-1", roles=["USER"]),
        )
        is True
    )
    assert (
        has_mvp_global_scope(
            _settings(APP_ENV="production", AUTH_MODE="trusted_headers"),
            _principal("user-1", roles=["USER"]),
        )
        is False
    )
    assert (
        has_mvp_global_scope(
            _settings(APP_ENV="production", AUTH_MODE="trusted_headers"),
            _principal("admin-1", roles=["MVP_ADMIN"]),
        )
        is True
    )


def test_business_task_service_keeps_owner_isolation_outside_local_mode() -> None:
    service = BusinessTaskService.__new__(BusinessTaskService)
    service.settings = _settings(APP_ENV="production", AUTH_MODE="trusted_headers")
    own_task = SimpleNamespace(created_by_user_id="user-1")
    foreign_task = SimpleNamespace(created_by_user_id="user-2")

    service._ensure_task_access(own_task, _principal("user-1", roles=["USER"]))
    from app.core.exceptions import AuthorizationError

    with pytest.raises(AuthorizationError):
        service._ensure_task_access(foreign_task, _principal("user-1", roles=["USER"]))


class _SessionPages:
    def __init__(self, pages: list[object]) -> None:
        self._pages = list(pages)

    def scalars(self, statement):
        offset = int(getattr(statement._offset_clause, "value", 0) or 0)
        limit = int(getattr(statement._limit_clause, "value", len(self._pages)) or len(self._pages))
        return list(self._pages[offset : offset + limit])


def test_list_solutions_skips_inaccessible_rows_and_keeps_limit_after_filtering() -> None:
    foreign = SimpleNamespace(
        solution_version_id="sol-foreign",
        business_task_id="task-foreign",
        generation_run_id="gen-foreign",
        generation_run=SimpleNamespace(knowledge_version_id="kv-foreign"),
        verification_runs=[],
        status="published",
        solution_title="Foreign",
        published_at=None,
        created_at=datetime(2026, 4, 6, tzinfo=UTC),
    )
    own = SimpleNamespace(
        solution_version_id="sol-own",
        business_task_id="task-own",
        generation_run_id="gen-own",
        generation_run=SimpleNamespace(knowledge_version_id="kv-own"),
        verification_runs=[],
        status="published",
        solution_title="Own",
        published_at=None,
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
    )
    service = SimpleNamespace(
        session=_SessionPages([foreign, own]),
        settings=_settings(APP_ENV="production", AUTH_MODE="trusted_headers"),
        map_solution_state=lambda status: str(status),
        map_verification_run_state=lambda status: str(status),
    )

    class _VerificationQuery:
        def _ensure_solution_access(self, solution, principal):
            if solution.solution_version_id != "sol-own":
                raise AuthorizationError("denied")

    rows = list_solutions(
        service,
        _principal("user-1", roles=["USER"]),
        verification_query_service_factory=lambda session, settings=None: _VerificationQuery(),
        limit=1,
    )

    assert [item["solution_version_id"] for item in rows] == ["sol-own"]


def test_operations_list_overfetches_until_visible_rows_are_found() -> None:
    own_run = SimpleNamespace(
        generation_run_id="gen-own",
        status=SimpleNamespace(value=GenerationRunStatus.COMPLETED.value),
        current_stage="completed",
        correlation_id="corr-own",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        started_by_user_id="user-1",
        business_task_id="task-1",
        knowledge_version_id="kv-1",
        solution_version=SimpleNamespace(solution_version_id="sol-1"),
        diagnostics={},
    )
    foreign_runs = [
        SimpleNamespace(
            generation_run_id=f"gen-foreign-{idx}",
            status=SimpleNamespace(value=GenerationRunStatus.COMPLETED.value),
            current_stage="completed",
            correlation_id=f"corr-foreign-{idx}",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            started_by_user_id="user-2",
            business_task_id=f"task-{idx}",
            knowledge_version_id=f"kv-{idx}",
            solution_version=None,
            diagnostics={},
        )
        for idx in range(3)
    ]
    all_runs = foreign_runs + [own_run]

    class _GenerationRunsRepo:
        def list_recent(self, *, limit=100, offset=0, **kwargs):
            return all_runs[offset : offset + limit]

        def get(self, operation_id):
            for item in all_runs:
                if item.generation_run_id == operation_id:
                    return item
            return None

    service = OperationsQueryService.__new__(OperationsQueryService)
    service.session = SimpleNamespace()
    service.settings = SimpleNamespace()
    service.operation_steps = SimpleNamespace(list_for_operation=lambda **kwargs: [])
    service.audit = SimpleNamespace(list_filtered=lambda **kwargs: [])
    service.knowledge_runs = SimpleNamespace(list_recent=lambda **kwargs: [], get=lambda _id: None)
    service.generation_runs = _GenerationRunsRepo()
    service.verification_runs = SimpleNamespace(
        list_recent=lambda **kwargs: [], get=lambda _id: None
    )

    rows = service.list_operations(limit=1, principal=_principal("user-1"))

    assert [row["operation_id"] for row in rows] == ["gen-own"]


class _ScalarList:
    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)


class _SessionForDocuments:
    def __init__(self, items):
        self._items = items

    def scalars(self, statement):
        return _ScalarList(self._items)


def test_source_document_repository_batches_by_source_without_name_error() -> None:
    doc_a = SimpleNamespace(source_id="src-a", document_id="doc-a")
    doc_b = SimpleNamespace(source_id="src-b", document_id="doc-b")
    repo = SourceDocumentRepository(_SessionForDocuments([doc_a, doc_b]))

    grouped = repo.list_for_sources(["src-a", "src-b"])

    assert [item.document_id for item in grouped["src-a"]] == ["doc-a"]
    assert [item.document_id for item in grouped["src-b"]] == ["doc-b"]


def test_scheduled_sync_execution_is_restricted_outside_local_runtime() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.settings = _settings(APP_ENV="production", AUTH_MODE="trusted_headers")

    with pytest.raises(AuthorizationError):
        service._ensure_scheduled_sync_execution_allowed(_principal("user-1", roles=["USER"]))

    service._ensure_scheduled_sync_execution_allowed(
        _principal("svc", roles=["USER"], account_type=AccountType.SERVICE)
    )
    local_service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    local_service.settings = _settings(APP_ENV="local", AUTH_MODE="local_noauth")
    local_service._ensure_scheduled_sync_execution_allowed(_principal("user-1", roles=["USER"]))
