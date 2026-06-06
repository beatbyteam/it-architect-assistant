from __future__ import annotations

import re

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

_TECHNICAL_EVIDENCE_RE = re.compile(
    r"^(?:[a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}|VR-[A-Z]+-\d+)$",
    re.IGNORECASE,
)
_TECHNICAL_PREFIX_RE = re.compile(
    r"^(?:[a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})[_-]",
    re.IGNORECASE,
)


def _clean_document_title(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    basename = re.split(r"[\\/]", text.split("?", 1)[0].split("#", 1)[0])[-1]
    return _TECHNICAL_PREFIX_RE.sub("", basename).strip() or basename


def _human_evidence_ref(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text or _TECHNICAL_EVIDENCE_RE.fullmatch(text):
        return None
    return text


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
        document_title = _clean_document_title(top_item.get("document_title"))
        evidence_ref = document_title or _human_evidence_ref(result.evidence_ref)
        return result.model_copy(
            update={"diagnostics": diagnostics, "evidence_ref": evidence_ref}
        )
