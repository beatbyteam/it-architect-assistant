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
                "Решение опубликовано и готово к проверке",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-02",
                "Версия базы знаний для проверки зафиксирована",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-03",
                "В активной версии базы знаний есть обязательные нормативные материалы",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-04",
                "Протокол содержит документы-основания",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-STR-01", "Цель и контекст задачи отражены в решении", "structure", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-STR-02", "Ограничения и допущения отражены в решении", "structure", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-STR-03",
                "Подразделы архитектуры TOGAF описывают состав компонентов",
                "structure",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-STR-04",
                "Архитектура данных и приложений раскрывает интеграции и API",
                "structure",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-STR-05",
                "Дополнительные сведения фиксируют риски и открытые вопросы",
                "structure",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-STR-06",
                "Все обязательные разделы TOGAF присутствуют",
                "structure",
                Severity.CRITICAL,
            ),
            VerificationRuleDefinition(
                "VR-STR-07",
                "Разделы TOGAF следуют каноническому порядку и вложенности",
                "structure",
                Severity.CRITICAL,
            ),
            VerificationRuleDefinition(
                "VR-NRM-01",
                "Решение не противоречит ODA / IG1242",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-02",
                "Разделы архитектуры TOGAF согласованы с метамоделью ArchiMate 3.2",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-03",
                "Выбранные технологии соответствуют технологическому стандарту",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-04",
                "Шаблоны и принципы соблюдаются там, где они обязательны",
                "normative",
                Severity.MINOR,
            ),
            VerificationRuleDefinition(
                "VR-NRM-05",
                "Разделы архитектуры используют только разрешённые элементы ArchiMate",
                "normative",
                Severity.CRITICAL,
            ),
            VerificationRuleDefinition(
                "VR-NRM-06",
                "Разделы архитектуры содержат хотя бы один допустимый элемент ArchiMate",
                "normative",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-01",
                "Компоненты, интеграции и решения внутренне согласованы",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-02",
                "Основания и доказательства связаны с разделами решения",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-03",
                "Бизнес-сервисы поддержаны компонентами приложений",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-04",
                "Компоненты приложений поддержаны технологическими узлами и сервисами",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-05",
                "Для объектов данных указаны источник и потребительский контекст",
                "consistency",
                Severity.MAJOR,
            ),
            VerificationRuleDefinition(
                "VR-CNS-06",
                "Бизнес-задача прослеживается до архитектурных решений",
                "consistency",
                Severity.MAJOR,
            ),
        ]

    def list_rules(self) -> list[VerificationRuleDefinition]:
        return list(self._rules)

    def get(self, code: str) -> VerificationRuleDefinition | None:
        return next((item for item in self._rules if item.code == code), None)
