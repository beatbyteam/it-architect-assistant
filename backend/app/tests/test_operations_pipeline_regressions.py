from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.api.v1.routes import knowledge_documents_routes as routes
from app.bootstrap.bundles import _resolve_requested_by
from app.core.exceptions import ConflictError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    BusinessTaskStatus,
    GenerationRunStatus,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    ProtocolSummaryStatus,
    SourceScope,
    UpdateRunType,
    VerificationRunStatus,
)
from app.domain.services.generation.run_service import GenerationRunService
from app.domain.services.generation.runtime import _run_publication_stage
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.mvp_task_write_service import _canonical_task_state
from app.domain.services.operations import OperationsQueryService
from app.domain.services.verification.runtime import _publish_verification_protocol
from app.schemas.knowledge import KnowledgeUpdateRunStartRequest


def _principal(user_id: str = "user-1") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
        is_authenticated=True,
    )


def test_operation_steps_use_stage_order_without_marking_future_steps_completed() -> None:
    row: dict[str, object] = {
        "started_at": "2026-04-05T10:00:00+00:00",
        "finished_at": None,
        "current_stage": "parsing",
        "status": "running",
        "diagnostics": {},
        "operation_kind": "knowledge_update_run",
    }

    steps = OperationsQueryService._build_operation_steps(row)
    statuses = {item["code"]: item["status"] for item in steps}

    assert statuses["queued"] == "completed"
    assert statuses["loading"] == "completed"
    assert statuses["parsing"] == "running"
    assert statuses["extracting"] == "pending"
    assert statuses["indexing"] == "pending"


def test_generation_operation_steps_explain_model_wait_stage() -> None:
    row: dict[str, object] = {
        "started_at": "2026-04-05T10:00:00+00:00",
        "finished_at": None,
        "current_stage": "model_generation",
        "status": "running",
        "diagnostics": {},
        "operation_kind": "generation_run",
    }

    steps = OperationsQueryService._build_operation_steps(row)
    statuses = {item["code"]: item["status"] for item in steps}
    titles = {item["code"]: item["title"] for item in steps}

    assert statuses["prompting"] == "completed"
    assert statuses["model_generation"] == "running"
    assert statuses["validating"] == "pending"
    assert statuses["persisting"] == "pending"
    assert titles["model_generation"] == "Ожидание ответа модели"


def test_operation_detail_merges_persisted_steps_with_planned_generation_pipeline() -> None:
    row: dict[str, object] = {
        "started_at": "2026-04-05T10:00:00+00:00",
        "finished_at": None,
        "current_stage": "model_generation",
        "status": "running",
        "diagnostics": {},
        "operation_kind": "generation_run",
    }
    persisted_steps = [
        {
            "code": "queued",
            "title": "Поставлено в очередь",
            "status": "queued",
            "started_at": "2026-04-05T10:00:00+00:00",
            "finished_at": None,
            "detail": "Generation run created",
            "error_code": None,
            "payload": None,
        },
        {
            "code": "prompting",
            "title": "Подготовка промпта",
            "status": "running",
            "started_at": "2026-04-05T10:01:00+00:00",
            "finished_at": None,
            "detail": "Prompt artifact prepared",
            "error_code": None,
            "payload": None,
        },
    ]

    steps = OperationsQueryService._merge_operation_steps(row, persisted_steps)
    statuses = {item["code"]: item["status"] for item in steps}

    assert statuses["queued"] == "completed"
    assert statuses["prompting"] == "completed"
    assert statuses["model_generation"] == "running"
    assert statuses["completed"] == "pending"


def test_last_problem_step_prefers_failed_stage_payload_over_generic_failed_step() -> None:
    failed_step = SimpleNamespace(
        status="failed",
        step_code="failed",
        payload={"failed_stage": "validating"},
    )

    assert (
        OperationsQueryService._derive_last_problem_step(
            "failed", [failed_step], "failed", diagnostics={}
        )
        == "validating"
    )


def test_build_public_start_payload_prefers_explicit_requested_by_override() -> None:
    service = cast(Any, KnowledgeUpdateService.__new__(KnowledgeUpdateService))
    payload = KnowledgeUpdateRunStartRequest(
        knowledge_base_id="kb-1",
        run_type=UpdateRunType.MANUAL,
        source_scope=SourceScope.ALL,
        requested_by="external-initiator",
        execute_inline=False,
    )

    result = service.build_public_start_payload(payload, _principal())

    assert result.requested_by == "external-initiator"


def test_bundle_requested_by_prefers_explicit_override() -> None:
    resolved = _resolve_requested_by(_principal(), requested_by="bundle-import")

    assert resolved == "bundle-import"


def test_upload_document_keeps_file_when_refresh_fails_after_commit(
    tmp_path: Path, monkeypatch
) -> None:
    target_path = tmp_path / "kb-1" / "uploaded.md"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("# Uploaded", encoding="utf-8")

    class _Session:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _document: object) -> None:
            raise RuntimeError("refresh failed")

        def rollback(self) -> None:
            self.rollbacks += 1

    class _KnowledgeSourceService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def get_document_payload(self, document_id: str, principal: AuthPrincipal):
            return {"document_id": document_id, "principal": principal.user_id}

    session = _Session()
    settings = SimpleNamespace(
        knowledge_upload_dir=str(tmp_path),
        knowledge_max_upload_size_bytes=1024,
    )
    principal = _principal()

    monkeypatch.setattr(
        routes, "_resolve_upload_base", lambda **kwargs: SimpleNamespace(knowledge_base_id="kb-1")
    )

    async def _fake_persist_uploaded_file(*, file, upload_dir, max_size_bytes):
        return "uploaded.md", target_path

    monkeypatch.setattr(routes, "_persist_uploaded_file", _fake_persist_uploaded_file)
    monkeypatch.setattr(routes, "KnowledgeSourceService", _KnowledgeSourceService)
    monkeypatch.setattr(
        routes, "_ensure_upload_source", lambda **kwargs: SimpleNamespace(source_id="src-1")
    )
    monkeypatch.setattr(
        routes, "_register_uploaded_document", lambda **kwargs: SimpleNamespace(document_id="doc-1")
    )
    monkeypatch.setattr(
        routes, "SourceDocumentResponse", SimpleNamespace(model_validate=lambda payload: payload)
    )

    with pytest.raises(RuntimeError, match="refresh failed"):
        asyncio.run(
            routes.upload_document(
                session=cast(Any, session),
                settings=cast(Any, settings),
                principal=principal,
                file=cast(Any, SimpleNamespace(filename="uploaded.md")),
                title="Uploaded",
                knowledge_base_id="kb-1",
                _guard=principal,
            )
        )

    assert session.commits == 1
    assert session.rollbacks == 0
    assert target_path.exists() is True


def test_ensure_upload_source_activates_new_manual_upload_source() -> None:
    service = SimpleNamespace()
    created_source = SimpleNamespace(source_id="src-new")
    calls: list[tuple[str, object]] = []

    service.list_sources = lambda knowledge_base_id, principal=None: []

    def _create_source(payload, principal, auto_commit=True):
        calls.append(("create", payload))
        return created_source

    def _update_source(source_id, payload, principal, auto_commit=True):
        calls.append(("update", source_id, payload))
        return SimpleNamespace(source_id=source_id, status="active")

    service.create_source = _create_source
    service.update_source = _update_source
    service.session = SimpleNamespace(rollback=lambda: None)

    resolved = routes._ensure_upload_source(
        service=service,
        principal=_principal(),
        knowledge_base_id="kb-1",
        upload_dir=Path("/tmp/uploads"),
        auto_commit=False,
    )

    assert resolved.source_id == "src-new"
    assert calls[0][0] == "create"
    assert calls[1][0] == "update"
    assert calls[1][1] == "src-new"
    assert calls[1][2].status.value == "active"


def test_upload_and_ingest_batch_requests_single_auto_activating_run(
    monkeypatch, tmp_path: Path
) -> None:
    target_paths = [tmp_path / "kb-1" / "first.md", tmp_path / "kb-1" / "second.md"]
    captured: dict[str, object] = {}

    class _Session:
        def __init__(self) -> None:
            self.refreshes: list[str] = []
            self.rollbacks = 0

        def refresh(self, document: object) -> None:
            self.refreshes.append(str(getattr(document, "document_id", "")))

        def rollback(self) -> None:
            self.rollbacks += 1

    class _KnowledgeSourceService:
        def __init__(self, session, settings=None) -> None:
            self.session = session
            self.settings = settings

        def get_document_payload(self, document_id: str, principal: AuthPrincipal):
            return {"document_id": document_id, "principal": principal.user_id}

    class _KnowledgeUpdateService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def start_run(self, payload, principal):
            captured["auto_activate_if_validated"] = payload.auto_activate_if_validated
            captured["selected_source_ids"] = list(payload.selected_source_ids)
            captured["document_ids"] = list(payload.document_ids)
            captured["run_type"] = payload.run_type
            captured["reason"] = payload.reason
            return {"update_run_id": "run-1"}

        def get_run_response(self, update_run_id: str, principal: AuthPrincipal):
            return {"update_run_id": update_run_id, "principal": principal.user_id}

    async def _fake_persist_uploaded_file(*, file, upload_dir, max_size_bytes):
        index = 0 if file.filename == "first.md" else 1
        target_paths[index].parent.mkdir(parents=True, exist_ok=True)
        target_paths[index].write_text(f"content {index}", encoding="utf-8")
        return file.filename, target_paths[index]

    documents = [
        SimpleNamespace(document_id="doc-1", source_id="src-1"),
        SimpleNamespace(document_id="doc-2", source_id="src-1"),
    ]

    def _fake_register_uploaded_document(**kwargs):
        index = 0 if kwargs["original_name"] == "first.md" else 1
        captured[f"title_{index}"] = kwargs["title"]
        return documents[index]

    monkeypatch.setattr(
        routes, "_resolve_upload_base", lambda **kwargs: SimpleNamespace(knowledge_base_id="kb-1")
    )
    monkeypatch.setattr(routes, "_persist_uploaded_file", _fake_persist_uploaded_file)
    monkeypatch.setattr(routes, "KnowledgeSourceService", _KnowledgeSourceService)
    monkeypatch.setattr(routes, "KnowledgeUpdateService", _KnowledgeUpdateService)
    monkeypatch.setattr(
        routes, "_ensure_upload_source", lambda **kwargs: SimpleNamespace(source_id="src-1")
    )
    monkeypatch.setattr(routes, "_register_uploaded_document", _fake_register_uploaded_document)
    monkeypatch.setattr(
        routes, "SourceDocumentResponse", SimpleNamespace(model_validate=lambda payload: payload)
    )
    monkeypatch.setattr(
        routes, "KnowledgeUpdateRunResponse", SimpleNamespace(model_validate=lambda payload: payload)
    )
    monkeypatch.setattr(
        routes,
        "DocumentBatchMutationResponse",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    principal = _principal()
    result = asyncio.run(
        routes.upload_and_ingest_documents(
            session=cast(Any, _Session()),
            settings=cast(
                Any,
                SimpleNamespace(
                    knowledge_upload_dir=str(tmp_path),
                    knowledge_max_upload_size_bytes=1024,
                ),
            ),
            principal=principal,
            files=[
                cast(Any, SimpleNamespace(filename="first.md")),
                cast(Any, SimpleNamespace(filename="second.md")),
            ],
            title="Uploaded",
            knowledge_base_id="kb-1",
            execute_update_inline=False,
            reason=None,
            _guard=principal,
        )
    )

    assert captured["auto_activate_if_validated"] is True
    assert captured["selected_source_ids"] == ["src-1"]
    assert captured["document_ids"] == ["doc-1", "doc-2"]
    assert captured["run_type"] == UpdateRunType.UPLOAD
    assert captured["reason"] == "batch_upload:kb-1"
    assert captured["title_0"] == "Uploaded 1"
    assert captured["title_1"] == "Uploaded 2"
    assert len(result.documents) == 2
    assert result.update_run["update_run_id"] == "run-1"


def test_upload_and_ingest_batch_removes_persisted_files_on_registration_failure(
    monkeypatch, tmp_path: Path
) -> None:
    target_paths = [tmp_path / "kb-1" / "first.md", tmp_path / "kb-1" / "second.md"]

    class _Session:
        def __init__(self) -> None:
            self.rollbacks = 0

        def rollback(self) -> None:
            self.rollbacks += 1

    async def _fake_persist_uploaded_file(*, file, upload_dir, max_size_bytes):
        index = 0 if file.filename == "first.md" else 1
        target_paths[index].parent.mkdir(parents=True, exist_ok=True)
        target_paths[index].write_text(f"content {index}", encoding="utf-8")
        return file.filename, target_paths[index]

    session = _Session()
    principal = _principal()
    monkeypatch.setattr(
        routes, "_resolve_upload_base", lambda **kwargs: SimpleNamespace(knowledge_base_id="kb-1")
    )
    monkeypatch.setattr(routes, "_persist_uploaded_file", _fake_persist_uploaded_file)
    monkeypatch.setattr(routes, "KnowledgeSourceService", lambda session, settings: SimpleNamespace())
    monkeypatch.setattr(
        routes, "_ensure_upload_source", lambda **kwargs: SimpleNamespace(source_id="src-1")
    )
    monkeypatch.setattr(
        routes,
        "_register_uploaded_document",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("registration failed")),
    )

    with pytest.raises(RuntimeError, match="registration failed"):
        asyncio.run(
            routes.upload_and_ingest_documents(
                session=cast(Any, session),
                settings=cast(
                    Any,
                    SimpleNamespace(
                        knowledge_upload_dir=str(tmp_path),
                        knowledge_max_upload_size_bytes=1024,
                    ),
                ),
                principal=principal,
                files=[
                    cast(Any, SimpleNamespace(filename="first.md")),
                    cast(Any, SimpleNamespace(filename="second.md")),
                ],
                title=None,
                knowledge_base_id="kb-1",
                execute_update_inline=False,
                reason=None,
                _guard=principal,
            )
        )

    assert session.rollbacks == 1
    assert all(not path.exists() for path in target_paths)


def test_persist_uploaded_file_reports_size_limit_as_validation_error(tmp_path: Path) -> None:
    class _Upload:
        filename = "large.md"

        def __init__(self) -> None:
            self._chunks = [b"too large"]
            self.closed = False

        async def read(self, _size: int) -> bytes:
            return self._chunks.pop(0) if self._chunks else b""

        async def close(self) -> None:
            self.closed = True

    upload = _Upload()

    with pytest.raises(ValidationError) as exc_info:
        asyncio.run(
            routes._persist_uploaded_file(
                file=cast(Any, upload),
                upload_dir=tmp_path,
                max_size_bytes=1,
            )
        )

    assert exc_info.value.error_code == "DOCUMENT_SIZE_LIMIT_EXCEEDED"
    assert upload.closed is True
    assert list(tmp_path.iterdir()) == []


def test_upload_and_ingest_requests_auto_activation(monkeypatch, tmp_path: Path) -> None:
    target_path = tmp_path / "kb-1" / "uploaded.weirdext"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("uploaded content", encoding="utf-8")
    captured: dict[str, object] = {}

    class _Session:
        def refresh(self, _obj: object) -> None:
            return None

        def rollback(self) -> None:
            return None

    class _KnowledgeSourceService:
        def __init__(self, session, settings=None) -> None:
            self.session = session
            self.settings = settings

        def get_document_payload(self, document_id: str, principal: AuthPrincipal):
            return {
                "document_id": document_id,
                "knowledge_base_id": "kb-1",
                "source_id": "src-1",
                "source_type": "manual_upload",
                "document_type": "other",
                "title": "Uploaded",
                "uri": str(target_path),
                "version_label": None,
                "checksum": None,
                "is_latest": True,
                "status": "registered",
                "registered_at": "2026-04-13T00:00:00Z",
            }

    class _KnowledgeUpdateService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def start_run(self, payload, principal):
            captured["auto_activate_if_validated"] = payload.auto_activate_if_validated
            captured["selected_source_ids"] = list(payload.selected_source_ids)
            return {"update_run_id": "run-1"}

        def get_run_response(self, update_run_id: str, principal: AuthPrincipal):
            return {
                "update_run_id": update_run_id,
                "knowledge_base_id": "kb-1",
                "run_type": "upload",
                "status": "queued",
                "current_stage": "queued",
                "source_scope": "selected",
                "selected_source_ids": ["src-1"],
                "started_at": "2026-04-13T00:00:00Z",
            }

    settings = SimpleNamespace(
        knowledge_upload_dir=str(tmp_path),
        knowledge_max_upload_size_bytes=1024,
    )
    principal = _principal()
    session = _Session()

    monkeypatch.setattr(
        routes, "_resolve_upload_base", lambda **kwargs: SimpleNamespace(knowledge_base_id="kb-1")
    )

    async def _fake_persist_uploaded_file(*, file, upload_dir, max_size_bytes):
        return "uploaded.weirdext", target_path

    monkeypatch.setattr(routes, "_persist_uploaded_file", _fake_persist_uploaded_file)
    monkeypatch.setattr(routes, "KnowledgeSourceService", _KnowledgeSourceService)
    monkeypatch.setattr(routes, "KnowledgeUpdateService", _KnowledgeUpdateService)
    monkeypatch.setattr(
        routes, "_ensure_upload_source", lambda **kwargs: SimpleNamespace(source_id="src-1")
    )
    monkeypatch.setattr(
        routes,
        "_register_uploaded_document",
        lambda **kwargs: SimpleNamespace(document_id="doc-1", source_id="src-1"),
    )
    monkeypatch.setattr(
        routes, "SourceDocumentResponse", SimpleNamespace(model_validate=lambda payload: payload)
    )
    monkeypatch.setattr(
        routes, "KnowledgeUpdateRunResponse", SimpleNamespace(model_validate=lambda payload: payload)
    )

    result = asyncio.run(
        routes.upload_and_ingest_document(
            session=cast(Any, session),
            settings=cast(Any, settings),
            principal=principal,
            file=cast(Any, SimpleNamespace(filename="uploaded.weirdext")),
            title="Uploaded",
            knowledge_base_id="kb-1",
            execute_update_inline=True,
            reason=None,
            _guard=principal,
        )
    )

    assert captured["auto_activate_if_validated"] is True
    assert captured["selected_source_ids"] == ["src-1"]
    assert result.update_run is not None
    assert result.update_run.update_run_id == "run-1"


def test_generation_publication_keeps_completed_state_when_refresh_fails_after_commit() -> None:
    class _Session:
        def __init__(self) -> None:
            self.commits = 0
            self.refresh_calls = 0

        def add(self, _obj: object) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _obj: object) -> None:
            self.refresh_calls += 1
            raise RuntimeError("refresh failed")

    session = _Session()
    run = SimpleNamespace(
        generation_run_id="run-1",
        started_by_user_id="user-1",
        correlation_id="corr-1",
        status=GenerationRunStatus.RUNNING,
        current_stage="publishing",
        diagnostics={},
    )
    task = SimpleNamespace(
        business_task_id="task-1",
        status=BusinessTaskStatus.READY_FOR_GENERATION,
        updated_at=None,
    )
    solution = SimpleNamespace(
        solution_version_id="sol-1",
        published_at=None,
    )
    published_artifact = SimpleNamespace(published_artifact_id="pub-1", revision_no=3)
    audit_calls: list[str] = []
    service = SimpleNamespace(
        session=session,
        publication=SimpleNamespace(
            publish=lambda **kwargs: (solution, published_artifact)
        ),
        _record_operation_step=lambda *args, **kwargs: None,
        _with_stage_history=lambda diagnostics, *args, **kwargs: diagnostics,
        audit=SimpleNamespace(record=lambda **kwargs: audit_calls.append(kwargs["event_type"])),
    )

    result = _run_publication_stage(
        service,
        run=cast(Any, run),
        task=task,
        solution=solution,
        payload=SimpleNamespace(),
        quality_outcomes={},
        coverage_summary={},
        stage_metrics={},
        total_duration_sec=1.0,
    )

    assert result is run
    assert run.status == GenerationRunStatus.COMPLETED
    assert run.current_stage == "completed"
    assert task.status == BusinessTaskStatus.COMPLETED
    assert session.commits == 1
    assert session.refresh_calls == 2
    assert audit_calls == ["generation.run.completed"]


def test_generation_cancel_run_marks_current_step_and_audit_event() -> None:
    commits: list[bool] = []
    records: list[dict[str, Any]] = []
    audit_calls: list[dict[str, Any]] = []
    run = SimpleNamespace(
        generation_run_id="run-1",
        business_task_id="task-1",
        business_task=SimpleNamespace(created_by_user_id="user-1"),
        status=GenerationRunStatus.RUNNING,
        current_stage="model_generation",
        diagnostics={},
        started_by_user_id="user-1",
        correlation_id="corr-1",
        finished_at=None,
    )
    service = object.__new__(GenerationRunService)
    service.get_run = lambda _run_id, _principal=None: run
    service.session = SimpleNamespace(
        add=lambda _obj: None,
        commit=lambda: commits.append(True),
        refresh=lambda _obj: None,
    )
    service._record_operation_step = lambda _run, **kwargs: records.append(kwargs)
    service.audit = SimpleNamespace(record=lambda **kwargs: audit_calls.append(kwargs))

    result = service.cancel_run("run-1", _principal())

    assert result is run
    assert run.status == GenerationRunStatus.CANCELED
    assert run.current_stage == "canceled"
    assert run.finished_at is not None
    assert run.diagnostics["error_code"] == "CANCELED_BY_USER"
    assert [item["stage"] for item in records] == ["model_generation", "canceled"]
    assert [item["status"] for item in records] == ["canceled", "canceled"]
    assert audit_calls[0]["event_type"] == "generation.run.canceled"
    assert commits == [True]


def test_generation_cancel_run_rejects_finished_run() -> None:
    run = SimpleNamespace(status=GenerationRunStatus.COMPLETED)
    service = object.__new__(GenerationRunService)
    service.get_run = lambda _run_id, _principal=None: run

    with pytest.raises(ConflictError):
        service.cancel_run("run-1", _principal())


def test_knowledge_update_cancel_run_rejects_candidate_and_records_cancellation() -> None:
    commits: list[bool] = []
    records: list[dict[str, Any]] = []
    audit_calls: list[dict[str, Any]] = []
    run = SimpleNamespace(
        update_run_id="update-1",
        knowledge_base_id="kb-1",
        status=KnowledgeUpdateStatus.INDEXING,
        current_stage="indexing",
        started_at=datetime.now(UTC),
        finished_at=None,
        duration_sec=None,
        summary={"stage_history": []},
        initiator_user_id="user-1",
        correlation_id="corr-1",
    )
    candidate = SimpleNamespace(
        knowledge_version_id="version-1",
        status=KnowledgeVersionStatus.PREPARING,
        summary={},
    )
    service = object.__new__(KnowledgeUpdateService)
    service.get_run = lambda _run_id, _principal=None: run
    service._serialize_run = lambda item: {
        "update_run_id": item.update_run_id,
        "status": item.status,
        "current_stage": item.current_stage,
        "summary": item.summary,
    }
    service._append_stage_history = (
        lambda history, stage, detail=None, stage_status=None: list(history or [])
        + [{"stage": stage, "detail": detail, "status": stage_status}]
    )
    service._record_operation_step = lambda _run, **kwargs: records.append(kwargs)
    service.versions = SimpleNamespace(get_by_update_run_id=lambda _run_id: candidate)
    service.session = SimpleNamespace(
        add=lambda _obj: None,
        commit=lambda: commits.append(True),
        refresh=lambda _obj: None,
    )
    service.audit = SimpleNamespace(record=lambda **kwargs: audit_calls.append(kwargs))

    result = service.cancel_run("update-1", _principal())

    assert result["status"] == KnowledgeUpdateStatus.CANCELED
    assert run.current_stage == "canceled"
    assert run.summary["quality_summary"]["error_code"] == "CANCELED_BY_USER"
    assert candidate.status == KnowledgeVersionStatus.REJECTED
    assert [item["stage"] for item in records] == ["indexing", "canceled"]
    assert audit_calls[0]["event_type"] == "knowledge.refresh.canceled"
    assert commits == [True]


def test_canonical_task_state_marks_legacy_ready_task_completed_when_solution_exists() -> None:
    task = SimpleNamespace(
        status=BusinessTaskStatus.READY_FOR_GENERATION,
        generation_runs=[
            SimpleNamespace(
                started_at=None,
                status=GenerationRunStatus.COMPLETED,
                solution_version=SimpleNamespace(solution_version_id="sol-1"),
            ),
        ],
    )

    assert _canonical_task_state(cast(Any, task)) == BusinessTaskStatus.COMPLETED.value


def test_verification_publication_keeps_completed_state_when_refresh_fails_after_commit() -> None:
    class _Session:
        def __init__(self) -> None:
            self.commits = 0
            self.refresh_calls = 0

        def add(self, _obj: object) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _obj: object) -> None:
            self.refresh_calls += 1
            raise RuntimeError("refresh failed")

    session = _Session()
    run = SimpleNamespace(
        verification_run_id="ver-1",
        solution_version_id="sol-1",
        started_by_user_id="user-1",
        correlation_id="corr-2",
        status=VerificationRunStatus.RUNNING,
        current_stage="publishing",
        diagnostics={},
    )
    protocol = SimpleNamespace(verification_protocol_id="vp-1")
    published_artifact = SimpleNamespace(published_artifact_id="pub-2", revision_no=4)
    audit_calls: list[str] = []
    payload = SimpleNamespace(
        final_status=ProtocolSummaryStatus.PASSED,
        check_results=[],
    )
    service = SimpleNamespace(
        session=session,
        persistence=SimpleNamespace(persist=lambda **kwargs: (protocol, published_artifact)),
        _record_operation_step=lambda *args, **kwargs: None,
        _with_stage_history=lambda diagnostics, *args, **kwargs: diagnostics,
        audit=SimpleNamespace(record=lambda **kwargs: audit_calls.append(kwargs["event_type"])),
    )

    result = _publish_verification_protocol(
        service,
        run=cast(Any, run),
        payload=payload,
        validation_summary={},
        rule_lookup={},
        rule_groups=[],
        support_context={},
        stage_metrics={},
        total_duration_sec=1.0,
    )

    assert result is run
    assert run.status == VerificationRunStatus.COMPLETED
    assert run.current_stage == "completed"
    assert session.commits == 1
    assert session.refresh_calls == 1
    assert audit_calls == ["verification.run.completed"]


def test_knowledge_update_queue_dispatch_does_not_depend_on_refresh_after_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.commits = 0
            self.refresh_calls = 0

        def add(self, obj: object) -> None:
            self.added.append(obj)

        def flush(self) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _obj: object) -> None:
            self.refresh_calls += 1
            raise RuntimeError("refresh failed")

    queued_ids: list[str] = []

    class _Job:
        @staticmethod
        def delay(run_id: str) -> None:
            queued_ids.append(run_id)

    session = _Session()
    service = cast(Any, KnowledgeUpdateService.__new__(KnowledgeUpdateService))
    service.session = session
    service.settings = SimpleNamespace(app_env="production")
    service.idempotency = SimpleNamespace(
        resolve_existing=lambda **kwargs: None, register=lambda **kwargs: None
    )
    service._get_base = lambda knowledge_base_id, principal=None: SimpleNamespace(
        knowledge_base_id=knowledge_base_id
    )
    service._ensure_system_bases = lambda principal=None: None
    service._get_default_user_base = lambda principal=None: SimpleNamespace(
        knowledge_base_id="kb-default"
    )
    service._get_running_run_with_recovery = lambda knowledge_base_id=None: None
    service._resolve_scope_sources = (
        lambda source_scope, selected_source_ids, knowledge_base_id=None: [
            SimpleNamespace(source_id="src-1")
        ]
    )
    service.update_runs = SimpleNamespace(add=lambda run: session.add(run))
    service.operations = SimpleNamespace(record_step=lambda **kwargs: None)
    service.audit = SimpleNamespace(record=lambda **kwargs: None)
    service._create_candidate_version = lambda run, selected_sources: SimpleNamespace(
        knowledge_version_id="kv-1", source_snapshot={}
    )
    service._should_force_inline_without_worker = lambda: False
    monkeypatch.setattr("app.tasks.jobs.knowledge.run_knowledge_update", _Job)

    run = service._create_run(
        payload=cast(
            Any,
            SimpleNamespace(
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
                execute_inline=False,
                auto_activate_if_validated=False,
            ),
        ),
        initiator_user_id="svc.worker",
        principal=_principal(),
    )

    assert str(run.update_run_id) in queued_ids
    assert run.status.value == "queued"
    assert session.commits == 2
    assert session.refresh_calls == 0
