from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.models.generation import BusinessTask

QUESTION_TEMPLATES: dict[str, str] = {
    "goal": "Какова основная цель решения и какой бизнес-результат ожидается?",
    "context": "Какой текущий контекст, окружение или исходная система рассматриваются?",
    "constraints": "Какие есть ограничения: сроки, безопасность, производительность, бюджет, нормативные требования?",
    "integrations": "С какими системами, API, сервисами или данными требуется интеграция? Если интеграций нет, это нужно явно зафиксировать.",
    "expected_output": "Какой ожидается объём и фокус решения: концепт, high-level design, интеграционная схема, компонентная модель?",
    "nfr": "Какие нефункциональные требования важны: безопасность, доступность, производительность, мониторинг, резервное копирование?",
}


@dataclass(frozen=True, slots=True)
class AnswerEvaluation:
    status: str
    normalized_answer: str | None
    found_aspects: list[str]
    missing_aspects: list[str]
    low_signal: bool = False
    explicit_negative: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "normalized_answer": self.normalized_answer,
            "found_aspects": list(self.found_aspects),
            "missing_aspects": list(self.missing_aspects),
            "low_signal": self.low_signal,
            "explicit_negative": self.explicit_negative,
        }


@dataclass(frozen=True, slots=True)
class ReadinessAssessment:
    ready: bool
    missing_inputs: list[str]
    substantive_answers: dict[str, bool]
    answer_evaluations: dict[str, dict[str, Any]]
    signals: dict[str, Any]
    question_items: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing_inputs": list(self.missing_inputs),
            "substantive_answers": dict(self.substantive_answers),
            "answer_evaluations": dict(self.answer_evaluations),
            "signals": dict(self.signals),
            "question_items": list(self.question_items),
        }


class TaskReadinessPolicy:
    LOW_SIGNAL_ANSWERS = {
        "n/a",
        "na",
        "нет",
        "не знаю",
        "unknown",
        "none",
        "-",
        "?",
        "todo",
        "tbd",
        "пока не знаю",
        "непонятно",
        "без деталей",
        "что-нибудь",
        "как-нибудь",
        "потом уточню",
    }

    MIN_ANSWER_LENGTH_BY_CODE = {
        "goal": 12,
        "context": 12,
        "constraints": 8,
        "integrations": 8,
        "expected_output": 8,
        "nfr": 8,
    }

    QUESTION_ASPECT_LABELS: dict[str, dict[str, str]] = {
        "goal": {
            "objective": "что именно нужно изменить",
            "subject": "какой объект или процесс затрагиваем",
            "business_effect": "какой ожидается бизнес-эффект или метрика результата",
        },
        "context": {
            "current_state": "что есть сейчас",
            "scope_entity": "какая система, процесс или контур рассматривается",
            "pain_point": "какая проблема или исходная точка наблюдается",
        },
        "constraints": {
            "constraint_category": "какие именно ограничения важны",
            "constraint_detail": "в чём выражается ограничение",
        },
        "integrations": {
            "counterparty": "с чем именно нужно интегрироваться",
            "exchange_mode": "какой обмен или интерфейс ожидается",
        },
        "expected_output": {
            "artifact_type": "какой именно артефакт нужен на выходе",
            "detail_level": "какая нужна глубина или фокус результата",
        },
        "nfr": {
            "security": "требования безопасности и доступа",
            "availability": "доступность или отказоустойчивость",
            "performance": "производительность, нагрузка или SLA",
            "operations": "мониторинг, резервное копирование или восстановление",
        },
    }

    def assess(self, task: BusinessTask) -> ReadinessAssessment:
        raw_text = (getattr(task, "task_text", None) or "").strip()
        metadata = dict(getattr(task, "task_metadata", None) or {})
        context_notes = self._extract_context_notes(metadata)
        text_parts = [raw_text, *context_notes]
        combined_text = "\n".join(text_parts)
        answers = {
            str(key): str(value).strip()
            for key, value in (metadata.get("clarification_answers") or {}).items()
            if value
        }

        answer_evaluations = {
            code: self.evaluate_answer(answers.get(code), code=code)
            for code in QUESTION_TEMPLATES
        }
        task_text_evaluations = {
            code: self.evaluate_answer(combined_text, code=code)
            for code in QUESTION_TEMPLATES
        }

        def present(code: str, *, metadata_key: str | None = None) -> bool:
            if answer_evaluations[code].status == "ready":
                return True
            if task_text_evaluations[code].status == "ready":
                return True
            if metadata_key is None:
                return False
            metadata_value = metadata.get(metadata_key)
            if not metadata_value:
                return False
            return self.evaluate_answer(str(metadata_value), code=code).status == "ready"

        goal_present = present("goal")
        context_present = present("context", metadata_key="context")
        constraints_present = present("constraints")
        integrations_present = present("integrations")
        expected_output_present = present("expected_output", metadata_key="expected_output")
        nfr_present = present("nfr")

        missing: list[str] = []
        if not goal_present:
            missing.append("goal")
        if not context_present:
            missing.append("context")
        if not constraints_present:
            missing.append("constraints")
        if not integrations_present:
            missing.append("integrations")
        if not expected_output_present:
            missing.append("expected_output")
        if not nfr_present:
            missing.append("nfr")

        signals = {
            "raw_text_length": len(raw_text),
            "context_note_count": len(context_notes),
            "goal_present": goal_present,
            "context_present": context_present,
            "constraints_present": constraints_present,
            "integrations_present": integrations_present,
            "expected_output_present": expected_output_present,
            "nfr_present": nfr_present,
            "clarification_answer_count": len(answers),
            "task_text_evaluations": {
                code: evaluation.as_dict()
                for code, evaluation in task_text_evaluations.items()
            },
            "input_presence": {
                code: {
                    "answer_status": answer_evaluations[code].status,
                    "task_text_status": task_text_evaluations[code].status,
                    "present": present_value,
                }
                for code, present_value in {
                    "goal": goal_present,
                    "context": context_present,
                    "constraints": constraints_present,
                    "integrations": integrations_present,
                    "expected_output": expected_output_present,
                    "nfr": nfr_present,
                }.items()
            },
        }

        def question_evaluation(code: str) -> AnswerEvaluation:
            answer_evaluation = answer_evaluations[code]
            if answer_evaluation.normalized_answer:
                return answer_evaluation
            return task_text_evaluations[code]

        question_items = [
            {
                "question_code": code,
                "question_text": self.build_question_text(code, question_evaluation(code)),
                "required": True,
            }
            for code in missing
        ]

        return ReadinessAssessment(
            ready=not missing,
            missing_inputs=missing,
            substantive_answers={
                code: evaluation.status in {"partial", "ready"}
                for code, evaluation in answer_evaluations.items()
            },
            answer_evaluations={
                code: evaluation.as_dict() for code, evaluation in answer_evaluations.items()
            },
            signals=signals,
            question_items=question_items,
        )

    @staticmethod
    def _extract_context_notes(metadata: dict[str, Any]) -> list[str]:
        raw_value = metadata.get("context_notes")
        if raw_value is None:
            raw_value = metadata.get("context")
        if isinstance(raw_value, str):
            note = raw_value.strip()
            return [note] if note else []
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        return []

    def is_substantive_answer(self, value: str | None, *, code: str | None = None) -> bool:
        return self.evaluate_answer(value, code=code).status in {"partial", "ready"}

    def build_question_text(self, code: str, evaluation: AnswerEvaluation | None = None) -> str:
        base = {
            "goal": "Основная цель решения и бизнес-результат.",
            "context": "Текущий контекст, окружение или исходная система.",
            "constraints": "Ограничения и обязательные условия.",
            "integrations": "Интеграции с системами, API, сервисами или данными.",
            "expected_output": "Ожидаемый результат и формат архитектурного артефакта.",
            "nfr": "Нефункциональные требования: безопасность, доступность, производительность, мониторинг и резервное копирование.",
        }.get(code, QUESTION_TEMPLATES[code])

        if evaluation is None or evaluation.status == "ready":
            return base

        aspect_labels = self.QUESTION_ASPECT_LABELS.get(code, {})
        missing = [
            aspect_labels.get(item, item.replace("_", " "))
            for item in evaluation.missing_aspects
        ]
        if not missing:
            return base

        details = " ".join(f"{index}. {item};" for index, item in enumerate(missing, start=1))
        return f"{base} Уточните детали: {details}".strip()

    def evaluate_answer(self, value: str | None, *, code: str | None = None) -> AnswerEvaluation:
        if value is None:
            return self._empty_evaluation(code)

        normalized = " ".join(str(value).strip().split())
        if not normalized:
            return self._empty_evaluation(code)

        lowered = normalized.lower()
        if lowered in self.LOW_SIGNAL_ANSWERS:
            return self._insufficient_evaluation(code, normalized, low_signal=True)

        evaluator = {
            "goal": self._evaluate_goal_answer,
            "context": self._evaluate_context_answer,
            "constraints": self._evaluate_constraints_answer,
            "integrations": self._evaluate_integrations_answer,
            "expected_output": self._evaluate_expected_output_answer,
            "nfr": self._evaluate_nfr_answer,
        }.get(code or "")

        if evaluator is None:
            if len(normalized) < self.MIN_ANSWER_LENGTH_BY_CODE.get(code or "", 8):
                return self._insufficient_evaluation(code, normalized)
            return AnswerEvaluation(
                status="ready",
                normalized_answer=normalized,
                found_aspects=["free_form"],
                missing_aspects=[],
            )

        return evaluator(normalized)

    def _empty_evaluation(self, code: str | None) -> AnswerEvaluation:
        return AnswerEvaluation(
            status="insufficient",
            normalized_answer=None,
            found_aspects=[],
            missing_aspects=self._default_missing_aspects(code),
        )

    def _insufficient_evaluation(
        self,
        code: str | None,
        normalized: str,
        *,
        low_signal: bool = False,
    ) -> AnswerEvaluation:
        return AnswerEvaluation(
            status="insufficient",
            normalized_answer=normalized,
            found_aspects=[],
            missing_aspects=self._default_missing_aspects(code),
            low_signal=low_signal,
        )

    def _default_missing_aspects(self, code: str | None) -> list[str]:
        return list(self.QUESTION_ASPECT_LABELS.get(code or "", {}).keys())

    @staticmethod
    def _contains_any(text: str, patterns: list[str]) -> bool:
        return any(pattern in text for pattern in patterns)

    @staticmethod
    def _has_digit(text: str) -> bool:
        return any(char.isdigit() for char in text)

    def _evaluate_goal_answer(self, normalized: str) -> AnswerEvaluation:
        lowered = normalized.lower()
        found: list[str] = []

        if self._contains_any(
            lowered,
            [
                "цель",
                "целевой",
                "сниз",
                "уменьш",
                "ускор",
                "автомат",
                "повыс",
                "сократ",
                "оптимиз",
                "обеспеч",
                "мигр",
                "внедр",
                "улучш",
            ],
        ):
            found.append("objective")

        if self._contains_any(
            lowered,
            [
                "процесс",
                "заяв",
                "заказ",
                "клиент",
                "отчет",
                "сервис",
                "систем",
                "данн",
                "интеграц",
                "канал",
                "поток",
                "документ",
            ],
        ) or len([word for word in lowered.split() if len(word) >= 5]) >= 3:
            found.append("subject")

        if self._contains_any(
            lowered,
            [
                "результат",
                "чтобы",
                "для того",
                "в результате",
                "эффект",
                "outcome",
                "business outcome",
                "эконом",
                "sla",
                "доступност",
                "качеств",
                "точност",
                "срок",
                "время",
                "стоим",
                "метрик",
                "kpi",
            ],
        ) or self._has_digit(lowered):
            found.append("business_effect")

        if len(found) == 3:
            status = "ready"
        elif len(found) >= 2:
            status = "partial"
        else:
            status = "insufficient"

        return AnswerEvaluation(
            status=status,
            normalized_answer=normalized,
            found_aspects=found,
            missing_aspects=[
                item for item in ("objective", "subject", "business_effect") if item not in found
            ],
        )

    def _evaluate_context_answer(self, normalized: str) -> AnswerEvaluation:
        lowered = normalized.lower()
        found: list[str] = []

        if self._contains_any(
            lowered,
            [
                "сейчас",
                "текущ",
                "as is",
                "существующ",
                "сегодня",
                "имеется",
                "используется",
                "контекст",
            ],
        ):
            found.append("current_state")

        if self._contains_any(
            lowered,
            [
                "систем",
                "процесс",
                "контур",
                "модул",
                "приложен",
                "команд",
                "пользоват",
                "канал",
                "crm",
                "erp",
                "sap",
                "1с",
                "kafka",
                "шина",
            ],
        ):
            found.append("scope_entity")

        if self._contains_any(
            lowered,
            [
                "проблем",
                "ручн",
                "ошиб",
                "долго",
                "узк",
                "не хватает",
                "разрознен",
                "задерж",
                "неудоб",
                "дублир",
                "потер",
            ],
        ):
            found.append("pain_point")

        if "current_state" in found and ("scope_entity" in found or "pain_point" in found):
            status = "ready"
        elif found:
            status = "partial"
        else:
            status = "insufficient"

        return AnswerEvaluation(
            status=status,
            normalized_answer=normalized,
            found_aspects=found,
            missing_aspects=[
                item for item in ("current_state", "scope_entity", "pain_point") if item not in found
            ],
        )

    def _evaluate_constraints_answer(self, normalized: str) -> AnswerEvaluation:
        lowered = normalized.lower()
        if self._contains_any(
            lowered,
            [
                "ограничений нет",
                "жестких ограничений нет",
                "без ограничений",
                "нет специальных ограничений",
            ],
        ):
            return AnswerEvaluation(
                status="ready",
                normalized_answer=normalized,
                found_aspects=["constraint_category", "constraint_detail"],
                missing_aspects=[],
                explicit_negative=True,
            )

        categories = {
            "time": ["срок", "дедлайн", "недел", "месяц", "квартал"],
            "security": ["безопас", "шифр", "доступ", "персональн", "auth", "sso"],
            "performance": ["sla", "latency", "нагруз", "производ", "доступност", "rps"],
            "budget": ["бюдж", "стоим", "затрат", "финанс"],
            "compliance": ["регламент", "норматив", "152-фз", "audit", "соответств"],
        }

        found: list[str] = []
        matched_categories = [
            name for name, patterns in categories.items() if self._contains_any(lowered, patterns)
        ]
        if matched_categories:
            found.append("constraint_category")

        if self._has_digit(lowered) or self._contains_any(
            lowered,
            [
                "не более",
                "не меньше",
                "только",
                "запрещ",
                "обязательно",
                "должен",
                "нельзя",
                "допускается",
            ],
        ):
            found.append("constraint_detail")

        if "constraint_category" in found and ("constraint_detail" in found or len(matched_categories) >= 2):
            status = "ready"
        elif found:
            status = "partial"
        else:
            status = "insufficient"

        return AnswerEvaluation(
            status=status,
            normalized_answer=normalized,
            found_aspects=found,
            missing_aspects=[
                item for item in ("constraint_category", "constraint_detail") if item not in found
            ],
        )

    def _evaluate_integrations_answer(self, normalized: str) -> AnswerEvaluation:
        lowered = normalized.lower()
        if self._contains_any(
            lowered,
            [
                "интеграций нет",
                "без интеграций",
                "внешних систем нет",
                "автономно",
                "изолированно",
            ],
        ):
            return AnswerEvaluation(
                status="ready",
                normalized_answer=normalized,
                found_aspects=["counterparty", "exchange_mode"],
                missing_aspects=[],
                explicit_negative=True,
            )

        found: list[str] = []
        if self._contains_any(
            lowered,
            [
                "sap",
                "1с",
                "crm",
                "erp",
                "dwh",
                "kafka",
                "postgres",
                "oracle",
                "email",
                "ldap",
                "ad",
                "billing",
                "api gateway",
                "service bus",
                "очеред",
                "интегр",
                "внешн",
                "смежн",
                "систем",
            ],
        ):
            found.append("counterparty")

        if self._contains_any(
            lowered,
            [
                "api",
                "rest",
                "soap",
                "webhook",
                "файл",
                "обмен",
                "событ",
                "очеред",
                "mq",
                "данн",
                "статус",
                "запрос",
                "синхрон",
                "асинхрон",
            ],
        ):
            found.append("exchange_mode")

        if len(found) == 2:
            status = "ready"
        elif found:
            status = "partial"
        else:
            status = "insufficient"

        return AnswerEvaluation(
            status=status,
            normalized_answer=normalized,
            found_aspects=found,
            missing_aspects=[
                item for item in ("counterparty", "exchange_mode") if item not in found
            ],
        )

    def _evaluate_expected_output_answer(self, normalized: str) -> AnswerEvaluation:
        lowered = normalized.lower()
        found: list[str] = []

        if self._contains_any(
            lowered,
            [
                "hld",
                "high-level",
                "концепт",
                "концепция",
                "архитектурн",
                "решени",
                "дизайн",
                "компонентн",
                "интеграцион",
                "диаграм",
                "схем",
                "модель",
                "документ",
                "артефакт",
                "рекомендац",
            ],
        ):
            found.append("artifact_type")

        if self._contains_any(
            lowered,
            [
                "верхнеуров",
                "high-level",
                "hld",
                "деталь",
                "на уровне",
                "для согласования",
                "чернов",
                "подроб",
                "только концепт",
                "без детализации",
                "фокус",
                "вариант",
            ],
        ):
            found.append("detail_level")

        if {"artifact_type", "detail_level"}.issubset(found):
            status = "ready"
        elif found:
            status = "partial"
        else:
            status = "insufficient"

        return AnswerEvaluation(
            status=status,
            normalized_answer=normalized,
            found_aspects=found,
            missing_aspects=[
                item for item in ("artifact_type", "detail_level") if item not in found
            ],
        )

    def _evaluate_nfr_answer(self, normalized: str) -> AnswerEvaluation:
        lowered = normalized.lower()
        if self._contains_any(
            lowered,
            [
                "нет специальных nfr",
                "нет специальных нефункциональных",
                "нефункциональных требований нет",
                "без специальных нефункциональных",
            ],
        ):
            return AnswerEvaluation(
                status="ready",
                normalized_answer=normalized,
                found_aspects=["security", "availability", "performance", "operations"],
                missing_aspects=[],
                explicit_negative=True,
            )

        groups = {
            "security": [
                "безопас",
                "доступ",
                "аутенти",
                "авториз",
                "шифр",
                "tls",
                "sso",
                "mfa",
                "rbac",
                "персональн",
                "security",
                "authentication",
                "authorization",
                "encryption",
            ],
            "availability": [
                "доступност",
                "отказоуст",
                "резервирован",
                "реплика",
                "кластер",
                "failover",
                "availability",
                "ha",
                "resilience",
                "redundancy",
            ],
            "performance": [
                "производ",
                "нагруз",
                "задерж",
                "масштаб",
                "sla",
                "rps",
                "latency",
                "throughput",
                "performance",
                "scalability",
            ],
            "operations": [
                "монитор",
                "лог",
                "метрик",
                "трасс",
                "alert",
                "backup",
                "бэкап",
                "резервн",
                "восстанов",
                "rpo",
                "rto",
                "observability",
                "monitoring",
            ],
        }
        found = [
            name
            for name, patterns in groups.items()
            if self._contains_any(lowered, patterns)
        ]
        if len(found) >= 3:
            status = "ready"
        elif found:
            status = "partial"
        else:
            status = "insufficient"
        return AnswerEvaluation(
            status=status,
            normalized_answer=normalized,
            found_aspects=found,
            missing_aspects=[item for item in groups if item not in found],
        )
