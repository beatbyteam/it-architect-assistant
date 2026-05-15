from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.db.enums import (
    VerificationRunStatus,
)
from app.db.models.generation import SolutionVersion
from app.db.models.knowledge import (
    NormativeRule,
)
from app.db.models.verification import (
    VerificationRun,
)
from app.integrations.verification import (
    VerificationRuleDefinition,
)

logger = logging.getLogger(__name__)

TERMINAL_VERIFICATION_STATUSES = {
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELED,
}


@dataclass(slots=True)
class VerificationExecutionContext:
    solution: SolutionVersion
    run: VerificationRun
    rules: list[VerificationRuleDefinition]
    rule_lookup: dict[str, NormativeRule]
    support_context_by_scope: dict[str, list[Any]] = field(default_factory=dict)
    knowledge_versions: list[Any] = field(default_factory=list)
    selected_document_ids: list[str] = field(default_factory=list)
