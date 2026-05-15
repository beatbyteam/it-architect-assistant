from __future__ import annotations

from typing import Protocol

from app.integrations.verification import VerificationCheckResultPayload, VerificationRuleDefinition

from .common import VerificationExecutionContext
from .rule_executors import VerificationSupportContext


class VerificationRuleExecutor(Protocol):
    def execute(
        self,
        *,
        rule: VerificationRuleDefinition,
        context: VerificationExecutionContext,
        support: VerificationSupportContext,
    ) -> VerificationCheckResultPayload: ...
