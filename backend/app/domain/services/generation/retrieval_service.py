from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    GenerationRunStatus,
)
from app.db.models.generation import (
    BusinessTask,
)
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


def _fragment_score_value(fragment: RetrievedFragment) -> float:
    score = fragment.score
    return float(score) if score is not None else float("-inf")


class RetrievalService:
    MIN_REQUIRED_ROLE_COVERAGE = 0.5

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
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
        diagnostics_list: list[dict[str, Any]] = []
        versions = [self.versions.get_with_documents(version_id) for version_id in requested_ids]
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
        fragments = sorted(merged_fragments.values(), key=_fragment_score_value, reverse=True)[
            :limit
        ]
        coverage = self._build_coverage_summary(
            versions=[item for item in versions if item is not None],
            fragments=fragments,
            query_text=query_text,
        )
        diagnostics = {
            "knowledge_version_ids": requested_ids,
            "version_diagnostics": diagnostics_list,
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
