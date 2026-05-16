from __future__ import annotations

import logging
from typing import Any

from app.core.exceptions import ValidationError
from app.db.enums import (
    CheckResultStatus,
    VerificationRunStatus,
)
from app.integrations.verification import (
    VerificationProtocolPayload,
)

logger = logging.getLogger(__name__)

TERMINAL_VERIFICATION_STATUSES = {
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELED,
}


class VerificationPostValidator:
    def validate(
        self, payload: VerificationProtocolPayload, *, expected_rule_codes: list[str] | None = None
    ) -> dict[str, Any]:
        failed = sum(1 for item in payload.check_results if item.status == CheckResultStatus.FAILED)
        warnings = sum(
            1 for item in payload.check_results if item.status == CheckResultStatus.WARNING
        )
        incomplete = sum(
            1 for item in payload.check_results if item.status == CheckResultStatus.NOT_DETERMINED
        )
        rule_codes = [item.rule_code for item in payload.check_results if item.rule_code]
        duplicate_rule_codes = sorted({code for code in rule_codes if rule_codes.count(code) > 1})
        missing_rule_codes: list[str] = []
        if expected_rule_codes is not None:
            missing_rule_codes = [code for code in expected_rule_codes if code not in rule_codes]
        findings_without_evidence = [
            item.rule_code or item.check_name
            for item in payload.check_results
            if item.status
            in {
                CheckResultStatus.WARNING,
                CheckResultStatus.FAILED,
                CheckResultStatus.NOT_DETERMINED,
            }
            and not (item.evidence_ref or item.diagnostics)
        ]
        unresolved_section_links = [
            item.rule_code or item.check_name
            for item in payload.check_results
            if not item.is_technical_check
            and item.status
            in {
                CheckResultStatus.WARNING,
                CheckResultStatus.FAILED,
                CheckResultStatus.NOT_DETERMINED,
            }
            and not item.related_section_ref
            and (item.rule_code or "").startswith(("VR-STR", "VR-NRM", "VR-CNS"))
        ]
        if duplicate_rule_codes:
            raise ValidationError(
                f"Протокол проверки содержит дубли результатов правил: {', '.join(duplicate_rule_codes)}",
                error_code="VERIFICATION_RULE_DUPLICATES",
            )
        if missing_rule_codes:
            raise ValidationError(
                f"Протокол проверки покрывает не все правила: {', '.join(missing_rule_codes)}",
                error_code="VERIFICATION_RULE_COVERAGE_INCOMPLETE",
            )
        if findings_without_evidence:
            raise ValidationError(
                f"В замечаниях проверки нет основания или диагностики: {', '.join(findings_without_evidence)}",
                error_code="VERIFICATION_FINDINGS_EVIDENCE_MISSING",
            )
        if unresolved_section_links:
            raise ValidationError(
                f"Замечания проверки не связаны с разделами решения: {', '.join(unresolved_section_links)}",
                error_code="VERIFICATION_SECTION_LINKS_MISSING",
            )
        return {
            "check_count": len(payload.check_results),
            "failed_count": failed,
            "warning_count": warnings,
            "incomplete_count": incomplete,
            "final_status": payload.final_status.value,
            "missing_rule_count": len(missing_rule_codes),
            "duplicate_rule_count": len(duplicate_rule_codes),
            "evidence_gap_count": len(findings_without_evidence),
            "unresolved_section_link_count": len(unresolved_section_links),
        }
