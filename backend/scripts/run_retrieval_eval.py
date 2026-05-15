from __future__ import annotations

import argparse
import json

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.integrations.knowledge.evaluation import (
    aggregate_retrieval_eval,
    evaluate_retrieval_case,
    load_retrieval_eval_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run retrieval evaluation against a knowledge version"
    )
    parser.add_argument("--dataset", required=True, help="Path to retrieval eval JSON dataset")
    parser.add_argument(
        "--knowledge-version-id", default=None, help="Override dataset knowledge_version_id"
    )
    args = parser.parse_args()

    dataset_name, dataset_version_id, cases = load_retrieval_eval_cases(args.dataset)
    knowledge_version_id = args.knowledge_version_id or dataset_version_id
    if not knowledge_version_id:
        raise SystemExit(
            "knowledge_version_id must be provided either in dataset or via --knowledge-version-id"
        )

    session = SessionLocal()
    try:
        settings = get_settings()
        service = KnowledgeQueryService(session, settings)
        results = []
        for case in cases:
            result = service.search_text(
                query_text=case.query_text,
                knowledge_version_id=knowledge_version_id,
                limit=max(int(case.top_k or 10), 10),
                use_case=case.use_case,
                section_code=case.section_code,
            )
            results.append(
                evaluate_retrieval_case(case, result.fragments, diagnostics=result.diagnostics)
            )
        aggregated = aggregate_retrieval_eval(
            results, dataset_name=dataset_name, knowledge_version_id=str(knowledge_version_id)
        )
        print(json.dumps(aggregated.as_dict(), ensure_ascii=False, indent=2, default=str))
    finally:
        session.close()


if __name__ == "__main__":
    main()
