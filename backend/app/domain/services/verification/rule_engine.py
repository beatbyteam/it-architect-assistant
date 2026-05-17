from __future__ import annotations

from app.core.exceptions import ValidationError
from app.integrations.verification import (
    VerificationCheckResultPayload,
    VerificationProtocolPayload,
)

from .common import VerificationExecutionContext
from .executor_contracts import VerificationRuleExecutor
from .rule_executors import (
    ConsistencyRulesExecutor,
    NfrRulesExecutor,
    NormativeRulesExecutor,
    StructureRulesExecutor,
    TechnicalRulesExecutor,
    VerificationSupportContext,
    aggregate_summary_status,
    build_summary,
)


class VerificationRuleEngine:
    def __init__(self, executors: dict[str, VerificationRuleExecutor] | None = None) -> None:
        self.executors: dict[str, VerificationRuleExecutor] = executors or {
            "technical": TechnicalRulesExecutor(),
            "structure": StructureRulesExecutor(),
            "normative": NormativeRulesExecutor(),
            "consistency": ConsistencyRulesExecutor(),
            "nfr": NfrRulesExecutor(),
        }

    def execute(self, context: VerificationExecutionContext) -> VerificationProtocolPayload:
        support = self._build_support_context(context)
        results: list[VerificationCheckResultPayload] = []
        for rule in context.rules:
            executor = self.executors.get(rule.group)
            if executor is None:
                raise ValidationError(
                    f"Для правила {rule.code} не настроена группа обработчиков",
                    error_code="VERIFICATION_EXECUTOR_GROUP_MISSING",
                )
            try:
                result = executor.execute(rule=rule, context=context, support=support)
                results.append(self._attach_rule_evidence(result, support=support))
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(f"Не удалось выполнить правило проверки {rule.code}") from exc
        final_status = aggregate_summary_status(results)
        summary = build_summary(final_status, results)
        return VerificationProtocolPayload(
            summary=summary, check_results=results, final_status=final_status
        )

    def _build_support_context(
        self, context: VerificationExecutionContext
    ) -> VerificationSupportContext:
        return VerificationSupportContext.build(context)

    @staticmethod
    def _attach_rule_evidence(
        result: VerificationCheckResultPayload, *, support: VerificationSupportContext
    ) -> VerificationCheckResultPayload:
        if not result.rule_code:
            return result
        evidence_items = support.evidence_for_rule(result.rule_code)
        if not evidence_items:
            return result
        diagnostics = dict(result.diagnostics or {})
        diagnostics["rag_evidence"] = evidence_items
        top_item = evidence_items[0]
        evidence_hint = " ".join(
            str(item).strip()
            for item in [
                top_item.get("document_title"),
                top_item.get("source_location"),
            ]
            if str(item or "").strip()
        )
        evidence_ref = result.evidence_ref
        if evidence_hint and evidence_hint not in str(evidence_ref or ""):
            evidence_ref = (
                f"{evidence_ref} | RAG: {evidence_hint}"
                if evidence_ref
                else f"RAG: {evidence_hint}"
            )
        return result.model_copy(
            update={"diagnostics": diagnostics, "evidence_ref": evidence_ref}
        )
