from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    FragmentStatus,
    GenerationRunStatus,
)
from app.db.models.generation import (
    BusinessTask,
)
from app.db.models.knowledge import KnowledgeFragment, KnowledgeVersionDocument, SourceDocument
from app.db.repositories.knowledge import KnowledgeVersionRepository
from app.domain.services.knowledge_basis import (
    build_basis_inventory_for_version_documents,
)
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.domain.services.knowledge_telemetry import build_retrieval_telemetry_summary
from app.integrations.generation import (
    RetrievedFragment,
)

from .common import RetrievalResult, _clarification_context_lines, _context_notes

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}

SECTION_RETRIEVAL_FOCUS = {
    "general_information": "corporate architecture document template TOGAF document structure",
    "business_architecture": "business processes roles goals capabilities value streams",
    "data_architecture": "data objects source consumer ownership data exchange",
    "application_architecture": "application components services APIs integrations interfaces",
    "technology_architecture": "infrastructure platform Docker PostgreSQL runtime technology standards",
    "additional_information": "risks constraints assumptions open questions NFR security availability performance monitoring backup",
}


def _fragment_score_value(fragment: RetrievedFragment) -> float:
    score = fragment.score
    return float(score) if score is not None else float("-inf")


class RetrievalService:
    MIN_REQUIRED_ROLE_COVERAGE = 0.5

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.knowledge_query = KnowledgeQueryService(session, settings)
        self.versions = KnowledgeVersionRepository(session)

    def retrieve_for_task(
        self,
        *,
        task: BusinessTask,
        knowledge_version_ids: list[str] | None = None,
        knowledge_version_id: str | None = None,
        principal: AuthPrincipal | None = None,
        limit: int = 10,
    ) -> RetrievalResult:
        query_text = self._build_query_text(task)
        requested_ids = [
            str(item)
            for item in (
                knowledge_version_ids
                or ([] if knowledge_version_id is None else [knowledge_version_id])
            )
            if item
        ]
        if not requested_ids:
            raise ValidationError(
                "At least one knowledge version is required for retrieval",
                error_code="KNOWLEDGE_SCOPE_EMPTY",
            )
        merged_fragments: dict[str, RetrievedFragment] = {}
        section_fragment_ids: dict[str, list[str]] = {}
        diagnostics_list: list[dict[str, Any]] = []
        section_diagnostics: list[dict[str, Any]] = []
        settings = getattr(self, "settings", None)
        section_limit = max(
            0,
            int(getattr(settings, "generation_section_retrieval_limit", 0) or 0),
        )
        versions = [self.versions.get_with_documents(version_id) for version_id in requested_ids]
        loaded_versions = [item for item in versions if item is not None]
        for version_id in requested_ids:
            result = self.knowledge_query.search_text(
                query_text=query_text,
                knowledge_version_id=version_id,
                limit=max(limit, 8),
                use_case="generation",
                principal=principal,
            )
            diagnostics_list.append(dict(result.diagnostics or {}))
            for fragment in result.fragments:
                existing = merged_fragments.get(fragment.fragment_id)
                if existing is None or _fragment_score_value(fragment) > _fragment_score_value(
                    existing
                ):
                    merged_fragments[fragment.fragment_id] = fragment
            if section_limit:
                for section_code, section_focus in SECTION_RETRIEVAL_FOCUS.items():
                    section_result = self.knowledge_query.search_text(
                        query_text=f"{query_text}\nSection focus: {section_focus}",
                        knowledge_version_id=version_id,
                        limit=section_limit,
                        use_case="generation",
                        section_code=section_code,
                        principal=principal,
                    )
                    section_diagnostics.append(
                        {
                            "knowledge_version_id": version_id,
                            "section_code": section_code,
                            "selected_fragment_count": len(section_result.fragments),
                            "top_fragment_ids": [
                                fragment.fragment_id for fragment in section_result.fragments
                            ],
                            "timings_ms": dict(
                                (section_result.diagnostics or {}).get("timings_ms") or {}
                            ),
                            "empty_result": bool(
                                (section_result.diagnostics or {}).get("empty_result")
                            ),
                        }
                    )
                    for fragment in section_result.fragments:
                        fragment.metadata = {
                            **dict(fragment.metadata or {}),
                            "generation_section_code": section_code,
                        }
                        section_fragment_ids.setdefault(section_code, []).append(
                            fragment.fragment_id
                        )
                        existing = merged_fragments.get(fragment.fragment_id)
                        if existing is None or _fragment_score_value(fragment) > _fragment_score_value(
                            existing
                        ):
                            merged_fragments[fragment.fragment_id] = fragment
        fragments = self._select_generation_fragments(
            merged_fragments=merged_fragments,
            section_fragment_ids=section_fragment_ids,
            limit=limit,
        )
        fallback_fragments = self._required_role_fallback_fragments(
            versions=loaded_versions,
            fragments=fragments,
        )
        if fallback_fragments:
            existing_ids = {fragment.fragment_id for fragment in fragments}
            fragments.extend(
                fragment
                for fragment in fallback_fragments
                if fragment.fragment_id not in existing_ids
            )
        coverage = self._build_coverage_summary(
            versions=loaded_versions,
            fragments=fragments,
            query_text=query_text,
        )
        diagnostics = {
            "knowledge_version_ids": requested_ids,
            "version_diagnostics": diagnostics_list,
            "section_retrieval": {
                "enabled": bool(section_limit),
                "limit_per_section": section_limit,
                "sections_with_fragments": sorted(
                    section for section, ids in section_fragment_ids.items() if ids
                ),
                "diagnostics": section_diagnostics,
            },
            "required_role_fallback": {
                "added_fragment_count": len(fallback_fragments),
                "added_fragment_ids": [fragment.fragment_id for fragment in fallback_fragments],
                "added_roles": sorted(
                    {
                        str(fragment.metadata.get("role_code"))
                        for fragment in fallback_fragments
                        if fragment.metadata.get("role_code")
                    }
                ),
            },
            "coverage_summary": coverage,
        }
        diagnostics["coverage_ok"] = self.is_coverage_sufficient(coverage)
        diagnostics["coverage_warning"] = (
            None if diagnostics["coverage_ok"] else self._coverage_warning_message(coverage)
        )
        version_telemetry = [build_retrieval_telemetry_summary(item) for item in diagnostics_list]
        diagnostics["telemetry_summary"] = {
            "version_count": len(requested_ids),
            "coverage_ok": diagnostics["coverage_ok"],
            "coverage_warning": diagnostics["coverage_warning"],
            "selected_fragment_count": len(fragments),
            "selected_document_count": len(
                {str(fragment.document_id) for fragment in fragments if fragment.document_id}
            ),
            "required_role_coverage": coverage.get("required_role_coverage"),
            "version_telemetry": version_telemetry,
            "aggregate_latency_ms": round(
                sum(float(item.get("latency_ms") or 0.0) for item in version_telemetry), 3
            ),
            "empty_result_versions": [
                item.get("knowledge_version_id")
                for item in version_telemetry
                if item.get("empty_result")
            ],
        }
        return RetrievalResult(fragments=fragments, diagnostics=diagnostics)

    @staticmethod
    def _select_generation_fragments(
        *,
        merged_fragments: dict[str, RetrievedFragment],
        section_fragment_ids: dict[str, list[str]],
        limit: int,
    ) -> list[RetrievedFragment]:
        selected_ids: list[str] = []
        seen: set[str] = set()
        for section_code in SECTION_RETRIEVAL_FOCUS:
            for fragment_id in section_fragment_ids.get(section_code) or []:
                if fragment_id in seen or fragment_id not in merged_fragments:
                    continue
                selected_ids.append(fragment_id)
                seen.add(fragment_id)
                break
        for fragment in sorted(
            merged_fragments.values(), key=_fragment_score_value, reverse=True
        ):
            if fragment.fragment_id in seen:
                continue
            selected_ids.append(fragment.fragment_id)
            seen.add(fragment.fragment_id)
            if len(selected_ids) >= limit:
                break
        return [merged_fragments[fragment_id] for fragment_id in selected_ids[:limit]]

    def _required_role_fallback_fragments(
        self,
        *,
        versions: list[Any],
        fragments: list[RetrievedFragment],
        per_role_limit: int = 1,
    ) -> list[RetrievedFragment]:
        version_documents = [
            doc
            for version in versions
            for doc in list(getattr(version, "version_documents", []) or [])
        ]
        required_roles = sorted(
            {
                str(getattr(item, "role_code", "") or "")
                for item in version_documents
                if bool(getattr(item, "required_flag", False)) and getattr(item, "role_code", None)
            }
        )
        retrieved_roles = {
            str(fragment.metadata.get("role_code") or "reference_only") for fragment in fragments
        }
        missing_roles = [role for role in required_roles if role not in retrieved_roles]
        if not missing_roles:
            return []

        fallback: list[RetrievedFragment] = []
        seen_fragment_ids = {fragment.fragment_id for fragment in fragments}
        for role_code in missing_roles:
            role_fragments = self._load_required_role_fragments(
                versions=versions,
                role_code=role_code,
                limit=per_role_limit,
            )
            for fragment in role_fragments:
                if fragment.fragment_id in seen_fragment_ids:
                    continue
                seen_fragment_ids.add(fragment.fragment_id)
                fallback.append(fragment)
        return fallback

    def _load_required_role_fragments(
        self,
        *,
        versions: list[Any],
        role_code: str,
        limit: int,
    ) -> list[RetrievedFragment]:
        loaded: list[RetrievedFragment] = []
        for version in versions:
            version_id = str(getattr(version, "knowledge_version_id", "") or "")
            document_ids = [
                str(getattr(item, "document_id", "") or "")
                for item in list(getattr(version, "version_documents", []) or [])
                if bool(getattr(item, "required_flag", False))
                and str(getattr(item, "role_code", "") or "") == role_code
            ]
            document_ids = [item for item in document_ids if item]
            if not version_id or not document_ids:
                continue
            statement = (
                select(KnowledgeFragment)
                .join(
                    KnowledgeVersionDocument,
                    (KnowledgeVersionDocument.knowledge_version_id == KnowledgeFragment.knowledge_version_id)
                    & (KnowledgeVersionDocument.document_id == KnowledgeFragment.document_id),
                )
                .where(
                    KnowledgeFragment.knowledge_version_id == version_id,
                    KnowledgeFragment.document_id.in_(document_ids),
                    KnowledgeVersionDocument.role_code == role_code,
                    KnowledgeVersionDocument.required_flag.is_(True),
                    KnowledgeFragment.status == FragmentStatus.ACTIVE,
                )
                .options(
                    selectinload(KnowledgeFragment.document).selectinload(SourceDocument.source)
                )
                .order_by(KnowledgeFragment.created_at.asc(), KnowledgeFragment.fragment_id.asc())
                .limit(max(1, int(limit or 1)))
            )
            rows = list(self.session.scalars(statement))
            for row in rows:
                loaded.append(self._retrieved_fragment_from_required_role(row, role_code=role_code))
        return loaded

    @staticmethod
    def _retrieved_fragment_from_required_role(
        fragment: KnowledgeFragment,
        *,
        role_code: str,
    ) -> RetrievedFragment:
        document = getattr(fragment, "document", None)
        source = getattr(document, "source", None)
        metadata = {
            **dict(getattr(fragment, "fragment_metadata", None) or {}),
            "role_code": role_code,
            "required_flag": True,
            "document_title": getattr(document, "title", None),
            "document_type": getattr(
                getattr(document, "document_type", None),
                "value",
                getattr(document, "document_type", None),
            ),
            "version_label": getattr(document, "version_label", None),
            "source_name": getattr(source, "name", None),
            "source_id": str(getattr(source, "source_id", "") or "") or None,
            "source_location": fragment.source_location,
            "selection_reason": "required_role_fallback",
            "retrieval_rank": 0,
        }
        return RetrievedFragment(
            fragment_id=str(fragment.fragment_id),
            document_id=str(fragment.document_id),
            title=fragment.title,
            content=fragment.content,
            fragment_type=getattr(fragment.fragment_type, "value", fragment.fragment_type),
            source_location=fragment.source_location,
            score=0.0,
            lexical_score=0.0,
            vector_score=0.0,
            keyword_score=0.0,
            metadata=metadata,
        )

    def is_coverage_sufficient(self, coverage: dict[str, Any]) -> bool:
        if int(coverage.get("retrieved_fragment_count") or 0) < 2:
            return False
        required_roles = list(coverage.get("required_roles") or [])
        if not required_roles:
            return True
        if int(coverage.get("retrieved_required_fragment_count") or 0) < 1:
            return False
        return (
            float(coverage.get("required_role_coverage") or 0.0) >= self.MIN_REQUIRED_ROLE_COVERAGE
        )

    def _coverage_warning_message(self, coverage: dict[str, Any]) -> str:
        missing_roles = coverage.get("missing_required_roles") or []
        if missing_roles:
            return f"Retrieved knowledge does not sufficiently cover required basis roles: {', '.join(missing_roles)}."
        return "Retrieved knowledge coverage is too low for safe generation."

    def _build_coverage_summary(
        self, *, versions: list[Any], fragments: list[RetrievedFragment], query_text: str
    ) -> dict[str, Any]:
        version_documents = [
            doc
            for version in versions
            for doc in list(getattr(version, "version_documents", []) or [])
        ]
        basis_inventory = build_basis_inventory_for_version_documents(version_documents)
        required_roles = [
            item["role_code"]
            for item in basis_inventory.required_packages
            if item.get("required") and item.get("present")
        ]
        fragment_role_codes = [
            str(fragment.metadata.get("role_code") or "reference_only") for fragment in fragments
        ]
        retrieved_required_roles = sorted(
            {role for role in fragment_role_codes if role in required_roles}
        )
        selected_documents = sorted(
            {str(fragment.document_id) for fragment in fragments if fragment.document_id}
        )
        role_counts: dict[str, int] = {}
        for role in fragment_role_codes:
            role_counts[role] = role_counts.get(role, 0) + 1
        query_profile = self.knowledge_query._build_query_profile(
            query_text=query_text, use_case="generation"
        )
        return {
            "knowledge_version_ids": [
                str(getattr(version, "knowledge_version_id", ""))
                for version in versions
                if version is not None
            ],
            "required_roles": required_roles,
            "retrieved_roles": sorted(set(fragment_role_codes)),
            "retrieved_required_roles": retrieved_required_roles,
            "missing_required_roles": [
                role for role in required_roles if role not in retrieved_required_roles
            ],
            "required_role_coverage": round(
                len(retrieved_required_roles) / max(len(required_roles), 1), 3
            ),
            "required_basis_present": bool(basis_inventory.required_basis_present),
            "retrieved_fragment_count": len(fragments),
            "retrieved_required_fragment_count": sum(
                1 for role in fragment_role_codes if role in required_roles
            ),
            "retrieved_document_count": len(selected_documents),
            "retrieved_documents": selected_documents,
            "role_counts": role_counts,
            "query_profile": query_profile,
        }

    @staticmethod
    def _build_query_text(task: BusinessTask) -> str:
        clarification_block = "\n".join(_clarification_context_lines(task))
        context_block = "\n".join(_context_notes(task))
        return "\n".join(
            part
            for part in [task.title or "", task.task_text, clarification_block, context_block]
            if part
        )
