from __future__ import annotations

from .knowledge_routes_common import (
    APIRouter,
    AuthPrincipal,
    KnowledgeVersionActivateRequest,
    KnowledgeVersionResponse,
    KnowledgeVersionService,
    PrincipalDep,
    Query,
    SessionDep,
    UserDep,
    ValidationError,
)

router = APIRouter()


@router.get("/versions", response_model=list[KnowledgeVersionResponse])
def list_versions(
    session: SessionDep,
    principal: PrincipalDep,
    knowledge_base_id: str | None = Query(default=None),
    _guard: AuthPrincipal = UserDep,
):
    versions = KnowledgeVersionService(session).list_version_payloads(
        knowledge_base_id=knowledge_base_id,
        principal=principal,
    )
    return [KnowledgeVersionResponse.model_validate(item) for item in versions]


@router.get("/versions/{knowledge_version_id}", response_model=KnowledgeVersionResponse)
def get_version(
    knowledge_version_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return KnowledgeVersionResponse.model_validate(
        KnowledgeVersionService(session).get_version_payload(
            knowledge_version_id,
            principal,
        )
    )


@router.post("/versions/{knowledge_version_id}/activate", response_model=KnowledgeVersionResponse)
def activate_version(
    knowledge_version_id: str,
    payload: KnowledgeVersionActivateRequest,
    session: SessionDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    version = KnowledgeVersionService(session).activate(
        knowledge_version_id,
        principal,
        reason=payload.reason,
    )
    return KnowledgeVersionResponse.model_validate(
        KnowledgeVersionService(session).get_version_payload(
            str(version.knowledge_version_id),
            principal,
        )
    )


@router.delete("/versions/{knowledge_version_id}", include_in_schema=False)
def delete_version_not_supported(knowledge_version_id: str, _principal: AuthPrincipal = UserDep):
    _ = knowledge_version_id
    raise ValidationError(
        (
            "Physical deletion of knowledge versions is not supported in MVP; "
            "create and activate a new version instead"
        ),
        error_code="KNOWLEDGE_VERSION_DELETE_UNSUPPORTED",
    )
