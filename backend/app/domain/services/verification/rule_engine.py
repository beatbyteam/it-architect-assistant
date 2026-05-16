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
                results.append(executor.execute(rule=rule, context=context, support=support))
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
