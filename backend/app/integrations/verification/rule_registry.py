from __future__ import annotations

from dataclasses import dataclass

from app.db.enums import Severity


@dataclass(frozen=True, slots=True)
class VerificationRuleDefinition:
    code: str
    name: str
    group: str
    default_severity: Severity
    technical: bool = False


class VerificationRuleRegistry:
    version = "mvp-v4-sectioned-togaf-archimate"

    def __init__(self) -> None:
        self._rules = [
            VerificationRuleDefinition(
                "VR-TEC-01",
                "Solution exists and is ready for verification",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-02",
                "Knowledge version for verification is defined",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-03",
                "Required normative basis package exists in active knowledge version",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-04",
                "Protocol contains basis documents",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-STR-01", "Goal and task context are captured", "structure", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-STR-02", "Constraints and assumptions are captured", "structure", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-STR-03",
                "TOGAF architecture subsections describe the component composition",
                "structure",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-STR-04",
                "Data/Application architecture disclose integrations and APIs",
                "structure",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-STR-05",
                "Additional information records risks and open questions",
                "structure",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-STR-06",
                "All mandatory TOGAF sections are present",
                "structure",
                Severity.CRITICAL,
            ),
            VerificationRuleDefinition(
                "VR-STR-07",
                "TOGAF sections follow canonical order and nesting",
                "structure",
                Severity.CRITICAL,
            ),
            VerificationRuleDefinition(
                "VR-NRM-01",
                "Solution does not contradict ODA / IG1242",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-02",
                "TOGAF architecture sections align with ArchiMate 3.2 metamodel",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-03",
                "Selected technologies align with the technology standard",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-04",
                "Templates and principles are respected when they are required",
                "normative",
                Severity.MINOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-05",
                "Architecture sections use only whitelisted ArchiMate elements",
                "normative",
                Severity.CRITICAL,
            ),
            VerificationRuleDefinition(
                "VR-NRM-06",
                "Architecture sections expose at least one allowed ArchiMate element",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-01",
                "Components, integrations and decisions are internally consistent",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-02",
                "Evidence and basis are linked to solution sections",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-03",
                "Business services are supported by application components",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-04",
                "Application components are supported by technology nodes/services",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-05",
                "Data objects have identifiable source and consumer context",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-06",
                "Business task is traceable to architecture decisions",
                "consistency",
                Severity.MAJOR,
            ),
        ]

    def list_rules(self) -> list[VerificationRuleDefinition]:
        return list(self._rules)

    def get(self, code: str) -> VerificationRuleDefinition | None:
        return next((item for item in self._rules if item.code == code), None)
