from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import DependencyUnavailableError
from app.core.security import AuthPrincipal
from app.db.models.knowledge import (
    EmbeddingSpace,
    KnowledgeFragment,
    KnowledgeFragmentEmbedding,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    SourceDocument,
)
from app.db.repositories.knowledge import EmbeddingSpaceRepository
from app.domain.architecture import summarize_guidance_by_section
from app.integrations.generation.llm_gateway import RetrievedFragment
from app.integrations.knowledge.embedding import EmbeddingService
from app.integrations.knowledge.policy_stack import build_policy_stack
from app.integrations.knowledge.reranker import RerankerService
from app.integrations.knowledge.retrieval_policies import (
    RetrievalCandidate,
    RetrievalPolicyRegistry,
    RetrievalScoredCandidate,
    cosine_similarity,
    keyword_overlap_score,
    lexical_rank_candidates,
    reciprocal_rank_fuse,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class KnowledgeQueryResult:
    fragments: list[RetrievedFragment]
    diagnostics: dict[str, Any]


class KnowledgeQueryService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.embeddings = EmbeddingService(
            profile_code=self.settings.embedding_profile,
            provider_name=self.settings.embedding_provider,
            dimensions=self.settings.embedding_dimensions,
            base_url=self.settings.embedding_base_url,
            api_key=self.settings.embedding_api_key,
            timeout_sec=self.settings.embedding_timeout_sec,
            model_id=self.settings.embedding_model_id,
            batch_size=self.settings.embedding_batch_size,
        )
        self.embedding_spaces = EmbeddingSpaceRepository(session)
        self.reranker = RerankerService(self.settings)

    def search_text(
        self,
        *,
        query_text: str,
        knowledge_version_id: str,
        limit: int = 8,
        use_case: str = "generation",
        section_code: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> KnowledgeQueryResult:
        version = self._get_accessible_version(knowledge_version_id, principal)
        knowledge_version_id = str(version.knowledge_version_id)
        started = time.perf_counter()
        policy = RetrievalPolicyRegistry.get(use_case)
        encode_started = time.perf_counter()
        encoded_query = self.embeddings.encode_query(query_text)
        if not encoded_query.vectors:
            raise DependencyUnavailableError(
                "embedding_provider",
                "Embedding provider returned an empty vector payload for the retrieval query",
                error_code="EMBEDDING_RESPONSE_EMPTY",
            )
        query_vector = encoded_query.vectors[0]
        encode_ms = round((time.perf_counter() - encode_started) * 1000, 2)
        policy_stack = build_policy_stack(
            use_case=use_case,
            embeddings=self.embeddings,
            reranker_provider=self.settings.reranker_provider,
        ).as_dict()
        version_document_map = self._load_version_document_map(knowledge_version_id)
        query_profile = self._build_query_profile(
            query_text=query_text, use_case=use_case, section_code=section_code
        )

        load_started = time.perf_counter()
        fragments_raw = list(
            self.session.scalars(
                select(KnowledgeFragment)
                .where(KnowledgeFragment.knowledge_version_id == knowledge_version_id)
                .options(
                    selectinload(KnowledgeFragment.document).selectinload(SourceDocument.source),
                    selectinload(KnowledgeFragment.fragment_embeddings).selectinload(
                        KnowledgeFragmentEmbedding.embedding_space
                    ),
                )
            )
        )
        load_ms = round((time.perf_counter() - load_started) * 1000, 2)
        active_space = self._resolve_preferred_embedding_space(knowledge_version_id, fragments_raw)
        vector_stage_started = time.perf_counter()
        db_vector_candidates, db_vector_score_by_fragment_id, vector_backend = (
            self._load_vector_candidates_from_db(
                knowledge_version_id=knowledge_version_id,
                query_vector=query_vector,
                active_space=active_space,
                limit=policy.vector_candidate_limit,
            )
        )
        compute_python_vector_scores = not (
            vector_backend == "pgvector_hnsw" and db_vector_candidates
        )
        all_candidates = [
            self._build_candidate(
                fragment,
                query_vector,
                query_text=query_text,
                version_document_map=version_document_map,
                section_code=section_code,
                embedding_space_id=str(active_space.embedding_space_id)
                if active_space is not None
                else None,
                embedding_space_code=active_space.code if active_space is not None else None,
                vector_score_override=db_vector_score_by_fragment_id.get(str(fragment.fragment_id)),
                compute_python_vector_score=compute_python_vector_scores,
            )
            for fragment in fragments_raw
        ]

        if db_vector_candidates:
            candidate_index = {candidate.fragment_id: candidate for candidate in all_candidates}
            vector_candidates = [
                candidate_index[candidate.fragment_id]
                for candidate in db_vector_candidates
                if candidate.fragment_id in candidate_index
            ]
        else:
            vector_ranked = sorted(
                all_candidates, key=lambda item: item.initial_vector_score, reverse=True
            )
            vector_candidates = vector_ranked[: policy.vector_candidate_limit]
            vector_backend = "python_cosine_fallback"
        vector_ms = round((time.perf_counter() - vector_stage_started) * 1000, 2)

        lexical_stage_started = time.perf_counter()
        lexical_ranked, lexical_diagnostics = lexical_rank_candidates(
            query_text=query_text,
            candidates=all_candidates,
        )
        lexical_candidates = lexical_ranked[: policy.keyword_candidate_limit]
        keyword_ranked = sorted(all_candidates, key=lambda item: item.keyword_score, reverse=True)
        keyword_candidates = keyword_ranked[: policy.keyword_candidate_limit]
        lexical_ms = round((time.perf_counter() - lexical_stage_started) * 1000, 2)

        fusion_stage_started = time.perf_counter()
        fusion_scores = reciprocal_rank_fuse(
            rankings=[vector_candidates, lexical_candidates, keyword_candidates],
            k=policy.fusion_rrf_k,
        )
        candidate_index = {candidate.fragment_id: candidate for candidate in all_candidates}
        fused_candidates: list[RetrievalCandidate] = []
        for fragment_id, score in sorted(
            fusion_scores.items(), key=lambda item: item[1], reverse=True
        ):
            candidate = candidate_index.get(fragment_id)
            if candidate is None:
                continue
            candidate.fusion_score = round(float(score), 8)
            fused_candidates.append(candidate)
        fused_candidates = fused_candidates[: policy.fused_candidate_limit]
        fusion_ms = round((time.perf_counter() - fusion_stage_started) * 1000, 2)

        reranked, reranker_diagnostics = self.reranker.rerank(
            query_text=query_text,
            candidates=fused_candidates,
            policy=policy,
        )
        selection_stage_started = time.perf_counter()
        selected_entries = self._select_diverse_candidates(
            reranked=reranked,
            limit=limit,
            use_case=use_case,
            query_profile=query_profile,
        )
        selection_ms = round((time.perf_counter() - selection_stage_started) * 1000, 2)
        fragments = [
            RetrievedFragment(
                fragment_id=item.candidate.fragment_id,
                document_id=item.candidate.document_id,
                title=item.candidate.title,
                content=item.candidate.content,
                fragment_type=item.candidate.fragment_type,
                source_location=item.candidate.source_location,
                score=item.score,
                lexical_score=item.lexical_score,
                vector_score=item.vector_score,
                keyword_score=item.keyword_score,
                metadata={
                    **item.candidate.metadata,
                    "selection_reason": reason,
                    "retrieval_rank": rank,
                    "fusion_score": item.candidate.fusion_score,
                    "reranker_provider": reranker_diagnostics.provider_name,
                    "reranker_backend": reranker_diagnostics.backend,
                },
            )
            for rank, (item, reason) in enumerate(selected_entries, start=1)
        ]
        selected_doc_types = Counter(
            str(fragment.metadata.get("document_type") or "unknown") for fragment in fragments
        )
        candidate_doc_types = Counter(
            str(candidate.metadata.get("document_type") or "unknown")
            for candidate in all_candidates
        )
        candidate_role_codes = Counter(
            str(candidate.metadata.get("role_code") or "reference_only")
            for candidate in all_candidates
        )
        candidate_fragment_types = Counter(
            str(candidate.fragment_type or "unknown") for candidate in all_candidates
        )
        fragments_with_embeddings = sum(
            1 for candidate in all_candidates if bool(candidate.metadata.get("embedding_key"))
        )
        if not fragments_raw:
            empty_result_reason = "no_fragments_in_version"
        elif active_space is None:
            empty_result_reason = "no_embedding_space_available"
        elif not fragments_with_embeddings:
            empty_result_reason = "no_embeddings_for_active_space"
        elif not fused_candidates:
            empty_result_reason = "no_candidates_after_fusion"
        elif not fragments:
            empty_result_reason = "no_candidates_after_selection"
        else:
            empty_result_reason = None
        selected_role_codes = Counter(
            str(fragment.metadata.get("role_code") or "reference_only") for fragment in fragments
        )
        selected_documents = Counter(
            str(fragment.metadata.get("document_title") or fragment.document_id)
            for fragment in fragments
        )
        diagnostics = {
            "knowledge_version_id": knowledge_version_id,
            "retrieval_backend": f"{vector_backend}+python_rrf_rerank",
            "vector_backend": vector_backend,
            "lexical_backend": lexical_diagnostics.backend,
            "policy_id": policy.policy_id,
            "active_embedding_space_id": str(active_space.embedding_space_id)
            if active_space is not None
            else None,
            "active_embedding_space_code": active_space.code if active_space is not None else None,
            "vector_candidate_count": len(vector_candidates),
            "lexical_candidate_count": len(lexical_candidates),
            "keyword_candidate_count": len(keyword_candidates),
            "fused_candidate_count": len(fused_candidates),
            "reranked_candidate_count": len(reranked),
            "reranked_count": len(fragments),
            "query_length": len(query_text),
            "query_profile": query_profile,
            "guidance_summary_by_section": summarize_guidance_by_section(fragments),
            "policy_stack": policy_stack,
            "empty_result": len(fragments) == 0,
            "empty_result_reason": empty_result_reason,
            "lexical_diagnostics": {
                "document_count": lexical_diagnostics.document_count,
                "avg_document_length": lexical_diagnostics.avg_document_length,
            },
            "reranker": {
                "provider_name": reranker_diagnostics.provider_name,
                "model_id": reranker_diagnostics.model_id,
                "latency_ms": reranker_diagnostics.latency_ms,
                "fallback_used": reranker_diagnostics.fallback_used,
                "candidate_count": reranker_diagnostics.candidate_count,
                "reranked_count": reranker_diagnostics.reranked_count,
                "backend": reranker_diagnostics.backend,
            },
            "candidate_pool_summary": {
                "fragment_count": len(all_candidates),
                "fragment_with_embedding_count": fragments_with_embeddings,
                "document_types": dict(candidate_doc_types),
                "role_codes": dict(candidate_role_codes),
                "fragment_types": dict(candidate_fragment_types),
            },
            "selected_counts": {
                "required_fragments": sum(
                    1 for fragment in fragments if bool(fragment.metadata.get("required_flag"))
                ),
                "document_types": dict(selected_doc_types),
                "role_codes": dict(selected_role_codes),
                "documents": dict(selected_documents),
            },
            "selected_fragments": [self._fragment_summary(fragment) for fragment in fragments],
            "trace": {
                "top_fragment_ids": [fragment.fragment_id for fragment in fragments],
                "fragment_types": [fragment.fragment_type for fragment in fragments],
                "document_titles": [
                    fragment.metadata.get("document_title") for fragment in fragments
                ],
                "knowledge_basis_roles": [
                    fragment.metadata.get("role_code") for fragment in fragments
                ],
                "fusion_top_fragment_ids": [
                    candidate.fragment_id for candidate in fused_candidates[:10]
                ],
            },
            "timings_ms": {
                "total": round((time.perf_counter() - started) * 1000, 2),
                "encode_query": encode_ms,
                "load_fragments": load_ms,
                "vector_ranking": vector_ms,
                "lexical_ranking": lexical_ms,
                "fusion": fusion_ms,
                "reranker": reranker_diagnostics.latency_ms,
                "selection": selection_ms,
            },
        }
        logger.info(
            "retrieval_trace",
            extra={
                "stage": "retrieval",
                "stage_status": policy.policy_id,
                "entity_id": knowledge_version_id,
                "run_id": knowledge_version_id,
                "policy_stack": policy_stack,
                "empty_result": len(fragments) == 0,
                "empty_result_reason": empty_result_reason,
                "query_profile": query_profile,
                "guidance_summary_by_section": summarize_guidance_by_section(fragments),
                "selected_fragment_ids": [fragment.fragment_id for fragment in fragments],
                "active_embedding_space_code": active_space.code
                if active_space is not None
                else None,
                "reranker_provider": reranker_diagnostics.provider_name,
            },
        )
        return KnowledgeQueryResult(fragments=fragments, diagnostics=diagnostics)

    def _supports_db_vector_search(
        self, *, active_space: EmbeddingSpace | None, knowledge_version_id: str
    ) -> bool:
        if active_space is None:
            return False
        version = self.session.get(KnowledgeVersion, knowledge_version_id)
        if version is None:
            return False
        version_space_id = str(getattr(version, "embedding_space_id", "") or "")
        active_space_id = str(getattr(active_space, "embedding_space_id", "") or "")
        if not active_space_id:
            return False
        if not version_space_id:
            return True
        return version_space_id == active_space_id

    def _load_vector_candidates_from_db(
        self,
        *,
        knowledge_version_id: str,
        query_vector: list[float],
        active_space: EmbeddingSpace | None,
        limit: int,
    ) -> tuple[list[RetrievalCandidate], dict[str, float], str]:
        if not self._supports_db_vector_search(
            active_space=active_space, knowledge_version_id=knowledge_version_id
        ):
            return [], {}, "python_cosine_fallback"
        try:
            distance_expr = KnowledgeFragment.embedding.cosine_distance(query_vector)
            statement = (
                select(KnowledgeFragment, distance_expr.label("distance"))
                .where(
                    KnowledgeFragment.knowledge_version_id == knowledge_version_id,
                    KnowledgeFragment.embedding.is_not(None),
                )
                .options(
                    selectinload(KnowledgeFragment.document).selectinload(SourceDocument.source)
                )
                .order_by(distance_expr.asc())
                .limit(limit)
            )
            rows = list(self.session.execute(statement).all())
        except Exception as exc:  # pragma: no cover - safe runtime fallback
            logger.warning("db_vector_retrieval_fallback", extra={"reason": str(exc)})
            return [], {}, "python_cosine_fallback"
        candidates: list[RetrievalCandidate] = []
        score_map: dict[str, float] = {}
        for fragment, distance in rows:
            fragment_id = str(fragment.fragment_id)
            vector_score = max(0.0, 1.0 - float(distance or 0.0))
            score_map[fragment_id] = round(vector_score, 8)
            candidates.append(
                RetrievalCandidate(
                    fragment_id=fragment_id,
                    document_id=str(fragment.document_id),
                    title=fragment.title,
                    content=fragment.content,
                    fragment_type=fragment.fragment_type.value if fragment.fragment_type else None,
                    source_location=fragment.source_location,
                    initial_vector_score=round(vector_score, 8),
                    keyword_score=0.0,
                    metadata={},
                )
            )
        return candidates, score_map, "pgvector_hnsw"

    def _resolve_preferred_embedding_space(
        self, knowledge_version_id: str, fragments: list[KnowledgeFragment]
    ) -> EmbeddingSpace | None:
        version = self.session.get(KnowledgeVersion, knowledge_version_id)
        if version is not None and getattr(version, "embedding_space_id", None):
            version_space_id = str(version.embedding_space_id)
            for fragment in fragments:
                for row in fragment.fragment_embeddings or []:
                    if str(row.embedding_space_id) == version_space_id:
                        return row.embedding_space or self.embedding_spaces.get(version_space_id)
        active = self.embedding_spaces.get_active()
        if active is not None:
            active_id = str(active.embedding_space_id)
            if any(
                str(row.embedding_space_id) == active_id
                for fragment in fragments
                for row in (fragment.fragment_embeddings or [])
            ):
                return active
        space_ids: dict[str, EmbeddingSpace] = {}
        for fragment in fragments:
            for row in fragment.fragment_embeddings or []:
                if row.embedding_space is not None:
                    space_ids[str(row.embedding_space_id)] = row.embedding_space
        if active is not None and not space_ids:
            return active
        if not space_ids:
            return None
        return max(
            space_ids.values(),
            key=lambda item: item.created_at.timestamp() if item.created_at is not None else 0.0,
        )

    def _embedding_row_for_fragment(
        self, fragment: KnowledgeFragment, *, embedding_space_id: str | None
    ) -> KnowledgeFragmentEmbedding | None:
        rows = list(fragment.fragment_embeddings or [])
        if embedding_space_id is not None:
            for row in rows:
                if str(row.embedding_space_id) == str(embedding_space_id):
                    return row
            return None
        return rows[0] if rows else None

    def _get_accessible_version(
        self, knowledge_version_id: str, principal: AuthPrincipal | None = None
    ) -> KnowledgeVersion:
        from app.domain.services.knowledge.version_service import KnowledgeVersionService

        return KnowledgeVersionService(self.session).get_version(knowledge_version_id, principal)

    def _load_version_document_map(self, knowledge_version_id: str) -> dict[str, dict[str, Any]]:
        rows = list(
            self.session.scalars(
                select(KnowledgeVersionDocument)
                .where(KnowledgeVersionDocument.knowledge_version_id == knowledge_version_id)
                .options(
                    selectinload(KnowledgeVersionDocument.document).selectinload(
                        SourceDocument.source
                    )
                )
            )
        )
        mapping: dict[str, dict[str, Any]] = {}
        for row in rows:
            document = row.document
            source = document.source if document is not None else None
            mapping[str(row.document_id)] = {
                "role_code": row.role_code,
                "required_flag": bool(row.required_flag),
                "document_title": document.title if document is not None else None,
                "document_type": getattr(document.document_type, "value", document.document_type)
                if document is not None
                else None,
                "version_label": document.version_label if document is not None else None,
                "source_name": source.name if source is not None else None,
                "source_id": str(source.source_id) if source is not None else None,
            }
        return mapping

    def _build_candidate(
        self,
        fragment: KnowledgeFragment,
        query_vector: list[float],
        *,
        query_text: str,
        version_document_map: dict[str, dict[str, Any]],
        section_code: str | None = None,
        embedding_space_id: str | None = None,
        embedding_space_code: str | None = None,
        vector_score_override: float | None = None,
        compute_python_vector_score: bool = True,
    ) -> RetrievalCandidate:
        vector_score = float(vector_score_override or 0.0)
        embedding_row = self._embedding_row_for_fragment(
            fragment, embedding_space_id=embedding_space_id
        )
        if (
            compute_python_vector_score
            and vector_score_override is None
            and embedding_row is not None
            and embedding_row.embedding is not None
        ):
            embedding_values = list(embedding_row.embedding)
            if embedding_values:
                vector_score = cosine_similarity(query_vector, embedding_values)
        metadata = dict(fragment.fragment_metadata or {})
        version_metadata = version_document_map.get(str(fragment.document_id), {})
        metadata = {**version_metadata, **metadata}
        document = getattr(fragment, "document", None)
        metadata.setdefault(
            "document_type",
            getattr(
                getattr(document, "document_type", None),
                "value",
                getattr(document, "document_type", None),
            ),
        )
        metadata.setdefault("source_location", fragment.source_location)
        metadata.setdefault("document_title", getattr(document, "title", None))
        metadata.setdefault("version_label", getattr(document, "version_label", None))
        metadata.setdefault("source_name", getattr(getattr(document, "source", None), "name", None))
        metadata.setdefault("embedding_space_code", embedding_space_code)
        if embedding_row is not None:
            metadata.setdefault("embedding_key", embedding_row.embedding_key)
        section_tags = [str(item) for item in (metadata.get("section_tags") or []) if item]
        knowledge_kind = str(metadata.get("knowledge_kind") or "domain")
        section_focus_match = bool(section_code and section_code in section_tags)
        source_weight = 1.0
        if section_focus_match:
            source_weight *= 1.18
        if knowledge_kind == "methodology":
            source_weight *= 1.05
        metadata["section_focus_match"] = section_focus_match
        metadata["source_weight"] = round(
            float(metadata.get("source_weight") or 1.0) * source_weight, 4
        )
        return RetrievalCandidate(
            fragment_id=str(fragment.fragment_id),
            document_id=str(fragment.document_id),
            title=fragment.title,
            content=fragment.content,
            fragment_type=fragment.fragment_type.value if fragment.fragment_type else None,
            source_location=fragment.source_location,
            initial_vector_score=round(vector_score, 8),
            keyword_score=round(
                keyword_overlap_score(query_text, fragment.content, fragment.title), 8
            ),
            metadata=metadata,
        )

    def _build_query_profile(
        self, *, query_text: str, use_case: str, section_code: str | None = None
    ) -> dict[str, Any]:
        lowered = query_text.lower()
        integration_focus = any(
            token in lowered
            for token in {"integration", "интеграц", "api", "rest", "event", "queue", "webhook"}
        )
        technology_focus = any(
            token in lowered
            for token in {
                "docker",
                "kubernetes",
                "postgres",
                "redis",
                "python",
                "java",
                "runtime",
                "deployment",
                "infra",
            }
        )
        normative_focus = (
            any(
                token in lowered
                for token in {
                    "норм",
                    "oda",
                    "ig1242",
                    "archimate",
                    "compliance",
                    "policy",
                    "rule",
                    "verification",
                }
            )
            or use_case == "verification"
        )
        component_focus = any(
            token in lowered
            for token in {"component", "boundary", "service", "module", "сервис", "компонент"}
        )
        return {
            "integration_focus": integration_focus,
            "technology_focus": technology_focus,
            "normative_focus": normative_focus,
            "component_focus": component_focus,
            "section_code": section_code,
            "use_case": use_case,
        }

    def _select_diverse_candidates(
        self,
        *,
        reranked: list[RetrievalScoredCandidate],
        limit: int,
        use_case: str,
        query_profile: dict[str, Any],
    ) -> list[tuple[RetrievalScoredCandidate, str]]:
        selected: list[tuple[RetrievalScoredCandidate, str]] = []
        document_cap = 3 if use_case == "generation" else 4
        document_counts: dict[str, int] = {}
        required_taken = False
        normative_taken = False
        integration_taken = False
        for item in reranked:
            candidate = item.candidate
            metadata = candidate.metadata or {}
            document_id = str(candidate.document_id)
            document_count = document_counts.get(document_id, 0)
            if document_count >= document_cap:
                continue
            reason = "score"
            if bool(metadata.get("required_flag")) and not required_taken:
                reason = "required_basis"
                required_taken = True
            elif (
                bool(query_profile.get("normative_focus"))
                and str(metadata.get("knowledge_kind") or "") == "normative"
                and not normative_taken
            ):
                reason = "normative_match"
                normative_taken = True
            elif (
                bool(query_profile.get("integration_focus"))
                and bool(
                    metadata.get("integration_pattern")
                    or metadata.get("integration_focus")
                    or metadata.get("section_focus_match")
                )
                and not integration_taken
            ):
                reason = "integration_match"
                integration_taken = True
            selected.append((item, reason))
            document_counts[document_id] = document_count + 1
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _fragment_summary(fragment: RetrievedFragment) -> dict[str, Any]:
        return {
            "fragment_id": fragment.fragment_id,
            "document_id": fragment.document_id,
            "title": fragment.title,
            "fragment_type": fragment.fragment_type,
            "score": fragment.score,
            "vector_score": fragment.vector_score,
            "lexical_score": fragment.lexical_score,
            "keyword_score": fragment.keyword_score,
            "document_title": fragment.metadata.get("document_title"),
            "role_code": fragment.metadata.get("role_code"),
            "required_flag": bool(fragment.metadata.get("required_flag")),
            "source_location": fragment.source_location,
            "fusion_score": fragment.metadata.get("fusion_score"),
            "selection_reason": fragment.metadata.get("selection_reason"),
        }
