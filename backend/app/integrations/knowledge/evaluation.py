from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log2
from pathlib import Path
from typing import Any

from app.integrations.generation.llm_gateway import RetrievedFragment


@dataclass(slots=True)
class RetrievalEvalCase:
    case_id: str
    query_text: str
    use_case: str = "generation"
    section_code: str | None = None
    expected_fragment_ids: list[str] | None = None
    expected_document_ids: list[str] | None = None
    relevance_by_fragment_id: dict[str, float] | None = None
    relevance_by_document_id: dict[str, float] | None = None
    top_k: int = 10

    def normalized_expected_targets(self) -> dict[str, float]:
        targets: dict[str, float] = {}
        for fragment_id in self.expected_fragment_ids or []:
            targets[f"fragment:{fragment_id}"] = max(
                float(targets.get(f"fragment:{fragment_id}") or 0.0), 1.0
            )
        for document_id in self.expected_document_ids or []:
            targets[f"document:{document_id}"] = max(
                float(targets.get(f"document:{document_id}") or 0.0), 1.0
            )
        for fragment_id, relevance in (self.relevance_by_fragment_id or {}).items():
            targets[f"fragment:{fragment_id}"] = max(
                float(targets.get(f"fragment:{fragment_id}") or 0.0), float(relevance)
            )
        for document_id, relevance in (self.relevance_by_document_id or {}).items():
            targets[f"document:{document_id}"] = max(
                float(targets.get(f"document:{document_id}") or 0.0), float(relevance)
            )
        return targets


@dataclass(slots=True)
class RetrievalEvalCaseResult:
    case_id: str
    query_text: str
    use_case: str
    section_code: str | None
    top_k: int
    expected_target_count: int
    predicted_fragment_ids: list[str]
    predicted_document_ids: list[str]
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float
    hit_at_10: float
    hit_after_rerank: float
    first_relevant_rank: int | None
    matched_targets: list[str]
    diagnostics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query_text": self.query_text,
            "use_case": self.use_case,
            "section_code": self.section_code,
            "top_k": self.top_k,
            "expected_target_count": self.expected_target_count,
            "predicted_fragment_ids": self.predicted_fragment_ids,
            "predicted_document_ids": self.predicted_document_ids,
            "recall_at_5": self.recall_at_5,
            "recall_at_10": self.recall_at_10,
            "mrr_at_10": self.mrr_at_10,
            "ndcg_at_10": self.ndcg_at_10,
            "hit_at_10": self.hit_at_10,
            "hit_after_rerank": self.hit_after_rerank,
            "first_relevant_rank": self.first_relevant_rank,
            "matched_targets": self.matched_targets,
            "diagnostics": self.diagnostics,
        }


@dataclass(slots=True)
class RetrievalEvalRunResult:
    dataset_name: str | None
    knowledge_version_id: str
    case_count: int
    metrics: dict[str, float]
    cases: list[RetrievalEvalCaseResult]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "knowledge_version_id": self.knowledge_version_id,
            "case_count": self.case_count,
            "metrics": self.metrics,
            "cases": [item.as_dict() for item in self.cases],
        }


def load_retrieval_eval_cases(
    payload: Mapping[str, Any] | str | Path,
) -> tuple[str | None, str | None, list[RetrievalEvalCase]]:
    if isinstance(payload, Path):
        raw = json.loads(payload.read_text(encoding="utf-8"))
    elif isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith(("{", "[")):
            raw = json.loads(stripped)
        else:
            raw = json.loads(Path(payload).read_text(encoding="utf-8"))
    else:
        raw = dict(payload)
    dataset_name = raw.get("dataset_name")
    knowledge_version_id = raw.get("knowledge_version_id")
    cases = [parse_eval_case(item) for item in list(raw.get("cases") or [])]
    return dataset_name, knowledge_version_id, cases


def parse_eval_case(payload: Mapping[str, Any]) -> RetrievalEvalCase:
    case = RetrievalEvalCase(
        case_id=str(
            payload.get("case_id") or payload.get("id") or payload.get("query_text") or "case"
        ),
        query_text=str(payload.get("query_text") or "").strip(),
        use_case=str(payload.get("use_case") or "generation").strip() or "generation",
        section_code=(
            str(payload.get("section_code")).strip() if payload.get("section_code") else None
        ),
        expected_fragment_ids=[
            str(item)
            for item in list(payload.get("expected_fragment_ids") or [])
            if str(item).strip()
        ],
        expected_document_ids=[
            str(item)
            for item in list(payload.get("expected_document_ids") or [])
            if str(item).strip()
        ],
        relevance_by_fragment_id={
            str(k): float(v) for k, v in dict(payload.get("relevance_by_fragment_id") or {}).items()
        },
        relevance_by_document_id={
            str(k): float(v) for k, v in dict(payload.get("relevance_by_document_id") or {}).items()
        },
        top_k=max(1, int(payload.get("top_k") or 10)),
    )
    if not case.query_text:
        raise ValueError("query_text is required for retrieval evaluation case")
    if not case.normalized_expected_targets():
        raise ValueError(
            "retrieval evaluation case must include expected fragment/document ids or relevance maps"
        )
    return case


def evaluate_retrieval_case(
    case: RetrievalEvalCase,
    fragments: Sequence[RetrievedFragment],
    diagnostics: Mapping[str, Any] | None = None,
) -> RetrievalEvalCaseResult:
    targets = case.normalized_expected_targets()
    top_k = max(1, int(case.top_k or 10))
    predicted = list(fragments[:top_k])
    predicted_fragment_ids = [str(item.fragment_id) for item in predicted]
    predicted_document_ids = [str(item.document_id) for item in predicted]
    relevance_vector = [_match_relevance(fragment=item, targets=targets) for item in predicted[:10]]
    matched_targets = sorted(
        {
            target
            for fragment in predicted[:10]
            for target in _matched_targets(fragment=fragment, targets=targets)
        }
    )
    first_relevant_rank = None
    for index, score in enumerate(relevance_vector, start=1):
        if score > 0:
            first_relevant_rank = index
            break
    return RetrievalEvalCaseResult(
        case_id=case.case_id,
        query_text=case.query_text,
        use_case=case.use_case,
        section_code=case.section_code,
        top_k=top_k,
        expected_target_count=len(targets),
        predicted_fragment_ids=predicted_fragment_ids,
        predicted_document_ids=predicted_document_ids,
        recall_at_5=round(_recall_at_k(targets, predicted[:5]), 6),
        recall_at_10=round(_recall_at_k(targets, predicted[:10]), 6),
        mrr_at_10=round((1.0 / first_relevant_rank) if first_relevant_rank else 0.0, 6),
        ndcg_at_10=round(_ndcg_at_k(relevance_vector, 10), 6),
        hit_at_10=1.0 if first_relevant_rank is not None and first_relevant_rank <= 10 else 0.0,
        hit_after_rerank=1.0 if first_relevant_rank is not None else 0.0,
        first_relevant_rank=first_relevant_rank,
        matched_targets=matched_targets,
        diagnostics=dict(diagnostics or {}),
    )


def aggregate_retrieval_eval(
    case_results: Sequence[RetrievalEvalCaseResult],
    *,
    dataset_name: str | None,
    knowledge_version_id: str,
) -> RetrievalEvalRunResult:
    results = list(case_results)
    count = max(len(results), 1)
    metrics = {
        "Recall@5": round(sum(item.recall_at_5 for item in results) / count, 6),
        "Recall@10": round(sum(item.recall_at_10 for item in results) / count, 6),
        "MRR@10": round(sum(item.mrr_at_10 for item in results) / count, 6),
        "nDCG@10": round(sum(item.ndcg_at_10 for item in results) / count, 6),
        "HitRate@10": round(sum(item.hit_at_10 for item in results) / count, 6),
        "HitAfterRerank": round(sum(item.hit_after_rerank for item in results) / count, 6),
    }
    return RetrievalEvalRunResult(
        dataset_name=dataset_name,
        knowledge_version_id=knowledge_version_id,
        case_count=len(results),
        metrics=metrics,
        cases=results,
    )


def _matched_targets(*, fragment: RetrievedFragment, targets: Mapping[str, float]) -> list[str]:
    matched: list[str] = []
    fragment_key = f"fragment:{fragment.fragment_id}"
    document_key = f"document:{fragment.document_id}"
    if fragment_key in targets and float(targets[fragment_key]) > 0:
        matched.append(fragment_key)
    if document_key in targets and float(targets[document_key]) > 0:
        matched.append(document_key)
    return matched


def _match_relevance(*, fragment: RetrievedFragment, targets: Mapping[str, float]) -> float:
    matched = _matched_targets(fragment=fragment, targets=targets)
    if not matched:
        return 0.0
    return max(float(targets[item]) for item in matched)


def _recall_at_k(targets: Mapping[str, float], fragments: Sequence[RetrievedFragment]) -> float:
    if not targets:
        return 0.0
    matched = {
        target
        for fragment in fragments
        for target in _matched_targets(fragment=fragment, targets=targets)
    }
    return len(matched) / max(len(targets), 1)


def _dcg(scores: Sequence[float]) -> float:
    total = 0.0
    for index, score in enumerate(scores, start=1):
        if score <= 0:
            continue
        total += (2 ** float(score) - 1) / log2(index + 1)
    return total


def _ndcg_at_k(scores: Sequence[float], k: int) -> float:
    observed = list(scores[:k])
    if not observed:
        return 0.0
    ideal = sorted(observed, reverse=True)
    ideal_dcg = _dcg(ideal)
    if ideal_dcg <= 0:
        return 0.0
    return _dcg(observed) / ideal_dcg
