from __future__ import annotations

from .knowledge_routes_common import (
    APIRouter,
    AuthPrincipal,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseDocumentResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseSelectRequest,
    KnowledgeBaseService,
    KnowledgeBaseUpdateRequest,
    KnowledgeBundleImportRequest,
    KnowledgeBundleImportResponse,
    KnowledgeEmbeddingProfileSwitchRequest,
    KnowledgeReindexRequest,
    KnowledgeSourceService,
    KnowledgeUpdateRunResponse,
    KnowledgeUpdateService,
    PrincipalDep,
    Query,
    SessionDep,
    SettingsDep,
    SourceScope,
    UpdateRunType,
    UserDep,
    import_knowledge_bundle,
    principal_requested_by,
    status,
    uuid4,
)

router = APIRouter()


@router.get("/bases", response_model=list[KnowledgeBaseResponse])
def list_knowledge_bases(
    session: SessionDep,
    principal: PrincipalDep,
    include_archived: bool = Query(default=False),
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeBaseService(session)
    return [
        KnowledgeBaseResponse.model_validate(item)
        for item in service.list_payloads(principal, include_archived=include_archived)
    ]


@router.post(
    "/bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeBaseService(session)
    base = service.create_user_base(
        name=payload.name,
        description=payload.description,
        principal=principal,
    )
    return KnowledgeBaseResponse.model_validate(service.build_base_payload(base, principal))


@router.get("/bases/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    knowledge_base_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    include_archived: bool = Query(default=False),
    _guard: AuthPrincipal = UserDep,
):
    return KnowledgeBaseResponse.model_validate(
        KnowledgeBaseService(session).get_base_payload(
            knowledge_base_id,
            principal,
            include_archived=include_archived,
        )
    )


@router.patch("/bases/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdateRequest,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeBaseService(session)
    base = service.update_user_base(
        knowledge_base_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        principal=principal,
    )
    return KnowledgeBaseResponse.model_validate(service.build_base_payload(base, principal))


@router.post("/bases/{knowledge_base_id}/archive", response_model=KnowledgeBaseResponse)
def archive_knowledge_base(
    knowledge_base_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeBaseService(session)
    base = service.archive_user_base(knowledge_base_id, principal)
    return KnowledgeBaseResponse.model_validate(
        service.get_base_payload(
            str(base.knowledge_base_id),
            principal,
            include_archived=True,
        )
    )


@router.post("/bases/{knowledge_base_id}/restore", response_model=KnowledgeBaseResponse)
def restore_knowledge_base(
    knowledge_base_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeBaseService(session)
    base = service.restore_user_base(knowledge_base_id, principal)
    return KnowledgeBaseResponse.model_validate(
        service.get_base_payload(str(base.knowledge_base_id), principal)
    )


@router.get(
    "/bases/{knowledge_base_id}/documents",
    response_model=list[KnowledgeBaseDocumentResponse],
)
def list_base_documents(
    knowledge_base_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    knowledge_version_id: str | None = Query(default=None),
    include_deleted: bool = Query(default=True),
    include_archived_base: bool = Query(default=False),
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeSourceService(session).list_base_document_payloads(
        knowledge_base_id,
        knowledge_version_id=knowledge_version_id,
        include_deleted=include_deleted,
        include_archived_base=include_archived_base,
        principal=principal,
    )
    return [KnowledgeBaseDocumentResponse.model_validate(item) for item in payload]


@router.get(
    "/bases/{knowledge_base_id}/update-runs",
    response_model=list[KnowledgeUpdateRunResponse],
)
def list_base_update_runs(
    knowledge_base_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    limit: int = Query(default=20, ge=1, le=100),
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeUpdateService(session, settings)
    payload = service.list_run_responses(
        limit=limit,
        knowledge_base_id=knowledge_base_id,
        principal=principal,
    )
    return [KnowledgeUpdateRunResponse.model_validate(item) for item in payload]


@router.post(
    "/bases/{knowledge_base_id}/sync",
    response_model=KnowledgeUpdateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_base_sync(
    knowledge_base_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    execute_inline: bool | None = Query(default=None),
    reason: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeUpdateService(session, settings)
    run = service.start_manual_run(
        knowledge_base_id=knowledge_base_id,
        source_scope=SourceScope.ALL,
        selected_source_ids=[],
        correlation_id=f"knowledge-manual-sync-{uuid4().hex[:12]}",
        reason=reason or "manual_sync",
        requested_by=principal_requested_by(principal),
        execute_inline=execute_inline,
        run_type=UpdateRunType.MANUAL,
        principal=principal,
    )
    return KnowledgeUpdateRunResponse.model_validate(
        service.get_run_response(str(run.update_run_id), principal)
    )


@router.post(
    "/bases/{knowledge_base_id}/reindex",
    response_model=KnowledgeUpdateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reindex_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeReindexRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeUpdateService(session, settings)
    run = service.start_manual_run(
        knowledge_base_id=knowledge_base_id,
        source_scope=SourceScope.ALL,
        correlation_id=f"knowledge-base-reindex-{uuid4().hex[:12]}",
        reason=payload.reason or "knowledge_base_reindex",
        requested_by=principal_requested_by(principal),
        execute_inline=payload.execute_inline,
        run_type=UpdateRunType.REBUILD,
        force_reindex_all_in_scope=True,
        principal=principal,
    )
    return KnowledgeUpdateRunResponse.model_validate(
        service.get_run_response(str(run.update_run_id), principal)
    )


@router.post(
    "/bases/{knowledge_base_id}/embedding-profile",
    response_model=KnowledgeUpdateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def switch_knowledge_base_embedding_profile(
    knowledge_base_id: str,
    payload: KnowledgeEmbeddingProfileSwitchRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeUpdateService(session, settings)
    run = service.start_manual_run(
        knowledge_base_id=knowledge_base_id,
        source_scope=SourceScope.ALL,
        correlation_id=f"knowledge-embedding-switch-{uuid4().hex[:12]}",
        reason=(payload.reason or f"embedding_profile_switch:{payload.target_embedding_profile}"),
        requested_by=principal_requested_by(principal),
        execute_inline=payload.execute_inline,
        run_type=UpdateRunType.REBUILD,
        force_reindex_all_in_scope=True,
        target_embedding_profile=payload.target_embedding_profile,
        principal=principal,
    )
    return KnowledgeUpdateRunResponse.model_validate(
        service.get_run_response(str(run.update_run_id), principal)
    )


@router.post("/bases/{knowledge_base_id}/select", response_model=KnowledgeBaseResponse)
def select_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseSelectRequest,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    KnowledgeBaseService(session).select_user_base(
        knowledge_base_id,
        principal,
        knowledge_version_id=(
            str(payload.knowledge_version_id) if payload.knowledge_version_id else None
        ),
    )
    return KnowledgeBaseResponse.model_validate(
        KnowledgeBaseService(session).get_base_payload(knowledge_base_id, principal)
    )


@router.post(
    "/bundles/import",
    response_model=KnowledgeBundleImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_bundle(
    payload: KnowledgeBundleImportRequest,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    result = import_knowledge_bundle(
        session,
        manifest_uri=payload.manifest_uri,
        knowledge_base_id=str(payload.knowledge_base_id) if payload.knowledge_base_id else None,
        principal=principal,
        start_update=True,
        activate_if_validated=payload.activate_if_validated,
        execute_update_inline=bool(payload.execute_update_inline),
        reason=payload.reason,
        requested_by=principal_requested_by(principal),
    )
    return KnowledgeBundleImportResponse.model_validate(result.as_dict())
