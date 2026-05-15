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
            raise ValueError("finding_text is required for warning and failed statuses")
        if self.status == CheckResultStatus.NOT_DETERMINED and not (
            self.finding_text or self.diagnostics
        ):
            raise ValueError("not_determined status requires finding_text or diagnostics")
        if self.status in {
            CheckResultStatus.WARNING,
            CheckResultStatus.FAILED,
            CheckResultStatus.NOT_DETERMINED,
        } and not (self.evidence_ref or self.diagnostics):
            raise ValueError(
                "warning/failed/not_determined statuses require evidence_ref or diagnostics"
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
                "passed summary is incompatible with warnings/failures/incomplete checks"
            )
        if self.final_status == ProtocolSummaryStatus.PASSED_WITH_COMMENTS and (
            CheckResultStatus.FAILED in statuses or CheckResultStatus.NOT_DETERMINED in statuses
        ):
            raise ValueError("passed_with_comments cannot include failed or not_determined checks")
        if (
            self.final_status == ProtocolSummaryStatus.FAILED
            and CheckResultStatus.FAILED not in statuses
        ):
            raise ValueError("failed summary requires at least one failed check")
        if (
            self.final_status == ProtocolSummaryStatus.FAILED
            and CheckResultStatus.NOT_DETERMINED in statuses
        ):
            raise ValueError(
                "failed summary cannot include not_determined checks; use incomplete instead"
            )
        if (
            self.final_status == ProtocolSummaryStatus.INCOMPLETE
            and CheckResultStatus.NOT_DETERMINED not in statuses
        ):
            raise ValueError("incomplete summary requires not_determined checks")
        return self
