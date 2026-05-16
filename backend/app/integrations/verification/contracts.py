from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.enums import CheckResultStatus, ProtocolSummaryStatus, Severity


class VerificationCheckResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_code: str | None = Field(default=None, max_length=100)
    check_name: str = Field(min_length=1, max_length=300)
    rule_group: str | None = Field(default=None, max_length=50)
    status: CheckResultStatus
    severity: Severity
    finding_text: str | None = None
    evidence_ref: str | None = None
    related_section_ref: str | None = None
    diagnostics: dict | None = None
    is_technical_check: bool = False

    @model_validator(mode="after")
    def validate_diagnostics(self) -> VerificationCheckResultPayload:
        if (
            self.status in {CheckResultStatus.WARNING, CheckResultStatus.FAILED}
            and not self.finding_text
        ):
            raise ValueError("для предупреждений и ошибок нужен текст замечания")
        if self.status == CheckResultStatus.NOT_DETERMINED and not (
            self.finding_text or self.diagnostics
        ):
            raise ValueError("для статуса ручной проверки нужен текст замечания или диагностика")
        if self.status in {
            CheckResultStatus.WARNING,
            CheckResultStatus.FAILED,
            CheckResultStatus.NOT_DETERMINED,
        } and not (self.evidence_ref or self.diagnostics):
            raise ValueError(
                "для предупреждений, ошибок и ручной проверки нужны основание или диагностика"
            )
        return self


class VerificationProtocolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    check_results: list[VerificationCheckResultPayload] = Field(min_length=1)
    final_status: ProtocolSummaryStatus

    @model_validator(mode="after")
    def validate_summary_status(self) -> VerificationProtocolPayload:
        statuses = {item.status for item in self.check_results}
        if self.final_status == ProtocolSummaryStatus.PASSED and statuses - {
            CheckResultStatus.PASSED,
            CheckResultStatus.NOT_APPLICABLE,
        }:
            raise ValueError(
                "итог «без замечаний» несовместим с предупреждениями, ошибками или неполными проверками"
            )
        if self.final_status == ProtocolSummaryStatus.PASSED_WITH_COMMENTS and (
            CheckResultStatus.FAILED in statuses or CheckResultStatus.NOT_DETERMINED in statuses
        ):
            raise ValueError("итог «есть комментарии» не может содержать ошибки или неполные проверки")
        if (
            self.final_status == ProtocolSummaryStatus.FAILED
            and CheckResultStatus.FAILED not in statuses
        ):
            raise ValueError("итог «не пройдена» требует хотя бы одну проверку с ошибкой")
        if (
            self.final_status == ProtocolSummaryStatus.FAILED
            and CheckResultStatus.NOT_DETERMINED in statuses
        ):
            raise ValueError(
                "итог «не пройдена» не может содержать неполные проверки; используйте итог «неполная»"
            )
        if (
            self.final_status == ProtocolSummaryStatus.INCOMPLETE
            and CheckResultStatus.NOT_DETERMINED not in statuses
        ):
            raise ValueError("итог «неполная» требует хотя бы одну неполную проверку")
        return self
