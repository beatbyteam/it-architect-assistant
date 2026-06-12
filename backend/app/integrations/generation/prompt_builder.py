from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.domain.architecture import (
    assess_section_readiness,
    section_generation_plan_records,
    summarize_guidance_by_section,
)
from app.integrations.generation.llm_gateway import RetrievedFragment
from app.integrations.generation.prompt_registry import PromptTemplate
from app.integrations.generation.token_budget import TokenBudgetManager

logger = logging.getLogger(__name__)

RETRIEVAL_CONTEXT_CONTRACT_VERSION = "retrieved_fragments_only_v1"


@dataclass(slots=True)
class PromptArtifact:
    prompt_version: str
    system_prompt: str
    user_prompt: str
    task_block: str
    context_block: str
    knowledge_block: str
    included_fragment_ids: list[str]
    dropped_fragment_ids: list[str]
    token_budget: dict[str, int]
    retrieval_trace: dict[str, Any]
    section_generation_plan: list[dict[str, Any]]
    section_readiness: list[dict[str, Any]]
    retrieval_contract_version: str
    knowledge_manifest: list[dict[str, Any]]

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


class GenerationPromptBuilder:
    def __init__(
        self, budget_manager: TokenBudgetManager, *, fragment_char_limit: int = 1600
    ) -> None:
        self.budget_manager = budget_manager
        self.fragment_char_limit = max(200, int(fragment_char_limit or 1600))

    def build(
        self,
        *,
        template: PromptTemplate,
        task_title: str,
        task_text: str,
        context_items: list[str],
        retrieved_fragments: list[RetrievedFragment],
    ) -> PromptArtifact:
        task_block = f"Title: {task_title}\nTask: {task_text}".strip()
        context_block = (
            "\n".join(f"- {item}" for item in context_items)
            or "- Явный дополнительный контекст не указан"
        )
        knowledge_manifest = [self._fragment_summary(fragment) for fragment in retrieved_fragments]
        knowledge_items = [self._format_fragment(fragment) for fragment in retrieved_fragments]
        base_text = "\n\n".join([template.system_prompt, task_block, context_block])
        budget_result = self.budget_manager.trim_items(base_text, knowledge_items)
        included_fragments, dropped_fragments = self._partition_fragments_by_budget(
            retrieved_fragments=retrieved_fragments,
            budget_result=budget_result,
        )
        included_fragment_ids = [fragment.fragment_id for fragment in included_fragments]
        dropped_fragment_ids = [fragment.fragment_id for fragment in dropped_fragments]
        knowledge_block = (
            "\n\n".join(budget_result.selected_items)
            or "Из базы знаний не найдено релевантных фрагментов"
        )
        knowledge_block = (
            "Ниже приведены только найденные фрагменты базы знаний. Модель должна опираться на них и не считать, что имеет прямой доступ к исходным файлам.\n\n"
            + knowledge_block
        )
        section_generation_plan = section_generation_plan_records()
        section_readiness = [
            assess_section_readiness(
                item["section_code"],
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
            )
            for item in section_generation_plan
        ]
        guidance_summary = summarize_guidance_by_section(retrieved_fragments)
        section_plan_lines: list[str] = []
        for item, readiness in zip(section_generation_plan, section_readiness, strict=False):
            allowed = ", ".join(item.get("allowed_archimate_elements") or []) or "n/a"
            missing = ", ".join(readiness.get("missing_signal_groups") or []) or "none"
            guidance = guidance_summary.get(item["section_code"], {})
            guidance_titles = ", ".join(guidance.get("document_titles") or []) or "none"
            guidance_fragments = guidance.get("fragment_count") or 0
            methodology_fragments = guidance.get("methodology_fragment_count") or 0
            section_plan_lines.append(
                f"- {item['heading']} ({item['section_code']}): purpose={item['purpose']} | allowed={allowed} | readiness={readiness['status']} ({readiness['score']}) | missing_signals={missing} | guidance_fragments={guidance_fragments} | methodology_fragments={methodology_fragments} | guidance_titles={guidance_titles} | fallback_focus={item['fallback_focus']}"
            )
        section_plan_block = "\n".join(section_plan_lines)
        user_prompt = template.user_prompt_template.format(
            task_text=task_block,
            context_block=context_block,
            knowledge_block=knowledge_block,
            section_plan_block=section_plan_block,
        )
        artifact = PromptArtifact(
            prompt_version=template.version_id,
            system_prompt=template.system_prompt,
            user_prompt=user_prompt,
            task_block=task_block,
            context_block=context_block,
            knowledge_block=knowledge_block,
            included_fragment_ids=included_fragment_ids,
            dropped_fragment_ids=dropped_fragment_ids,
            token_budget={
                "available_input_tokens": budget_result.available_tokens,
                "consumed_input_tokens": budget_result.consumed_tokens,
                "dropped_fragment_count": len(budget_result.dropped_items),
            },
            retrieval_trace={
                "included_fragments": [
                    self._fragment_summary(fragment) for fragment in included_fragments
                ],
                "dropped_fragments": [
                    self._fragment_summary(fragment) for fragment in dropped_fragments
                ],
            },
            section_generation_plan=section_generation_plan,
            section_readiness=section_readiness,
            retrieval_contract_version=RETRIEVAL_CONTEXT_CONTRACT_VERSION,
            knowledge_manifest=knowledge_manifest,
        )
        logger.info(
            "prompt_artifact_built",
            extra={
                "stage": "prompt_build",
                "stage_status": artifact.prompt_version,
                "retrieval_contract_version": artifact.retrieval_contract_version,
            },
        )
        return artifact

    @staticmethod
    def _partition_fragments_by_budget(
        *,
        retrieved_fragments: list[RetrievedFragment],
        budget_result: Any,
    ) -> tuple[list[RetrievedFragment], list[RetrievedFragment]]:
        included = [
            retrieved_fragments[index]
            for index in budget_result.selected_indexes
            if index < len(retrieved_fragments)
        ]
        dropped = [
            retrieved_fragments[index]
            for index in budget_result.dropped_indexes
            if index < len(retrieved_fragments)
        ]
        return included, dropped

    def _format_fragment(self, fragment: RetrievedFragment) -> str:
        title = fragment.title or fragment.fragment_type or "Knowledge fragment"
        document_title = fragment.metadata.get("document_title") or fragment.document_id
        role_code = fragment.metadata.get("role_code") or "reference_only"
        required_flag = "yes" if bool(fragment.metadata.get("required_flag")) else "no"
        document_type = fragment.metadata.get("document_type") or "unknown"
        section_path = fragment.metadata.get("section_path") or []
        section_heading = (
            fragment.metadata.get("section_heading")
            or " / ".join(str(item) for item in section_path)
            or "n/a"
        )
        score = f"{float(fragment.score or 0.0):.4f}"
        lexical_score = f"{float(fragment.lexical_score or 0.0):.4f}"
        vector_score = f"{float(fragment.vector_score or 0.0):.4f}"
        source_location = fragment.source_location or str(
            fragment.metadata.get("source_location") or "n/a"
        )
        content, truncated = self._trim_fragment_content(fragment.content)
        return (
            f"[fragment_id={fragment.fragment_id}]\n"
            f"document_title={document_title}\n"
            f"title={title}\n"
            f"fragment_type={fragment.fragment_type or 'n/a'}\n"
            f"role_code={role_code}\n"
            f"required_flag={required_flag}\n"
            f"document_type={document_type}\n"
            f"section_heading={section_heading}\n"
            f"source_location={source_location}\n"
            f"retrieval_score={score}\n"
            f"lexical_score={lexical_score}\n"
            f"vector_score={vector_score}\n"
            f"content_truncated={'yes' if truncated else 'no'}\n"
            "content:\n"
            f"{content}"
        )

    def _trim_fragment_content(self, content: str) -> tuple[str, bool]:
        normalized = " ".join(str(content or "").split())
        if len(normalized) <= self.fragment_char_limit:
            return normalized, False
        return normalized[: self.fragment_char_limit - 1].rstrip() + "…", True

    @staticmethod
    def _fragment_summary(fragment: RetrievedFragment) -> dict[str, Any]:
        return {
            "fragment_id": fragment.fragment_id,
            "document_id": fragment.document_id,
            "fragment_type": fragment.fragment_type,
            "title": fragment.title,
            "score": fragment.score,
            "lexical_score": fragment.lexical_score,
            "vector_score": fragment.vector_score,
            "keyword_score": fragment.keyword_score,
            "source_location": fragment.source_location,
            "document_title": fragment.metadata.get("document_title"),
            "role_code": fragment.metadata.get("role_code"),
            "required_flag": bool(fragment.metadata.get("required_flag")),
            "selection_reason": fragment.metadata.get("selection_reason"),
            "content_length": len(fragment.content or ""),
            "metadata": fragment.metadata,
        }
