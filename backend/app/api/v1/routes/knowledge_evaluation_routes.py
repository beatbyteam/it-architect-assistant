from __future__ import annotations

from .knowledge_routes_common import (
    APIRouter,
    AuthPrincipal,
    KnowledgeQueryService,
    RetrievalEvaluationRequest,
    RetrievalEvaluationResponse,
    SessionDep,
    SettingsDep,
    UserDep,
    aggregate_retrieval_eval,
    evaluate_retrieval_case,
    parse_eval_case,
)

router = APIRouter()


@router.post("/evaluation/retrieval", response_model=RetrievalEvaluationResponse)
def run_retrieval_evaluation(
    payload: RetrievalEvaluationRequest,
    session: SessionDep,
    settings: SettingsDep,
    _principal: AuthPrincipal = UserDep,
):
    service = KnowledgeQueryService(session, settings)
    case_results = []
    for case_payload in payload.cases:
        case = parse_eval_case(case_payload.model_dump())
        result = service.search_text(
            query_text=case.query_text,
            knowledge_version_id=str(payload.knowledge_version_id),
            limit=max(int(case.top_k or 10), 10),
            use_case=case.use_case,
            section_code=case.section_code,
            principal=_principal,
        )
        case_results.append(
            evaluate_retrieval_case(
                case,
                result.fragments,
                diagnostics=result.diagnostics,
            )
        )
    aggregated = aggregate_retrieval_eval(
        case_results,
        dataset_name=payload.dataset_name,
        knowledge_version_id=str(payload.knowledge_version_id),
    )
    return RetrievalEvaluationResponse.model_validate(aggregated.as_dict())
