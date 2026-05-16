from __future__ import annotations

from pathlib import Path

from sqlalchemy.exc import IntegrityError

from app.db.enums import Criticality, KnowledgeBaseKind, SourceDocumentStatus, SourceStatus
from app.integrations.knowledge.source_readers import is_document_explicitly_excluded
from app.integrations.knowledge.source_security import SourceDocumentPolicyError

from .knowledge_routes_common import (
    APIRouter,
    AuthPrincipal,
    Body,
    DocumentBatchMutationResponse,
    DocumentChunkResponse,
    DocumentExtractedItemsResponse,
    DocumentMemoryResponse,
    DocumentMutationResponse,
    DocumentSnapshotResponse,
    DocumentType,
    File,
    Form,
    InternalKnowledgeUpdateRunStartRequest,
    KnowledgeBaseService,
    KnowledgeReindexRequest,
    KnowledgeSourceService,
    KnowledgeUpdateRunResponse,
    KnowledgeUpdateService,
    PrincipalDep,
    Query,
    SessionDep,
    SettingsDep,
    SourceCreateRequest,
    SourceDocumentCreateRequest,
    SourceDocumentResponse,
    SourceDocumentUpdateRequest,
    SourceScope,
    SourceType,
    SourceUpdateRequest,
    UpdateRunType,
    UploadFile,
    UserDep,
    ValidationError,
    enforce_document_size_limit,
    guess_document_type_from_name,
    principal_requested_by,
    status,
    uuid4,
)

router = APIRouter()


def _upload_dir_for_base(settings: SettingsDep, knowledge_base_id: str) -> Path:
    return Path(settings.knowledge_upload_dir).resolve() / str(knowledge_base_id)


def _find_manual_upload_source(
    service: KnowledgeSourceService,
    *,
    knowledge_base_id: str,
    principal: AuthPrincipal | None = None,
):
    return next(
        (
            item
            for item in service.list_sources(
                knowledge_base_id=knowledge_base_id,
                principal=principal,
            )
            if getattr(item, "source_type", None) in {SourceType.MANUAL_UPLOAD, "manual_upload"}
        ),
        None,
    )


def _infer_uploaded_document_type(
    filename: str,
    title: str | None = None,
) -> DocumentType:
    inferred = guess_document_type_from_name(filename)
    if inferred != DocumentType.OTHER:
        return inferred
    return guess_document_type_from_name(title or filename)


def _resolve_update_run_id(run: object) -> str:
    value = run.get("update_run_id") if isinstance(run, dict) else getattr(run, "update_run_id", None)
    if value is None:
        raise ValidationError(
            "Knowledge update run id is missing",
            error_code="KNOWLEDGE_UPDATE_RUN_ID_MISSING",
        )
    return str(value)


def _resolve_reindex_request(
    payload: KnowledgeReindexRequest | None,
    *,
    execute_inline: bool | None = None,
    legacy_execute_inline: bool | None = None,
    reason: str | None = None,
) -> KnowledgeReindexRequest:
    if payload is not None:
        return payload
    resolved_execute_inline = (
        execute_inline if execute_inline is not None else legacy_execute_inline
    )
    return KnowledgeReindexRequest(execute_inline=resolved_execute_inline, reason=reason)


async def _persist_uploaded_file(
    *,
    file: UploadFile,
    upload_dir: Path,
    max_size_bytes: int,
) -> tuple[str, Path]:
    original_name = Path(file.filename or "material.bin").name
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}_{original_name}"
    target_path = upload_dir / stored_name
    total_size = 0
    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                enforce_document_size_limit(total_size, max_size_bytes=max_size_bytes)
                handle.write(chunk)
    except SourceDocumentPolicyError as exc:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise ValidationError(
            str(exc),
            error_code=exc.error_code,
            details={"filename": original_name, "max_size_bytes": max_size_bytes},
        ) from exc
    except Exception:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return original_name, target_path


def _resolve_upload_base(
    *,
    session: SessionDep,
    principal: AuthPrincipal,
    knowledge_base_id: str | None,
):
    base_service = KnowledgeBaseService(session)
    if knowledge_base_id:
        return base_service.get_base(knowledge_base_id, principal)
    base_service.ensure_system_bases(principal)
    scope = base_service.get_existing_effective_scope(principal)
    selected_base = scope.selected_user_base if scope is not None else None
    if selected_base is not None and selected_base.kind == KnowledgeBaseKind.USER_MANAGED:
        return selected_base
    raise ValidationError(
        "knowledge_base_id is required when uploading documents before a user knowledge base is selected",
        error_code="KNOWLEDGE_BASE_REQUIRED",
    )


def _normalize_upload_source_status(value: str | SourceStatus | None) -> SourceStatus:
    if value is None or str(value).strip() == "":
        return SourceStatus.ACTIVE
    if isinstance(value, SourceStatus):
        status_value = value
    else:
        try:
            status_value = SourceStatus(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(
                "Upload source status must be active or disabled",
                error_code="INVALID_UPLOAD_SOURCE_STATUS",
            ) from exc
    if status_value not in {SourceStatus.ACTIVE, SourceStatus.DISABLED}:
        raise ValidationError(
            "Upload source status must be active or disabled",
            error_code="INVALID_UPLOAD_SOURCE_STATUS",
        )
    return status_value


def _ensure_upload_source(
    *,
    service: KnowledgeSourceService,
    principal: AuthPrincipal,
    knowledge_base_id: str,
    upload_dir: Path,
    refresh_policy: str | None = None,
    source_status: SourceStatus | None = None,
    auto_commit: bool = True,
):
    desired_base_uri = upload_dir.as_uri()
    desired_refresh_policy = (refresh_policy or "manual").strip() or "manual"
    desired_status = source_status or SourceStatus.ACTIVE
    upload_source = _find_manual_upload_source(
        service,
        knowledge_base_id=knowledge_base_id,
        principal=principal,
    )
    if upload_source is None:
        try:
            created_source = service.create_source(
                SourceCreateRequest(
                    knowledge_base_id=knowledge_base_id,
                    source_type=SourceType.MANUAL_UPLOAD,
                    name="Загруженные файлы",
                    base_uri=desired_base_uri,
                    criticality=Criticality.REQUIRED,
                    refresh_policy=desired_refresh_policy,
                ),
                principal,
                auto_commit=auto_commit,
            )
            return service.update_source(
                str(created_source.source_id),
                SourceUpdateRequest(status=desired_status),
                principal,
                auto_commit=auto_commit,
            )
        except IntegrityError:
            service.session.rollback()
            upload_source = _find_manual_upload_source(
                service,
                knowledge_base_id=knowledge_base_id,
                principal=principal,
            )
            if upload_source is None:
                raise

    update_name: str | None = None
    update_base_uri: str | None = None
    update_refresh_policy: str | None = None
    update_status: SourceStatus | None = None
    if str(getattr(upload_source, "base_uri", "") or "") != desired_base_uri:
        update_base_uri = desired_base_uri
    if str(getattr(upload_source, "name", "") or "") != "Загруженные файлы":
        update_name = "Загруженные файлы"
    if str(getattr(upload_source, "refresh_policy", "") or "") != desired_refresh_policy:
        update_refresh_policy = desired_refresh_policy
    current_status = str(
        getattr(
            getattr(upload_source, "status", None),
            "value",
            getattr(upload_source, "status", None),
        )
        or ""
    )
    if current_status != desired_status.value:
        update_status = desired_status

    if any(
        value is not None
        for value in (
            update_name,
            update_base_uri,
            update_refresh_policy,
            update_status,
        )
    ):
        return service.update_source(
            str(upload_source.source_id),
            SourceUpdateRequest(
                name=update_name,
                base_uri=update_base_uri,
                refresh_policy=update_refresh_policy,
                status=update_status,
            ),
            principal,
            auto_commit=auto_commit,
        )
    return upload_source


def _register_uploaded_document(
    *,
    service: KnowledgeSourceService,
    principal: AuthPrincipal,
    upload_source_id: str,
    target_path: Path,
    original_name: str,
    title: str | None,
    auto_commit: bool = True,
):
    return service.register_document(
        upload_source_id,
        SourceDocumentCreateRequest(
            document_type=_infer_uploaded_document_type(original_name, title),
            title=((title or original_name).strip() or original_name),
            uri=target_path.as_uri(),
        ),
        principal,
        auto_commit=auto_commit,
    )


def _title_for_uploaded_file(
    *,
    title: str | None,
    original_name: str,
    index: int,
    total: int,
) -> str | None:
    normalized_title = (title or "").strip()
    if total <= 1:
        return normalized_title or None
    if normalized_title:
        return f"{normalized_title} {index + 1}"
    return original_name


@router.post("/uploads", response_model=SourceDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    knowledge_base_id: str | None = Form(default=None),
    refresh_policy: str | None = Form(default=None),
    source_status: str | None = Form(default=None),
    _guard: AuthPrincipal = UserDep,
):
    requested_source_status = _normalize_upload_source_status(source_status)
    base = _resolve_upload_base(
        session=session,
        principal=principal,
        knowledge_base_id=knowledge_base_id,
    )
    upload_dir = _upload_dir_for_base(settings, str(base.knowledge_base_id))
    original_name, target_path = await _persist_uploaded_file(
        file=file,
        upload_dir=upload_dir,
        max_size_bytes=int(settings.knowledge_max_upload_size_bytes),
    )

    service = KnowledgeSourceService(session, settings)
    try:
        upload_source = _ensure_upload_source(
            service=service,
            principal=principal,
            knowledge_base_id=str(base.knowledge_base_id),
            upload_dir=upload_dir,
            refresh_policy=refresh_policy,
            source_status=requested_source_status,
            auto_commit=False,
        )
        document = _register_uploaded_document(
            service=service,
            principal=principal,
            upload_source_id=str(upload_source.source_id),
            target_path=target_path,
            original_name=original_name,
            title=title,
            auto_commit=False,
        )
        session.commit()
    except Exception:
        session.rollback()
        target_path.unlink(missing_ok=True)
        raise
    session.refresh(document)
    return SourceDocumentResponse.model_validate(
        service.get_document_payload(str(document.document_id), principal)
    )


@router.post(
    "/uploads/ingest-batch",
    response_model=DocumentBatchMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_and_ingest_documents(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
    knowledge_base_id: str | None = Form(default=None),
    refresh_policy: str | None = Form(default=None),
    source_status: str | None = Form(default=None),
    execute_update_inline: bool | None = Form(default=None),
    reason: str | None = Form(default=None),
    _guard: AuthPrincipal = UserDep,
):
    if not files:
        raise ValidationError(
            "At least one file must be provided",
            error_code="UPLOAD_FILES_REQUIRED",
        )
    requested_source_status = _normalize_upload_source_status(source_status)
    if requested_source_status != SourceStatus.ACTIVE:
        raise ValidationError(
            "Upload source must be active to start document ingestion",
            error_code="UPLOAD_SOURCE_MUST_BE_ACTIVE",
        )
    base = _resolve_upload_base(
        session=session,
        principal=principal,
        knowledge_base_id=knowledge_base_id,
    )
    upload_dir = _upload_dir_for_base(settings, str(base.knowledge_base_id))
    persisted_files: list[tuple[str, Path]] = []
    try:
        for file in files:
            original_name, target_path = await _persist_uploaded_file(
                file=file,
                upload_dir=upload_dir,
                max_size_bytes=int(settings.knowledge_max_upload_size_bytes),
            )
            persisted_files.append((original_name, target_path))

        service = KnowledgeSourceService(session, settings)
        upload_source = _ensure_upload_source(
            service=service,
            principal=principal,
            knowledge_base_id=str(base.knowledge_base_id),
            upload_dir=upload_dir,
            refresh_policy=refresh_policy,
            source_status=requested_source_status,
            auto_commit=False,
        )
        documents = [
            _register_uploaded_document(
                service=service,
                principal=principal,
                upload_source_id=str(upload_source.source_id),
                target_path=target_path,
                original_name=original_name,
                title=_title_for_uploaded_file(
                    title=title,
                    original_name=original_name,
                    index=index,
                    total=len(persisted_files),
                ),
                auto_commit=False,
            )
            for index, (original_name, target_path) in enumerate(persisted_files)
        ]
        updater = KnowledgeUpdateService(session, settings)
        run = updater.start_run(
            InternalKnowledgeUpdateRunStartRequest(
                knowledge_base_id=str(base.knowledge_base_id),
                run_type=UpdateRunType.UPLOAD,
                source_scope=SourceScope.SELECTED,
                selected_source_ids=[str(upload_source.source_id)],
                document_ids=[str(document.document_id) for document in documents],
                force_reindex_all_in_scope=False,
                force_reindex_document_ids=[],
                auto_activate_if_validated=True,
                target_embedding_profile=None,
                reason=reason or f"batch_upload:{base.knowledge_base_id}",
                requested_by=principal_requested_by(principal),
                correlation_id=f"knowledge-upload-batch-{uuid4().hex[:12]}",
                idempotency_key=None,
                execute_inline=execute_update_inline,
            ),
            principal,
        )
    except Exception:
        session.rollback()
        for _, target_path in persisted_files:
            target_path.unlink(missing_ok=True)
        raise

    for document in documents:
        session.refresh(document)
    return DocumentBatchMutationResponse(
        documents=[
            SourceDocumentResponse.model_validate(
                service.get_document_payload(str(document.document_id), principal)
            )
            for document in documents
        ],
        update_run=KnowledgeUpdateRunResponse.model_validate(
            updater.get_run_response(_resolve_update_run_id(run), principal)
        ),
    )


@router.post(
    "/uploads/ingest",
    response_model=DocumentMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_and_ingest_document(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    knowledge_base_id: str | None = Form(default=None),
    refresh_policy: str | None = Form(default=None),
    source_status: str | None = Form(default=None),
    execute_update_inline: bool | None = Form(default=None),
    reason: str | None = Form(default=None),
    _guard: AuthPrincipal = UserDep,
):
    requested_source_status = _normalize_upload_source_status(source_status)
    if requested_source_status != SourceStatus.ACTIVE:
        raise ValidationError(
            "Upload source must be active to start document ingestion",
            error_code="UPLOAD_SOURCE_MUST_BE_ACTIVE",
        )
    base = _resolve_upload_base(
        session=session,
        principal=principal,
        knowledge_base_id=knowledge_base_id,
    )
    upload_dir = _upload_dir_for_base(settings, str(base.knowledge_base_id))
    original_name, target_path = await _persist_uploaded_file(
        file=file,
        upload_dir=upload_dir,
        max_size_bytes=int(settings.knowledge_max_upload_size_bytes),
    )

    service = KnowledgeSourceService(session, settings)
    try:
        upload_source = _ensure_upload_source(
            service=service,
            principal=principal,
            knowledge_base_id=str(base.knowledge_base_id),
            upload_dir=upload_dir,
            refresh_policy=refresh_policy,
            source_status=requested_source_status,
            auto_commit=False,
        )
        document = _register_uploaded_document(
            service=service,
            principal=principal,
            upload_source_id=str(upload_source.source_id),
            target_path=target_path,
            original_name=original_name,
            title=title,
            auto_commit=False,
        )
        updater = KnowledgeUpdateService(session, settings)
        run = updater.start_run(
            InternalKnowledgeUpdateRunStartRequest(
                knowledge_base_id=str(base.knowledge_base_id),
                run_type=UpdateRunType.UPLOAD,
                source_scope=SourceScope.SELECTED,
                selected_source_ids=[str(upload_source.source_id)],
                document_ids=[str(document.document_id)],
                force_reindex_all_in_scope=False,
                force_reindex_document_ids=[],
                auto_activate_if_validated=True,
                target_embedding_profile=None,
                reason=reason or f"upload_document:{document.document_id}",
                requested_by=principal_requested_by(principal),
                correlation_id=f"knowledge-upload-{uuid4().hex[:12]}",
                idempotency_key=None,
                execute_inline=execute_update_inline,
            ),
            principal,
        )
    except Exception:
        session.rollback()
        target_path.unlink(missing_ok=True)
        raise
    session.refresh(document)
    return DocumentMutationResponse(
        document=SourceDocumentResponse.model_validate(
            service.get_document_payload(str(document.document_id), principal)
        ),
        update_run=KnowledgeUpdateRunResponse.model_validate(
            updater.get_run_response(_resolve_update_run_id(run), principal)
        ),
    )


@router.get("/documents/{document_id}", response_model=SourceDocumentResponse)
def get_document(
    document_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return SourceDocumentResponse.model_validate(
        KnowledgeSourceService(session).get_document_payload(document_id, principal)
    )


@router.post(
    "/documents/{document_id}/reindex",
    response_model=KnowledgeUpdateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reindex_document(
    document_id: str,
    payload: KnowledgeReindexRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    source_service = KnowledgeSourceService(session, settings)
    document = source_service.get_document(document_id, principal)
    if document.status == SourceDocumentStatus.ARCHIVED or is_document_explicitly_excluded(
        document
    ):
        raise ValidationError(
            (
                "Archived or excluded documents cannot be reindexed directly; "
                "restore or register the document again first"
            ),
            error_code="DOCUMENT_NOT_REINDEXABLE",
            details={
                "document_id": document_id,
                "status": getattr(document.status, "value", document.status),
            },
        )
    source = source_service.get_source(str(document.source_id), principal)
    run = KnowledgeUpdateService(session, settings).start_manual_run(
        knowledge_base_id=str(source.knowledge_base_id),
        source_scope=SourceScope.SELECTED,
        selected_source_ids=[str(document.source_id)],
        document_ids=[str(document.document_id)],
        force_reindex_document_ids=[str(document.document_id)],
        correlation_id=f"knowledge-document-reindex-{uuid4().hex[:12]}",
        reason=payload.reason or f"document_reindex:{document_id}",
        requested_by=principal_requested_by(principal),
        execute_inline=payload.execute_inline,
        run_type=UpdateRunType.REBUILD,
        principal=principal,
    )
    return KnowledgeUpdateRunResponse.model_validate(
        KnowledgeUpdateService(session, settings).get_run_response(
            _resolve_update_run_id(run),
            principal,
        )
    )


@router.get("/documents/{document_id}/snapshot", response_model=DocumentSnapshotResponse)
def get_document_snapshot(
    document_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    knowledge_version_id: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeSourceService(session).get_document_snapshot_payload(
        document_id,
        knowledge_version_id=knowledge_version_id,
        principal=principal,
    )
    return DocumentSnapshotResponse.model_validate(payload)


@router.get("/documents/{document_id}/chunks", response_model=list[DocumentChunkResponse])
def list_document_chunks(
    document_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    knowledge_version_id: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeSourceService(session).list_document_chunk_payloads(
        document_id,
        knowledge_version_id=knowledge_version_id,
        principal=principal,
    )
    return [DocumentChunkResponse.model_validate(item) for item in payload]


@router.get("/documents/{document_id}/memory", response_model=DocumentMemoryResponse)
def get_document_memory(
    document_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    knowledge_version_id: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeSourceService(session).get_document_memory_payload(
        document_id,
        knowledge_version_id=knowledge_version_id,
        principal=principal,
    )
    return DocumentMemoryResponse.model_validate(payload)


@router.get(
    "/documents/{document_id}/extracted-items",
    response_model=DocumentExtractedItemsResponse,
)
def list_document_extracted_items(
    document_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    knowledge_version_id: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeSourceService(session).list_document_extracted_item_payloads(
        document_id,
        knowledge_version_id=knowledge_version_id,
        principal=principal,
    )
    return DocumentExtractedItemsResponse.model_validate(payload)


@router.patch("/documents/{document_id}", response_model=SourceDocumentResponse)
def update_document(
    document_id: str,
    payload: SourceDocumentUpdateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    document = service.update_document(document_id, payload, principal)
    return SourceDocumentResponse.model_validate(
        service.get_document_payload(str(document.document_id), principal)
    )


@router.post("/documents/{document_id}/disable", response_model=SourceDocumentResponse)
def disable_document(
    document_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    document = service.disable_document(document_id, principal, settings=settings)
    return SourceDocumentResponse.model_validate(
        service.get_document_payload(str(document.document_id), principal)
    )


@router.post(
    "/documents/{document_id}/remove",
    response_model=DocumentMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def remove_document(
    document_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    payload: KnowledgeReindexRequest | None = Body(default=None),
    execute_inline: bool | None = Query(default=None),
    execute_update_inline: bool | None = Query(default=None, alias="execute_update_inline"),
    reason: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    resolved_payload = _resolve_reindex_request(
        payload,
        execute_inline=execute_inline,
        legacy_execute_inline=execute_update_inline,
        reason=reason,
    )
    service = KnowledgeSourceService(session, settings)
    document, run = service.remove_document_and_start_update(
        document_id,
        principal,
        settings=settings,
        reason=resolved_payload.reason,
        execute_inline=resolved_payload.execute_inline,
    )
    updater = KnowledgeUpdateService(session, settings)
    return DocumentMutationResponse(
        document=SourceDocumentResponse.model_validate(
            service.get_document_payload(str(document.document_id), principal)
        ),
        update_run=KnowledgeUpdateRunResponse.model_validate(
            updater.get_run_response(_resolve_update_run_id(run), principal)
        ),
    )
