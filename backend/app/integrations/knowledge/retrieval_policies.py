from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.db.enums import FragmentType

TOKEN_RE = re.compile(r"[\w\-/\.]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    policy_id: str
    retrieve_limit: int
    rerank_limit: int
    vector_weight: float
    lexical_weight: float
    metadata_weight: float
    keyword_weight: float
    vector_candidate_limit: int
    keyword_candidate_limit: int
    fused_candidate_limit: int
    fusion_rrf_k: int = 60
    fragment_weights: dict[str, float] = field(default_factory=dict)
    document_type_weights: dict[str, float] = field(default_factory=dict)
    title_boost: float = 0.15


GENERATION_POLICY_V1 = RetrievalPolicy(
    policy_id="generation_retrieval_policy_togaf_archimate_v1",
    retrieve_limit=24,
    rerank_limit=12,
    vector_weight=0.34,
    lexical_weight=0.3,
    metadata_weight=0.16,
    keyword_weight=0.2,
    vector_candidate_limit=36,
    keyword_candidate_limit=36,
    fused_candidate_limit=24,
    fusion_rrf_k=60,
    fragment_weights={
        FragmentType.REQUIREMENT.value: 1.15,
        FragmentType.COMPONENT.value: 1.1,
        FragmentType.INTEGRATION.value: 1.08,
        FragmentType.API.value: 1.04,
        FragmentType.RULE.value: 0.95,
    },
    document_type_weights={
        "architecture": 1.1,
        "api": 1.05,
        "normative": 0.98,
        "technology": 1.0,
    },
)

VERIFICATION_POLICY_V1 = RetrievalPolicy(
    policy_id="verification_retrieval_policy_togaf_archimate_v1",
    retrieve_limit=28,
    rerank_limit=12,
    vector_weight=0.26,
    lexical_weight=0.28,
    metadata_weight=0.2,
    keyword_weight=0.26,
    vector_candidate_limit=40,
    keyword_candidate_limit=40,
    fused_candidate_limit=28,
    fusion_rrf_k=60,
    fragment_weights={
        FragmentType.RULE.value: 1.2,
        FragmentType.REQUIREMENT.value: 1.12,
        FragmentType.API.value: 1.08,
        FragmentType.INTEGRATION.value: 1.05,
        FragmentType.COMPONENT.value: 1.0,
    },
    document_type_weights={
        "normative": 1.18,
        "api": 1.1,
        "architecture": 1.02,
        "technology": 1.0,
    },
    title_boost=0.1,
)


@dataclass(slots=True)
class RetrievalCandidate:
    fragment_id: str
    document_id: str
    title: str | None
    content: str
    fragment_type: str | None = None
    source_location: str | None = None
    initial_vector_score: float = 0.0
    lexical_score: float = 0.0
    keyword_score: float = 0.0
    fusion_score: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalScoredCandidate:
    candidate: RetrievalCandidate
    score: float
    lexical_score: float
    vector_score: float
    metadata_score: float
    keyword_score: float


@dataclass(frozen=True, slots=True)
class LexicalMatchDiagnostics:
    backend: str
    document_count: int
    avg_document_length: float


class RetrievalPolicyRegistry:
    _defaults = {
        "generation": GENERATION_POLICY_V1,
        "verification": VERIFICATION_POLICY_V1,
        GENERATION_POLICY_V1.policy_id: GENERATION_POLICY_V1,
        VERIFICATION_POLICY_V1.policy_id: VERIFICATION_POLICY_V1,
        "generation_retrieval_policy_togaf_archimate_v2_hybrid_rrf": GENERATION_POLICY_V1,
        "verification_retrieval_policy_togaf_archimate_v2_hybrid_rrf": VERIFICATION_POLICY_V1,
    }

    @classmethod
    def get(cls, use_case: str) -> RetrievalPolicy:
        return cls._defaults.get(use_case, GENERATION_POLICY_V1)


class RetrievalReranker:
    provider_name = "heuristic"

    def rerank(
        self,
        *,
        candidates: list[RetrievalCandidate],
        query_text: str,
        policy: RetrievalPolicy,
    ) -> list[RetrievalScoredCandidate]:
        query_tokens = _tokenize(query_text)
        scored: list[RetrievalScoredCandidate] = []
        for candidate in candidates:
            lexical_overlap = _lexical_overlap(query_tokens, candidate.content, candidate.title)
            lexical = max(candidate.lexical_score, lexical_overlap)
            vector = max(0.0, candidate.initial_vector_score)
            keyword = max(candidate.keyword_score, lexical_overlap)
            metadata = _metadata_score(candidate.metadata, candidate.fragment_type, policy)
            title_match = _title_match_bonus(query_tokens, candidate.title) * policy.title_boost
            fusion_bonus = max(0.0, candidate.fusion_score)
            total = (
                (vector * policy.vector_weight)
                + (lexical * policy.lexical_weight)
                + (metadata * policy.metadata_weight)
                + (keyword * policy.keyword_weight)
                + title_match
                + (fusion_bonus * 0.12)
            )
            scored.append(
                RetrievalScoredCandidate(
                    candidate=candidate,
                    score=round(total, 8),
                    lexical_score=round(lexical, 8),
                    vector_score=round(vector, 8),
                    metadata_score=round(metadata + title_match, 8),
                    keyword_score=round(keyword, 8),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: policy.rerank_limit]


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_list = list(left)
    right_list = list(right)
    if not left_list or not right_list:
        return 0.0
    if len(left_list) != len(right_list):
        return 0.0
    numerator = sum(a * b for a, b in zip(left_list, right_list, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left_list))
    right_norm = math.sqrt(sum(value * value for value in right_list))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def keyword_overlap_score(query_text: str, content: str, title: str | None = None) -> float:
    return _lexical_overlap(_tokenize(query_text), content, title)


def lexical_rank_candidates(
    *,
    query_text: str,
    candidates: Sequence[RetrievalCandidate],
) -> tuple[list[RetrievalCandidate], LexicalMatchDiagnostics]:
    query_terms = [token for token in _ordered_tokens(query_text) if len(token) > 1]
    tokenized_docs = [
        _ordered_tokens(
            " ".join(part for part in (candidate.title or "", candidate.content) if part)
        )
        for candidate in candidates
    ]
    document_count = len(tokenized_docs)
    if document_count == 0:
        return [], LexicalMatchDiagnostics(
            backend="bm25_python", document_count=0, avg_document_length=0.0
        )
    lengths = [len(tokens) for tokens in tokenized_docs]
    avg_doc_length = sum(lengths) / max(document_count, 1)
    document_frequencies: Counter[str] = Counter()
    term_frequencies: list[Counter[str]] = []
    for tokens in tokenized_docs:
        tf = Counter(tokens)
        term_frequencies.append(tf)
        document_frequencies.update(set(tokens))

    k1 = 1.5
    b = 0.75
    scored: list[tuple[float, RetrievalCandidate]] = []
    for candidate, tf, doc_len in zip(candidates, term_frequencies, lengths, strict=False):
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if freq <= 0:
                continue
            df = document_frequencies.get(term, 0)
            idf = math.log(1 + ((document_count - df + 0.5) / (df + 0.5))) if df else 0.0
            numerator = freq * (k1 + 1.0)
            denominator = freq + k1 * (1.0 - b + b * (doc_len / max(avg_doc_length, 1.0)))
            score += idf * (numerator / max(denominator, 1e-9))
        boosted_score = score + (
            keyword_overlap_score(query_text, candidate.content, candidate.title) * 0.25
        )
        candidate.lexical_score = round(boosted_score, 8)
        scored.append((boosted_score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [item[1] for item in scored]
    return ranked, LexicalMatchDiagnostics(
        backend="bm25_python",
        document_count=document_count,
        avg_document_length=round(avg_doc_length, 2),
    )


def reciprocal_rank_fuse(
    *,
    rankings: Sequence[Sequence[RetrievalCandidate]],
    k: int = 60,
) -> dict[str, float]:
    fused: defaultdict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, candidate in enumerate(ranking, start=1):
            fused[candidate.fragment_id] += 1.0 / (k + rank)
    return dict(fused)


def _metadata_score(
    metadata: dict[str, object], fragment_type: str | None, policy: RetrievalPolicy
) -> float:
    score = policy.fragment_weights.get(fragment_type or "", 1.0)
    document_type = str(metadata.get("document_type") or "")
    score *= policy.document_type_weights.get(document_type, 1.0)
    source_weight = metadata.get("source_weight")
    if isinstance(source_weight, int | float):
        score *= float(source_weight)
    if metadata.get("normative_flag") and policy is VERIFICATION_POLICY_V1:
        score *= 1.04
    if metadata.get("api_flag") and policy is GENERATION_POLICY_V1:
        score *= 1.02
    if metadata.get("required_flag"):
        score *= 1.02
    return score


def _ordered_tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1]


def _tokenize(text: str) -> set[str]:
    return set(_ordered_tokens(text))


def _lexical_overlap(query_tokens: set[str], content: str, title: str | None = None) -> float:
    if not query_tokens:
        return 0.0
    candidate_tokens = _tokenize(content)
    if title:
        candidate_tokens |= _tokenize(title)
    if not candidate_tokens:
        return 0.0
    overlap = len(query_tokens & candidate_tokens)
    return overlap / max(len(query_tokens), 1)


def _title_match_bonus(query_tokens: set[str], title: str | None) -> float:
    if not title:
        return 0.0
    title_tokens = _tokenize(title)
    if not title_tokens:
        return 0.0
    return len(query_tokens & title_tokens) / len(title_tokens)
