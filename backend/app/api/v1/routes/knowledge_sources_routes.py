from __future__ import annotations

from .knowledge_routes_common import (
    APIRouter,
    AuthPrincipal,
    KnowledgeSourceService,
    PrincipalDep,
    Query,
    SessionDep,
    SettingsDep,
    SourceCreateRequest,
    SourceDocumentCreateRequest,
    SourceDocumentResponse,
    SourceResponse,
    SourceUpdateRequest,
    UserDep,
    status,
)

router = APIRouter()


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    knowledge_base_id: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    payload = service.list_source_payloads(
        knowledge_base_id=knowledge_base_id,
        principal=principal,
    )
    return [SourceResponse.model_validate(item) for item in payload]


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: SourceCreateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    source = service.create_source(payload, principal)
    return SourceResponse.model_validate(
        service.get_source_payload(str(source.source_id), principal)
    )


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return SourceResponse.model_validate(
        KnowledgeSourceService(session, settings).get_source_payload(source_id, principal)
    )


@router.patch("/sources/{source_id}", response_model=SourceResponse)
def update_source(
    source_id: str,
    payload: SourceUpdateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    source = service.update_source(source_id, payload, principal, settings=settings)
    return SourceResponse.model_validate(
        service.get_source_payload(str(source.source_id), principal)
    )


@router.post("/sources/{source_id}/archive", response_model=SourceResponse)
def archive_source(
    source_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    source = service.archive_source(source_id, principal, settings=settings)
    return SourceResponse.model_validate(
        service.get_source_payload(str(source.source_id), principal)
    )


@router.post("/sources/{source_id}/disable", response_model=SourceResponse)
def disable_source(
    source_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    source = service.disable_source(source_id, principal, settings=settings)
    return SourceResponse.model_validate(
        service.get_source_payload(str(source.source_id), principal)
    )


@router.get("/sources/{source_id}/documents", response_model=list[SourceDocumentResponse])
def list_source_documents(
    source_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    documents = KnowledgeSourceService(session, settings).list_document_payloads(
        source_id,
        principal,
    )
    return [SourceDocumentResponse.model_validate(item) for item in documents]


@router.post(
    "/sources/{source_id}/documents",
    response_model=SourceDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_source_document(
    source_id: str,
    payload: SourceDocumentCreateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeSourceService(session, settings)
    document = service.register_document(source_id, payload, principal)
    return SourceDocumentResponse.model_validate(
        service.get_document_payload(str(document.document_id), principal)
    )
